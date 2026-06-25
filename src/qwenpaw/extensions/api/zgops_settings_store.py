# -*- coding: utf-8 -*-
"""Settings-page store for the zgops CMDB connection.

Namespace ``zgops`` / endpoint ``/zgops-settings``. Fields mirror the
``ZGOPS_*`` env vars that the zgops-cmdb skills (and resource_import /
alarm_analyst_service in the main process) read. Resolved through here
(DB override > env > default) and materialised into ``os.environ`` by
:mod:`working_secrets` so skill subprocesses inherit them. See
:mod:`provider_settings_base`.
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

_NAMESPACE = "zgops"

# Cluster-internal CMDB service; the default "恢复默认" / fresh-deploy value.
DEFAULT_ZGOPS_BASE_URL = "http://cnos-iomp-inoe-ui-cmdb:80"

__all__ = [
    "CLEAR_SENTINEL",
    "ZGOPS_FIELD_SPECS",
    "resolve_text",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

ZGOPS_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "zgops_base_url",
            "ZGOPS_BASE_URL",
            DEFAULT_ZGOPS_BASE_URL,
            "str",
            "zgops",
        ),
        FieldSpec(
            "zgops_username",
            "ZGOPS_USERNAME",
            "",
            "str",
            "zgops",
        ),
        FieldSpec(
            "zgops_password",
            "ZGOPS_PASSWORD",
            "",
            "str",
            "zgops",
            sensitive=True,
        ),
        FieldSpec(
            "zgops_session_name",
            "ZGOPS_SESSION_NAME",
            "",
            "str",
            "zgops",
        ),
    )
}

_SPEC_BY_ENV = base.spec_by_env(ZGOPS_FIELD_SPECS)


def resolve_text(
    env_var: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one ``ZGOPS_*`` field as text for materialisation."""
    return base.resolve_text(
        _SPEC_BY_ENV, env_var, namespace=_NAMESPACE, db_path=db_path
    )


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    return base.build_payload(
        ZGOPS_FIELD_SPECS, namespace=_NAMESPACE, db_path=db_path
    )


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.apply_update(
        ZGOPS_FIELD_SPECS, body, namespace=_NAMESPACE, db_path=db_path
    )


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    base.reset_setting(
        ZGOPS_FIELD_SPECS, key, namespace=_NAMESPACE, db_path=db_path
    )


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return base.has_override(key, namespace=_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.set_overrides(partial, namespace=_NAMESPACE, db_path=db_path)
