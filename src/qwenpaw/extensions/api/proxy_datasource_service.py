# -*- coding: utf-8 -*-
"""Datasource config CRUD — JSON file persistence."""
from __future__ import annotations

import json
from typing import Any

from qwenpaw.extensions.api.proxy_datasource_models import (
    DatasourceConfig,
    DatasourceSummary,
)
from qwenpaw.extensions.runtime_data_paths import (
    PROXY_DATASOURCES_CONFIG_PATH,
    PROXY_DATASOURCES_DATA_DIR,
    ensure_extension_data_dir,
)

_CONFIG_CACHE: dict[str, DatasourceConfig] | None = None


def _load_all() -> dict[str, DatasourceConfig]:
    """Load all datasource configs from the JSON file."""
    global _CONFIG_CACHE
    ensure_extension_data_dir(PROXY_DATASOURCES_DATA_DIR)

    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    if not PROXY_DATASOURCES_CONFIG_PATH.exists():
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE

    raw = json.loads(PROXY_DATASOURCES_CONFIG_PATH.read_text(encoding="utf-8"))
    _CONFIG_CACHE = {}
    for item in raw:
        cfg = DatasourceConfig.model_validate(item)
        _CONFIG_CACHE[cfg.id] = cfg
    return _CONFIG_CACHE


def _save_all(configs: dict[str, DatasourceConfig]) -> None:
    """Persist all configs to disk and refresh the cache."""
    global _CONFIG_CACHE
    ensure_extension_data_dir(PROXY_DATASOURCES_DATA_DIR)
    data = [cfg.model_dump() for cfg in configs.values()]
    PROXY_DATASOURCES_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _CONFIG_CACHE = configs


def list_datasources() -> list[DatasourceSummary]:
    """List all datasources (safe summary, no headers)."""
    configs = _load_all()
    return [
        DatasourceSummary(
            id=cfg.id,
            name=cfg.name,
            description=cfg.description,
            url_template=cfg.url_template,
            method=cfg.method,
            default_params=cfg.default_params,
            timeout=cfg.timeout,
            enabled=cfg.enabled,
        )
        for cfg in configs.values()
    ]


def get_datasource(datasource_id: str) -> DatasourceConfig | None:
    """Get a single datasource config (includes headers — server-side only)."""
    return _load_all().get(datasource_id)


def get_datasource_summary(datasource_id: str) -> DatasourceSummary | None:
    """Get a single datasource summary (safe for client)."""
    cfg = get_datasource(datasource_id)
    if cfg is None:
        return None
    return DatasourceSummary(
        id=cfg.id,
        name=cfg.name,
        description=cfg.description,
        url_template=cfg.url_template,
        method=cfg.method,
        default_params=cfg.default_params,
        timeout=cfg.timeout,
        enabled=cfg.enabled,
    )


def save_datasource(cfg: DatasourceConfig) -> DatasourceConfig:
    """Create a new datasource config."""
    configs = _load_all()
    if cfg.id in configs:
        raise ValueError(f"数据源 '{cfg.id}' 已存在")
    configs[cfg.id] = cfg
    _save_all(configs)
    return cfg


def update_datasource(
    datasource_id: str,
    cfg: DatasourceConfig,
) -> DatasourceConfig | None:
    """Update an existing datasource config."""
    configs = _load_all()
    if datasource_id not in configs:
        return None
    # allow id rename
    if cfg.id != datasource_id:
        if cfg.id in configs:
            raise ValueError(f"数据源 '{cfg.id}' 已存在")
        del configs[datasource_id]
    configs[cfg.id] = cfg
    _save_all(configs)
    return cfg


def delete_datasource(datasource_id: str) -> bool:
    """Delete a datasource config."""
    configs = _load_all()
    if datasource_id not in configs:
        return False
    del configs[datasource_id]
    _save_all(configs)
    return True


def invalidate_cache() -> None:
    """Drop the in-process cache so the next read reloads from disk."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


def list_bigscreen_datasources() -> list[DatasourceConfig]:
    """Enabled datasources that opted into the big-screen catalog."""
    return [
        cfg
        for cfg in _load_all().values()
        if cfg.enabled
        and cfg.big_screen is not None
        and cfg.big_screen.enabled
    ]


def _resolve_url(url_template: str, params: dict[str, Any]) -> str:
    try:
        return url_template.format(**params)
    except KeyError as exc:
        raise RuntimeError(f"URL 模板缺少参数: {exc}") from exc


def execute_datasource_request(
    cfg: DatasourceConfig,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Server-side call to a registered datasource (big-screen use).

    Unlike the public ``/proxy/{id}`` route this allows operator-
    registered intranet hosts (the operator deliberately registered
    them), but it **locks the scheme+host to the template** so a
    param can never redirect the call elsewhere (anti-SSRF-via-param).
    Returns ``{"status_code", "json", "text"}``; raises ``RuntimeError``
    on transport failure so the caller marks the capability failed.
    """
    import httpx

    from urllib.parse import urlparse

    merged = {**cfg.default_params, **(params or {})}
    template_netloc = urlparse(cfg.url_template).netloc
    if "{" in template_netloc or "}" in template_netloc:
        raise RuntimeError("数据源 URL 的主机部分不允许使用参数占位符")

    target_url = _resolve_url(cfg.url_template, merged)
    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https") or parsed.netloc != (
        template_netloc
    ):
        raise RuntimeError("解析后的请求地址主机被篡改,已阻断")

    body: str | None = None
    if cfg.method in ("POST", "PUT") and cfg.body_template is not None:
        if isinstance(cfg.body_template, str):
            try:
                body = cfg.body_template.format(**merged)
            except KeyError:
                body = cfg.body_template
        else:
            body = json.dumps({**cfg.body_template, **merged})

    try:
        with httpx.Client(timeout=cfg.timeout) as client:
            resp = client.request(
                method=cfg.method,
                url=target_url,
                headers=dict(cfg.headers),
                content=body,
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"数据源响应超时: {cfg.id}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"数据源请求失败: {exc}") from exc

    payload: Any = None
    try:
        payload = resp.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    return {
        "status_code": resp.status_code,
        "json": payload,
        "text": resp.text if payload is None else "",
    }
