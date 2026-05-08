from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from qwenpaw.constant import EnvVarLoader

DEFAULT_INOE_API_BASE_URL = "http://gateway:30080"
REAL_ALARM_LIST_ENDPOINT = "/resource/realalarm/list"
REAL_ALARM_TIMEOUT_SECONDS = 8.0
DEFAULT_REAL_ALARM_LIMIT = 10
MAX_REAL_ALARM_LIMIT = 50
MOCK_DATA_PATH = (
    Path(__file__).resolve().parents[4]
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "query"
    / "skills"
    / "real-alarm"
    / "mock_data.json"
)

SEVERITY_TO_LEVEL = {
    "1": "critical",
    "2": "urgent",
    "3": "warning",
}


def _get_gateway_real_alarm_url() -> str:
    configured = EnvVarLoader.get_str(
        "INOE_API_BASE_URL",
        DEFAULT_INOE_API_BASE_URL,
    ).strip()
    base_url = configured or DEFAULT_INOE_API_BASE_URL
    return urljoin(f"{base_url.rstrip('/')}/", REAL_ALARM_LIST_ENDPOINT.lstrip("/"))


def _get_real_alarm_timeout_seconds() -> float:
    return EnvVarLoader.get_float(
        "INOE_API_TIMEOUT",
        REAL_ALARM_TIMEOUT_SECONDS,
        min_value=0.1,
    )


def _build_real_alarm_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    }
    bearer_token = EnvVarLoader.get_str(
        "INOE_API_TOKEN",
        "",
    ).strip()
    if bearer_token:
        headers["Authorization"] = (
            bearer_token
            if bearer_token.lower().startswith("bearer ")
            else f"Bearer {bearer_token}"
        )
    return headers


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _load_mock_alarm_rows() -> list[dict[str, Any]]:
    if not MOCK_DATA_PATH.exists():
        return []
    payload = json.loads(MOCK_DATA_PATH.read_text(encoding="utf-8"))
    return list(payload.get("rows") or [])


PORTAL_REAL_ALARM_MOCK_TITLE = "数据库锁异常"


def _filter_portal_mock_alarm_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("alarmtitle") or "").strip() == PORTAL_REAL_ALARM_MOCK_TITLE
    ]


def _load_portal_mock_alarm_rows() -> list[dict[str, Any]]:
    return _filter_portal_mock_alarm_rows(_load_mock_alarm_rows())


def _post_real_alarm_list(*, limit: int, begin_time: str, end_time: str) -> dict[str, Any]:
    body = {
        "pageNum": 1,
        "pageSize": limit,
        "alarmseverity": "",
        "alarmstatus": "1",
        "params": {
            "beginEventtime": begin_time,
            "endEventtime": end_time,
        },
    }
    with httpx.Client(timeout=_get_real_alarm_timeout_seconds()) as client:
        response = client.post(
            _get_gateway_real_alarm_url(),
            json=body,
            headers=_build_real_alarm_headers(),
        )
        response.raise_for_status()
        return response.json()


def _build_dispatch_content(row: dict[str, Any], *, title: str, device_name: str) -> str:
    subtype = str(row.get("alarmsubtype") or row.get("alarmSubType") or "").strip()
    combined_lower = " ".join(filter(None, (title.lower(), device_name.lower(), subtype.lower())))

    if "mysql" in combined_lower and any(
        token in combined_lower
        for token in ("死锁", "数据库锁", "deadlock", "database-lock", "database lock")
    ):
        return "mysql/死锁 + cmdb/新增/插入"

    fallback_device_name = "" if device_name == "--" else device_name
    return " / ".join(filter(None, (title, fallback_device_name, subtype)))


def _normalize_alarm_row(row: dict[str, Any]) -> dict[str, Any]:
    severity = str(row.get("alarmseverity") or "").strip() or "4"
    device_name = str(row.get("devName") or "").strip() or "--"
    manage_ip = str(row.get("manageIp") or "").strip() or "--"
    title = str(row.get("alarmtitle") or "").strip() or "未命名告警"
    event_time = str(row.get("eventtime") or "")
    alarm_id = str(row.get("alarmuniqueid") or title)
    res_id = str(row.get("devId") or "").strip()
    return {
        "id": alarm_id,
        "alarmId": alarm_id,
        "resId": res_id,
        "title": title,
        "level": SEVERITY_TO_LEVEL.get(severity, "info"),
        "status": "active",
        "eventTime": event_time,
        "timeLabel": event_time,
        "deviceName": device_name,
        "manageIp": manage_ip,
        "employeeId": "fault",
        "dispatchContent": _build_dispatch_content(row, title=title, device_name=device_name),
        "visibleContent": f"{title}（{device_name} {manage_ip}）",
    }


def query_portal_real_alarms(limit: int, now: datetime | None = None) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or DEFAULT_REAL_ALARM_LIMIT), MAX_REAL_ALARM_LIMIT))
    current_time = now or datetime.now(timezone.utc)
    begin_time = _format_dt(current_time - timedelta(days=7))
    end_time = _format_dt(current_time)

    source = "live"
    try:
        result = _post_real_alarm_list(limit=safe_limit, begin_time=begin_time, end_time=end_time)
        rows = list(result.get("rows") or [])
    except Exception:
        source = "mock"
        rows = _load_portal_mock_alarm_rows()
    else:
        if not rows:
            source = "mock"
            rows = _load_portal_mock_alarm_rows()

    items = [_normalize_alarm_row(row) for row in rows[:safe_limit]]
    return {
        "total": len(items),
        "items": items,
        "source": source,
    }
