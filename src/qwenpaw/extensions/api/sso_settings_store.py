# -*- coding: utf-8 -*-
"""Single source of truth for the INOE OAuth2 single-sign-on credentials.

The portal acts as an OAuth2 client (``client_id`` ``ndai``) against the
INOE auth gateway (IdP). To exchange an authorization ``code`` for a token
the backend needs four values: the gateway base URL, the client id, the
HMAC signing secret, and the registered redirect URI. None of these belong
in source — they are deployment-specific and the secret must never ship in
the repo or reach the browser.

This module makes those four values a standalone settings concern with its
own namespace (``sso``) and its own ``/sso-settings`` API, mirroring
:mod:`inoe_settings_store`. Resolution order for each field::

    sso-namespace page override  ->  environment variable  ->  default

so the settings page wins, the env var is the transition fallback, and the
hard-coded default is empty (the operator must configure the integration).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qwenpaw.extensions.api import inoe_settings_store, settings_store
from qwenpaw.extensions.api.diagnosis_settings_store import (
    CLEAR_SENTINEL,
    FieldSpec,
    coerce_value,
    mask_token,
)
from qwenpaw.extensions.runtime_data_paths import (
    SETTINGS_DB_PATH as DEFAULT_DB_PATH,
)

# This concern owns the ``sso`` namespace in the shared settings DB.
_NAMESPACE = "sso"

# OAuth2 endpoints (authorize/token/userinfo) live under this path on the
# INOE gateway. When the SSO gateway base is left blank, we derive it from
# the platform's INOE gateway address (inoe_settings_store) + this suffix,
# so operators don't configure the same host twice.
_OAUTH2_PATH_SUFFIX = "/auth/oauth2"

# token-passthrough validates the INOE login token against this path,
# resolved against the platform INOE gateway *root* (not /auth/oauth2).
# Default is INOE's own getInfo endpoint (verified working on the demo);
# override to /auth/oauth2/userinfo once that is deployed.
DEFAULT_USERINFO_PATH = "/admin/user/getInfo"

__all__ = [
    "CLEAR_SENTINEL",
    "SSO_FIELD_SPECS",
    "get_gateway_base_url",
    "get_userinfo_url",
    "get_client_id",
    "get_client_secret",
    "get_redirect_uri",
    "is_configured",
    "is_token_login_ready",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]

SSO_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "sso_gateway_base_url",
            "QWENPAW_SSO_GATEWAY_BASE_URL",
            "",
            "str",
            "sso",
        ),
        FieldSpec(
            "sso_client_id",
            "QWENPAW_SSO_CLIENT_ID",
            "",
            "str",
            "sso",
        ),
        FieldSpec(
            "sso_client_secret",
            "QWENPAW_SSO_CLIENT_SECRET",
            "",
            "str",
            "sso",
            sensitive=True,
        ),
        FieldSpec(
            "sso_redirect_uri",
            "QWENPAW_SSO_REDIRECT_URI",
            "",
            "str",
            "sso",
        ),
        FieldSpec(
            "sso_userinfo_path",
            "QWENPAW_SSO_USERINFO_PATH",
            DEFAULT_USERINFO_PATH,
            "str",
            "sso",
        ),
    )
}


# ---------------------------------------------------------------------------
# Resolution: sso override -> env -> default (delegated to FieldSpec.resolve)
# ---------------------------------------------------------------------------


def _resolve(spec: FieldSpec, *, db_path: Path = DEFAULT_DB_PATH) -> Any:
    overrides = settings_store.get_namespace(_NAMESPACE, db_path=db_path)
    if spec.key in overrides:
        raw = overrides[spec.key]
        return raw if isinstance(raw, str) else str(raw or "")
    return spec.env_value()


def get_gateway_base_url(*, db_path: Path = DEFAULT_DB_PATH) -> str:
    """OAuth2 base URL (authorize/token/userinfo live directly under it).

    An explicit ``sso_gateway_base_url`` override wins (e.g. when SSO must
    go through a different host/nginx path). Otherwise it is derived from
    the platform INOE gateway address + ``/auth/oauth2`` so the host is
    configured in one place only.
    """
    spec = SSO_FIELD_SPECS["sso_gateway_base_url"]
    override = str(_resolve(spec, db_path=db_path) or "").strip()
    if override:
        return override.rstrip("/")
    inoe_base = inoe_settings_store.get_base_url(db_path=db_path).rstrip("/")
    return f"{inoe_base}{_OAUTH2_PATH_SUFFIX}" if inoe_base else ""


def get_client_id(*, db_path: Path = DEFAULT_DB_PATH) -> str:
    return str(
        _resolve(SSO_FIELD_SPECS["sso_client_id"], db_path=db_path) or ""
    ).strip()


def get_client_secret(*, db_path: Path = DEFAULT_DB_PATH) -> str:
    return str(
        _resolve(SSO_FIELD_SPECS["sso_client_secret"], db_path=db_path) or ""
    ).strip()


def get_redirect_uri(*, db_path: Path = DEFAULT_DB_PATH) -> str:
    return str(
        _resolve(SSO_FIELD_SPECS["sso_redirect_uri"], db_path=db_path) or ""
    ).strip()


def get_userinfo_url(*, db_path: Path = DEFAULT_DB_PATH) -> str:
    """Full URL the token-passthrough flow calls to validate a login token.

    ``sso_userinfo_path`` is resolved against the platform INOE gateway
    *root* (e.g. ``http://gw:30080`` + ``/admin/user/getInfo``). An absolute
    http(s) path is taken verbatim. Empty when the INOE gateway is unset.
    """
    path = str(
        _resolve(SSO_FIELD_SPECS["sso_userinfo_path"], db_path=db_path) or ""
    ).strip() or DEFAULT_USERINFO_PATH
    if path.lower().startswith(("http://", "https://")):
        return path
    base = inoe_settings_store.get_base_url(db_path=db_path).rstrip("/")
    if not base:
        return ""
    return f"{base}/{path.lstrip('/')}"


def is_token_login_ready(*, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Whether token-passthrough can run (just needs a userinfo URL)."""
    return bool(get_userinfo_url(db_path=db_path))


def is_configured(*, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Whether the three values needed to exchange a code are all present.

    ``redirect_uri`` is optional on the wire (only required when the IdP
    registered the code against one), so it is not part of this check.
    """
    return bool(
        get_gateway_base_url(db_path=db_path)
        and get_client_id(db_path=db_path)
        and get_client_secret(db_path=db_path)
    )


# ---------------------------------------------------------------------------
# Settings API: payload / update / reset (mirrors inoe_settings_store)
# ---------------------------------------------------------------------------


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Whether ``key`` currently has a page override."""
    return key in settings_store.get_namespace(_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Write raw override values into the sso namespace (test convenience)."""
    settings_store.set_values(_NAMESPACE, partial, db_path=db_path)


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Build the ``{effective, env, overrides, groups}`` payload.

    Same shape as :func:`inoe_settings_store.build_settings_payload` so the
    portal reuses one settings payload type. The client secret is masked in
    both the effective and env layers.
    """
    overrides = settings_store.get_namespace(_NAMESPACE, db_path=db_path)
    effective: dict[str, Any] = {}
    env: dict[str, Any] = {}
    override_keys: dict[str, bool] = {}
    groups: dict[str, str] = {}
    for key, spec in SSO_FIELD_SPECS.items():
        override_keys[key] = key in overrides
        groups[key] = spec.group
        if spec.sensitive:
            eff_raw = str(_resolve(spec, db_path=db_path) or "")
            env_raw = str(spec.env_value() or "")
            effective[key] = {
                "is_set": bool(eff_raw),
                "masked": mask_token(eff_raw),
            }
            env[key] = {
                "is_set": bool(env_raw),
                "masked": mask_token(env_raw),
            }
        else:
            effective[key] = _resolve(spec, db_path=db_path)
            env[key] = spec.env_value()
    return {
        "effective": effective,
        "env": env,
        "overrides": override_keys,
        "groups": groups,
    }


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Validate a partial update and persist it into the sso namespace.

    Sensitive (secret) fields: an empty string is a no-op (keep current),
    and ``CLEAR_SENTINEL`` deletes the override. Unknown keys are rejected.
    Raises ``ValueError`` on invalid input (mapped to HTTP 400 by caller).
    """
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    to_set: dict[str, Any] = {}
    to_delete: list[str] = []
    for key, raw in body.items():
        spec = SSO_FIELD_SPECS.get(key)
        if spec is None:
            raise ValueError(f"Unknown setting: {key}")
        if spec.sensitive:
            if raw == CLEAR_SENTINEL:
                to_delete.append(key)
                continue
            if isinstance(raw, str) and raw.strip() == "":
                # Empty = leave the stored secret untouched.
                continue
        to_set[key] = coerce_value(spec, raw)
    for key in to_delete:
        settings_store.delete_value(_NAMESPACE, key, db_path=db_path)
    if to_set:
        settings_store.set_values(_NAMESPACE, to_set, db_path=db_path)


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Drop one field's override so it falls back to env/default."""
    if key not in SSO_FIELD_SPECS:
        raise ValueError(f"Unknown setting: {key}")
    settings_store.delete_value(_NAMESPACE, key, db_path=db_path)
