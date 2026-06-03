from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import requests

from qwenpaw.constant import EnvVarLoader

DEFAULT_INOE_API_BASE_URL = "http://gateway:30080"
REAL_ALARM_LIST_ENDPOINT = "/resource/realalarm/list"
REAL_ALARM_TIMEOUT_SECONDS = 30.0
DEFAULT_REAL_ALARM_LIMIT = 100
MAX_REAL_ALARM_LIMIT = 200
DEFAULT_REAL_ALARM_LOOKBACK_HOURS = 24

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


DEFAULT_REAL_ALARM_TIMEZONE_OFFSET = 8


def _get_alarm_timezone() -> timezone:
    offset_hours = float(
        EnvVarLoader.get_str(
            "PORTAL_REAL_ALARM_TIMEZONE_OFFSET",
            str(DEFAULT_REAL_ALARM_TIMEZONE_OFFSET),
        ).strip() or str(DEFAULT_REAL_ALARM_TIMEZONE_OFFSET)
    )
    return timezone(timedelta(hours=offset_hours))


def _format_dt(value: datetime) -> str:
    return value.astimezone(_get_alarm_timezone()).strftime("%Y-%m-%d %H:%M:%S")


def _build_real_alarm_payload(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    source: str,
    total: Any | None = None,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or DEFAULT_REAL_ALARM_LIMIT), MAX_REAL_ALARM_LIMIT))
    items = [_normalize_alarm_row(row) for row in rows[:safe_limit]]
    items.sort(key=lambda a: a.get("eventTime") or "")
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


def build_real_alarm_list_request_body(
    *,
    page_num: int = 1,
    page_size: int,
    begin_time: str | None = None,
    end_time: str | None = None,
    alarm_status: str | None = None,
) -> dict[str, Any]:
    return {
        "pageNum": page_num,
        "pageSize": page_size,
        "alarmuniqueid": None,
        "alarmclass": None,
        "devName": None,
        "manageIp": None,
        "neId": None,
        "locatenename": None,
        "onuId": None,
        "locatenestatus": None,
        "eventtime": None,
        "daltime": None,
        "eventlasttime": None,
        "canceltime": None,
        "alarmseverity": "",
        "alarmseveritys": [],
        "vendorserialno": None,
        "alarmstatus": str(alarm_status).strip() if alarm_status else None,
        "speciality": None,
        "addInfo9": None,
        "clearuser": None,
        "ackflag": None,
        "acktime": None,
        "ackuser": None,
        "alarmtitle": None,
        "alarmtext": None,
        "alarmregion": None,
        "alarmcounty": None,
        "cityList": [],
        "countyList": [],
        "circName": "",
        "linkName": "",
        "circId": "",
        "linkId": "",
        "params": {"beginEventtime": begin_time, "endEventtime": end_time},
    }


def _post_real_alarm_list(
    *,
    limit: int,
    begin_time: str | None = None,
    end_time: str | None = None,
    alarm_status: str | None = None,
) -> dict[str, Any]:
    body = build_real_alarm_list_request_body(
        page_num=1,
        page_size=limit,
        begin_time=begin_time,
        end_time=end_time,
        alarm_status=alarm_status,
    )
    url = _get_gateway_real_alarm_url()
    headers = _build_real_alarm_headers()
    timeout_seconds = _get_real_alarm_timeout_seconds()
    try:
        response = requests.post(
            url,
            json=body,
            headers=headers,
            timeout=timeout_seconds,
        )
    except requests.exceptions.ConnectionError:
        return _curl_post_real_alarm_json(
            url=url,
            headers=headers,
            data=body,
            timeout_seconds=timeout_seconds,
        )
    response.raise_for_status()
    return response.json()


def _curl_post_real_alarm_json(
    *,
    url: str,
    headers: dict[str, str],
    data: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    timeout_value = str(int(timeout_seconds))
    args = [
        "curl",
        "-sS",
        "-X",
        "POST",
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
    args.extend(["--data-binary", json.dumps(data, ensure_ascii=False)])
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
            error_text = (completed.stderr or completed.stdout or "curl 请求失败").strip()
            return {"code": 500, "msg": f"curl 请求失败: {error_text}", "total": 0, "rows": []}

        status_code = int((completed.stdout or "").strip() or "0")
        with open(body_path, "r", encoding="utf-8", errors="replace") as handle:
            response_text = handle.read()
        if status_code >= 400:
            return {"code": status_code, "msg": response_text, "total": 0, "rows": []}
        if not response_text.strip():
            return {"code": 500, "msg": "接口返回空响应", "total": 0, "rows": []}
        result = json.loads(response_text)
        if not isinstance(result, dict):
            return {"code": 500, "msg": "接口返回格式异常：预期为 JSON 对象", "total": 0, "rows": []}
        return result
    except Exception as exc:  # noqa: BLE001
        return {"code": 500, "msg": f"curl 回退失败: {exc}", "total": 0, "rows": []}
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


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


def query_portal_real_alarms(
    limit: int,
    now: datetime | None = None,
    lookback_minutes: int | None = None,
    alarm_status: str | None = None,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or DEFAULT_REAL_ALARM_LIMIT), MAX_REAL_ALARM_LIMIT))
    current_time = now or datetime.now(timezone.utc)
    begin_time: str | None = None
    end_time: str | None = None
    if lookback_minutes is not None:
        lookback_delta = timedelta(minutes=max(1, int(lookback_minutes)))
        begin_time = _format_dt(current_time - lookback_delta)
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
        return build_empty_portal_real_alarms_payload(safe_limit)
    total = result.get("total") if isinstance(result, dict) else None
    return _build_real_alarm_payload(rows, limit=safe_limit, source="live", total=total)
