# -*- coding: utf-8 -*-
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
BUSINESS_COCKPIT_ENDPOINT = "/resource/monitor/overview/business/cockpit"
REAL_ALARM_LIST_ENDPOINT = "/resource/realalarm/list"
# Today's workorder stats live on the same INOE gateway, under the
# inoe-ferry 工单 module (which also backs the order-workflow skill).
# Returns data: {inProgressCount, finishedCount, todoCount}.
WORKORDER_STATS_ENDPOINT = "/api/v1/work-order/getWorkOrder"
# Alarm-count trend grouped by severity (1=紧急/2=严重/3=普通/4=预警). The
# gateway only offers per-day buckets, so the overview shows the last N days.
SEVERITY_TREND_ENDPOINT = "/resource/alarm/statistics/statSeverityTrend"
SEVERITY_TREND_DAYS = 7
# Exact endpoints used by the monitoring dashboard's alarm widgets.  Keep
# these separate from the generic real-alarm integration: their day window
# and aggregation are the dashboard's public data contract.
DASHBOARD_SEVERITY_ENDPOINT = "/resource/alarm/statistics/statSeverity"
DASHBOARD_ALARM_LIST_ENDPOINT = "/resource/alarm/statistics/hisAlarmList"
DASHBOARD_ALARM_LIST_LIMIT = 1000
ACTIVE_ALARM_LOOKBACK_HOURS = 24
# CMDB CI summary — the INOE homepage's "资产总数" reads total_ci_count from
# here (excludes group 26). Requires a token with CMDB (维易) access; the
# overview falls back to asset-overview totalResources when it is unavailable.
CMDB_STAT_SUMMARY_ENDPOINT = "/cmdb/api/v0.1/stat/summary"
CMDB_EXCLUDE_GROUP_IDS = "26"

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
    if not inoe_settings_store.get_effective_token():
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


def query_business_cockpit() -> dict[str, Any]:
    return _get_envelope(
        BUSINESS_COCKPIT_ENDPOINT,
        {"status": -1, "name": "", "sort": "error"},
    )


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


def _dashboard_day_window(now: datetime | None = None) -> tuple[str, str]:
    current = (now or datetime.now(timezone.utc)).astimezone(_alarm_timezone())
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = current.replace(hour=23, minute=59, second=59, microsecond=0)
    return (
        day_start.strftime("%Y-%m-%d %H:%M:%S"),
        day_end.strftime("%Y-%m-%d %H:%M:%S"),
    )


def query_dashboard_alarm_severity(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read the same severity aggregation as the monitoring dashboard."""
    begin_time, end_time = _dashboard_day_window(now)
    return _get_envelope(
        DASHBOARD_SEVERITY_ENDPOINT,
        {
            "type": 1,
            "beginTime": begin_time,
            "endTime": end_time,
            "alarmClassType": 0,
        },
    )


def query_dashboard_alarm_history(
    *,
    now: datetime | None = None,
    limit: int = DASHBOARD_ALARM_LIST_LIMIT,
) -> dict[str, Any]:
    """Read the dashboard's complete same-day alarm history for TOP analysis."""
    begin_time, end_time = _dashboard_day_window(now)
    page_size = max(1, min(int(limit or DASHBOARD_ALARM_LIST_LIMIT), 1000))
    return _get_envelope(
        DASHBOARD_ALARM_LIST_ENDPOINT,
        {
            "beginTime": begin_time,
            "endTime": end_time,
            "sortType": 1,
            "pageNum": 1,
            "pageSize": page_size,
        },
    )


def query_dashboard_active_alarm_history(
    *,
    now: datetime | None = None,
    limit: int = DASHBOARD_ALARM_LIST_LIMIT,
) -> dict[str, Any]:
    """Read the rolling 24-hour, uncleared alarm list for health status."""
    current = (now or datetime.now(timezone.utc)).astimezone(_alarm_timezone())
    begin_time = (current - timedelta(hours=ACTIVE_ALARM_LOOKBACK_HOURS)).strftime(
        "%Y-%m-%d %H:%M:%S",
    )
    end_time = current.strftime("%Y-%m-%d %H:%M:%S")
    page_size = max(1, min(int(limit or DASHBOARD_ALARM_LIST_LIMIT), 1000))
    return _get_envelope(
        DASHBOARD_ALARM_LIST_ENDPOINT,
        {
            "beginTime": begin_time,
            "endTime": end_time,
            "sortType": 1,
            "isClear": 0,
            "pageNum": 1,
            "pageSize": page_size,
        },
    )


def query_cmdb_summary() -> dict[str, Any]:
    now = datetime.now(_alarm_timezone())
    params = {
        "start_time": now.strftime("%Y-%m-%d 00:00:00"),
        "end_time": now.strftime("%Y-%m-%d 23:59:59"),
        "exclude_group_ids": CMDB_EXCLUDE_GROUP_IDS,
    }
    query = urlencode(params, quote_via=quote)
    return _get_envelope(f"{CMDB_STAT_SUMMARY_ENDPOINT}?{query}")


def query_active_alarm_total() -> int:
    payload = query_portal_real_alarms(limit=1)
    return int(payload.get("total") or 0) if isinstance(payload, dict) else 0


def query_monitoring_overview_dashboard() -> dict[str, Any]:
    return {
        "assetOverview": query_asset_overview(),
        "businessCockpit": query_business_cockpit(),
        "alarmTop5": query_alarm_top5(),
        "topology": query_topology(),
        "workorderStats": query_workorder_stats(),
        "severityTrend": query_severity_trend(),
        "cmdbSummary": query_cmdb_summary(),
        "activeAlarmTotal": query_active_alarm_total(),
    }
