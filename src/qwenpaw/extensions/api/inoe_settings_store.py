# -*- coding: utf-8 -*-
"""Single source of truth for the INOE alarm-gateway connection.

The INOE gateway (base URL / bearer token / request timeout) is shared
infrastructure: the monitoring overview dashboard, the portal real-alarm
list, and the alarm-workorder bridge all talk to it. Historically each
consumer resolved the connection on its own — some via the shared settings
store (page override > env > default), some reading ``.env`` directly. That
drift is exactly what let ``/overview`` 500 while the real-alarm list kept
working: they pointed at different gateways.

This module makes the INOE connection a *standalone* settings concern with
its own namespace (``inoe``) and its own ``/inoe-settings`` API, so every
consumer reads one resolved value.

Resolution order for each field::

    inoe-namespace override -> (legacy) diagnosis-namespace override
                            -> environment variable -> hard-coded default

The legacy diagnosis layer exists only for migration: these three keys used
to live under the ``diagnosis`` namespace.
:func:`migrate_legacy_inoe_overrides` moves any existing values into the new
namespace once; the legacy read is a safety net if migration has not run yet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.api.diagnosis_settings_store import (
    CLEAR_SENTINEL,
    FieldSpec,
    coerce_value,
    mask_token,
)
from qwenpaw.extensions.runtime_data_paths import (
    SETTINGS_DB_PATH as DEFAULT_DB_PATH,
)

# This concern owns the ``inoe`` namespace; ``diagnosis`` is the legacy home.
_NAMESPACE = "inoe"
_LEGACY_NAMESPACE = "diagnosis"

# Set once after the legacy values have been copied into ``inoe``.
_MIGRATION_FLAG = "inoe_namespace_migrated_v1"

DEFAULT_INOE_API_BASE_URL = "http://gateway:30080"
DEFAULT_INOE_API_TIMEOUT_SECONDS = 30.0

# Re-exported so callers can build masked PUT bodies without importing the
# diagnosis module.
__all__ = [
    "CLEAR_SENTINEL",
    "INOE_FIELD_SPECS",
    "get_base_url",
    "get_token",
    "get_timeout_seconds",
    "build_headers",
    "build_url",
    "build_settings_payload",
    "apply_settings_update",
    "reset_setting",
    "has_override",
    "set_overrides",
    "migrate_legacy_inoe_overrides",
]

INOE_FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "inoe_api_base_url",
            "INOE_API_BASE_URL",
            DEFAULT_INOE_API_BASE_URL,
            "str",
            "inoe",
        ),
        FieldSpec(
            "inoe_api_token",
            "INOE_API_TOKEN",
            "",
            "str",
            "inoe",
            sensitive=True,
        ),
        FieldSpec(
            "inoe_api_timeout_seconds",
            "INOE_API_TIMEOUT",
            DEFAULT_INOE_API_TIMEOUT_SECONDS,
            "float",
            "inoe",
            min_value=0.1,
        ),
    )
}

_INOE_KEYS = tuple(INOE_FIELD_SPECS.keys())


# ---------------------------------------------------------------------------
# One-time migration: diagnosis namespace -> inoe namespace
# ---------------------------------------------------------------------------


def migrate_legacy_inoe_overrides(*, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Copy any INOE overrides out of the legacy ``diagnosis`` namespace.

    Idempotent and best-effort: guarded by a one-time flag, and any failure
    is swallowed because :func:`_resolve` still falls back to reading the
    legacy namespace directly.
    """
    try:
        if settings_store.is_migrated(_MIGRATION_FLAG, db_path=db_path):
            return
        legacy = settings_store.get_namespace(
            _LEGACY_NAMESPACE,
            db_path=db_path,
        )
        current = settings_store.get_namespace(_NAMESPACE, db_path=db_path)
        moved = {
            key: legacy[key]
            for key in _INOE_KEYS
            if key in legacy and key not in current
        }
        if moved:
            settings_store.set_values(_NAMESPACE, moved, db_path=db_path)
            for key in moved:
                settings_store.delete_value(
                    _LEGACY_NAMESPACE,
                    key,
                    db_path=db_path,
                )
        settings_store.mark_migrated(_MIGRATION_FLAG, db_path=db_path)
    except Exception:  # noqa: BLE001 - migration must never break reads
        pass


# ---------------------------------------------------------------------------
# Resolution: inoe override -> legacy override -> env -> default
# ---------------------------------------------------------------------------


def _typed_override(spec: FieldSpec, raw: Any) -> Any:
    """Coerce a stored override value to the field's type, clamping bounds."""
    if spec.kind == "float":
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return float(spec.default)
        if spec.min_value is not None and value < spec.min_value:
            return float(spec.min_value)
        if spec.max_value is not None and value > spec.max_value:
            return float(spec.max_value)
        return value
    if spec.kind == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return int(spec.default)
        if spec.min_value is not None and value < spec.min_value:
            return int(spec.min_value)
        if spec.max_value is not None and value > spec.max_value:
            return int(spec.max_value)
        return value
    if isinstance(raw, str):
        return raw
    return str(raw) if raw is not None else ""


def _resolve(spec: FieldSpec, *, db_path: Path = DEFAULT_DB_PATH) -> Any:
    migrate_legacy_inoe_overrides(db_path=db_path)
    for namespace in (_NAMESPACE, _LEGACY_NAMESPACE):
        overrides = settings_store.get_namespace(namespace, db_path=db_path)
        if spec.key in overrides:
            return _typed_override(spec, overrides[spec.key])
    return spec.env_value()


def get_base_url(*, db_path: Path = DEFAULT_DB_PATH) -> str:
    raw = str(_resolve(INOE_FIELD_SPECS["inoe_api_base_url"], db_path=db_path))
    return (raw.strip() or DEFAULT_INOE_API_BASE_URL).rstrip("/")


def get_token(*, db_path: Path = DEFAULT_DB_PATH) -> str:
    return str(
        _resolve(INOE_FIELD_SPECS["inoe_api_token"], db_path=db_path) or ""
    ).strip()


def get_timeout_seconds(*, db_path: Path = DEFAULT_DB_PATH) -> float:
    return float(
        _resolve(
            INOE_FIELD_SPECS["inoe_api_timeout_seconds"],
            db_path=db_path,
        )
    )


# ---------------------------------------------------------------------------
# HTTP request helpers (shared by every INOE consumer)
# ---------------------------------------------------------------------------


def build_headers(*, db_path: Path = DEFAULT_DB_PATH) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    }
    token = get_token(db_path=db_path)
    if token:
        headers["Authorization"] = (
            token if token.lower().startswith("bearer ") else f"Bearer {token}"
        )
    return headers


def build_url(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    url = urljoin(f"{get_base_url(db_path=db_path)}/", path.lstrip("/"))
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


# ---------------------------------------------------------------------------
# Settings API: payload / update / reset (mirrors diagnosis_settings_store)
# ---------------------------------------------------------------------------


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Whether ``key`` has a page override (in either namespace)."""
    return key in settings_store.get_namespace(
        _NAMESPACE, db_path=db_path
    ) or key in settings_store.get_namespace(
        _LEGACY_NAMESPACE, db_path=db_path
    )


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Write raw override values into the inoe namespace (test convenience)."""
    settings_store.set_values(_NAMESPACE, partial, db_path=db_path)


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Build the ``{effective, env, overrides, groups}`` payload.

    Same shape as :func:`diagnosis_settings_store.build_settings_payload` so
    the portal reuses one ``DiagnosisSettingsPayload`` type. The token is
    masked in both the effective and env layers.
    """
    migrate_legacy_inoe_overrides(db_path=db_path)
    inoe_overrides = settings_store.get_namespace(_NAMESPACE, db_path=db_path)
    legacy_overrides = settings_store.get_namespace(
        _LEGACY_NAMESPACE,
        db_path=db_path,
    )
    effective: dict[str, Any] = {}
    env: dict[str, Any] = {}
    override_keys: dict[str, bool] = {}
    groups: dict[str, str] = {}
    for key, spec in INOE_FIELD_SPECS.items():
        override_keys[key] = key in inoe_overrides or key in legacy_overrides
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
    """Validate a partial update and persist it into the inoe namespace.

    Sensitive (token) fields: an empty string is a no-op (keep current),
    and ``CLEAR_SENTINEL`` deletes the override. Unknown keys are rejected.
    Raises ``ValueError`` on invalid input (mapped to HTTP 400 by caller).
    """
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    to_set: dict[str, Any] = {}
    to_delete: list[str] = []
    for key, raw in body.items():
        spec = INOE_FIELD_SPECS.get(key)
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
        settings_store.delete_value(_LEGACY_NAMESPACE, key, db_path=db_path)
    if to_set:
        settings_store.set_values(_NAMESPACE, to_set, db_path=db_path)


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Drop one field's override so it falls back to env/default."""
    if key not in INOE_FIELD_SPECS:
        raise ValueError(f"Unknown setting: {key}")
    settings_store.delete_value(_NAMESPACE, key, db_path=db_path)
    settings_store.delete_value(_LEGACY_NAMESPACE, key, db_path=db_path)
