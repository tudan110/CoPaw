# -*- coding: utf-8 -*-
"""Datasource config CRUD — JSON file persistence."""
from __future__ import annotations

import json
from pathlib import Path
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


def get_datasource(id: str) -> DatasourceConfig | None:
    """Get a single datasource config (includes headers — server-side only)."""
    return _load_all().get(id)


def get_datasource_summary(id: str) -> DatasourceSummary | None:
    """Get a single datasource summary (safe for client)."""
    cfg = get_datasource(id)
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


def update_datasource(id: str, cfg: DatasourceConfig) -> DatasourceConfig | None:
    """Update an existing datasource config."""
    configs = _load_all()
    if id not in configs:
        return None
    # allow id rename
    if cfg.id != id:
        if cfg.id in configs:
            raise ValueError(f"数据源 '{cfg.id}' 已存在")
        del configs[id]
    configs[cfg.id] = cfg
    _save_all(configs)
    return cfg


def delete_datasource(id: str) -> bool:
    """Delete a datasource config."""
    configs = _load_all()
    if id not in configs:
        return False
    del configs[id]
    _save_all(configs)
    return True