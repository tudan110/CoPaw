# -*- coding: utf-8 -*-
"""Settings-page store for the operator (page-operator) menu connection.

Namespace ``operator`` / endpoint ``/operator-settings``. The operator agent's
``page-operator`` skill resolves portal menu routes (getRouters) from an INOE
endpoint, exactly like ``page-navigator``. Historically both read the *shared*
``INOE_MENU_*`` / ``INOE_API_*`` env vars, so they could not be pointed at
different backends from the settings page without colliding.

This store gives the operator its own ``OPERATOR_MENU_*`` env vars (independent
of the 平台/``inoe`` tab that drives page-navigator). Fields are resolved
through here (DB override > env > default) and materialised into ``os.environ``
by :mod:`working_secrets` so the skill subprocess inherits them. The skill
falls back to ``INOE_MENU_*`` / ``INOE_API_*`` when an operator field is unset.
See :mod:`provider_settings_base`.
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

_NAMESPACE = "operator"

__all__ = [
    "CLEAR_SENTINEL",
    "OPERATOR_FIELD_SPECS",
    "resolve_text",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

OPERATOR_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "operator_menu_base_url",
            "OPERATOR_MENU_BASE_URL",
            "",
            "str",
            "operator",
        ),
        FieldSpec(
            "operator_menu_token",
            "OPERATOR_MENU_TOKEN",
            "",
            "str",
            "operator",
            sensitive=True,
        ),
        FieldSpec(
            "operator_menu_app_code",
            "OPERATOR_MENU_APP_CODE",
            "inoe",
            "str",
            "operator",
        ),
        FieldSpec(
            "operator_menu_timeout_seconds",
            "OPERATOR_MENU_TIMEOUT_SECONDS",
            20.0,
            "float",
            "operator",
            min_value=0.1,
        ),
        FieldSpec(
            "operator_menu_cache_ttl_seconds",
            "OPERATOR_MENU_CACHE_TTL_SECONDS",
            600.0,
            "float",
            "operator",
            min_value=0,
        ),
    )
}

_SPEC_BY_ENV = base.spec_by_env(OPERATOR_FIELD_SPECS)


def resolve_text(
    env_var: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one ``OPERATOR_*`` field as text for materialisation."""
    return base.resolve_text(
        _SPEC_BY_ENV, env_var, namespace=_NAMESPACE, db_path=db_path
    )


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    return base.build_payload(
        OPERATOR_FIELD_SPECS, namespace=_NAMESPACE, db_path=db_path
    )


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.apply_update(
        OPERATOR_FIELD_SPECS, body, namespace=_NAMESPACE, db_path=db_path
    )


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    base.reset_setting(
        OPERATOR_FIELD_SPECS, key, namespace=_NAMESPACE, db_path=db_path
    )


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return base.has_override(key, namespace=_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.set_overrides(partial, namespace=_NAMESPACE, db_path=db_path)
