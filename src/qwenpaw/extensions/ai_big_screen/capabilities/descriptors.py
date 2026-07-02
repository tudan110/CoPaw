# -*- coding: utf-8 -*-
"""The seven built-in data-capability descriptors.

Each fetcher is a *synchronous* function (the registry wraps it in
``asyncio.to_thread`` + ``wait_for``) that reuses an existing
integration. Fetchers may pre-compute a ``sourceStatus`` hint; the
final honest adjudication happens in ``capabilities.execute_capability``.

Honesty rules enforced here (spec §5/§11):
- ``real-alarms`` passes ``raise_on_error=True`` so backend failures
  propagate and become ``failed`` instead of an empty "live" payload;
- ``workorders`` blocks any non-live provider source — no sample data;
- the big-screen path never routes through integrations with a
  sample-data fallback (kept out of this module by design and pinned
  by a unit test).
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from qwenpaw.extensions.ai_big_screen.capabilities.fields import (
    CAPABILITY_FIELD_DEFINITIONS,
    DEFAULT_CAPABILITY_FIELDS,
    columns_for_capability_fields,
    safe_int,
)

Fetcher = Callable[[Mapping[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# generic payload helpers (ported from the legacy monolith)
# ---------------------------------------------------------------------------


def _build_metric_rows(
    data: Any,
    *,
    prefix: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            label = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                rows.append(
                    {"name": label, "value": "--" if value is None else value},
                )
            elif isinstance(value, list):
                rows.append({"name": label, "value": len(value)})
            elif isinstance(value, dict):
                rows.extend(
                    _build_metric_rows(
                        value,
                        prefix=label,
                        limit=limit - len(rows),
                    ),
                )
            if len(rows) >= limit:
                break
    elif isinstance(data, list):
        for index, item in enumerate(data[:limit]):
            if isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("title")
                    or item.get("resName")
                    or f"item-{index + 1}"
                )
                value = (
                    item.get("value")
                    or item.get("count")
                    or item.get("total")
                    or item.get("num")
                    or 0
                )
                rows.append({"name": str(name), "value": value})
            else:
                rows.append({"name": f"item-{index + 1}", "value": str(item)})
    return rows[:limit]


def _first_numeric_value(data: Any) -> int | float | None:
    if isinstance(data, (int, float)):
        return data
    if isinstance(data, dict):
        for key in (
            "total",
            "count",
            "assetTotal",
            "resourceTotal",
            "hostTotal",
            "value",
        ):
            value = data.get(key)
            if isinstance(value, (int, float)):
                return value
        for value in data.values():
            nested = _first_numeric_value(value)
            if nested is not None:
                return nested
    if isinstance(data, list):
        return len(data)
    return None


def _build_topology_nodes(data: Any) -> list[dict[str, str]]:
    rows = _build_metric_rows(data, limit=18)
    return [
        {
            "name": str(row.get("name") or "--"),
            "status": "warning" if index == 0 else "normal",
        }
        for index, row in enumerate(rows)
    ]


def _envelope_source_status(envelope: Any) -> str:
    if not isinstance(envelope, dict):
        return "unavailable"
    code = safe_int(envelope.get("code"), 200)
    if code >= 400:
        return "unavailable"
    data = envelope.get("data")
    if data in (None, [], {}):
        return "empty"
    return "live"


# ---------------------------------------------------------------------------
# system-logs (incl. risk-summary analysis mode)
# ---------------------------------------------------------------------------

_LEVEL_SCORES = {
    "critical": 95,
    "fatal": 92,
    "error": 82,
    "err": 78,
    "warning": 58,
    "warn": 58,
}

_KEYWORD_SCORES = {
    "高危": 92,
    "严重": 86,
    "攻击": 90,
    "注入": 90,
    "漏洞": 88,
    "异常": 72,
    "失败": 68,
    "错误": 74,
    "超时": 70,
    "死锁": 84,
    "崩溃": 88,
    "critical": 95,
    "fatal": 92,
    "panic": 90,
    "exception": 78,
    "timeout": 70,
    "failed": 68,
    "failure": 68,
    "oom": 86,
    "deadlock": 84,
    "attack": 90,
    "inject": 90,
}


def _score_system_log_risk(
    row: Mapping[str, Any],
    query_params: Mapping[str, Any],
) -> dict[str, Any]:
    level = str(row.get("level") or row.get("severity") or "").strip().lower()
    message = str(
        row.get("message") or row.get("content") or row.get("text") or "",
    )
    lowered = message.lower()
    score = 0
    reasons: list[str] = []
    if level in _LEVEL_SCORES:
        score = max(score, _LEVEL_SCORES[level])
        reasons.append(f"级别 {level.upper()}")

    for keyword, keyword_score in _KEYWORD_SCORES.items():
        if keyword.lower() in lowered or keyword in message:
            score = max(score, keyword_score)
            reasons.append(keyword)

    risk_keywords = query_params.get("riskKeywords")
    if isinstance(risk_keywords, list):
        for keyword in risk_keywords:
            normalized = str(keyword or "").strip()
            if normalized and (
                normalized.lower() in lowered or normalized in message
            ):
                score = max(score, 76)
                reasons.append(normalized)

    if score < 55:
        return {"riskScore": 0, "riskLevel": "normal", "riskReason": ""}
    if score >= 88:
        risk_level = "critical"
    elif score >= 72:
        risk_level = "high"
    else:
        risk_level = "medium"
    deduped_reasons: list[str] = []
    for reason in reasons:
        if reason and reason not in deduped_reasons:
            deduped_reasons.append(reason)
    return {
        "riskScore": score,
        "riskLevel": risk_level,
        "riskReason": " / ".join(deduped_reasons[:4]) or "风险日志",
    }


def _build_system_log_risk_summary(
    *,
    rows: list[Any],
    limit: int,
    query_params: Mapping[str, Any],
) -> dict[str, Any]:
    risk_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        risk = _score_system_log_risk(row, query_params)
        if risk["riskScore"] <= 0:
            continue
        risk_rows.append({**row, **risk})
    risk_rows.sort(
        key=lambda item: int(item.get("riskScore") or 0),
        reverse=True,
    )
    top_rows = risk_rows[:limit]
    max_score = max(
        (int(item.get("riskScore") or 0) for item in top_rows),
        default=0,
    )
    return {
        "visualKind": "risk-pulse",
        "analysisMode": "risk_summary",
        "value": max_score,
        "unit": "风险分",
        "riskScore": max_score,
        "riskItems": top_rows,
        "total": len(risk_rows),
        "trend": f"识别 {len(risk_rows)} 条高危日志线索",
        "summary": (
            "未识别到明显高危日志"
            if not risk_rows
            else (
                f"最高风险 {max_score}，"
                f"请优先关注前 {min(len(top_rows), 5)} 条日志。"
            )
        ),
        "columns": [
            {"key": "time", "label": "时间"},
            {"key": "level", "label": "级别"},
            {"key": "riskScore", "label": "风险分"},
            {"key": "riskReason", "label": "风险原因"},
            {"key": "message", "label": "日志内容"},
        ],
        "rows": top_rows,
    }


def fetch_system_logs(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations import nightingale_logs

    limit = max(1, min(200, safe_int(query_params.get("limit"), 50)))
    lookback_minutes = max(
        1,
        min(24 * 60, safe_int(query_params.get("lookbackMinutes"), 15)),
    )
    search_strategy = str(
        query_params.get("searchStrategy")
        or query_params.get("search_strategy")
        or "single_window",
    ).strip()
    time_mode = str(
        query_params.get("timeMode") or query_params.get("time_mode") or "",
    ).strip()
    max_lookback_days = max(
        1,
        min(365, safe_int(query_params.get("maxLookbackDays"), 45)),
    )
    payload = nightingale_logs.query_nightingale_logs(
        limit=limit,
        lookback_minutes=lookback_minutes,
        query=str(query_params.get("query") or ""),
        from_time=str(
            query_params.get("fromTime")
            or query_params.get("from_time")
            or "",
        ),
        to_time=str(
            query_params.get("toTime") or query_params.get("to_time") or "",
        ),
        search_strategy=search_strategy,
        max_lookback_days=max_lookback_days,
    )
    rows = list(payload.get("rows") or [])
    columns = columns_for_capability_fields(
        "system-logs",
        query_params.get("fields"),
    )
    analysis_mode = str(
        query_params.get("analysisMode")
        or query_params.get("analysis_mode")
        or "",
    ).strip()
    resolved_time_range = (
        payload.get("resolvedTimeRange")
        if isinstance(payload.get("resolvedTimeRange"), dict)
        else {}
    )
    if search_strategy == "latest_non_empty":
        trend = (
            f"最近有日志窗口：{resolved_time_range.get('from') or '--'} ~ "
            f"{resolved_time_range.get('to') or '--'}"
            if rows
            else f"近 {max_lookback_days} 天未命中智观日志"
        )
    else:
        trend = f"最近 {lookback_minutes} 分钟智观日志"
    data = {
        "source": nightingale_logs.LOG_SOURCE,
        "sourceStatus": str(
            payload.get("sourceStatus") or ("live" if rows else "empty"),
        ),
        "lookbackMinutes": lookback_minutes,
        "timeMode": time_mode
        or (
            "latest_non_empty"
            if search_strategy == "latest_non_empty"
            else "relative"
        ),
        "searchStrategy": str(
            payload.get("searchStrategy") or search_strategy,
        ),
        "maxLookbackDays": max_lookback_days,
        "resolvedTimeRange": resolved_time_range,
        "attemptedTimeRanges": copy.deepcopy(
            payload.get("attemptedTimeRanges") or [],
        ),
        "total": int(payload.get("total") or len(rows)),
        "value": int(payload.get("total") or len(rows)),
        "unit": "条",
        "trend": trend,
        "message": str(payload.get("message") or ""),
        "columns": columns,
        "rows": rows[:limit],
    }
    if analysis_mode == "risk_summary":
        data.update(
            _build_system_log_risk_summary(
                rows=rows,
                limit=limit,
                query_params=query_params,
            ),
        )
    return data


# ---------------------------------------------------------------------------
# real-alarms — honest failure propagation (raise_on_error=True)
# ---------------------------------------------------------------------------

# "Query all" window when the conversation gives no time. hisAlarmList needs a
# begin/end, so "all" is expressed as a very wide window rather than an omitted
# filter (~10 years comfortably covers the platform's retained history).
_ALARM_QUERY_ALL_MINUTES = 10 * 366 * 24 * 60


def fetch_real_alarms(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations import working_secrets

    working_secrets.ensure_working_secrets_loaded()
    from qwenpaw.extensions.integrations import portal_real_alarms

    limit = max(1, min(200, safe_int(query_params.get("limit"), 100)))
    # No default recency window: when the conversation did not specify a time,
    # query the full alarm history (a very wide window, since hisAlarmList
    # requires a begin/end). The LLM fills ``lookbackMinutes`` only when the
    # user actually mentions a range ("最近2小时" -> 120), and it is not
    # capped — honour whatever was asked for.
    raw_lookback = query_params.get("lookbackMinutes")
    has_window = str(raw_lookback if raw_lookback is not None else "").strip()
    has_window = has_window not in ("", "0")
    if has_window:
        lookback_minutes = max(
            1,
            safe_int(raw_lookback, _ALARM_QUERY_ALL_MINUTES),
        )
    else:
        lookback_minutes = _ALARM_QUERY_ALL_MINUTES
    alarm_status = str(
        query_params.get("alarmStatus")
        or query_params.get("alarmstatus")
        or "",
    ).strip()
    payload = portal_real_alarms.query_portal_real_alarms(
        limit=limit,
        lookback_minutes=lookback_minutes,
        alarm_status=alarm_status or None,
        raise_on_error=True,
    )
    rows = list(payload.get("items") or [])
    # best-effort live duration per alarm (eventTime → now); the row
    # already carries the rich display fields from _normalize_alarm_row
    now = datetime.now(timezone.utc)
    for alarm in rows:
        if isinstance(alarm, dict) and not alarm.get("duration"):
            duration = portal_real_alarms.format_alarm_duration(
                str(alarm.get("eventTime") or ""),
                now=now,
            )
            if duration:
                alarm["duration"] = duration
    columns = columns_for_capability_fields(
        "real-alarms",
        query_params.get("fields"),
    )
    trend = f"最近 {lookback_minutes} 分钟告警" if has_window else "全部告警"
    return {
        "source": "portal-real-alarm-api",
        "sourceStatus": "live" if rows else "empty",
        "lookbackMinutes": lookback_minutes if has_window else None,
        "total": int(payload.get("total") or len(rows)),
        "value": int(payload.get("total") or len(rows)),
        "unit": "起",
        "trend": trend,
        "columns": columns,
        "rows": rows[:limit],
    }


# ---------------------------------------------------------------------------
# cmdb / workorders / alarm-top5 / topology / capability-gap
# ---------------------------------------------------------------------------


def fetch_cmdb_resources(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations import portal_monitoring_overview

    envelope = portal_monitoring_overview.query_asset_overview()
    source_status = _envelope_source_status(envelope)
    data = envelope.get("data") if isinstance(envelope, dict) else None
    message = (
        str(envelope.get("msg") or "接口不可用")
        if isinstance(envelope, dict)
        else "接口不可用"
    )
    rows = _build_metric_rows(data)
    columns = columns_for_capability_fields(
        "cmdb-resources",
        query_params.get("fields"),
    )
    value = _first_numeric_value(data)
    if value is None:
        value = len(rows)
    return {
        "source": "portal-asset-overview-api",
        "sourceStatus": source_status,
        "scope": str(query_params.get("scope") or "all"),
        "value": value,
        "unit": "项",
        "trend": (
            "来自 CMDB/资源概览接口" if source_status == "live" else message
        ),
        "message": "" if source_status == "live" else message,
        "columns": columns,
        "rows": rows,
        "raw": data,
    }


def fetch_workorders(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations import order_workflow

    limit = max(1, min(100, safe_int(query_params.get("limit"), 20)))
    time_range = str(query_params.get("timeRange") or "today")
    columns = columns_for_capability_fields(
        "workorders",
        query_params.get("fields"),
    )
    # 大屏对时延敏感：跳板半死时对同一条坏链路 urllib 20s + curl 兜底
    # 20s = 40s，而能力层 30s 就判超时、线程还在白烧。缩短到 6s 并禁掉
    # curl 兜底，同场景下每组件 ≤12s（2 次调用×6s）内诚实 failed。
    payload = order_workflow.query_order_workorders(
        limit=limit,
        time_range=time_range,
        timeout_seconds=6,
        disable_curl_fallback=True,
    )
    provider_source = str(payload.get("source") or "")
    if provider_source != "live":
        return {
            "source": order_workflow.ORDER_SOURCE,
            "sourceStatus": "unavailable",
            "timeRange": time_range,
            "total": 0,
            "value": 0,
            "unit": "单",
            "trend": "传统工单系统未返回实时数据",
            "message": "工单能力未返回实时来源，已阻断 mock/sample 数据展示。",
            "columns": columns,
            "rows": [],
        }
    rows = list(payload.get("items") or [])
    total = int(payload.get("total") or len(rows))
    return {
        "source": order_workflow.ORDER_SOURCE,
        "sourceStatus": "live" if rows else "empty",
        "timeRange": time_range,
        "total": total,
        "value": total,
        "unit": "单",
        "trend": "今日工单" if time_range == "today" else "工单查询结果",
        "stats": copy.deepcopy(payload.get("stats") or {}),
        "columns": columns,
        "rows": rows[:limit],
    }


def fetch_alarm_top5(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations import portal_monitoring_overview

    limit = max(1, min(20, safe_int(query_params.get("limit"), 5)))
    envelope = portal_monitoring_overview.query_alarm_top5()
    data = envelope.get("data") if isinstance(envelope, dict) else None
    rows = _build_metric_rows(data)[:limit]
    return {
        "source": "portal-alarm-statistics-api",
        "sourceStatus": _envelope_source_status(envelope),
        "columns": [
            {"key": "name", "label": "对象"},
            {"key": "value", "label": "数量"},
        ],
        "rows": rows,
        "categories": [str(row.get("name") or "") for row in rows],
        "series": [safe_int(row.get("value"), 0) for row in rows],
    }


def fetch_topology_impact(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations import portal_monitoring_overview

    envelope = portal_monitoring_overview.query_topology()
    data = envelope.get("data") if isinstance(envelope, dict) else None
    nodes = _build_topology_nodes(data)
    return {
        "source": "portal-topology-api",
        "sourceStatus": _envelope_source_status(envelope),
        "scope": str(query_params.get("scope") or "active"),
        "nodes": nodes,
        "raw": data,
    }


def fetch_capability_gap(query_params: Mapping[str, Any]) -> dict[str, Any]:
    requested_data = str(
        query_params.get("requestedData") or "未接入数据",
    ).strip()
    reason = str(
        query_params.get("reason") or "当前没有可复用的真实取数能力",
    ).strip()
    suggested_skill = (
        str(query_params.get("suggestedSkillName") or "--").strip() or "--"
    )
    suggested_api = (
        str(query_params.get("suggestedApi") or "--").strip() or "--"
    )
    required_inputs = query_params.get("requiredInputs")
    validation_plan = str(
        query_params.get("validationPlan")
        or "接入真实接口后以 sourceStatus=live 的响应作为展示依据。",
    ).strip()
    rows = [
        {"name": "数据对象", "value": requested_data},
        {"name": "缺口原因", "value": reason},
        {"name": "建议 skill", "value": suggested_skill},
        {"name": "建议接口", "value": suggested_api},
        {
            "name": "所需输入",
            "value": (
                "、".join(str(item) for item in required_inputs)
                if isinstance(required_inputs, list)
                else str(
                    required_inputs
                    or "数据源地址、鉴权方式、查询参数、返回字段映射",
                )
            ),
        },
        {"name": "校验方式", "value": validation_plan},
    ]
    return {
        "source": "ai-capability-planning",
        "sourceStatus": "unavailable",
        "message": (
            "当前没有可复用的真实数据能力，已生成接入方案，未展示模拟数据。"
        ),
        "columns": [
            {"key": "name", "label": "事项"},
            {"key": "value", "label": "方案"},
        ],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# capability metadata (AI-facing catalog, legacy wire shape preserved)
# ---------------------------------------------------------------------------

CAPABILITY_METADATA: list[dict[str, Any]] = [
    {
        "id": "system-logs",
        "name": "系统日志",
        "domain": "log",
        "description": (
            "查询智观日志服务接入的业务/应用/系统日志，默认最近 15 分钟；"
            "不是 QwenPaw 智能体运行日志、控制台输出、本机 /var/log "
            "或会话历史。"
        ),
        "inputSchema": {
            "lookbackMinutes": 15,
            "limit": 50,
            "query": "",
            "analysisMode": "",
            "riskKeywords": [],
            "fromTime": "",
            "toTime": "",
            "timeMode": "relative",
            # Default to latest_non_empty: try the requested window first,
            # then walk back to the most recent window that actually has
            # logs (and label the range), so a quiet index shows real
            # historical data instead of an empty screen.
            "searchStrategy": "latest_non_empty",
            "maxLookbackDays": 45,
            "fields": DEFAULT_CAPABILITY_FIELDS["system-logs"],
        },
        "outputSchema": {
            "columns": "array",
            "rows": "array",
            "sourceStatus": "string",
        },
        "availableFields": CAPABILITY_FIELD_DEFINITIONS["system-logs"],
        "supportedVisuals": [
            "table",
            "text",
            "risk-pulse",
            "status-stream",
            # D-max palette (P1 renderer) — keeps legacy entries first so
            # the semantic fast-path default visual stays unchanged.
            "alarm-stream",
            "timeline",
            "heatmap",
            "metric-kpi",
            "flip-number",
            "composed",
        ],
        "permissionScope": "nightingale-log:read",
        "cachePolicy": {"ttlSeconds": 30},
        "refreshPolicy": {"intervalSeconds": 30},
        "dataSource": "zhiguan-log-service",
        "skillName": "nightingale-log",
        "examplePrompts": [
            "最近15分钟系统日志",
            "看一下智观日志",
            "最近业务日志",
        ],
    },
    {
        "id": "real-alarms",
        "name": "系统告警",
        "domain": "alarm",
        "description": (
            "调用资源告警接口读取告警。默认查询全部告警；仅当用户在对话中明确"
            "提到时间范围时，才填写 lookbackMinutes（最近 N 分钟，例如"
            "「最近2小时」=120、「最近7天」=10080），不提时间就留空查全部。"
        ),
        "inputSchema": {
            "limit": 100,
            "lookbackMinutes": 0,
            "alarmStatus": "",
            "fields": DEFAULT_CAPABILITY_FIELDS["real-alarms"],
        },
        "outputSchema": {
            "columns": "array",
            "rows": "array",
            "total": "number",
        },
        "availableFields": CAPABILITY_FIELD_DEFINITIONS["real-alarms"],
        "supportedVisuals": [
            "table",
            "metric-card",
            "bar-chart",
            "status-stream",
            "risk-pulse",
            "metric-kpi",
            "flip-number",
            "donut",
            "gauge",
            "line-chart",
            "area-chart",
            "alarm-stream",
            "top-n",
            "timeline",
            "heatmap",
            "composed",
        ],
        "permissionScope": "alarm:read",
        "cachePolicy": {"ttlSeconds": 60},
        "refreshPolicy": {"intervalSeconds": 60},
        "dataSource": "portal-real-alarm-api",
        "examplePrompts": [
            "查询告警信息",
            "全部系统告警",
            "最近2小时告警",
        ],
    },
    {
        "id": "cmdb-resources",
        "name": "CMDB 资源信息",
        "domain": "resource",
        "description": "调用资源/资产概览接口读取 CMDB 资源统计和资源状态。",
        "inputSchema": {
            "scope": "all",
            "fields": DEFAULT_CAPABILITY_FIELDS["cmdb-resources"],
        },
        "outputSchema": {
            "value": "number",
            "unit": "string",
            "rows": "array",
        },
        "availableFields": CAPABILITY_FIELD_DEFINITIONS["cmdb-resources"],
        "supportedVisuals": [
            "metric-card",
            "table",
            "bar-chart",
            "metric-kpi",
            "flip-number",
            "top-n",
            "donut",
            "gauge",
            "liquid-ball",
            "bar3d",
            "composed",
        ],
        "permissionScope": "resource:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-asset-overview-api",
        "examplePrompts": ["CMDB资源信息", "资产资源概览"],
    },
    {
        "id": "workorders",
        "name": "工单信息",
        "domain": "workorder",
        "description": (
            "调用 order-workflow 传统工单系统能力读取今日工单统计和"
            "待办工单；不使用告警 mock 数据伪装工单。"
        ),
        "inputSchema": {
            "timeRange": "today",
            "limit": 20,
            "fields": DEFAULT_CAPABILITY_FIELDS["workorders"],
        },
        "outputSchema": {
            "columns": "array",
            "rows": "array",
            "total": "number",
        },
        "availableFields": CAPABILITY_FIELD_DEFINITIONS["workorders"],
        "supportedVisuals": [
            "table",
            "metric-card",
            "bar-chart",
            "status-stream",
            "metric-kpi",
            "flip-number",
            "donut",
            "gauge",
            "top-n",
            "timeline",
            "funnel",
            "alarm-stream",
            "composed",
        ],
        "permissionScope": "workorder:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-order-workflow-api",
        "skillName": "order-workflow",
        "examplePrompts": ["今日工单", "待处理工单", "工单处置情况"],
    },
    {
        "id": "alarm-top5",
        "name": "告警对象 Top5",
        "domain": "alarm",
        "description": "调用告警统计接口读取告警对象排行。",
        "inputSchema": {"limit": 5},
        "outputSchema": {
            "categories": "array",
            "series": "array",
            "rows": "array",
        },
        "supportedVisuals": [
            "bar-chart",
            "table",
            "top-n",
            "donut",
            "bar3d",
            "composed",
        ],
        "permissionScope": "alarm:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-alarm-statistics-api",
        "examplePrompts": ["告警排行", "告警最多的资源"],
    },
    {
        "id": "topology-impact",
        "name": "拓扑影响范围",
        "domain": "topology",
        "description": "调用拓扑接口读取资源拓扑和影响关系。",
        "inputSchema": {"scope": "active"},
        "outputSchema": {"nodes": "array"},
        "supportedVisuals": ["topology", "table", "graph", "composed"],
        "permissionScope": "topology:read",
        "cachePolicy": {"ttlSeconds": 180},
        "refreshPolicy": {"intervalSeconds": 180},
        "dataSource": "portal-topology-api",
        "examplePrompts": ["拓扑影响范围", "资源链路影响"],
    },
    {
        "id": "web-live-data",
        "name": "实时公开数据",
        "domain": "public",
        "description": (
            "联网实时查询公开互联网信息（城市天气、汇率、新闻资讯检索、"
            "百科常识等公开数据），返回真实检索结果并标注来源。"
            "当用户需要的数据是公开信息、且不属于已接入的内部运维能力时"
            "使用本能力（queryParams.query 写明要查什么，如“南京天气”）。"
            "内部系统/业务数据未接入时不要用本能力，请用 capability-gap。"
        ),
        "inputSchema": {"query": "", "kind": "auto"},
        "outputSchema": {
            "rows": "array",
            "columns": "array",
            "value": "number",
            "sourceStatus": "string",
        },
        "supportedVisuals": [
            "text",
            "table",
            "metric-card",
            "metric-kpi",
            "flip-number",
            "line-chart",
            "area-chart",
            "alarm-stream",
            "top-n",
            "composed",
        ],
        "permissionScope": "public-web:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 300},
        "dataSource": "web-live-providers",
        "skillName": "",
        "examplePrompts": ["南京天气", "美元兑人民币汇率", "搜索最新AI资讯"],
    },
    {
        "id": "capability-gap",
        "name": "待接入数据能力",
        "domain": "planning",
        "description": (
            "当用户提出的数据对象无法由已接入 skill/API 真实查询时使用。"
            "只输出取数方案、所需接口和接入建议，不展示编造业务数据。"
        ),
        "inputSchema": {
            "requestedData": "",
            "reason": "",
            "suggestedSkillName": "",
            "suggestedApi": "",
            "requiredInputs": [],
            "validationPlan": "",
        },
        "outputSchema": {
            "columns": "array",
            "rows": "array",
            "sourceStatus": "string",
        },
        "supportedVisuals": ["table", "text"],
        "permissionScope": "capability-plan:read",
        "cachePolicy": {"ttlSeconds": 0},
        "refreshPolicy": {"intervalSeconds": 0},
        "dataSource": "ai-capability-planning",
        "skillName": "",
        "examplePrompts": ["需要还没接入的数据", "帮我设计新的取数逻辑"],
    },
]


# Functional domain + backing connection per built-in capability, so the
# config center can group by domain (告警/工单/CMDB/日志…) and show which
# connection each capability needs. Injected into CAPABILITY_METADATA below.
_CAPABILITY_CLASSIFICATION: dict[str, tuple[str, str]] = {
    "system-logs": ("logs", "n9e"),
    "real-alarms": ("alarm", "inoe"),
    "cmdb-resources": ("cmdb", "inoe"),
    "workorders": ("workorder", "order"),
    "alarm-top5": ("alarm", "inoe"),
    "topology-impact": ("cmdb", "inoe"),
    "web-live-data": ("web", ""),
    "capability-gap": ("", ""),
}

for _meta in CAPABILITY_METADATA:
    _category, _connection = _CAPABILITY_CLASSIFICATION.get(
        str(_meta.get("id") or ""),
        ("", ""),
    )
    _meta.setdefault("category", _category)
    _meta.setdefault("connection", _connection)


def fetch_web_live(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.ai_big_screen.capabilities import web_live

    return web_live.fetch_web_live_data(query_params)


FETCHERS: dict[str, Fetcher] = {
    "system-logs": fetch_system_logs,
    "real-alarms": fetch_real_alarms,
    "cmdb-resources": fetch_cmdb_resources,
    "workorders": fetch_workorders,
    "alarm-top5": fetch_alarm_top5,
    "topology-impact": fetch_topology_impact,
    "web-live-data": fetch_web_live,
    "capability-gap": fetch_capability_gap,
}
