# -*- coding: utf-8 -*-
"""Settings-page store for the Nightingale (N9E) log connection.

Namespace ``n9e`` / endpoint ``/n9e-settings``. Fields mirror the shared
``N9E_*`` env vars that the log skills (log-hazard-detection,
log-security-scan, nightingale-log) read via ``_n9e_client.py`` (env is
preferred, ``.env`` is only a fallback). Resolved here (DB override > env >
default) and materialised into ``os.environ`` by :mod:`working_secrets`.
See :mod:`provider_settings_base`.

Note: per-skill tuning ``N9E_LOG_MAX_SIZE`` / ``N9E_LOG_TIMEOUT`` differ
between skills, so they stay as each skill's script default and are not
modelled here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qwenpaw.extensions.api import provider_settings_base as base
from qwenpaw.extensions.api.provider_settings_base import (
    CLEAR_SENTINEL,
    FieldSpec,
)
from qwenpaw.extensions.runtime_data_paths import (
    SETTINGS_DB_PATH as DEFAULT_DB_PATH,
)

_NAMESPACE = "n9e"

DEFAULT_TIMESTAMP_FIELD = "@timestamp"

__all__ = [
    "CLEAR_SENTINEL",
    "N9E_FIELD_SPECS",
    "resolve_text",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

N9E_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "n9e_api_base_url",
            "N9E_API_BASE_URL",
            "",
            "str",
            "n9e",
        ),
        FieldSpec(
            "n9e_user_token",
            "N9E_USER_TOKEN",
            "",
            "str",
            "n9e",
            sensitive=True,
        ),
        FieldSpec(
            "n9e_log_datasource_id",
            "N9E_LOG_DATASOURCE_ID",
            "1",
            "str",
            "n9e",
        ),
        FieldSpec(
            "n9e_log_index",
            "N9E_LOG_INDEX",
            "",
            "str",
            "n9e",
        ),
        FieldSpec(
            "n9e_log_timestamp_field",
            "N9E_LOG_TIMESTAMP_FIELD",
            DEFAULT_TIMESTAMP_FIELD,
            "str",
            "n9e",
        ),
    )
}

_SPEC_BY_ENV = base.spec_by_env(N9E_FIELD_SPECS)


def resolve_text(
    env_var: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one ``N9E_*`` field as text for materialisation."""
    return base.resolve_text(
        _SPEC_BY_ENV, env_var, namespace=_NAMESPACE, db_path=db_path
    )


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    return base.build_payload(
        N9E_FIELD_SPECS, namespace=_NAMESPACE, db_path=db_path
    )


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.apply_update(
        N9E_FIELD_SPECS, body, namespace=_NAMESPACE, db_path=db_path
    )


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    base.reset_setting(
        N9E_FIELD_SPECS, key, namespace=_NAMESPACE, db_path=db_path
    )


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return base.has_override(key, namespace=_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.set_overrides(partial, namespace=_NAMESPACE, db_path=db_path)
