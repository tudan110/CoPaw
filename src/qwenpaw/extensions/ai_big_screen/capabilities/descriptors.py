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


# T-017: raw payload keys like "resourceTypeStats.硬件设备.totalCount" made
# metric tables unreadable. Pure envelope segments are dropped, known leaf
# keys are translated, and the remaining path joins with "·"; unknown keys
# pass through untranslated so rows stay honest rather than pretty-but-wrong.
_METRIC_ENVELOPE_SEGMENTS = {
    "resourceTypeStats",
    "hostResourceTop",
    "data",
    "stats",
    "statistics",
}

_METRIC_SEGMENT_LABELS = {
    "totalCount": "总数",
    "normalCount": "正常",
    "alarmCount": "告警",
    "abnormalCount": "异常",
    "onlineCount": "在线",
    "offlineCount": "离线",
    "totalResources": "资源总数",
    "healthRate": "健康率",
    "healthStatus": "健康状态",
    "usageRate": "使用率",
    "resourceName": "资源名称",
    "queryTime": "查询时间",
    "physical": "物理机",
    "virtual": "虚拟机",
    "cpuTop5": "CPU TOP5",
    "memoryTop5": "内存 TOP5",
    "storageTop5": "存储 TOP5",
}


def _metric_row_label(prefix: str, key: str) -> str:
    segment = _METRIC_SEGMENT_LABELS.get(key, str(key))
    if not prefix:
        return segment
    return f"{prefix}·{segment}"


def _build_metric_rows(
    data: Any,
    *,
    prefix: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            key_text = str(key)
            if isinstance(value, dict):
                # Envelope containers ("resourceTypeStats") carry no
                # meaning of their own — flatten them out of the label.
                child_prefix = (
                    prefix
                    if key_text in _METRIC_ENVELOPE_SEGMENTS
                    else _metric_row_label(prefix, key_text)
                )
                rows.extend(
                    _build_metric_rows(
                        value,
                        prefix=child_prefix,
                        limit=limit - len(rows),
                    ),
                )
                if len(rows) >= limit:
                    break
                continue
            label = _metric_row_label(prefix, key_text)
            if isinstance(value, str) and value in prefix.split("·"):
                # Echo attribute (e.g. resourceTypeName repeating the
                # parent segment) — pure noise, save the row budget.
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                rows.append(
                    {"name": label, "value": "--" if value is None else value},
                )
            elif isinstance(value, list):
                rows.append({"name": label, "value": len(value)})
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
            if normalized and (normalized.lower() in lowered or normalized in message):
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
            query_params.get("fromTime") or query_params.get("from_time") or "",
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
        query_params.get("analysisMode") or query_params.get("analysis_mode") or "",
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
            "latest_non_empty" if search_strategy == "latest_non_empty" else "relative"
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
        query_params.get("alarmStatus") or query_params.get("alarmstatus") or "",
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


def _shape_asset_overview_rows(data: Any) -> list[dict[str, Any]]:
    """Typed per-resource-type rows from the asset-overview payload.

    Returns ``[]`` when the payload doesn't match the known
    ``resourceTypeStats`` schema so the caller can fall back to the
    generic metric walk.
    """
    if not isinstance(data, dict):
        return []
    stats = data.get("resourceTypeStats")
    if not isinstance(stats, dict) or not stats:
        return []
    rows: list[dict[str, Any]] = []
    for type_name, entry in stats.items():
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "type": str(entry.get("resourceTypeName") or type_name),
                "total": safe_int(entry.get("totalCount"), 0),
                "normal": safe_int(entry.get("normalCount"), 0),
                "alarm": safe_int(entry.get("alarmCount"), 0),
            },
        )
    return rows


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
    rows = _shape_asset_overview_rows(data)
    if rows:
        columns = columns_for_capability_fields(
            "cmdb-resources",
            query_params.get("fields"),
        )
        value = _first_numeric_value(
            (data or {}).get("totalResources") if isinstance(data, dict) else None,
        )
        if value is None:
            value = sum(safe_int(row.get("total"), 0) for row in rows)
        health_rate = (data or {}).get("healthRate")
        trend = "来自 CMDB/资源概览接口"
        if isinstance(health_rate, (int, float)):
            trend = f"资源健康率 {health_rate}%"
    else:
        # Unknown payload shape — generic metric walk keeps name/value
        # semantics, so the columns must follow the rows, not the
        # capability field catalog.
        rows = _build_metric_rows(data)
        columns = [
            {"key": "name", "label": "指标"},
            {"key": "value", "label": "值"},
        ]
        value = _first_numeric_value(data)
        if value is None:
            value = len(rows)
        trend = "来自 CMDB/资源概览接口" if source_status == "live" else message
    return {
        "source": "portal-asset-overview-api",
        "sourceStatus": source_status,
        "scope": str(query_params.get("scope") or "all"),
        "value": value,
        "unit": "项",
        "trend": trend if source_status == "live" else message,
        "message": "" if source_status == "live" else message,
        "columns": columns,
        "rows": rows,
        "raw": data,
    }


def fetch_system_inspection(
    query_params: Mapping[str, Any],
) -> dict[str, Any]:
    """System-wide inspection view backed by the live resource-health API.

    Per-CI metric inspection requires both a CMDB CI ID and a CI type.  A
    generic dashboard request such as "系统巡检数据" has neither, so it must
    use the real aggregate health endpoint rather than invoking that script
    with empty arguments.
    """
    from qwenpaw.extensions.integrations import portal_monitoring_overview

    envelope = portal_monitoring_overview.query_asset_overview()
    source_status = _envelope_source_status(envelope)
    data = envelope.get("data") if isinstance(envelope, dict) else None
    message = (
        str(envelope.get("msg") or "系统巡检接口不可用")
        if isinstance(envelope, dict)
        else "系统巡检接口不可用"
    )
    rows = _shape_asset_overview_rows(data)
    columns = columns_for_capability_fields(
        "system-inspection",
        query_params.get("fields"),
    )
    total = (
        _first_numeric_value(data.get("totalResources"))
        if isinstance(data, dict)
        else None
    )
    if total is None:
        total = sum(safe_int(row.get("total"), 0) for row in rows)
    health_rate = data.get("healthRate") if isinstance(data, dict) else None
    return {
        "source": "portal-system-inspection-api",
        "sourceStatus": source_status,
        "value": total,
        "total": total,
        "unit": "项",
        "healthRate": health_rate,
        "trend": "系统资源实时巡检概览"
        if source_status == "live"
        else message,
        "message": "" if source_status == "live" else message,
        "columns": columns,
        "rows": rows,
    }


def _map_application_ci(ci: Mapping[str, Any]) -> dict[str, Any]:
    """Veops project CI → big-screen row (same fields the chat answer shows)."""
    op_duty = ci.get("op_duty")
    if isinstance(op_duty, list):
        op_duty_text = "、".join(
            str(item).strip() for item in op_duty if str(item).strip()
        )
    else:
        op_duty_text = str(op_duty or "").strip()
    alarm_raw = ci.get("alarm_status")
    alarm_text = str(alarm_raw).strip() if alarm_raw is not None else ""
    # Only "-1" has a verified meaning (no alarms); anything else passes
    # through raw rather than guessing an enum.
    alarm_label = "无告警" if alarm_text == "-1" else (alarm_text or "--")
    status = str(ci.get("status") or "").strip()
    project_status = str(ci.get("project_status") or "").strip()
    if status and project_status and status != project_status:
        status_text = f"{status}（{project_status}）"
    else:
        status_text = status or project_status or "--"
    ci_id = ci.get("_id")
    return {
        "name": str(ci.get("project_name") or ci.get("name") or "--"),
        "ciId": ci_id if ci_id is not None else "--",
        "appType": str(ci.get("project_type") or "--"),
        "status": status_text,
        "alarmStatus": alarm_label,
        "level": str(ci.get("Level") or ci.get("level") or "--"),
        "opDuty": op_duty_text or "--",
        "installDate": str(ci.get("installation_date") or "--"),
    }


def fetch_cmdb_applications(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations import working_secrets

    # CMDB shares the platform INOE gateway/token with resource import.
    working_secrets.ensure_working_secrets_loaded()
    from qwenpaw.extensions.integrations.zgops_cmdb import application_query

    limit = max(1, min(200, safe_int(query_params.get("limit"), 50)))
    payload = application_query.query_application_cis(limit=limit)
    columns = columns_for_capability_fields(
        "cmdb-applications",
        query_params.get("fields"),
    )
    source_status = str(payload.get("source") or "error")
    if source_status == "error":
        source_status = "unavailable"
    rows = [
        _map_application_ci(item)
        for item in payload.get("items") or []
        if isinstance(item, Mapping)
    ]
    total = safe_int(payload.get("total"), len(rows))
    message = str(payload.get("message") or "")
    return {
        "source": application_query.ZGOPS_SOURCE,
        "sourceStatus": source_status,
        "value": total,
        "unit": "个",
        "trend": "CMDB 应用系统清单" if rows else message,
        "message": "" if source_status == "live" else message,
        "columns": columns,
        "rows": rows[:limit],
        "total": total,
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


_AUTHORED_MAX_ROWS = 200
_AUTHORED_MAX_COLUMNS = 12
_AUTHORED_MAX_CELL_CHARS = 200
_AUTHORED_MAX_TEXT_CHARS = 2000


def _sanitize_authored_content(raw: Any) -> dict[str, Any]:
    """Whitelist-sanitize planner-authored inline content.

    Scalars only, hard size caps — the authored channel opens the
    creation window without opening a code/markup channel (the
    no-arbitrary-code gate applies to authored content too).
    """
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    raw_columns = raw.get("columns")
    if isinstance(raw_columns, list):
        columns: list[dict[str, str]] = []
        for item in raw_columns[:_AUTHORED_MAX_COLUMNS]:
            if isinstance(item, Mapping):
                key = str(item.get("key") or "").strip()[:40]
                label = str(item.get("label") or key).strip()[:40]
            else:
                key = str(item or "").strip()[:40]
                label = key
            if key:
                columns.append({"key": key, "label": label or key})
        if columns:
            out["columns"] = columns
    raw_rows = raw.get("rows")
    if isinstance(raw_rows, list):
        rows: list[dict[str, Any]] = []
        for item in raw_rows[:_AUTHORED_MAX_ROWS]:
            if not isinstance(item, Mapping):
                continue
            row: dict[str, Any] = {}
            for key, value in list(item.items())[:_AUTHORED_MAX_COLUMNS]:
                cell_key = str(key)[:40]
                if isinstance(value, bool):
                    row[cell_key] = value
                elif isinstance(value, (int, float)):
                    row[cell_key] = value
                elif isinstance(value, str):
                    row[cell_key] = value[:_AUTHORED_MAX_CELL_CHARS]
            if row:
                rows.append(row)
        if rows:
            out["rows"] = rows
    raw_metrics = raw.get("metrics")
    if isinstance(raw_metrics, Mapping):
        metrics: dict[str, Any] = {}
        for key, value in list(raw_metrics.items())[:12]:
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                metrics[str(key)[:40]] = value
            elif isinstance(value, str):
                metrics[str(key)[:40]] = value[:_AUTHORED_MAX_CELL_CHARS]
        if metrics:
            out["metrics"] = metrics
    raw_text = raw.get("text")
    if isinstance(raw_text, str) and raw_text.strip():
        out["text"] = raw_text.strip()[:_AUTHORED_MAX_TEXT_CHARS]
    return out


def fetch_authored_content(query_params: Mapping[str, Any]) -> dict[str, Any]:
    """AI-authored inline content — the legitimate creation channel.

    The planner supplies the content itself (queryParams.content); this
    fetcher never touches a network. Provenance is explicit ("AI 生成")
    so authored content can never masquerade as an external data source
    — which is what the no-fake-data gate actually forbids.
    """
    content = _sanitize_authored_content(query_params.get("content"))
    rows = content.get("rows") or []
    columns = content.get("columns") or (
        [{"key": key, "label": key} for key in rows[0].keys()] if rows else []
    )
    metrics = dict(content.get("metrics") or {})
    if content.get("text"):
        metrics.setdefault("text", content["text"])
    has_content = bool(rows or metrics)
    payload: dict[str, Any] = {
        "source": "ai-authored",
        "sourceStatus": "live" if has_content else "empty",
        "trend": "内容由 AI 即席生成（非外部数据源）",
        "message": (
            "" if has_content else "AI 未在规划中内联内容——请把需求描述得更具体后重试。"
        ),
        "columns": columns,
        "rows": rows,
    }
    if metrics:
        payload["metrics"] = metrics
        if "value" not in metrics and len(metrics) == 1:
            payload["value"] = next(iter(metrics.values()))
    return payload


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
    suggested_api = str(query_params.get("suggestedApi") or "--").strip() or "--"
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
                    required_inputs or "数据源地址、鉴权方式、查询参数、返回字段映射",
                )
            ),
        },
        {"name": "校验方式", "value": validation_plan},
    ]
    return {
        "source": "ai-capability-planning",
        "sourceStatus": "unavailable",
        "message": ("当前没有可复用的真实数据能力，已生成接入方案，未展示模拟数据。"),
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
        "name": "CMDB 资源统计",
        "domain": "resource",
        "description": (
            "调用资源/资产概览接口读取 CMDB 资源类型统计"
            "（各类型总数/正常/告警）与健康率；这是统计汇总，"
            "不含应用记录，查询具体应用清单请用 cmdb-applications。"
        ),
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
        "examplePrompts": ["CMDB资源统计", "资产资源概览"],
    },
    {
        "id": "system-inspection",
        "name": "系统资源巡检",
        "domain": "inspection",
        "description": (
            "调用实时资源健康巡检接口，返回各资源类型的巡检总数、正常数、"
            "告警数和整体健康率。适用于未指定单个 CI 的系统巡检/健康概览；"
            "单个资源的指标明细仍需提供 CI ID 与资源类型。"
        ),
        "inputSchema": {
            "fields": DEFAULT_CAPABILITY_FIELDS["system-inspection"],
        },
        "outputSchema": {
            "value": "number",
            "healthRate": "number",
            "rows": "array",
        },
        "availableFields": CAPABILITY_FIELD_DEFINITIONS["system-inspection"],
        "supportedVisuals": [
            "table", "metric-card", "metric-kpi", "flip-number", "donut",
            "bar-chart", "gauge", "liquid-ball", "composed",
        ],
        "permissionScope": "inspection:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-system-inspection-api",
        "examplePrompts": ["系统巡检数据", "系统健康巡检", "资源巡检概览"],
    },
    {
        "id": "cmdb-applications",
        "name": "CMDB 应用信息",
        "domain": "resource",
        "description": (
            "调用 Veops CMDB 查询应用系统（project CI）的真实清单："
            "应用名称、CI ID、应用类型、应用状态、告警状态、等级、"
            "运维负责人、纳管时间。「应用信息/应用列表/应用系统」"
            "类请求用这个，而不是 cmdb-resources 的类型统计。"
        ),
        "inputSchema": {
            "limit": 50,
            "fields": DEFAULT_CAPABILITY_FIELDS["cmdb-applications"],
        },
        "outputSchema": {
            "columns": "array",
            "rows": "array",
            "total": "number",
        },
        "availableFields": CAPABILITY_FIELD_DEFINITIONS["cmdb-applications"],
        "supportedVisuals": [
            "table",
            "metric-card",
            "metric-kpi",
            "flip-number",
            "top-n",
            "status-stream",
            "donut",
            "bar-chart",
            "composed",
        ],
        "permissionScope": "resource:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "zgops-veops-cmdb-api",
        "examplePrompts": [
            "CMDB应用信息表",
            "应用系统列表",
            "查询应用状态",
        ],
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
    {
        "id": "ai-authored-content",
        "name": "AI 创作内容",
        "domain": "authored",
        "description": (
            "由规划模型即席生成的静态/可计算内容(乘法表、对照表、口诀、"
            "公式/知识说明等),内容随组件内联在 queryParams.content,"
            "零外部访问,来源明示为 AI 生成。绝不可用于告警/工单/CMDB/"
            "资源/日志/监控等运维数据——运维数据必须走真实数据能力。"
        ),
        "inputSchema": {"content": {}},
        "outputSchema": {
            "columns": "array",
            "rows": "array",
            "metrics": "object",
        },
        "supportedVisuals": [
            "table",
            "text",
            "metric-kpi",
            "flip-number",
            "bar-chart",
            "line-chart",
            "donut",
            "composed",
        ],
        "permissionScope": "authored:read",
        "cachePolicy": {"ttlSeconds": 0},
        "refreshPolicy": {"intervalSeconds": 0},
        "dataSource": "llm-authored",
        "examplePrompts": ["写一个99乘法表", "做一张常用端口对照表"],
    },
    {
        "id": "self-monitor-overview",
        "name": "智观AI 自监控",
        "domain": "monitor",
        "description": (
            "读取智观AI 自身的四层健康(体验/应用/依赖/资源)、降级与 429 "
            "计数、worker 存活与拨测状态。数据来自本地自监控 SQLite,"
            "无需任何外部连接。"
        ),
        "inputSchema": {"windowS": 3600, "limit": 20},
        "outputSchema": {
            "metrics": "object",
            "rows": "array",
            "categories": "array",
            "series": "array",
        },
        "supportedVisuals": [
            "metric-card",
            "table",
            "line-chart",
            "bar-chart",
            "gauge",
            "composed",
        ],
        "permissionScope": "self-monitor:read",
        "cachePolicy": {"ttlSeconds": 30},
        "refreshPolicy": {"intervalSeconds": 30},
        "dataSource": "self-monitor-sqlite",
        "examplePrompts": [
            "智观AI 自己的健康大屏",
            "系统自监控情况",
            "自监控四层健康",
        ],
    },
]


# Functional domain + backing connection per built-in capability, so the
# config center can group by domain (告警/工单/CMDB/日志…) and show which
# connection each capability needs. Injected into CAPABILITY_METADATA below.
_CAPABILITY_CLASSIFICATION: dict[str, tuple[str, str]] = {
    "system-logs": ("logs", "n9e"),
    "real-alarms": ("alarm", "inoe"),
    "cmdb-resources": ("cmdb", "inoe"),
    "cmdb-applications": ("cmdb", "zgops"),
    "workorders": ("workorder", "order"),
    "alarm-top5": ("alarm", "inoe"),
    "topology-impact": ("cmdb", "inoe"),
    "web-live-data": ("web", ""),
    "capability-gap": ("", ""),
    "ai-authored-content": ("authored", ""),
    "self-monitor-overview": ("monitor", "self"),
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


def fetch_self_monitor_overview(
    query_params: Mapping[str, Any],
) -> dict[str, Any]:
    """智观AI self-monitoring: four-layer vitals from the local rollup.

    Reads the self-monitor SQLite directly (no HTTP hop); honest
    ``sourceStatus`` per the capability contract.
    """
    import time as _time

    try:
        from qwenpaw.self_monitor.store import SelfMonitorStore

        window_s = max(300, min(86400 * 7, safe_int(query_params.get("windowS"), 3600)))
        store = SelfMonitorStore()
        now = _time.time()
        since = now - window_s

        latest = store.latest_samples(max_age_s=180.0)
        if not latest:
            return {
                "source": "self-monitor-sqlite",
                "sourceStatus": "empty",
                "message": "自监控暂无新鲜样本(后端刚启动或采集被禁用)",
                "rows": [],
                "columns": [],
            }

        degrade = store.counter_delta("qwenpaw_degrade_events_total", since=since)
        llm_429 = store.counter_delta(
            "qwenpaw_llm_requests_total",
            since=since,
            label_filter={"status": "429"},
        )
        chat_total = store.counter_delta("qwenpaw_chat_turns_total", since=since)
        chat_ok = store.counter_delta(
            "qwenpaw_chat_turns_total",
            since=since,
            label_filter={"status": "success"},
        )
        workers = sorted(
            {
                row["worker_id"]
                for row in latest
                if row["name"] == "qwenpaw_worker_up" and row["value"] >= 1.0
            }
        )
        datasources_down = [
            str(row["labels"].get("source") or "")
            for row in latest
            if row["name"] == "qwenpaw_datasource_up" and row["value"] < 1.0
        ]
        probes_down = [
            str(row["labels"].get("target") or "")
            for row in latest
            if row["name"] == "qwenpaw_probe_up" and row["value"] < 1.0
        ]

        rows = [
            {
                "layer": "L1 体验层",
                "status": "异常" if probes_down else "正常",
                "detail": (
                    f"拨测失败: {', '.join(probes_down)}"
                    if probes_down
                    else f"会话 {chat_total:.0f} 轮"
                ),
            },
            {
                "layer": "L2 应用层",
                "status": "正常",
                "detail": "治理/技能指标见控制台",
            },
            {
                "layer": "L3 依赖层",
                "status": "异常" if (degrade or datasources_down) else "正常",
                "detail": (
                    f"降级 {degrade:.0f} 起 · 429 {llm_429:.0f} 次"
                    + (
                        f" · 断连: {', '.join(datasources_down)}"
                        if datasources_down
                        else ""
                    )
                ),
            },
            {
                "layer": "L4 资源层",
                "status": "正常" if workers else "异常",
                "detail": f"worker 存活 {len(workers)}",
            },
        ]

        # llm request pulse, bucketed server-side for line charts
        bucket_s = max(60, window_s // 60)
        buckets: dict[int, float] = {}
        for row in store.query_metrics("qwenpaw_llm_requests_total", since=since):
            key = int(row["ts"]) // bucket_s * bucket_s
            buckets.setdefault(key, 0.0)
        prev_by_series: dict[str, float] = {}
        for row in store.query_metrics("qwenpaw_llm_requests_total", since=since):
            series_key = f'{row["worker_id"]}|{row["labels"]}'
            value = row["value"]
            prev = prev_by_series.get(series_key)
            if prev is not None:
                delta = value - prev if value >= prev else value
                key = int(row["ts"]) // bucket_s * bucket_s
                buckets[key] = buckets.get(key, 0.0) + delta
            prev_by_series[series_key] = value
        ordered = sorted(buckets.items())
        categories = [_time.strftime("%H:%M", _time.localtime(ts)) for ts, _ in ordered]
        series = [round(v, 1) for _, v in ordered]

        return {
            "source": "self-monitor-sqlite",
            "sourceStatus": "live",
            "columns": [
                {"key": "layer", "label": "层级"},
                {"key": "status", "label": "状态"},
                {"key": "detail", "label": "关键指标"},
            ],
            "rows": rows,
            "categories": categories,
            "series": series,
            "metrics": {
                "降级事件": int(degrade),
                "LLM 429": int(llm_429),
                "Worker 存活": len(workers),
                "会话成功率": (
                    round(chat_ok / chat_total * 100, 1) if chat_total > 0 else None
                ),
            },
            "total": len(rows),
        }
    except Exception as exc:  # honest failure, never raise
        return {
            "source": "self-monitor-sqlite",
            "sourceStatus": "unavailable",
            "message": f"自监控数据读取失败: {exc}",
            "rows": [],
            "columns": [],
        }


FETCHERS: dict[str, Fetcher] = {
    "system-logs": fetch_system_logs,
    "real-alarms": fetch_real_alarms,
    "cmdb-resources": fetch_cmdb_resources,
    "system-inspection": fetch_system_inspection,
    "cmdb-applications": fetch_cmdb_applications,
    "workorders": fetch_workorders,
    "alarm-top5": fetch_alarm_top5,
    "topology-impact": fetch_topology_impact,
    "web-live-data": fetch_web_live,
    "capability-gap": fetch_capability_gap,
    "ai-authored-content": fetch_authored_content,
    "self-monitor-overview": fetch_self_monitor_overview,
}
