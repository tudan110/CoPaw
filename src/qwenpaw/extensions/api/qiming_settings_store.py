# -*- coding: utf-8 -*-
"""Settings-page store for the Qiming model adapter connection.

Namespace ``qiming`` / endpoint ``/qiming-settings``. Fields mirror exactly
what ``qiming_openai_adapter`` reads from ``QWENPAW_QIMING_*`` env vars, so
the adapter can resolve them through here (DB override > env > default)
instead of only from ``.env``. See :mod:`provider_settings_base`.
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

_NAMESPACE = "qiming"

# Defaults match qiming_openai_adapter's hard-coded constants so resolution
# is unchanged when no override and no env value exist.
DEFAULT_COMPLETIONS_PATH = "/serviceAgent/rest/wsc/completions"
DEFAULT_MODELS = "qiming25_72b_fc"

__all__ = [
    "CLEAR_SENTINEL",
    "QIMING_FIELD_SPECS",
    "resolve_text",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

QIMING_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "qiming_base_url",
            "QWENPAW_QIMING_BASE_URL",
            "",
            "str",
            "qiming",
        ),
        FieldSpec(
            "qiming_completions_path",
            "QWENPAW_QIMING_COMPLETIONS_PATH",
            DEFAULT_COMPLETIONS_PATH,
            "str",
            "qiming",
        ),
        FieldSpec(
            "qiming_completions_url",
            "QWENPAW_QIMING_COMPLETIONS_URL",
            "",
            "str",
            "qiming",
        ),
        FieldSpec(
            "qiming_models",
            "QWENPAW_QIMING_MODELS",
            DEFAULT_MODELS,
            "str",
            "qiming",
        ),
        FieldSpec(
            "qiming_app_id",
            "QWENPAW_QIMING_APP_ID",
            "",
            "str",
            "qiming",
        ),
        FieldSpec(
            "qiming_app_key",
            "QWENPAW_QIMING_APP_KEY",
            "",
            "str",
            "qiming",
            sensitive=True,
        ),
        FieldSpec(
            "qiming_bearer_token",
            "QWENPAW_QIMING_BEARER_TOKEN",
            "",
            "str",
            "qiming",
            sensitive=True,
        ),
    )
}

_SPEC_BY_ENV = base.spec_by_env(QIMING_FIELD_SPECS)


def resolve_text(
    env_var: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one ``QWENPAW_QIMING_*`` field as text for the adapter."""
    return base.resolve_text(
        _SPEC_BY_ENV, env_var, namespace=_NAMESPACE, db_path=db_path
    )


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    return base.build_payload(
        QIMING_FIELD_SPECS, namespace=_NAMESPACE, db_path=db_path
    )


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.apply_update(
        QIMING_FIELD_SPECS, body, namespace=_NAMESPACE, db_path=db_path
    )


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    base.reset_setting(
        QIMING_FIELD_SPECS, key, namespace=_NAMESPACE, db_path=db_path
    )


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return base.has_override(key, namespace=_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.set_overrides(partial, namespace=_NAMESPACE, db_path=db_path)
