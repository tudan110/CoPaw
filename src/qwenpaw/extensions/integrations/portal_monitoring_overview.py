from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from qwenpaw.constant import EnvVarLoader
from qwenpaw.extensions.integrations.working_secrets import (
    ensure_working_secrets_loaded,
)

ensure_working_secrets_loaded()

DEFAULT_INOE_API_BASE_URL = "http://gateway:30080"
MONITORING_TIMEOUT_SECONDS = 30.0

ALARM_TOP5_ENDPOINT = "/resource/alarm/statistics/statResTop"
TOPOLOGY_ENDPOINT = "/resource/monitor/overview/topology"
ASSET_OVERVIEW_ENDPOINT = "/resource/monitor/overview/asset/overview"
REAL_ALARM_LIST_ENDPOINT = "/resource/realalarm/list"

ALARM_TOP5_DEFAULT_PARAMS = {
    "alarmClassType": 0,
    "type": 3,
    "alarmSeverity": 1,
}


def _make_error(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "msg": message, "data": None}


def _get_base_url() -> str:
    configured = EnvVarLoader.get_str(
        "INOE_API_BASE_URL",
        DEFAULT_INOE_API_BASE_URL,
    ).strip()
    return (configured or DEFAULT_INOE_API_BASE_URL).rstrip("/")


def _get_token() -> str:
    return EnvVarLoader.get_str("INOE_API_TOKEN", "").strip()


def _get_timeout_seconds() -> float:
    return EnvVarLoader.get_float(
        "INOE_API_TIMEOUT",
        MONITORING_TIMEOUT_SECONDS,
        min_value=0.1,
    )


def _build_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    }
    token = _get_token()
    if token:
        headers["Authorization"] = (
            token if token.lower().startswith("bearer ") else f"Bearer {token}"
        )
    return headers


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    url = urljoin(f"{_get_base_url()}/", path.lstrip("/"))
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def _normalize_envelope(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return {"code": 200, "msg": None, "data": payload}


def _get_envelope(
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _get_base_url():
        return _make_error(400, "未设置 INOE_API_BASE_URL")
    if not _get_token():
        return _make_error(401, "未设置 INOE_API_TOKEN")
    try:
        with httpx.Client(timeout=_get_timeout_seconds()) as client:
            response = client.get(
                _build_url(path, params),
                headers=_build_headers(),
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


def query_active_alarm_total() -> int:
    if not _get_base_url() or not _get_token():
        return 0
    body = {
        "pageNum": 1,
        "pageSize": 1,
        "alarmseverity": "",
        "alarmstatus": "1",
        "params": {},
    }
    try:
        with httpx.Client(timeout=_get_timeout_seconds()) as client:
            response = client.post(
                _build_url(REAL_ALARM_LIST_ENDPOINT),
                json=body,
                headers=_build_headers(),
            )
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict):
            return int(payload.get("total") or 0)
    except Exception:  # noqa: BLE001
        return 0
    return 0


def query_monitoring_overview_dashboard() -> dict[str, Any]:
    return {
        "assetOverview": query_asset_overview(),
        "alarmTop5": query_alarm_top5(),
        "topology": query_topology(),
        "activeAlarmTotal": query_active_alarm_total(),
    }
