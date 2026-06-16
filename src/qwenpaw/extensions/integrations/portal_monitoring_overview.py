from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from qwenpaw.extensions.api import diagnosis_settings_store
from qwenpaw.extensions.api import inoe_settings_store
from qwenpaw.extensions.integrations.working_secrets import (
    ensure_working_secrets_loaded,
)
from qwenpaw.extensions.integrations.portal_real_alarms import (
    query_portal_real_alarms,
)

ensure_working_secrets_loaded()

ALARM_TOP5_ENDPOINT = "/resource/alarm/statistics/statResTop"
TOPOLOGY_ENDPOINT = "/resource/monitor/overview/topology"
ASSET_OVERVIEW_ENDPOINT = "/resource/monitor/overview/asset/overview"
REAL_ALARM_LIST_ENDPOINT = "/resource/realalarm/list"
# Today's workorder stats live on the same INOE gateway, under /flowable
# (the gateway also backs the order-workflow skill). Returns
# data: {inProgressCount, finishedCount, todoCount}.
WORKORDER_STATS_ENDPOINT = "/flowable/workflow/workOrder/getWorkOrder"
# Alarm-count trend grouped by severity (1=紧急/2=严重/3=普通/4=预警). The
# gateway only offers per-day buckets, so the overview shows the last N days.
SEVERITY_TREND_ENDPOINT = "/resource/alarm/statistics/statSeverityTrend"
SEVERITY_TREND_DAYS = 7

ALARM_TOP5_DEFAULT_PARAMS = {
    "alarmClassType": 0,
    "type": 3,
    "alarmSeverity": 1,
}


def _make_error(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "msg": message, "data": None}


def _normalize_envelope(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return {"code": 200, "msg": None, "data": payload}


def _get_envelope(
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # INOE gateway connection is resolved from the shared settings store
    # (page override > legacy override > env > default) — the single source
    # used by every INOE consumer. See :mod:`inoe_settings_store`.
    if not inoe_settings_store.get_base_url():
        return _make_error(400, "未设置 INOE 网关地址")
    if not inoe_settings_store.get_token():
        return _make_error(401, "未设置 INOE 访问令牌")
    try:
        with httpx.Client(
            timeout=inoe_settings_store.get_timeout_seconds(),
        ) as client:
            response = client.get(
                inoe_settings_store.build_url(path, params),
                headers=inoe_settings_store.build_headers(),
            )
        if response.status_code >= 400:
            return _make_error(response.status_code, response.text[:500])
        return _normalize_envelope(response.json())
    except Exception as exc:  # noqa: BLE001
        return _make_error(500, f"{type(exc).__name__}: {exc}")


def query_asset_overview() -> dict[str, Any]:
    return _get_envelope(ASSET_OVERVIEW_ENDPOINT)


def query_alarm_top5() -> dict[str, Any]:
    return _get_envelope(ALARM_TOP5_ENDPOINT, ALARM_TOP5_DEFAULT_PARAMS)


def query_topology() -> dict[str, Any]:
    return _get_envelope(TOPOLOGY_ENDPOINT)


def query_workorder_stats() -> dict[str, Any]:
    return _get_envelope(WORKORDER_STATS_ENDPOINT)


def _alarm_timezone() -> timezone:
    # Same offset the real-alarm queries use, so day boundaries line up.
    offset_hours = diagnosis_settings_store.resolve_float(
        "timezone_offset_hours",
        "PORTAL_REAL_ALARM_TIMEZONE_OFFSET",
        8.0,
        min_value=-12,
        max_value=14,
    )
    return timezone(timedelta(hours=offset_hours))


def query_severity_trend(days: int = SEVERITY_TREND_DAYS) -> dict[str, Any]:
    span = max(1, int(days or SEVERITY_TREND_DAYS))
    now = datetime.now(_alarm_timezone())
    begin = (now - timedelta(days=span - 1)).strftime("%Y-%m-%d 00:00:00")
    end = now.strftime("%Y-%m-%d 23:59:59")
    # Encode with %20 (not '+'); the gateway expects literal-space dates.
    query = urlencode({"beginTime": begin, "endTime": end}, quote_via=quote)
    return _get_envelope(f"{SEVERITY_TREND_ENDPOINT}?{query}")


def query_active_alarm_total() -> int:
    payload = query_portal_real_alarms(limit=1)
    return int(payload.get("total") or 0) if isinstance(payload, dict) else 0


def query_monitoring_overview_dashboard() -> dict[str, Any]:
    return {
        "assetOverview": query_asset_overview(),
        "alarmTop5": query_alarm_top5(),
        "topology": query_topology(),
        "workorderStats": query_workorder_stats(),
        "severityTrend": query_severity_trend(),
        "activeAlarmTotal": query_active_alarm_total(),
    }
