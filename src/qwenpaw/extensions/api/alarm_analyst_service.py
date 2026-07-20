# -*- coding: utf-8 -*-
import json
import os
import re
import subprocess
import sys
import importlib.util
from pathlib import Path
from typing import Any


ALARM_ANALYST_SCRIPT_TIMEOUT_SECONDS = 180
RES_ID_RE = re.compile(
    r"(?:资源\s*ID(?:（CI\s*ID）|\(CI\s*ID\))?|CI\s*ID)[:：]\s*([0-9]+)",
)
DATETIME_RE = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})",
)
IP_RE = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
APP_NAME_LABEL_RE = re.compile(
    r"(?:应用名|应用)[:：]\s*([A-Za-z0-9_.\-\u4e00-\u9fa5]+)",
)
APP_NAME_SUFFIX_RE = re.compile(r"([A-Za-z0-9_.\-\u4e00-\u9fa5]+)\s*应用")
DATABASE_HINT_KEYWORDS = ("mysql", "死锁", "锁异常", "插入数据失败", "新增数据失败", "数据库")


def _fault_skill_root() -> Path:
    configured_root = os.getenv("QWENPAW_FAULT_SKILL_ROOT", "").strip()
    if configured_root:
        return Path(configured_root)
    return (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "fault"
        / "skills"
    )


def _alarm_analyst_skill_root() -> Path:
    return _fault_skill_root() / "alarm-analyst"


def _alarm_analyst_context_script() -> Path:
    return _alarm_analyst_skill_root() / "scripts" / "analyze_alarm_context.py"


def _workspace_root() -> Path:
    # _fault_skill_root() = .../working/workspaces/fault/skills, so the
    # workspaces root is two levels up (skills -> fault -> workspaces),
    # i.e. parents[1]. parents[2] wrongly dropped the "workspaces" segment,
    # breaking the zgops find_project / app_topology module load paths.
    return _fault_skill_root().parents[1]


def _zgops_find_project_path() -> Path:
    return (
        _workspace_root()
        / "query"
        / "skills"
        / "zgops-cmdb"
        / "scripts"
        / "find_project.py"
    )


def _zgops_app_topology_path() -> Path:
    return (
        _workspace_root()
        / "query"
        / "skills"
        / "zgops-cmdb"
        / "scripts"
        / "app_topology.py"
    )


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_alarm_dispatch_context(content: str | None) -> dict[str, str]:
    text = str(content or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    res_id_match = RES_ID_RE.search(text)
    event_time_match = DATETIME_RE.search(text)
    manage_ip_match = IP_RE.search(text)
    app_name_match = APP_NAME_LABEL_RE.search(
        text,
    ) or APP_NAME_SUFFIX_RE.search(text)

    title = ""
    device_name = ""
    if lines:
        headline = lines[0]
        if "（" in headline and "）" in headline:
            title = headline.split("（", 1)[0].strip()
            inner = headline.split("（", 1)[1].rsplit("）", 1)[0].strip()
            if inner:
                parts = inner.split()
                if parts:
                    device_name = parts[0].strip()
        elif "·" in headline:
            parts = [
                part.strip() for part in headline.split("·") if part.strip()
            ]
            if parts:
                title = parts[0]
            if len(parts) > 1:
                device_name = parts[1]
        else:
            title = headline

    app_keyword = app_name_match.group(1).strip() if app_name_match else ""
    if not app_keyword and "cmdb" in text.lower():
        app_keyword = "cmdb"

    return {
        "res_id": res_id_match.group(1) if res_id_match else "",
        "event_time": event_time_match.group(1) if event_time_match else "",
        "manage_ip": manage_ip_match.group(0) if manage_ip_match else "",
        "alarm_title": title,
        "device_name": device_name,
        "app_keyword": app_keyword,
    }


def _build_alarm_analyst_result(
    context: dict[str, Any],
    dispatch_context: dict[str, str],
) -> dict[str, Any]:
    topology = context.get("topology") or {}
    recent = (context.get("relatedAlarms") or {}).get("recent") or {}
    previous = (context.get("relatedAlarms") or {}).get("previous") or {}
    comparison = (context.get("relatedAlarms") or {}).get("comparison") or {}
    metric_analysis = context.get("metricAnalysis") or {}
    root_resource = topology.get("rootResource") or {}
    findings = context.get("findings") or []
    execution = context.get("execution") or {}
    execution_root = execution.get("rootResource") or {}
    execution_metrics = execution.get("metrics") or {}
    execution_topology = execution.get("topology") or {}
    execution_recent = execution.get("relatedAlarmsRecent") or {}
    execution_previous = execution.get("relatedAlarmsPrevious") or {}

    summary = findings[0] if findings else "已完成告警拓扑、关联告警和指标的联合分析。"
    root_cause = {
        "type": str(
            metric_analysis.get("metricType")
            or root_resource.get("ciTypeAlias")
            or root_resource.get("ciType")
            or "待分析",
        ),
        "object": str(
            root_resource.get("name")
            or dispatch_context.get("res_id")
            or "cmdb_resource",
        ),
    }

    root_status = "success" if execution_root.get("resolved") else "blocked"
    topology_expected = int(execution_topology.get("resourceIdsExpected") or 0)
    topology_collected = int(
        execution_topology.get("resourceIdsCollected") or 0,
    )
    if topology_collected <= 0:
        topology_status = "blocked"
    elif topology_expected > topology_collected:
        topology_status = "partial"
    else:
        topology_status = "success"

    def _alarm_step_status(branch: dict[str, Any]) -> str:
        expected = int(branch.get("expectedQueries") or 0)
        attempted = int(branch.get("attemptedQueries") or 0)
        failed_ids = branch.get("failedIds") or []
        if expected <= 0:
            return "blocked"
        if attempted != expected or failed_ids:
            return "partial"
        return "success"

    recent_status = _alarm_step_status(execution_recent)
    previous_status = _alarm_step_status(execution_previous)
    if not execution_metrics.get("metricTypeResolved"):
        metric_status = "blocked"
    elif int(execution_metrics.get("failedCount") or 0) > 0:
        metric_status = "partial"
    else:
        metric_status = "success"
    decision_status = str(execution.get("status") or "success")

    steps = [
        {"id": "root-resource", "status": root_status},
        {"id": "cmdb-topology", "status": topology_status},
        {"id": "related-alarms-recent", "status": recent_status},
        {"id": "related-alarms-compare", "status": previous_status},
        {"id": "metric-analysis", "status": metric_status},
        {"id": "decision-merge", "status": decision_status},
    ]
    recent_failed_ids = execution_recent.get("failedIds") or []
    previous_failed_ids = execution_previous.get("failedIds") or []
    metric_failed_count = int(execution_metrics.get("failedCount") or 0)
    metric_skipped_reason = str(execution_metrics.get("skippedReason") or "")
    log_entries = [
        {
            "stage": "root-resource",
            "summary": (
                f"根资源 `{execution_root.get('resId') or dispatch_context.get('res_id') or '-'}` "
                f"{'已确认' if execution_root.get('resolved') else '未确认'}，"
                f"资源类型 `{metric_analysis.get('metricType') or execution_root.get('ciType') or root_resource.get('ciType') or '-'}`。"
            ),
        },
        {
            "stage": "cmdb-topology",
            "summary": (
                f"共识别 {topology.get('resourceCount', 0)} 个拓扑关联资源，"
                f"收集到 {topology_collected}/{topology_expected} 个 fan-out 资源 ID。"
            ),
        },
        {
            "stage": "related-alarms",
            "summary": (
                f"当前窗口告警 {recent.get('total', 0)} 条，环比窗口告警 {previous.get('total', 0)} 条，差值 {comparison.get('deltaTotal', 0)} 条；"
                f"recent {execution_recent.get('attemptedQueries', 0)}/{execution_recent.get('expectedQueries', 0)}，"
                f"compare {execution_previous.get('attemptedQueries', 0)}/{execution_previous.get('expectedQueries', 0)}。"
                f"{' recent 失败资源: ' + ', '.join(recent_failed_ids) + '.' if recent_failed_ids else ''}"
                f"{' compare 失败资源: ' + ', '.join(previous_failed_ids) + '.' if previous_failed_ids else ''}"
            ),
        },
        {
            "stage": "metric-analysis",
            "summary": (
                f"根资源关键指标选中 {execution_metrics.get('selectedCount', 0)} 个，"
                f"成功查询 {execution_metrics.get('queriedCount', 0)} 个，失败 {metric_failed_count} 个。"
                f"{' skippedReason=' + metric_skipped_reason if metric_skipped_reason else ''}"
            ),
        },
    ]
    return {
        "summary": summary,
        "rootCause": root_cause,
        "steps": steps,
        "logEntries": log_entries,
        "actions": [
            {
                "type": "alarm-analyst-context",
                "context": context,
            },
        ],
    }


def _build_partial_alarm_analyst_result(
    dispatch_context: dict[str, str],
    content: str | None,
) -> dict[str, Any]:
    text = str(content or "").strip()
    normalized = text.lower()
    inferred_type = (
        "mysql"
        if any(
            keyword in normalized
            for keyword in ("mysql", "死锁", "锁异常", "插入数据失败", "新增数据失败")
        )
        else "待分析"
    )
    inferred_object = (
        dispatch_context.get("device_name")
        or dispatch_context.get("manage_ip")
        or "目标应用/资源"
    )

    summary = (
        "已进入 alarm-analyst 分析流程，但当前消息缺少可直接执行的资源 ID，"
        "无法完成根资源详情、拓扑扩散、拓扑告警 fan-out 与指标采集的全链路分析。"
    )
    return {
        "summary": summary,
        "rootCause": {
            "type": inferred_type,
            "object": inferred_object,
        },
        "steps": [
            {"id": "parse-input", "status": "success"},
            {"id": "resolve-root-resource", "status": "blocked"},
            {"id": "metric-analysis", "status": "blocked"},
            {"id": "cmdb-topology", "status": "blocked"},
            {"id": "related-alarms", "status": "blocked"},
        ],
        "logEntries": [
            {
                "stage": "parse-input",
                "summary": "已识别到 CMDB 应用写入失败 / 数据插入失败类故障语义。",
            },
            {
                "stage": "resolve-root-resource",
                "summary": "当前消息未提供 `资源 ID（CI ID）`，也没有足够的资源锚点可自动反查，无法继续执行完整 RCA。",
            },
            {
                "stage": "next-action",
                "summary": "请补充资源 ID、管理 IP、设备名或可唯一定位 CMDB 资源的信息后重试。",
            },
        ],
        "actions": [
            {
                "type": "alarm-analyst-context-missing-res-id",
                "requiredFields": ["resId"],
                "optionalFields": [
                    "manageIp",
                    "deviceName",
                    "alarmTitle",
                    "eventTime",
                ],
            },
        ],
    }


def _build_application_partial_result(
    *,
    dispatch_context: dict[str, str],
    app_keyword: str,
    candidates: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    candidate_lines = []
    for item in candidates[:10]:
        candidate_lines.append(
            f"{item.get('name') or '-'}（ID: {item.get('id') or '-'}）",
        )
    candidate_summary = (
        "、".join(candidate_lines) if candidate_lines else "无可用候选"
    )

    return {
        "summary": reason,
        "rootCause": {
            "type": "待分析",
            "object": dispatch_context.get("app_keyword")
            or dispatch_context.get("device_name")
            or "应用",
        },
        "steps": [
            {"id": "parse-input", "status": "success"},
            {"id": "match-application", "status": "blocked"},
            {"id": "cmdb-topology", "status": "blocked"},
            {"id": "related-alarms", "status": "blocked"},
            {"id": "metric-analysis", "status": "blocked"},
        ],
        "logEntries": [
            {
                "stage": "match-application",
                "summary": f"当前应用关键字：`{app_keyword or '-'}`；候选应用：{candidate_summary}",
            },
        ],
        "actions": [
            {
                "type": "alarm-analyst-application-candidates",
                "appKeyword": app_keyword,
                "candidates": candidates,
            },
        ],
    }


def _load_zgops_modules():
    # app_topology.py does a sibling `from find_project import ...`, so the
    # scripts dir must be importable before loading it.
    scripts_dir = str(_zgops_find_project_path().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    find_project = _load_module(
        "zgops_find_project_runtime",
        _zgops_find_project_path(),
    )
    app_topology = _load_module(
        "zgops_app_topology_runtime",
        _zgops_app_topology_path(),
    )
    return find_project, app_topology


def _load_zgops_client(find_project_module: Any):
    env = find_project_module._resolve_zgops_env()  # noqa: SLF001
    client = find_project_module.CmdbHttpClient(
        base_url=env.get("INOE_API_BASE_URL", ""),
        token=env.get("INOE_API_TOKEN", ""),
    )
    client.try_login()
    return client


def _select_root_resource_candidate(
    content: str,
    relation_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized = str(content or "").lower()
    candidates = []
    for item in relation_rows:
        ci_type = str(item.get("ci_type") or "").strip()
        if not ci_type:
            continue
        score = 0
        if ci_type == "mysql":
            score += 100
        elif ci_type in {"database", "PostgreSQL"}:
            score += 90
        elif ci_type in {"redis", "Kafka", "elasticsearch"}:
            score += 60
        elif ci_type in {"docker", "vserver"}:
            score += 30
        if any(keyword in normalized for keyword in DATABASE_HINT_KEYWORDS):
            if ci_type in {"mysql", "database", "PostgreSQL"}:
                score += 50
        if score > 0:
            candidates.append((score, item))

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    top_score = candidates[0][0]
    top_items = [item for score, item in candidates if score == top_score]
    if len(top_items) == 1:
        return top_items[0]
    mysql_items = [
        item for item in top_items if str(item.get("ci_type")) == "mysql"
    ]
    if len(mysql_items) == 1:
        return mysql_items[0]
    return top_items[0]


def _run_alarm_analyst_context_from_application(
    payload: dict,
    dispatch_context: dict[str, str],
) -> dict:
    app_keyword = dispatch_context.get("app_keyword", "")
    find_project, app_topology = _load_zgops_modules()
    client = _load_zgops_client(find_project)
    projects = client.list_projects()
    matched_projects, mode = find_project._match_projects(
        projects,
        app_keyword,
    )  # noqa: SLF001

    if not app_keyword:
        if len(projects) == 1:
            matched_projects = [projects[0]]
        else:
            candidates = [
                find_project._project_summary(item) for item in projects[:10]
            ]  # noqa: SLF001
            return _build_application_partial_result(
                dispatch_context=dispatch_context,
                app_keyword=app_keyword,
                candidates=candidates,
                reason="当前消息未提供可唯一识别的应用名，无法直接查询对应应用拓扑，请补充应用名或资源 ID。",
            )

    if not matched_projects:
        return _build_application_partial_result(
            dispatch_context=dispatch_context,
            app_keyword=app_keyword,
            candidates=[],
            reason=f"未找到与 `{app_keyword}` 匹配的应用，无法继续执行应用驱动的 RCA。",
        )

    if len(matched_projects) > 1:
        candidates = [
            find_project._project_summary(item)
            for item in matched_projects[:10]
        ]  # noqa: SLF001
        return _build_application_partial_result(
            dispatch_context=dispatch_context,
            app_keyword=app_keyword,
            candidates=candidates,
            reason=f"存在多个与 `{app_keyword}` 匹配的应用，需先明确目标应用，才能继续查询拓扑和关联告警。",
        )

    project = matched_projects[0]
    project_name = (
        find_project._project_name(project) or app_keyword
    )  # noqa: SLF001
    relation_rows = app_topology._fetch_relations(
        client,
        project.get("_id") or project.get("id"),
    )  # noqa: SLF001
    tree = app_topology._build_tree(project, relation_rows)  # noqa: SLF001
    option = app_topology._build_option(
        tree,
        f"{project_name} 应用关系拓扑",
    )  # noqa: SLF001

    root_candidate = _select_root_resource_candidate(
        str(payload.get("content") or ""),
        relation_rows,
    )
    if not root_candidate:
        return {
            "summary": f"已匹配应用 `{project_name}` 并查询到拓扑，但暂未能自动选出合适的根资源继续做指标分析。",
            "rootCause": {"type": "待分析", "object": project_name},
            "steps": [
                {"id": "match-application", "status": "success"},
                {"id": "app-topology", "status": "success"},
                {"id": "resolve-root-resource", "status": "blocked"},
            ],
            "logEntries": [
                {
                    "stage": "app-topology",
                    "summary": f"应用 `{project_name}` 的拓扑已获取，共 {len(relation_rows)} 条关系记录。",
                },
            ],
            "actions": [
                {
                    "type": "alarm-analyst-application-topology",
                    "project": {
                        "id": project.get("_id") or project.get("id"),
                        "name": project_name,
                    },
                    "option": option,
                },
            ],
        }

    dispatch_context = {
        **dispatch_context,
        "res_id": str(
            root_candidate.get("_id") or root_candidate.get("id") or "",
        ),
        "device_name": dispatch_context.get("device_name")
        or str(
            root_candidate.get("name")
            or root_candidate.get("db_instance")
            or "",
        ),
        "manage_ip": dispatch_context.get("manage_ip")
        or str(
            root_candidate.get("manage_ip")
            or root_candidate.get("db_ip")
            or "",
        ),
        "alarm_title": dispatch_context.get("alarm_title")
        or str(payload.get("content") or "").strip(),
    }

    context = _run_alarm_analyst_context(
        {
            **payload,
            "content": payload.get("content", "")
            + f"\n资源 ID（CI ID）：{dispatch_context['res_id']}",
        },
    )
    context.setdefault("actions", []).append(
        {
            "type": "alarm-analyst-application-topology",
            "project": {
                "id": project.get("_id") or project.get("id"),
                "name": project_name,
            },
            "option": option,
        },
    )
    context.setdefault("logEntries", []).insert(
        0,
        {
            "stage": "application-topology",
            "summary": f"已匹配应用 `{project_name}`，并从其拓扑中选择候选根资源 `{dispatch_context['res_id']}` 继续 RCA。",
        },
    )
    return context


def _run_alarm_analyst_context(payload: dict) -> dict:
    script_path = _alarm_analyst_context_script()
    if not script_path.exists():
        raise FileNotFoundError(
            f"alarm-analyst context script not found: {script_path}",
        )

    dispatch_context = parse_alarm_dispatch_context(payload.get("content"))
    res_id = dispatch_context.get("res_id", "")
    if not res_id:
        return _run_alarm_analyst_context_from_application(
            payload,
            dispatch_context,
        )

    command_args = [
        sys.executable,
        str(script_path),
        "--res-id",
        res_id,
        "--output",
        "json",
    ]
    if dispatch_context.get("alarm_title"):
        command_args.extend(["--alarm-title", dispatch_context["alarm_title"]])
    if dispatch_context.get("device_name"):
        command_args.extend(["--device-name", dispatch_context["device_name"]])
    if dispatch_context.get("manage_ip"):
        command_args.extend(["--manage-ip", dispatch_context["manage_ip"]])
    if dispatch_context.get("event_time"):
        command_args.extend(["--event-time", dispatch_context["event_time"]])

    completed = subprocess.run(
        command_args,
        cwd=str(_alarm_analyst_skill_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=ALARM_ANALYST_SCRIPT_TIMEOUT_SECONDS,
        check=False,
    )
    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    if completed.returncode != 0 and not stdout_text:
        raise RuntimeError(stderr_text or "alarm-analyst context query failed")
    if not stdout_text:
        raise RuntimeError("alarm-analyst context query returned empty output")

    context = json.loads(stdout_text)
    if context.get("code") != 200:
        raise RuntimeError(
            str(context.get("msg") or "alarm-analyst context query failed"),
        )
    return _build_alarm_analyst_result(context, dispatch_context)


def run_alarm_analyst_diagnose(payload: dict) -> dict:
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        raise ValueError("sessionId is required")

    result = _run_alarm_analyst_context(payload)
    return {
        "session": {
            "sessionId": session_id,
            "scene": "alarm_analyst_rca",
        },
        "result": result,
    }
