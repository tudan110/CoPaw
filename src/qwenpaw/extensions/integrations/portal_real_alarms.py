# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from qwenpaw.extensions.api import diagnosis_settings_store
from qwenpaw.extensions.api import inoe_settings_store

DEFAULT_INOE_API_BASE_URL = "http://gateway:30080"
REAL_ALARM_LIST_ENDPOINT = "/resource/alarm/statistics/hisAlarmList"
REAL_ALARM_TIMEOUT_SECONDS = 30.0
DEFAULT_REAL_ALARM_LIMIT = 100
MAX_REAL_ALARM_LIMIT = 200
DEFAULT_REAL_ALARM_QUERY_WINDOW_HOURS = 24.0
# Recovery verification looks up one alarm by exact alarmuniqueid; use a
# wide window so an old-but-still-active alarm is not misread as cleared
# just because its event time predates a narrow window.
RECOVERY_VERIFY_WINDOW_HOURS = 24.0 * 90

SEVERITY_TO_LEVEL = {
    "1": "critical",
    "2": "urgent",
    "3": "warning",
}

# Display-oriented maps, aligned with the real-alarm skill's
# scripts/utils/alarm_normalizer.py so the big-screen shows the same
# human-readable values the chat table does.
SEVERITY_TO_NAME = {
    "1": "紧急",
    "2": "严重",
    "3": "普通",
    "4": "预警",
}
STATUS_TO_NAME = {
    "0": "自动清除",
    "1": "活跃",
    "2": "同步清除",
    "3": "手工清除",
}
CLASS_TO_NAME = {
    "sys_log": "设备告警",
    "threshold": "性能告警",
    "derivative": "衍生告警",
}


def _get_gateway_real_alarm_url() -> str:
    # INOE connection is resolved by the shared accessor (page override >
    # legacy override > env > default). See :mod:`inoe_settings_store`.
    return inoe_settings_store.build_url(REAL_ALARM_LIST_ENDPOINT)


def _get_real_alarm_timeout_seconds() -> float:
    return inoe_settings_store.get_timeout_seconds()


def _build_real_alarm_headers() -> dict[str, str]:
    return inoe_settings_store.build_headers()


DEFAULT_REAL_ALARM_TIMEZONE_OFFSET = 8


def _get_alarm_timezone() -> timezone:
    offset_hours = diagnosis_settings_store.resolve_float(
        "timezone_offset_hours",
        "PORTAL_REAL_ALARM_TIMEZONE_OFFSET",
        float(DEFAULT_REAL_ALARM_TIMEZONE_OFFSET),
        min_value=-12,
        max_value=14,
    )
    return timezone(timedelta(hours=offset_hours))


def _format_dt(value: datetime) -> str:
    return value.astimezone(_get_alarm_timezone()).strftime(
        "%Y-%m-%d %H:%M:%S",
    )


def _resolve_query_window_hours() -> float:
    """Default begin/endTime window (hours) for hisAlarmList queries.

    Takes the max of the configurable query window and the analysis
    lookback, so the auto-takeover path never queries a narrower range
    than the analysis step needs (which would silently drop candidates).
    """
    window = diagnosis_settings_store.resolve_float(
        "alarm_query_window_hours",
        "QWENPAW_PORTAL_REAL_ALARM_QUERY_WINDOW_HOURS",
        DEFAULT_REAL_ALARM_QUERY_WINDOW_HOURS,
        min_value=1,
        max_value=8760,
    )
    lookback = diagnosis_settings_store.resolve_float(
        "analysis_lookback_hours",
        "QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS",
        0.0,
        min_value=0,
        max_value=720,
    )
    return max(window, lookback)


def _alarm_status_to_is_clear(alarm_status: str | None) -> str:
    """Map legacy ``alarmstatus`` to the new ``isClear`` query flag.

    Old API filtered by ``alarmstatus`` ("1"=active). New API uses
    ``isClear`` ("0"=active / "1"=cleared) — note the inversion. A missing
    status defaults to active, since every caller that omits it wants the
    active list.
    """
    status = str(alarm_status).strip() if alarm_status else "1"
    return "0" if status == "1" else "1"


def parse_alarm_event_time(text: str) -> datetime | None:
    """Parse an alarm ``eventTime`` string into an aware datetime.

    Event times arrive as ``"YYYY-MM-DD HH:MM:SS"`` in the alarm
    platform's local timezone (``timezone_offset_hours`` setting).
    Returns ``None`` when the text does not match.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=_get_alarm_timezone())
    return None


def format_alarm_duration(event_time: str, *, now: datetime) -> str:
    """Human-readable elapsed time since an alarm fired (e.g. ``4h10m``).

    Returns ``""`` when the event time is unparsable or in the future,
    so a missing/garbled timestamp never shows a misleading duration.
    """
    started = parse_alarm_event_time(event_time)
    if started is None:
        return ""
    elapsed = now - started
    minutes_total = int(elapsed.total_seconds() // 60)
    if minutes_total < 0:
        return ""
    days, rem = divmod(minutes_total, 24 * 60)
    hours, minutes = divmod(rem, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


def filter_alarms_started_after(
    payload: dict[str, Any],
    cutoff: datetime,
) -> dict[str, Any]:
    """Keep only alarms whose latest alarm time is at or after ``cutoff``.

    Keys on ``eventLastTime`` (latest alarm time), so a long-running but
    still-active alarm is analyzed — consistent with how the list filters
    and displays time. Falls back to ``eventTime`` when the latest time is
    missing. Alarms with a missing/unparsable time are kept (fail-open) so
    a real incident never gets silently dropped by the analysis window.
    """
    items = list(payload.get("items") or [])
    kept = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("eventLastTime") or item.get("eventTime") or "")
        event_time = parse_alarm_event_time(raw)
        if event_time is None or event_time >= cutoff:
            kept.append(item)
    return {
        **payload,
        "items": kept,
        "total": len(kept),
    }


def _build_real_alarm_payload(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    source: str,
    total: Any | None = None,
) -> dict[str, Any]:
    safe_limit = max(
        1,
        min(int(limit or DEFAULT_REAL_ALARM_LIMIT), MAX_REAL_ALARM_LIMIT),
    )
    items = [_normalize_alarm_row(row) for row in rows[:safe_limit]]
    # Preserve the gateway's sortType=1 order (latest alarm time desc);
    # the frontend no longer re-sorts. eventTime stays available for the
    # analysis-lookback filter (which keys on first-seen time).
    try:
        resolved_total = int(total) if total is not None else len(items)
    except (TypeError, ValueError):
        resolved_total = len(items)
    return {
        "total": max(0, resolved_total),
        "items": items,
        "source": source,
    }


def build_empty_portal_real_alarms_payload(limit: int) -> dict[str, Any]:
    return _build_real_alarm_payload([], limit=limit, source="live")


def build_real_alarm_list_query_params(
    *,
    page_num: int = 1,
    page_size: int,
    begin_time: str,
    end_time: str,
    alarm_status: str | None = None,
    alarm_unique_id: str | None = None,
) -> dict[str, Any]:
    """Build query params for the INOE ``hisAlarmList`` GET endpoint.

    ``beginTime``/``endTime`` are mandatory (alarm-event-time window);
    ``isClear`` replaces the legacy ``alarmstatus`` (inverted semantics);
    ``sortType=1`` sorts by latest alarm time descending.
    """
    params: dict[str, Any] = {
        "alarmSeverity": "1,2,3,4",
        "isClear": _alarm_status_to_is_clear(alarm_status),
        "beginTime": begin_time,
        "endTime": end_time,
        "pageNum": page_num,
        "pageSize": page_size,
        "sortType": 1,
    }
    if alarm_unique_id:
        params["alarmuniqueid"] = str(alarm_unique_id).strip()
    return params


# Name kept (``_post_*``) for back-compat with test mocks; the endpoint
# is now a GET. INOE ``hisAlarmList`` requires a begin/end window, so a
# default is filled when the caller did not compute one.
def _post_real_alarm_list(
    *,
    limit: int,
    begin_time: str | None = None,
    end_time: str | None = None,
    alarm_status: str | None = None,
    alarm_unique_id: str | None = None,
) -> dict[str, Any]:
    if not begin_time or not end_time:
        now = datetime.now(timezone.utc)
        window = timedelta(hours=_resolve_query_window_hours())
        begin_time = _format_dt(now - window)
        end_time = _format_dt(now)
    params = build_real_alarm_list_query_params(
        page_num=1,
        page_size=limit,
        begin_time=begin_time,
        end_time=end_time,
        alarm_status=alarm_status,
        alarm_unique_id=alarm_unique_id,
    )
    url = _get_gateway_real_alarm_url()
    headers = _build_real_alarm_headers()
    timeout_seconds = _get_real_alarm_timeout_seconds()
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout_seconds,
        )
    except requests.exceptions.ConnectionError:
        return _curl_get_real_alarm_json(
            url=url,
            headers=headers,
            params=params,
            timeout_seconds=timeout_seconds,
        )
    response.raise_for_status()
    return response.json()


def _curl_get_real_alarm_json(
    *,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    timeout_value = str(int(timeout_seconds))
    args = [
        "curl",
        "-sS",
        "--get",
        "--connect-timeout",
        timeout_value,
        "--max-time",
        timeout_value,
        "-o",
        body_path,
        "-w",
        "%{http_code}",
    ]
    for key, value in headers.items():
        args.extend(["-H", f"{key}: {value}"])
    for key, value in params.items():
        if value is None:
            continue
        args.extend(["--data-urlencode", f"{key}={value}"])
    args.append(url)

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=max(int(timeout_seconds) + 5, 10),
            check=False,
        )
        if completed.returncode != 0:
            error_text = (
                completed.stderr or completed.stdout or "curl 请求失败"
            ).strip()
            return {
                "code": 500,
                "msg": f"curl 请求失败: {error_text}",
                "total": 0,
                "rows": [],
            }

        status_code = int((completed.stdout or "").strip() or "0")
        with open(
            body_path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as handle:
            response_text = handle.read()
        if status_code >= 400:
            return {
                "code": status_code,
                "msg": response_text,
                "total": 0,
                "rows": [],
            }
        if not response_text.strip():
            return {"code": 500, "msg": "接口返回空响应", "total": 0, "rows": []}
        result = json.loads(response_text)
        if not isinstance(result, dict):
            return {
                "code": 500,
                "msg": "接口返回格式异常：预期为 JSON 对象",
                "total": 0,
                "rows": [],
            }
        return result
    except Exception as exc:  # noqa: BLE001
        return {
            "code": 500,
            "msg": f"curl 回退失败: {exc}",
            "total": 0,
            "rows": [],
        }
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def _build_dispatch_content(
    row: dict[str, Any],
    *,
    title: str,
    device_name: str,
) -> str:
    subtype = str(
        row.get("alarmsubtype") or row.get("alarmSubType") or "",
    ).strip()
    combined_lower = " ".join(
        filter(None, (title.lower(), device_name.lower(), subtype.lower())),
    )

    if "mysql" in combined_lower and any(
        token in combined_lower
        for token in (
            "死锁",
            "数据库锁",
            "deadlock",
            "database-lock",
            "database lock",
        )
    ):
        return "mysql/死锁 + cmdb/新增/插入"

    fallback_device_name = "" if device_name == "--" else device_name
    return " / ".join(filter(None, (title, fallback_device_name, subtype)))


def _build_alarm_message(
    *,
    level_name: str,
    title: str,
    device_name: str,
    manage_ip: str,
    status_name: str,
) -> str:
    """Rich one-line summary for stream/list/timeline visuals.

    The alarm-stream widget reads ``row["message"]``; without it a
    single alarm renders as a bare dot. Built from real fields only.
    """
    parts = [f"【{level_name}】{title}"]
    location = " ".join(
        token for token in (device_name, manage_ip) if token and token != "--"
    )
    if location:
        parts.append(location)
    if status_name and status_name != "未知":
        parts.append(status_name)
    return "｜".join(parts)


def _normalize_alarm_row(row: dict[str, Any]) -> dict[str, Any]:
    severity = str(row.get("alarmseverity") or "").strip() or "4"
    device_name = str(row.get("devName") or "").strip() or "--"
    manage_ip = str(row.get("manageIp") or "").strip() or "--"
    title = str(row.get("alarmtitle") or "").strip() or "未命名告警"
    event_time = str(row.get("eventtime") or "")
    alarm_id = str(row.get("alarmuniqueid") or title)
    res_id = str(row.get("devId") or "").strip()
    # Display-oriented enrichment (skill parity). Additive only — the
    # dispatch/chat flow reads title/level/status/dispatchContent/
    # employeeId/visibleContent, all left unchanged below.
    level_name = SEVERITY_TO_NAME.get(severity, severity or "未知")
    alarm_status = str(row.get("alarmstatus") or "").strip()
    status_name = STATUS_TO_NAME.get(alarm_status, alarm_status or "未知")
    alarm_class = str(row.get("alarmclass") or "").strip()
    class_name = CLASS_TO_NAME.get(alarm_class, alarm_class or "")
    speciality = str(row.get("speciality") or "").strip()
    region = str(row.get("alarmregion") or "").strip()
    ci_id = str(row.get("neId") or "").strip() or res_id
    event_last_time = str(row.get("eventlasttime") or "").strip()
    normalized = {
        "id": alarm_id,
        "alarmId": alarm_id,
        "resId": res_id,
        "title": title,
        "level": SEVERITY_TO_LEVEL.get(severity, "info"),
        "status": "active",
        "eventTime": event_time,
        "timeLabel": event_last_time or event_time,
        "deviceName": device_name,
        "manageIp": manage_ip,
        "employeeId": "fault",
        "dispatchContent": _build_dispatch_content(
            row,
            title=title,
            device_name=device_name,
        ),
        "visibleContent": f"{title}（{device_name} {manage_ip}）",
        # --- rich display fields (aligned with real-alarm skill) ---
        "levelName": level_name,
        "statusName": status_name,
        "className": class_name,
        "speciality": speciality,
        "region": region,
        "ciId": ci_id,
        "eventLastTime": event_last_time,
        "message": _build_alarm_message(
            level_name=level_name,
            title=title,
            device_name=device_name,
            manage_ip=manage_ip,
            status_name=status_name,
        ),
    }
    raw_count = row.get("alarmactcount")
    if raw_count is None:
        raw_count = row.get("alarmcount")
    if raw_count is None:
        raw_count = row.get("count")
    if raw_count is not None:
        try:
            normalized["count"] = int(raw_count)
        except (TypeError, ValueError):
            pass
    return normalized


def query_real_alarm_active_status(alarm_id: str) -> str:
    """Check whether one alarm is still in the INOE active list.

    Returns ``"still_active"``, ``"cleared"`` or ``"unavailable"``
    (gateway unreachable / error response). Unlike
    :func:`query_portal_real_alarms`, query failures are reported
    instead of masquerading as an empty live result — the recovery
    verification flow must not mistake "INOE is down" for "alarm gone".
    """
    normalized = str(alarm_id or "").strip()
    if not normalized:
        return "unavailable"
    try:
        now = datetime.now(timezone.utc)
        result = _post_real_alarm_list(
            limit=MAX_REAL_ALARM_LIMIT,
            begin_time=_format_dt(
                now - timedelta(hours=RECOVERY_VERIFY_WINDOW_HOURS)
            ),
            end_time=_format_dt(now),
            alarm_status="1",
            alarm_unique_id=normalized,
        )
    except Exception:
        return "unavailable"
    if not isinstance(result, dict):
        return "unavailable"
    code = result.get("code")
    if code is not None and str(code) not in ("0", "200"):
        return "unavailable"
    for row in result.get("rows") or []:
        if not isinstance(row, dict):
            continue
        candidate = str(
            row.get("alarmuniqueid") or row.get("alarmtitle") or "",
        ).strip()
        if candidate and candidate == normalized:
            return "still_active"
    return "cleared"


def query_portal_real_alarms(
    limit: int,
    now: datetime | None = None,
    lookback_minutes: int | None = None,
    alarm_status: str | None = None,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    safe_limit = max(
        1,
        min(int(limit or DEFAULT_REAL_ALARM_LIMIT), MAX_REAL_ALARM_LIMIT),
    )
    current_time = now or datetime.now(timezone.utc)
    # hisAlarmList requires a begin/end window. Use the explicit
    # lookback when given, else the configured default query window.
    if lookback_minutes is not None:
        window = timedelta(minutes=max(1, int(lookback_minutes)))
    else:
        window = timedelta(hours=_resolve_query_window_hours())
    begin_time = _format_dt(current_time - window)
    end_time = _format_dt(current_time)

    try:
        result = _post_real_alarm_list(
            limit=safe_limit,
            begin_time=begin_time,
            end_time=end_time,
            alarm_status=alarm_status,
        )
        rows = list(result.get("rows") or [])
    except Exception:
        # Legacy behaviour swallows backend failures into an empty
        # "live" payload, which makes outages indistinguishable from a
        # genuinely quiet system. Honest consumers (AI big-screen L2)
        # pass raise_on_error=True so failures can be adjudicated as
        # sourceStatus="failed" instead of "no alarms".
        if raise_on_error:
            raise
        return build_empty_portal_real_alarms_payload(safe_limit)
    total = result.get("total") if isinstance(result, dict) else None
    return _build_real_alarm_payload(
        rows,
        limit=safe_limit,
        source="live",
        total=total,
    )
