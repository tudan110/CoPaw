# -*- coding: utf-8 -*-
"""Settings-page store for the Xingchen model adapter connection.

Namespace ``xingchen`` / endpoint ``/xingchen-settings``. Fields mirror
what ``xingchen_openai_adapter`` reads from ``QWENPAW_XINGCHEN_*`` env vars
(connection + credentials + models), so the adapter resolves them through
here (DB override > env > default). See :mod:`provider_settings_base`.
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

_NAMESPACE = "xingchen"

# Defaults match xingchen_openai_adapter's hard-coded constants.
DEFAULT_CHAT_PATH = "/aipaas/lm/v1/telechat/chat115b"
DEFAULT_MODELS = "telechat-115b"

__all__ = [
    "CLEAR_SENTINEL",
    "XINGCHEN_FIELD_SPECS",
    "resolve_text",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

XINGCHEN_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "xingchen_base_url",
            "QWENPAW_XINGCHEN_BASE_URL",
            "",
            "str",
            "xingchen",
        ),
        FieldSpec(
            "xingchen_chat_path",
            "QWENPAW_XINGCHEN_CHAT_PATH",
            DEFAULT_CHAT_PATH,
            "str",
            "xingchen",
        ),
        FieldSpec(
            "xingchen_chat_url",
            "QWENPAW_XINGCHEN_CHAT_URL",
            "",
            "str",
            "xingchen",
        ),
        FieldSpec(
            "xingchen_models",
            "QWENPAW_XINGCHEN_MODELS",
            DEFAULT_MODELS,
            "str",
            "xingchen",
        ),
        FieldSpec(
            "xingchen_app_id",
            "QWENPAW_XINGCHEN_APP_ID",
            "",
            "str",
            "xingchen",
        ),
        FieldSpec(
            "xingchen_order_num",
            "QWENPAW_XINGCHEN_ORDER_NUM",
            "",
            "str",
            "xingchen",
        ),
        FieldSpec(
            "xingchen_authorization",
            "QWENPAW_XINGCHEN_AUTHORIZATION",
            "",
            "str",
            "xingchen",
            sensitive=True,
        ),
    )
}

_SPEC_BY_ENV = base.spec_by_env(XINGCHEN_FIELD_SPECS)


def resolve_text(
    env_var: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one ``QWENPAW_XINGCHEN_*`` field as text for the adapter."""
    return base.resolve_text(
        _SPEC_BY_ENV, env_var, namespace=_NAMESPACE, db_path=db_path
    )


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    return base.build_payload(
        XINGCHEN_FIELD_SPECS, namespace=_NAMESPACE, db_path=db_path
    )


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.apply_update(
        XINGCHEN_FIELD_SPECS, body, namespace=_NAMESPACE, db_path=db_path
    )


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    base.reset_setting(
        XINGCHEN_FIELD_SPECS, key, namespace=_NAMESPACE, db_path=db_path
    )


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return base.has_override(key, namespace=_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.set_overrides(partial, namespace=_NAMESPACE, db_path=db_path)
