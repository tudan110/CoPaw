# -*- coding: utf-8 -*-
"""Big-screen application list query against Veops CMDB (T-031).

The chat path reaches Veops through the ``zgops-cmdb`` skill scripts;
those hardcode 30s timeouts plus a curl subprocess fallback — exactly
the latency profile the big screen must avoid (see ``fetch_workorders``)
— and expose no configuration surface. The sibling
``resource_import.ZgopsCmdbClient`` can't be reused either: that module
imports pandas at module level, a heavy dependency only present in the
deploy image, and the big screen must also run from a plain dev venv.

So this is a deliberately self-contained stdlib client with the same
API/auth semantics: ``POST /api/v1/acl/login`` for an ``Access-Token``,
then ``GET /api/v0.1/ci/s?q=_type:<ci_type>``. Credentials resolve from
``os.environ`` (the settings page «CMDB / 资源导入» materialises
``ZGOPS_*`` there via ``working_secrets``) with the shared
``secrets/zgops-cmdb.env`` file as fallback.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ZGOPS_SOURCE = "zgops-veops-cmdb-api"

APPLICATION_CI_TYPE = "project"

_DEFAULT_TIMEOUT_SECONDS = 6.0

_CONFIG_KEYS = ("ZGOPS_BASE_URL", "ZGOPS_USERNAME", "ZGOPS_PASSWORD")


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _resolve_config() -> dict[str, str]:
    config = {key: str(os.environ.get(key) or "").strip() for key in _CONFIG_KEYS}
    if all(config.values()):
        return config
    working_dir = (
        os.environ.get("QWENPAW_WORKING_DIR")
        or os.environ.get("COPAW_WORKING_DIR")
        or "~/.qwenpaw"
    )
    env_file = Path(working_dir).expanduser() / "secrets" / "zgops-cmdb.env"
    fallback = _read_env_file(env_file)
    for key in _CONFIG_KEYS:
        if not config[key]:
            config[key] = str(fallback.get(key) or "").strip()
    return config


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    body = None
    headers = {"Accept-Language": "zh"}
    if token:
        headers["Access-Token"] = token
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


def _login(base_url: str, config: dict[str, str], timeout_seconds: float) -> str:
    payload = _request_json(
        f"{base_url}/api/v1/acl/login",
        method="POST",
        payload={
            "username": config["ZGOPS_USERNAME"],
            "password": config["ZGOPS_PASSWORD"],
        },
        timeout_seconds=timeout_seconds,
    )
    token = str((payload or {}).get("token") or "").strip()
    if not token:
        raise RuntimeError("Veops 登录响应缺少 token")
    return token


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
            "message": "CMDB 连接未配置（设置页«CMDB / 资源导入»）",
        }
    base_url = config["ZGOPS_BASE_URL"].rstrip("/")
    try:
        token = _login(base_url, config, timeout_seconds)
        query = urllib.parse.quote(f"_type:{ci_type}", safe=":_")
        payload = _request_json(
            f"{base_url}/api/v0.1/ci/s?q={query}&count={limit}&page=1",
            token=token,
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
