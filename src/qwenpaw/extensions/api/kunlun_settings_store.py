# -*- coding: utf-8 -*-
"""Settings-page store for the Kunlun open-gateway LLM adapter.

Namespace ``kunlun`` / endpoint ``/kunlun-settings``. Fields mirror what
``kunlun_openai_adapter`` reads from ``QWENPAW_KUNLUN_*`` env vars
(gateway connection + OAuth2 client credentials + models), so the adapter
resolves them through here (DB override > env > default). See
:mod:`provider_settings_base`.

The defaults encode subscription ``1043177`` (云算网智算统一网关): the
token endpoint was recovered by decrypting the colleague's SDK
``deliverables.enc`` — the gateway issues OAuth2 ``client_credentials``
tokens at ``/kunlun-auth-service/oauth2/token`` with HTTP Basic
``appCode:appSecret``.
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

_NAMESPACE = "kunlun"

# Defaults match kunlun_openai_adapter's hard-coded constants.
DEFAULT_BASE_URL = "https://ogw.klnaas.189.cn:21000"
DEFAULT_CHAT_PATH = "/api/chinatelecom/cnos/swdd/cpn/aiapp/v1/chat/completions"
DEFAULT_AUTH_PATH = "/kunlun-auth-service/oauth2/token"
# Placeholder from the subscription example; replace once the gateway team
# confirms the real 应用 ID for subscription 1043177.
DEFAULT_MODELS = "app_001"
DEFAULT_AI_USER_ID = "qwenpaw"

__all__ = [
    "CLEAR_SENTINEL",
    "KUNLUN_FIELD_SPECS",
    "resolve_text",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

KUNLUN_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "kunlun_base_url",
            "QWENPAW_KUNLUN_BASE_URL",
            DEFAULT_BASE_URL,
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_chat_path",
            "QWENPAW_KUNLUN_CHAT_PATH",
            DEFAULT_CHAT_PATH,
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_chat_url",
            "QWENPAW_KUNLUN_CHAT_URL",
            "",
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_auth_url",
            "QWENPAW_KUNLUN_AUTH_URL",
            "",
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_app_code",
            "QWENPAW_KUNLUN_APP_CODE",
            "",
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_app_secret",
            "QWENPAW_KUNLUN_APP_SECRET",
            "",
            "str",
            "kunlun",
            sensitive=True,
        ),
        FieldSpec(
            "kunlun_models",
            "QWENPAW_KUNLUN_MODELS",
            DEFAULT_MODELS,
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_model_id_header",
            "QWENPAW_KUNLUN_MODEL_ID_HEADER",
            "",
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_client_id",
            "QWENPAW_KUNLUN_CLIENT_ID",
            "",
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_ai_user_id",
            "QWENPAW_KUNLUN_AI_USER_ID",
            DEFAULT_AI_USER_ID,
            "str",
            "kunlun",
        ),
        FieldSpec(
            "kunlun_verify_ssl",
            "QWENPAW_KUNLUN_VERIFY_SSL",
            False,
            "bool",
            "kunlun",
        ),
    )
}

_SPEC_BY_ENV = base.spec_by_env(KUNLUN_FIELD_SPECS)


def resolve_text(
    env_var: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one ``QWENPAW_KUNLUN_*`` field as text for the adapter."""
    return base.resolve_text(
        _SPEC_BY_ENV,
        env_var,
        namespace=_NAMESPACE,
        db_path=db_path,
    )


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    return base.build_payload(
        KUNLUN_FIELD_SPECS,
        namespace=_NAMESPACE,
        db_path=db_path,
    )


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.apply_update(
        KUNLUN_FIELD_SPECS,
        body,
        namespace=_NAMESPACE,
        db_path=db_path,
    )


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    base.reset_setting(
        KUNLUN_FIELD_SPECS,
        key,
        namespace=_NAMESPACE,
        db_path=db_path,
    )


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return base.has_override(key, namespace=_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    base.set_overrides(partial, namespace=_NAMESPACE, db_path=db_path)
