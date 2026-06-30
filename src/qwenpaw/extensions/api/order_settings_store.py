# -*- coding: utf-8 -*-
"""Settings-page store for the work-order (order-workflow / ferry) connection.

Namespace ``order`` / endpoint ``/order-settings``. The big-screen 工单 path
and the ``order-workflow`` skill resolve the ferry work-order API from
``ORDER_API_BASE_URL`` / ``ORDER_AUTHORIZATION`` (see the skill's
``runtime/client.py``), **falling back to ``INOE_API_BASE_URL`` /
``INOE_API_TOKEN``** when those are unset. Historically these lived in the
shared ``secrets/inoe.env`` file; once that file stopped being auto-loaded the
ferry connection had no home on the settings page — work-orders silently fell
back to the (different) INOE platform endpoint and returned nothing.

This store gives work-orders their own ``ORDER_*`` env vars (the 工单 tab),
independent of the 平台/``inoe`` tab. Fields are resolved through here (DB
override > env > default) and materialised into ``os.environ`` by
:mod:`working_secrets` so the skill subprocess inherits them. Leaving a field
empty preserves the client's INOE fallback. See :mod:`provider_settings_base`.
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

_NAMESPACE = "order"

__all__ = [
    "CLEAR_SENTINEL",
    "ORDER_FIELD_SPECS",
    "resolve_text",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

ORDER_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "order_api_base_url",
            "ORDER_API_BASE_URL",
            "",
            "str",
            "order",
        ),
        FieldSpec(
            "order_authorization",
            "ORDER_AUTHORIZATION",
            "",
            "str",
            "order",
            sensitive=True,
        ),
        FieldSpec(
            "order_timeout_seconds",
            "ORDER_TIMEOUT_SECONDS",
            20.0,
            "float",
            "order",
            min_value=0.1,
        ),
        FieldSpec(
            "order_verify_ssl",
            "ORDER_VERIFY_SSL",
            True,
            "bool",
            "order",
        ),
        FieldSpec(
            "order_enable_curl_fallback",
            "ORDER_ENABLE_CURL_FALLBACK",
            True,
            "bool",
            "order",
        ),
    )
}

_SPEC_BY_ENV = base.spec_by_env(ORDER_FIELD_SPECS)


def resolve_text(
    env_var: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one ``ORDER_*`` field as text for materialisation."""
    return base.resolve_text(
        _SPEC_BY_ENV, env_var, namespace=_NAMESPACE, db_path=db_path
    )


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    return base.build_payload(
        ORDER_FIELD_SPECS, namespace=_NAMESPACE, db_path=db_path
    )


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.apply_update(
        ORDER_FIELD_SPECS, body, namespace=_NAMESPACE, db_path=db_path
    )


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    base.reset_setting(
        ORDER_FIELD_SPECS, key, namespace=_NAMESPACE, db_path=db_path
    )


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return base.has_override(key, namespace=_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.set_overrides(partial, namespace=_NAMESPACE, db_path=db_path)
