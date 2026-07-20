# -*- coding: utf-8 -*-
"""Big-screen application list query through the INOE CMDB gateway.

The chat path reaches Veops through the ``zgops-cmdb`` skill scripts;
those hardcode 30s timeouts plus a curl subprocess fallback — exactly
the latency profile the big screen must avoid (see ``fetch_workorders``)
— and expose no configuration surface. The sibling
``resource_import.ZgopsCmdbClient`` can't be reused either: that module
imports pandas at module level, a heavy dependency only present in the
deploy image, and the big screen must also run from a plain dev venv.

This is a deliberately self-contained stdlib client. All calls use the
platform settings page's ``INOE_API_BASE_URL`` and
``INOE_API_TOKEN``: ``Authorization: Bearer <token>`` and the gateway
route ``/cmdb/api/v0.1/...``. No CMDB username/password login is used.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

ZGOPS_SOURCE = "inoe-cmdb-gateway"

APPLICATION_CI_TYPE = "project"

_DEFAULT_TIMEOUT_SECONDS = 6.0

_CONFIG_KEYS = ("INOE_API_BASE_URL", "INOE_API_TOKEN")


def _resolve_config() -> dict[str, str]:
    return {key: str(os.environ.get(key) or "").strip() for key in _CONFIG_KEYS}


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    body = None
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def query_application_cis(
    *,
    ci_type: str = APPLICATION_CI_TYPE,
    limit: int = 100,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch application CIs; honest envelope, never raises.

    Returns ``{"source": "live"|"empty"|"error", "items": [...],
    "total": int, "message": str}``. ``items`` are raw Veops CI dicts;
    field mapping stays with the caller so this module carries no
    big-screen knowledge.
    """
    limit = max(1, min(500, int(limit)))
    config = _resolve_config()
    if not all(config.values()):
        return {
            "source": "error",
            "items": [],
            "total": 0,
            "message": "CMDB 网关未配置（设置页«平台»）",
        }
    base_url = config["INOE_API_BASE_URL"].rstrip("/")
    try:
        query = urllib.parse.quote(f"_type:{ci_type}", safe=":_")
        payload = _request_json(
            f"{base_url}/cmdb/api/v0.1/ci/s?q={query}&count={limit}&page=1",
            token=config["INOE_API_TOKEN"],
            timeout_seconds=timeout_seconds,
        )
    except Exception as error:  # noqa: BLE001 - honest envelope boundary
        return {
            "source": "error",
            "items": [],
            "total": 0,
            "message": f"CMDB 查询失败：{type(error).__name__}",
        }
    items: list[dict[str, Any]] = []
    total = 0
    if isinstance(payload, dict):
        raw_items = payload.get("result")
        if isinstance(raw_items, list):
            items = [item for item in raw_items if isinstance(item, dict)]
        try:
            total = int(payload.get("numfound") or len(items))
        except (TypeError, ValueError):
            total = len(items)
    elif isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]
        total = len(items)
    return {
        "source": "live" if items else "empty",
        "items": items,
        "total": total,
        "message": "" if items else "CMDB 中暂无应用系统记录",
    }
