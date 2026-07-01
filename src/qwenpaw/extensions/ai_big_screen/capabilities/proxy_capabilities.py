# -*- coding: utf-8 -*-
"""Operator-registered connectors → big-screen data capabilities (M3-B).

The proxy-datasource registry (``/proxy/datasources``) already lets an
operator register any HTTP source with URL template + auth + SSRF
guard. This bridges those registrations into the big-screen capability
catalog: a datasource that declares a ``big_screen`` binding becomes a
discoverable capability ``proxy:<id>``. The L1 planner matches the
user's intent against it by name/description and supplies only the
declared params; a generic fetcher calls the connector and maps the
JSON response onto rows/columns via the operator's declared mapping.

Safety: the URL/host stays the operator's template (params only fill
declared placeholders, host locked in ``execute_datasource_request``),
so the LLM can select + parameterise a connector but never invent a
call target.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Mapping

_LOGGER = logging.getLogger(__name__)

CAPABILITY_PREFIX = "proxy:"

_DEFAULT_VISUALS = [
    "table",
    "alarm-stream",
    "metric-card",
    "metric-kpi",
    "flip-number",
    "donut",
    "bar-chart",
    "line-chart",
    "composed",
]


def _service():
    # Lazy import keeps the capabilities package importable without the
    # API layer (and avoids any import cycle).
    from qwenpaw.extensions.api import proxy_datasource_service

    return proxy_datasource_service


def _dotted_get(payload: Any, path: str) -> Any:
    """Walk a dotted path (``a.b.c``) through nested dicts; '' → payload."""
    if not path:
        return payload
    current = payload
    for key in path.split("."):
        if isinstance(current, Mapping) and key in current:
            current = current[key]
        else:
            return None
    return current


def _coerce_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        # a dict response with an obvious list inside → use the first list
        for candidate_key in ("items", "rows", "data", "list", "records"):
            inner = value.get(candidate_key)
            if isinstance(inner, list):
                return [row for row in inner if isinstance(row, dict)]
        return [value]
    return []


def _capability_metadata(cfg: Any) -> dict[str, Any]:
    binding = cfg.big_screen
    fields = [
        {"key": field.key, "label": field.label or field.key}
        for field in binding.fields
    ]
    input_schema: dict[str, Any] = {}
    for param in binding.params:
        input_schema[param.name] = param.default
    return {
        "id": f"{CAPABILITY_PREFIX}{cfg.id}",
        "name": cfg.name,
        "domain": binding.domain or "custom",
        "category": binding.domain or "custom",
        "connection": f"{CAPABILITY_PREFIX}{cfg.id}",
        "description": (cfg.description or f"操作员注册的外部数据源「{cfg.name}」"),
        "inputSchema": input_schema,
        "outputSchema": {"columns": "array", "rows": "array"},
        "availableFields": fields,
        "supportedVisuals": list(_DEFAULT_VISUALS),
        "permissionScope": "proxy:read",
        "cachePolicy": {"ttlSeconds": 30},
        "refreshPolicy": {"intervalSeconds": 60},
        "dataSource": f"{CAPABILITY_PREFIX}{cfg.id}",
        "skillName": "",
        "examplePrompts": list(binding.example_prompts),
        # private: not part of the LLM-facing contract, used by fetcher
        "_proxyParamNames": [param.name for param in binding.params],
    }


def discover_proxy_capabilities() -> list[dict[str, Any]]:
    """Capability-metadata dicts for every big-screen-enabled connector."""
    try:
        configs = _service().list_bigscreen_datasources()
    except Exception:  # discovery must never break the catalog
        _LOGGER.warning("proxy capability discovery failed", exc_info=True)
        return []
    return [_capability_metadata(cfg) for cfg in configs]


def get_proxy_metadata(capability_id: str) -> dict[str, Any] | None:
    datasource_id = capability_id[len(CAPABILITY_PREFIX) :]
    try:
        cfg = _service().get_datasource(datasource_id)
    except Exception:
        return None
    if (
        cfg is None
        or not cfg.enabled
        or cfg.big_screen is None
        or not cfg.big_screen.enabled
    ):
        return None
    return _capability_metadata(cfg)


def fetch_proxy_capability(
    capability_id: str,
    query_params: Mapping[str, Any],
) -> dict[str, Any]:
    """Fetcher for a ``proxy:<id>`` capability — call connector, map rows."""
    service = _service()
    datasource_id = capability_id[len(CAPABILITY_PREFIX) :]
    cfg = service.get_datasource(datasource_id)
    if cfg is None or cfg.big_screen is None:
        return {
            "source": capability_id,
            "sourceStatus": "failed",
            "message": "数据源未注册或未声明大屏绑定。",
        }
    binding = cfg.big_screen

    # only declared params are forwarded (whitelist); the rest ignored
    allowed = {param.name for param in binding.params}
    forwarded = {
        key: value
        for key, value in dict(query_params or {}).items()
        if key in allowed
    }

    result = service.execute_datasource_request(cfg, forwarded)
    status_code = int(result.get("status_code") or 0)
    if status_code >= 400:
        return {
            "source": capability_id,
            "sourceStatus": "failed",
            "message": f"数据源返回 HTTP {status_code}。",
        }

    payload = result.get("json")
    rows = _coerce_rows(_dotted_get(payload, binding.rows_path))
    columns = [
        {"key": field.key, "label": field.label or field.key}
        for field in binding.fields
    ]
    if not columns and rows:
        columns = [{"key": key, "label": key} for key in rows[0].keys()]

    value: Any = None
    if binding.value_path:
        value = _dotted_get(payload, binding.value_path)
    if value is None:
        value = len(rows)
    total: Any = None
    if binding.total_path:
        total = _dotted_get(payload, binding.total_path)
    if not isinstance(total, int):
        total = len(rows)

    return {
        "source": capability_id,
        "sourceStatus": "live" if rows else "empty",
        "value": value,
        "unit": binding.unit,
        "total": total,
        "columns": columns,
        "rows": rows,
    }


def proxy_capability_ids() -> set[str]:
    return {meta["id"] for meta in discover_proxy_capabilities()}


def metadata_for_registry() -> list[dict[str, Any]]:
    """Catalog metadata with the private ``_proxy*`` keys stripped."""
    cleaned: list[dict[str, Any]] = []
    for meta in discover_proxy_capabilities():
        public = copy.deepcopy(meta)
        public.pop("_proxyParamNames", None)
        cleaned.append(public)
    return cleaned
