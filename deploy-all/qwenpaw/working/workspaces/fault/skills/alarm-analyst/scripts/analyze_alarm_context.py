#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
围绕单条告警的资源 ID 聚合 CMDB 拓扑、关联告警与指标信息。

使用方式:
    python scripts/analyze_alarm_context.py --res-id 3094 --output markdown
    python scripts/analyze_alarm_context.py --res-id 3094 --alarm-title 数据库锁异常 --metric-type mysql --output json
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import sys
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


ALLOWED_OUTPUTS = {"json", "markdown"}
DEFAULT_ALARM_WINDOW_MINUTES = 10
DEFAULT_REAL_ALARM_PAGE_SIZE = 100
DEFAULT_RELATED_ALARM_PREVIEW_LIMIT = 20


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return

    skill_dir = Path(__file__).resolve().parents[1]
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=False)


_load_skill_env()


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    return _skill_root().parents[2]


def _real_alarm_script_path() -> Path:
    return (
        _workspace_root()
        / "query"
        / "skills"
        / "real-alarm"
        / "scripts"
        / "get_alarms.py"
    )


def _veops_find_project_path() -> Path:
    return (
        _workspace_root()
        / "query"
        / "skills"
        / "zgops-cmdb"
        / "scripts"
        / "find_project.py"
    )


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _parse_datetime(value: str | None) -> datetime | None:
    text = _safe_str(value)
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _build_alarm_query_windows(
    *,
    event_time: str,
    window_minutes: int,
    compare_begin_time: str = "",
    compare_end_time: str = "",
) -> dict[str, str]:
    if window_minutes < 1:
        raise ValueError("window_minutes 必须大于等于 1")

    event_dt = _parse_datetime(event_time) or datetime.now(timezone.utc)
    recent_begin_dt = event_dt - timedelta(minutes=window_minutes)
    recent_end_dt = event_dt + timedelta(minutes=window_minutes)

    custom_compare_begin = _parse_datetime(compare_begin_time)
    custom_compare_end = _parse_datetime(compare_end_time)
    if bool(custom_compare_begin) != bool(custom_compare_end):
        raise ValueError("compare_begin_time 和 compare_end_time 必须同时提供")

    if custom_compare_begin and custom_compare_end:
        previous_begin_dt = custom_compare_begin
        previous_end_dt = custom_compare_end
    else:
        window_span = recent_end_dt - recent_begin_dt
        previous_end_dt = recent_begin_dt
        previous_begin_dt = previous_end_dt - window_span

    return {
        "recentBeginTime": _format_datetime(recent_begin_dt),
        "recentEndTime": _format_datetime(recent_end_dt),
        "previousBeginTime": _format_datetime(previous_begin_dt),
        "previousEndTime": _format_datetime(previous_end_dt),
        "anchorEventTime": _format_datetime(event_dt),
    }


def _load_cmdb_client():
    find_project = _load_module("veops_find_project", _veops_find_project_path())
    env_path = (
        _workspace_root()
        / "query"
        / "skills"
        / "zgops-cmdb"
        / ".env"
    )
    if not env_path.exists():
        raise ValueError(f"未找到 zgops-cmdb 的环境文件：{env_path}")

    env = find_project._load_env_file(env_path)  # noqa: SLF001
    base_url = _safe_str(env.get("VEOPS_BASE_URL"))
    if not base_url:
        raise ValueError(f"zgops-cmdb 的环境文件缺少 VEOPS_BASE_URL：{env_path}")

    username = _safe_str(env.get("VEOPS_USERNAME"))
    password = _safe_str(env.get("VEOPS_PASSWORD"))
    client = find_project.CmdbHttpClient(
        base_url=base_url,
        username=username,
        password=password,
    )
    login_mode = "anonymous"
    if username and password:
        try:
            client.login()
            login_mode = "authenticated"
        except Exception:
            login_mode = "anonymous"
    return client, find_project, login_mode


def _fetch_topology_relations(root_res_id: str) -> list[dict[str, Any]]:
    client, _find_project, _login_mode = _load_cmdb_client()
    payload = client._request_json(  # noqa: SLF001 - 复用 skill 内部 HTTP helper
        f"/api/v0.1/ci_relations/s?root_id={urllib.parse.quote(root_res_id)}&level=1,2,3&count=10000"
    )
    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        return [item for item in payload["result"] if isinstance(item, dict)]
    return []


def _fetch_root_resource_detail(client: Any, root_res_id: str) -> dict[str, Any]:
    payload = client._request_json(f"/api/v0.1/ci/{urllib.parse.quote(root_res_id)}")  # noqa: SLF001
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            return result
    return {}


def _resource_res_id(item: dict[str, Any]) -> str:
    for value in _resource_res_ids(item):
        return value
    return ""


def _resource_res_ids(item: dict[str, Any]) -> list[str]:
    candidate_keys = (
        "_id",
        "id",
        "ci_id",
        "ciId",
        "root_id",
        "rootId",
        "src_ci_id",
        "srcCiId",
        "dst_ci_id",
        "dstCiId",
        "source_id",
        "target_id",
        "parent_id",
        "child_id",
    )
    values: list[str] = []
    seen: set[str] = set()
    for key in candidate_keys:
        value = _safe_str(item.get(key))
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _resource_name(item: dict[str, Any]) -> str:
    candidates = (
        item.get("name"),
        item.get("project_name"),
        item.get("product_name"),
        item.get("middleware_name"),
        item.get("db_instance"),
        item.get("dev_name"),
        item.get("host_name"),
        item.get("vserver_name"),
        item.get("manage_ip"),
        item.get("private_ip"),
    )
    for value in candidates:
        text = _safe_str(value)
        if text:
            return text
    return _resource_res_id(item) or "unknown"


def _resource_ci_type(item: dict[str, Any]) -> str:
    """Return ci_type from CMDB resource data, used directly as metricType for metric API."""
    return _safe_str(item.get("ci_type"))


_ALARM_SEVERITY_MAP = {
    "1": "紧急",
    "2": "严重",
    "3": "普通",
    "4": "预警",
    "critical": "紧急",
    "urgent": "严重",
    "warning": "普通",
    "info": "预警",
}


def _resource_ci_type_alias(item: dict[str, Any]) -> str:
    return _safe_str(item.get("ci_type_alias")) or _resource_ci_type(item) or "资源"


def _extract_resource_dicts(payload: Any) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if _resource_res_id(node):
                resources.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return resources


def _collect_related_resource_ids(root_res_id: str, resource_rows: list[dict[str, Any]]) -> list[str]:
    ordered_ids: list[str] = []
    seen: set[str] = set()

    def _push(value: str) -> None:
        normalized = _safe_str(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_ids.append(normalized)

    _push(root_res_id)
    for item in _extract_resource_dicts(resource_rows):
        for related_res_id in _resource_res_ids(item):
            _push(related_res_id)
    return ordered_ids


def _build_topology_summary(
    root_res_id: str,
    resource_rows: list[dict[str, Any]],
    *,
    root_resource: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resource_ids = _collect_related_resource_ids(root_res_id, resource_rows)
    extracted_resources = _extract_resource_dicts(resource_rows)
    ci_type_counts = Counter(
        _resource_ci_type(item) or "unknown"
        for item in extracted_resources
        if _resource_res_id(item)
    )

    normalized_resources = []
    seen: set[str] = set()
    normalized_root_resource = None
    if root_resource:
        normalized_root_resource = {
            "resId": _safe_str(root_resource.get("_id") or root_resource.get("id") or root_res_id),
            "name": _resource_name(root_resource),
            "ciType": _resource_ci_type(root_resource),
            "ciTypeAlias": _resource_ci_type_alias(root_resource),
            "isRoot": True,
        }
        seen.add(normalized_root_resource["resId"])
        normalized_resources.append(normalized_root_resource)

    for item in extracted_resources:
        res_id = _resource_res_id(item)
        if not res_id or res_id in seen:
            continue
        seen.add(res_id)
        normalized_resources.append(
            {
                "resId": res_id,
                "name": _resource_name(item),
                "ciType": _resource_ci_type(item),
                "ciTypeAlias": _resource_ci_type_alias(item),
                "isRoot": res_id == _safe_str(root_res_id),
            }
        )

    if _safe_str(root_res_id) and _safe_str(root_res_id) not in seen:
        normalized_root_resource = {
            "resId": _safe_str(root_res_id),
            "name": _safe_str(root_res_id),
            "ciType": "",
            "ciTypeAlias": "资源",
            "isRoot": True,
        }
        normalized_resources.insert(0, normalized_root_resource)

    normalized_resources.sort(key=lambda item: (not item["isRoot"], item["ciTypeAlias"], item["name"]))
    return {
        "rootResId": _safe_str(root_res_id),
        "rootResource": normalized_root_resource,
        "resourceCount": len(resource_ids),
        "resourceIds": resource_ids,
        "ciTypeCounts": dict(ci_type_counts),
        "resources": normalized_resources,
    }


def _infer_metric_type(metric_type: str | None, topology_summary: dict[str, Any], alarm_title: str = "") -> str:
    explicit = _safe_str(metric_type)
    if explicit:
        return explicit
    root_resource = topology_summary.get("rootResource") or {}
    if _safe_str(root_resource.get("ciType")):
        return _safe_str(root_resource["ciType"])
    for resource in topology_summary.get("resources") or []:
        if _safe_str(resource.get("ciType")):
            return _safe_str(resource["ciType"])
    # Fallback: infer from alarm title keywords
    return _infer_metric_type_from_title(alarm_title)


def _infer_metric_type_from_title(title: str) -> str:
    """Infer metric type from alarm title keywords as last resort."""
    t = title.lower()
    if any(kw in t for kw in ("丢包", "ping", "链路", "端口", "带宽", "网络", "丢包率", "设备异常")):
        return "networkdevice"
    if any(kw in t for kw in ("cpu", "内存", "温度", "磁盘", "服务器", "主机")):
        return "server"
    if any(kw in t for kw in ("死锁", "锁异常", "慢sql", "数据库", "mysql", "postgresql", "postgres")):
        return "database"
    if any(kw in t for kw in ("中间件", "redis", "kafka", "mq", "rabbitmq", "消息队列")):
        return "middleware"
    return ""


def _load_real_alarm_execute():
    module = _load_module("real_alarm_get_alarms", _real_alarm_script_path())
    return module.execute


def _query_alarms_for_res_id(
    *,
    res_id: str,
    begin_time: str,
    end_time: str,
    api_base_url: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    execute = _load_real_alarm_execute()
    first_page = execute(
        page_num=1,
        page_size=1,
        token=token,
        api_base_url=api_base_url,
        begin_time=begin_time,
        end_time=end_time,
        ci_id=res_id,
    )
    if first_page.get("code") != 200:
        return {
            "resId": res_id,
            "code": first_page.get("code"),
            "msg": first_page.get("msg"),
            "total": 0,
            "rows": [],
        }

    total = int(first_page.get("total") or 0)
    if total == 0:
        return {
            "resId": res_id,
            "code": 200,
            "msg": "查询成功",
            "total": 0,
            "rows": [],
        }

    rows: list[dict[str, Any]] = []
    page_num = 1
    while len(rows) < total:
        result = execute(
            page_num=page_num,
            page_size=DEFAULT_REAL_ALARM_PAGE_SIZE,
            token=token,
            api_base_url=api_base_url,
            begin_time=begin_time,
            end_time=end_time,
            ci_id=res_id,
        )
        page_rows = result.get("rows") or []
        if result.get("code") != 200:
            return {
                "resId": res_id,
                "code": result.get("code"),
                "msg": result.get("msg"),
                "total": total,
                "rows": rows,
            }
        if not isinstance(page_rows, list) or not page_rows:
            break
        rows.extend(item for item in page_rows if isinstance(item, dict))
        if len(page_rows) < DEFAULT_REAL_ALARM_PAGE_SIZE:
            break
        page_num += 1
    return {
        "resId": res_id,
        "code": 200,
        "msg": "查询成功",
        "total": total,
        "rows": rows,
    }


def _alarm_res_id(row: dict[str, Any], fallback_res_id: str = "") -> str:
    return _safe_str(
        row.get("neId")
        or row.get("ciId")
        or row.get("devId")
        or row.get("ciid")
        or row.get("neid")
        or fallback_res_id
    )


def _merge_related_alarm_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    per_res_id: list[dict[str, Any]] = []

    for result in results:
        res_id = _safe_str(result.get("resId"))
        rows = result.get("rows") or []
        if not isinstance(rows, list):
            rows = []
        per_res_id.append(
            {
                "resId": res_id,
                "total": int(result.get("total") or len(rows)),
                "code": result.get("code"),
                "msg": result.get("msg"),
            }
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            unique_id = _safe_str(row.get("alarmuniqueid")) or f"{res_id}:{_safe_str(row.get('alarmtitle'))}:{_safe_str(row.get('eventtime'))}"
            if unique_id in seen_ids:
                continue
            seen_ids.add(unique_id)
            enriched = dict(row)
            enriched["resId"] = _alarm_res_id(enriched, res_id)
            all_rows.append(enriched)

    title_counts = Counter(_safe_str(row.get("alarmtitle")) or "未命名告警" for row in all_rows)
    severity_counts = Counter(_safe_str(row.get("alarmseverity")) or "unknown" for row in all_rows)
    return {
        "total": len(all_rows),
        "perResId": per_res_id,
        "titleCounts": dict(title_counts),
        "severityCounts": dict(severity_counts),
        "rows": sorted(all_rows, key=lambda item: (_safe_str(item.get("eventtime")), _safe_str(item.get("alarmtitle"))), reverse=True),
    }


def _build_alarm_comparison_summary(
    *,
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    current_title_counts = Counter(_safe_str(row.get("alarmtitle")) or "未命名告警" for row in current_rows)
    previous_title_counts = Counter(_safe_str(row.get("alarmtitle")) or "未命名告警" for row in previous_rows)

    title_delta: dict[str, int] = {}
    for title in set(current_title_counts) | set(previous_title_counts):
        delta = current_title_counts.get(title, 0) - previous_title_counts.get(title, 0)
        if delta:
            title_delta[title] = delta

    current_total = len(current_rows)
    previous_total = len(previous_rows)
    delta_total = current_total - previous_total
    growth_ratio = None
    if previous_total > 0:
        growth_ratio = round((delta_total / previous_total) * 100, 2)

    return {
        "currentTotal": current_total,
        "previousTotal": previous_total,
        "deltaTotal": delta_total,
        "growthRatio": growth_ratio,
        "titleDelta": title_delta,
    }


def _to_float(value: Any) -> float | None:
    text = _safe_str(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _infer_correlation_findings(
    *,
    current_alarm: dict[str, Any],
    related_alarm_rows: list[dict[str, Any]],
    metric_data_results: list[dict[str, Any]],
    alarm_comparison: dict[str, Any] | None = None,
) -> list[str]:
    findings: list[str] = []
    current_title = _safe_str(current_alarm.get("alarmtitle"))
    current_res_id = _safe_str(current_alarm.get("resId"))

    if current_title:
        same_title_rows = [
            row for row in related_alarm_rows
            if _safe_str(row.get("alarmtitle")) == current_title
        ]
        same_title_res_ids = sorted({_safe_str(row.get("resId")) for row in same_title_rows if _safe_str(row.get("resId"))})
        if len(same_title_res_ids) > 1:
            findings.append(
                f"同名告警 `{current_title}` 同时出现在 {len(same_title_res_ids)} 个关联资源上，说明问题可能沿拓扑链路扩散，而非只局限于单节点。"
            )
        elif same_title_res_ids:
            findings.append(
                f"当前告警标题 `{current_title}` 仅集中在资源 `{same_title_res_ids[0]}` 上，说明更像是单资源内部异常触发。"
            )

    if current_res_id:
        same_res_rows = [
            row for row in related_alarm_rows
            if _safe_str(row.get("resId")) == current_res_id
        ]
        same_res_titles = sorted({_safe_str(row.get("alarmtitle")) for row in same_res_rows if _safe_str(row.get("alarmtitle"))})
        if len(same_res_titles) > 1:
            findings.append(
                f"根资源 `{current_res_id}` 上同时存在 {len(same_res_titles)} 类告警，说明当前故障可能已经引起复合症状，而不是单一异常。"
            )

    comparison = alarm_comparison or {}
    delta_total = int(comparison.get("deltaTotal") or 0)
    previous_total = int(comparison.get("previousTotal") or 0)
    if delta_total > 0:
        if previous_total > 0:
            findings.append(
                f"关联告警总量相较上一等长时间窗口环比上升 `{delta_total}` 条，说明当前故障影响面正在扩大。"
            )
        else:
            findings.append("上一等长时间窗口未观察到关联告警，而当前窗口已有多条关联告警，说明问题是近期新增并正在扩散。")
    elif delta_total < 0:
        findings.append(
            f"关联告警总量相较上一等长时间窗口环比下降 `{abs(delta_total)}` 条，说明故障影响可能已部分收敛，但根资源仍需继续核查。"
        )

    hottest_delta = sorted(
        (comparison.get("titleDelta") or {}).items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    if hottest_delta:
        title, delta = hottest_delta[0]
        if delta > 0:
            findings.append(f"告警 `{title}` 在当前窗口较上一窗口新增 `{delta}` 条，优先级应高于其他伴随告警。")

    for item in metric_data_results:
        metric_code = _safe_str(item.get("metricCode")).lower()
        latest_value = _to_float(item.get("latestValue") or item.get("avgValue"))
        if latest_value is None:
            continue
        if "lock" in metric_code and latest_value > 0:
            findings.append(
                f"指标 `{item.get('metricCode')}` 存在非零值，说明锁等待链路仍然存在，和当前告警表现高度一致。"
            )
        elif "slow" in metric_code and latest_value > 0:
            findings.append(
                f"指标 `{item.get('metricCode')}` 仍有慢 SQL 现象，可能是当前告警的上游诱因。"
            )
        elif "thread" in metric_code and latest_value > 0:
            findings.append(
                f"指标 `{item.get('metricCode')}` 显示数据库线程存在压力，可能放大锁竞争或连接拥塞。"
            )

    if not findings:
        findings.append("当前尚未从关联告警与指标结果中观察到明确的拓扑扩散或指标异常模式，需结合更长时间窗口进一步核实。")
    return findings


def _empty_metric_analysis(metric_type: str = "") -> dict[str, Any]:
    return {
        "metricType": _safe_str(metric_type),
        "selectedMetrics": [],
        "metricDataResults": [],
    }


def _build_alarm_query_execution(
    *,
    expected_res_ids: list[str],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    success_ids: list[str] = []
    failed_ids: list[str] = []

    for result in results:
        res_id = _safe_str(result.get("resId"))
        if not res_id:
            continue
        if int(result.get("code") or 0) == 200:
            success_ids.append(res_id)
        else:
            failed_ids.append(res_id)

    return {
        "expectedQueries": len(expected_res_ids),
        "attemptedQueries": len(results),
        "successIds": success_ids,
        "failedIds": failed_ids,
    }


def _build_execution_summary(
    *,
    res_id: str,
    event_time: str,
    device_name: str,
    manage_ip: str,
    topology_summary: dict[str, Any],
    metric_analysis: dict[str, Any],
    recent_alarm_results: list[dict[str, Any]],
    previous_alarm_results: list[dict[str, Any]],
    metric_skipped_reason: str = "",
) -> dict[str, Any]:
    root_resource = topology_summary.get("rootResource") or {}
    resource_ids = [_safe_str(item) for item in topology_summary.get("resourceIds") or [] if _safe_str(item)]
    metric_type = _safe_str(metric_analysis.get("metricType"))
    selected_metrics = metric_analysis.get("selectedMetrics") or []
    metric_data_results = metric_analysis.get("metricDataResults") or []
    recent_execution = _build_alarm_query_execution(expected_res_ids=resource_ids, results=recent_alarm_results)
    previous_execution = _build_alarm_query_execution(expected_res_ids=resource_ids, results=previous_alarm_results)
    root_resolved = bool(_safe_str(root_resource.get("resId") or res_id))
    metric_type_resolved = bool(metric_type)
    metric_failed_count = max(len(selected_metrics) - len(metric_data_results), 0)

    status = "success"
    if not root_resolved or not metric_type_resolved:
        status = "blocked"
    elif (
        recent_execution["attemptedQueries"] != recent_execution["expectedQueries"]
        or previous_execution["attemptedQueries"] != previous_execution["expectedQueries"]
        or recent_execution["failedIds"]
        or previous_execution["failedIds"]
        or metric_failed_count > 0
    ):
        status = "partial"

    return {
        "status": status,
        "inputAnchors": {
            "resIdFound": bool(_safe_str(res_id)),
            "eventTimeFound": bool(_safe_str(event_time)),
            "deviceNameFound": bool(_safe_str(device_name)),
            "manageIpFound": bool(_safe_str(manage_ip)),
        },
        "rootResource": {
            "resolved": root_resolved,
            "resId": _safe_str(root_resource.get("resId") or res_id),
            "ciType": _safe_str(root_resource.get("ciType")),
        },
        "metrics": {
            "metricTypeResolved": metric_type_resolved,
            "selectedCount": len(selected_metrics),
            "queriedCount": len(metric_data_results),
            "failedCount": metric_failed_count,
            "skippedReason": _safe_str(metric_skipped_reason),
        },
        "topology": {
            "resourceIdsExpected": len(resource_ids),
            "resourceIdsCollected": len(resource_ids),
            "resourceIds": resource_ids,
        },
        "relatedAlarmsRecent": recent_execution,
        "relatedAlarmsPrevious": previous_execution,
    }


def _fetch_topology_summary(
    *,
    client: Any,
    root_res_id: str,
    root_resource: dict[str, Any],
) -> dict[str, Any]:
    payload = client._request_json(  # noqa: SLF001 - 复用 skill 内部 HTTP helper
        f"/api/v0.1/ci_relations/s?root_id={urllib.parse.quote(root_res_id)}&level=1,2,3&count=10000"
    )
    topology_rows = [item for item in payload.get("result", []) if isinstance(item, dict)] if isinstance(payload, dict) else []
    return _build_topology_summary(root_res_id, topology_rows, root_resource=root_resource)


def _fetch_metric_analysis(
    *,
    resolved_metric_type: str,
    root_res_id: str,
    api_base_url: str | None,
    token: str | None,
) -> tuple[dict[str, Any], str]:
    if not resolved_metric_type:
        return _empty_metric_analysis(), "missing_root_ci_type"

    from get_metric_definitions import analyze_metrics  # local script import

    try:
        metric_analysis = analyze_metrics(
            metric_type=resolved_metric_type,
            res_id=root_res_id,
            api_base_url=api_base_url,
            token=token,
        )
        return metric_analysis, ""
    except Exception as error:
        empty = _empty_metric_analysis(resolved_metric_type)
        return empty, f"metric_query_failed: {error}"


def analyze_alarm_context(
    *,
    res_id: str,
    alarm_title: str = "",
    alarm_severity: str = "",
    device_name: str = "",
    manage_ip: str = "",
    event_time: str = "",
    metric_type: str = "",
    window_minutes: int = DEFAULT_ALARM_WINDOW_MINUTES,
    compare_begin_time: str = "",
    compare_end_time: str = "",
    api_base_url: str | None = None,
    token: str | None = None,
    related_alarm_preview_limit: int = DEFAULT_RELATED_ALARM_PREVIEW_LIMIT,
) -> dict[str, Any]:
    root_res_id = _safe_str(res_id)
    if not root_res_id:
        raise ValueError("res_id 不能为空")

    windows = _build_alarm_query_windows(
        event_time=event_time,
        window_minutes=window_minutes,
        compare_begin_time=compare_begin_time,
        compare_end_time=compare_end_time,
    )
    begin_time = windows["recentBeginTime"]
    end_time = windows["recentEndTime"]
    previous_begin_time = windows["previousBeginTime"]
    previous_end_time = windows["previousEndTime"]

    client, _find_project, cmdb_access_mode = _load_cmdb_client()
    root_resource = _fetch_root_resource_detail(client, root_res_id)
    topology_summary = _build_topology_summary(root_res_id, [], root_resource=root_resource)
    resolved_metric_type = _infer_metric_type(metric_type, topology_summary, alarm_title)
    with ThreadPoolExecutor(max_workers=2) as executor:
        topology_future = executor.submit(
            _fetch_topology_summary,
            client=client,
            root_res_id=root_res_id,
            root_resource=root_resource,
        )
        metric_future = executor.submit(
            _fetch_metric_analysis,
            resolved_metric_type=resolved_metric_type,
            root_res_id=root_res_id,
            api_base_url=api_base_url,
            token=token,
        )
        topology_summary = topology_future.result()
        metric_analysis, metric_skipped_reason = metric_future.result()

    # Parallel alarm queries for all related resource IDs
    resource_ids = topology_summary["resourceIds"]
    with ThreadPoolExecutor(max_workers=min(len(resource_ids) * 2, 10)) as executor:
        recent_futures = [
            executor.submit(
                _query_alarms_for_res_id,
                res_id=related_res_id,
                begin_time=begin_time,
                end_time=end_time,
                api_base_url=api_base_url,
                token=token,
            )
            for related_res_id in resource_ids
        ]
        previous_futures = [
            executor.submit(
                _query_alarms_for_res_id,
                res_id=related_res_id,
                begin_time=previous_begin_time,
                end_time=previous_end_time,
                api_base_url=api_base_url,
                token=token,
            )
            for related_res_id in resource_ids
        ]
        recent_alarm_results = [f.result() for f in recent_futures]
        previous_alarm_results = [f.result() for f in previous_futures]
    merged_recent_alarms = _merge_related_alarm_results(recent_alarm_results)
    merged_previous_alarms = _merge_related_alarm_results(previous_alarm_results)
    alarm_comparison = _build_alarm_comparison_summary(
        current_rows=merged_recent_alarms["rows"],
        previous_rows=merged_previous_alarms["rows"],
    )

    current_alarm = {
        "alarmtitle": alarm_title,
        "alarmseverity": alarm_severity,
        "devName": device_name,
        "manageIp": manage_ip,
        "eventTime": event_time,
        "resId": root_res_id,
    }
    findings = _infer_correlation_findings(
        current_alarm=current_alarm,
        related_alarm_rows=merged_recent_alarms["rows"],
        metric_data_results=metric_analysis.get("metricDataResults") or [],
        alarm_comparison=alarm_comparison,
    )
    execution = _build_execution_summary(
        res_id=root_res_id,
        event_time=event_time,
        device_name=device_name,
        manage_ip=manage_ip,
        topology_summary=topology_summary,
        metric_analysis=metric_analysis,
        recent_alarm_results=recent_alarm_results,
        previous_alarm_results=previous_alarm_results,
        metric_skipped_reason=metric_skipped_reason,
    )

    return {
        "code": 200,
        "msg": "查询成功",
        "currentAlarm": current_alarm,
        "timeWindow": {
            "anchorEventTime": windows["anchorEventTime"],
            "beginTime": begin_time,
            "endTime": end_time,
            "previousBeginTime": previous_begin_time,
            "previousEndTime": previous_end_time,
        },
        "cmdbAccessMode": cmdb_access_mode,
        "topology": topology_summary,
        "relatedAlarms": {
            "recent": {
                **merged_recent_alarms,
                "previewRows": merged_recent_alarms["rows"][: max(1, related_alarm_preview_limit)],
            },
            "previous": {
                **merged_previous_alarms,
                "previewRows": merged_previous_alarms["rows"][: max(1, related_alarm_preview_limit)],
            },
            "comparison": alarm_comparison,
        },
        "metricAnalysis": metric_analysis,
        "findings": findings,
        "execution": execution,
    }


def _render_resources_table(resources: list[dict[str, Any]]) -> str:
    if not resources:
        return "- 未发现关联资源"
    lines = [
        "| 资源 ID | 资源名称 | 类型 | 根资源 |",
        "|---|---|---|---|",
    ]
    for item in resources:
        lines.append(
            "| {res_id} | {name} | {ci_type} | {is_root} |".format(
                res_id=_safe_str(item.get("resId")).replace("|", "\\|"),
                name=_safe_str(item.get("name")).replace("|", "\\|"),
                ci_type=_safe_str(item.get("ciTypeAlias") or item.get("ciType") or "-").replace("|", "\\|"),
                is_root="是" if item.get("isRoot") else "",
            )
        )
    return "\n".join(lines)


def _render_alarm_rows_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 未查到关联告警"
    lines = [
        "| 资源 ID | 告警标题 | 设备名称 | 管理 IP | 发生时间 | 级别 | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {res_id} | {title} | {device} | {ip} | {event_time} | {severity} | {status} |".format(
                res_id=_safe_str(row.get("resId")).replace("|", "\\|"),
                title=_safe_str(row.get("alarmtitle") or "未命名告警").replace("|", "\\|"),
                device=_safe_str(row.get("devName") or "-").replace("|", "\\|"),
                ip=_safe_str(row.get("manageIp") or "-").replace("|", "\\|"),
                event_time=_safe_str(row.get("eventtime") or "-").replace("|", "\\|"),
                severity=_safe_str(row.get("alarmseverity") or "-").replace("|", "\\|"),
                status=_safe_str(row.get("alarmstatus") or "-").replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def render_markdown(result: dict[str, Any]) -> str:
    topology = result.get("topology") or {}
    related_alarms = result.get("relatedAlarms") or {}
    metric_analysis = result.get("metricAnalysis") or {}
    current_alarm = result.get("currentAlarm") or {}
    recent_alarms = related_alarms.get("recent") or {}
    previous_alarms = related_alarms.get("previous") or {}
    alarm_comparison = related_alarms.get("comparison") or {}

    ci_type_summary = "、".join(
        f"{ci_type} {count} 个"
        for ci_type, count in sorted((topology.get("ciTypeCounts") or {}).items(), key=lambda item: item[0])
    ) or "-"
    top_titles = sorted(
        (recent_alarms.get("titleCounts") or {}).items(),
        key=lambda item: item[1],
        reverse=True,
    )[:5]
    top_title_summary = "、".join(f"{title} {count} 条" for title, count in top_titles) or "-"

    lines = [
        "# 告警上下文聚合分析",
        "",
        "## 当前告警",
        f"- 资源 ID（CI ID）：`{current_alarm.get('resId') or '-'}`",
        f"- 根资源类型（ciType）：`{(topology.get('rootResource') or {}).get('ciType') or '-'}`",
        f"- 告警标题：`{current_alarm.get('alarmtitle') or '-'}`",
        f"- 告警等级：`{_ALARM_SEVERITY_MAP.get(str(current_alarm.get('alarmseverity', '')).strip(), current_alarm.get('alarmseverity') or '-')}`",
        f"- 设备名称：`{current_alarm.get('devName') or '-'}`",
        f"- 管理 IP：`{current_alarm.get('manageIp') or '-'}`",
        f"- 告警时间：`{current_alarm.get('eventTime') or '-'}`",
        "",
        "## CMDB 拓扑扩散",
        f"- CMDB 访问方式：`{result.get('cmdbAccessMode') or '-'}`",
        f"- 关系时间窗口：`{result.get('timeWindow', {}).get('beginTime', '-')}` ~ `{result.get('timeWindow', {}).get('endTime', '-')}`",
        f"- 关联资源数：`{topology.get('resourceCount', 0)}`",
        f"- 资源类型分布：{ci_type_summary}",
        "",
        _render_resources_table(topology.get("resources") or []),
        "",
        "## 关联告警汇总",
        f"- 当前窗口关联告警总数：`{recent_alarms.get('total', 0)}`",
        f"- 前一等长窗口关联告警总数：`{previous_alarms.get('total', 0)}`",
        f"- 环比变化：`{alarm_comparison.get('deltaTotal', 0)}` 条",
        f"- 高频告警：{top_title_summary}",
        "",
        "### 当前窗口关联告警",
        _render_alarm_rows_table(recent_alarms.get("previewRows") or []),
        "",
        "### 前一等长窗口关联告警",
        _render_alarm_rows_table(previous_alarms.get("previewRows") or []),
        "",
        "## 指标分析",
        f"- 指标类型：`{metric_analysis.get('metricType') or '-'}`",
        f"- 选中的关键指标数：`{len(metric_analysis.get('selectedMetrics') or [])}`",
        "",
        "### 初步关系判断",
    ]
    lines.extend(f"- {item}" for item in (result.get("findings") or []))
    lines.extend(
        [
            "",
            "### 指标补充结论",
            f"- 详情请结合 `get_metric_definitions.py` 的指标定义与指标值结果继续综合判断。",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="围绕单条告警的资源 ID 聚合拓扑、关联告警和指标信息")
    parser.add_argument("--res-id", required=True, help="当前告警对应的资源 ID（CMDB CI ID）")
    parser.add_argument("--alarm-title", default="", help="当前告警标题")
    parser.add_argument("--device-name", default="", help="当前告警设备名称")
    parser.add_argument("--manage-ip", default="", help="当前告警管理 IP")
    parser.add_argument("--event-time", default="", help="当前告警发生时间，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--alarm-severity", default="", help="告警级别（1=紧急 2=严重 3=普通 4=预警）")
    parser.add_argument("--metric-type", default="", help="可选，显式指定指标类型；不传时优先从根资源 ciType 推断")
    parser.add_argument("--window-minutes", type=int, default=DEFAULT_ALARM_WINDOW_MINUTES, help="最近告警查询窗口，默认以告警时间为中心前后 10 分钟")
    parser.add_argument("--compare-begin-time", default="", help="可选，AI 自定义环比窗口开始时间，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--compare-end-time", default="", help="可选，AI 自定义环比窗口结束时间，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--api-base-url", default=None, help="告警/指标 API 基础地址，默认读取 .env")
    parser.add_argument("--token", default=None, help="Bearer Token，默认读取 .env")
    parser.add_argument("--related-alarm-preview-limit", type=int, default=DEFAULT_RELATED_ALARM_PREVIEW_LIMIT, help="Markdown 预览关联告警条数")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="json", help="输出格式")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = analyze_alarm_context(
            res_id=args.res_id,
            alarm_title=args.alarm_title,
            alarm_severity=args.alarm_severity,
            device_name=args.device_name,
            manage_ip=args.manage_ip,
            event_time=args.event_time,
            metric_type=args.metric_type,
            window_minutes=args.window_minutes,
            compare_begin_time=args.compare_begin_time,
            compare_end_time=args.compare_end_time,
            api_base_url=args.api_base_url,
            token=args.token,
            related_alarm_preview_limit=args.related_alarm_preview_limit,
        )
    except Exception as exc:  # noqa: BLE001
        error_payload = {"code": 500, "msg": str(exc)}
        print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.output == "markdown":
        print(render_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
