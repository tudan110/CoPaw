# -*- coding: utf-8 -*-
"""Override layer for alarm-diagnosis settings.

The portal alarm-analysis pipeline historically read all of its knobs
(auto-takeover polling, INOE gateway connection, query window) from
environment variables only. That made local development painful: large
batches of historical alarms would keep getting analyzed, burning LLM
tokens, with no way to pause it short of editing ``.env`` and restarting.

This module adds a thin *override* layer. Only fields the operator
explicitly sets on the portal "诊断" settings page are stored. Resolution
order for every field is:

    DB override  ->  environment variable  ->  hard-coded default

so page settings win, but anything left untouched still falls back to the
existing env behaviour. Values are JSON scalars (bool / int / float / str).

Persistence lives in the shared settings database
(``~/.qwenpaw/extensions/settings/settings.db``) under the ``diagnosis``
namespace — see :mod:`qwenpaw.extensions.api.settings_store`. The shared
store already caches reads per namespace, so the auto-takeover loop can
read the toggle on every iteration without hitting disk.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qwenpaw.constant import EnvVarLoader
from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.runtime_data_paths import (
    SETTINGS_DB_PATH as DEFAULT_DB_PATH,
)

# All diagnosis overrides live under this namespace in the shared DB.
_NAMESPACE = "diagnosis"


# ---------------------------------------------------------------------------
# Low-level override storage (delegates to the shared settings store)
# ---------------------------------------------------------------------------


def get_overrides(*, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Return all stored override values as ``{key: scalar}``."""
    return settings_store.get_namespace(_NAMESPACE, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Insert or replace the given override keys. Empty dict is a no-op."""
    settings_store.set_values(_NAMESPACE, partial, db_path=db_path)


def delete_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Remove a single override so the field falls back to env/default."""
    settings_store.delete_value(_NAMESPACE, key, db_path=db_path)


def has_override(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Whether ``key`` currently has a stored page override."""
    return key in get_overrides(db_path=db_path)


# ---------------------------------------------------------------------------
# Typed resolvers: DB override -> env var -> hard-coded default
# ---------------------------------------------------------------------------


def resolve_bool(
    key: str,
    env_var: str,
    default: bool,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    overrides = get_overrides(db_path=db_path)
    if key in overrides:
        value = overrides[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
    return EnvVarLoader.get_bool(env_var, default)


def resolve_float(
    key: str,
    env_var: str,
    default: float,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> float:
    overrides = get_overrides(db_path=db_path)
    if key in overrides:
        try:
            value = float(overrides[key])
        except (TypeError, ValueError):
            value = default
        if min_value is not None and value < min_value:
            return min_value
        if max_value is not None and value > max_value:
            return max_value
        return value
    return EnvVarLoader.get_float(
        env_var,
        default,
        min_value=min_value,
        max_value=max_value,
    )


def resolve_int(
    key: str,
    env_var: str,
    default: int,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    overrides = get_overrides(db_path=db_path)
    if key in overrides:
        try:
            value = int(overrides[key])
        except (TypeError, ValueError):
            value = default
        if min_value is not None and value < min_value:
            return min_value
        if max_value is not None and value > max_value:
            return max_value
        return value
    return EnvVarLoader.get_int(
        env_var,
        default,
        min_value=min_value,
        max_value=max_value,
    )


def resolve_str(
    key: str,
    env_var: str,
    default: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    overrides = get_overrides(db_path=db_path)
    if key in overrides:
        value = overrides[key]
        if isinstance(value, str):
            return value
        if value is not None:
            return str(value)
    return EnvVarLoader.get_str(env_var, default)


# ---------------------------------------------------------------------------
# Field registry — single source of truth for the settings API
# ---------------------------------------------------------------------------
#
# Each field declares its storage key, the env var it falls back to, the
# hard-coded default, its type, optional bounds, the UI group, and whether
# it is sensitive (token). The portal GET/PUT handlers and the call sites in
# portal_backend / portal_real_alarms all reference these keys so the three
# stay consistent.

# Sentinel a PUT may send for a sensitive field to clear its override.
CLEAR_SENTINEL = "__CLEAR__"


class FieldSpec:
    """Declarative description of one diagnosis-settings field."""

    def __init__(
        self,
        key: str,
        env_var: str,
        default: Any,
        kind: str,
        group: str,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
        sensitive: bool = False,
    ) -> None:
        self.key = key
        self.env_var = env_var
        self.default = default
        self.kind = kind  # "bool" | "int" | "float" | "str"
        self.group = group
        self.min_value = min_value
        self.max_value = max_value
        self.sensitive = sensitive

    def resolve(self, *, db_path: Path = DEFAULT_DB_PATH) -> Any:
        if self.kind == "bool":
            return resolve_bool(
                self.key,
                self.env_var,
                bool(self.default),
                db_path=db_path,
            )
        if self.kind == "int":
            return resolve_int(
                self.key,
                self.env_var,
                int(self.default),
                min_value=(
                    int(self.min_value) if self.min_value is not None else None
                ),
                max_value=(
                    int(self.max_value) if self.max_value is not None else None
                ),
                db_path=db_path,
            )
        if self.kind == "float":
            return resolve_float(
                self.key,
                self.env_var,
                float(self.default),
                min_value=self.min_value,
                max_value=self.max_value,
                db_path=db_path,
            )
        return resolve_str(
            self.key,
            self.env_var,
            str(self.default),
            db_path=db_path,
        )

    def env_value(self) -> Any:
        """Value that would apply if no page override existed (env/default)."""
        if self.kind == "bool":
            return EnvVarLoader.get_bool(self.env_var, bool(self.default))
        if self.kind == "int":
            return EnvVarLoader.get_int(
                self.env_var,
                int(self.default),
                min_value=(
                    int(self.min_value) if self.min_value is not None else None
                ),
                max_value=(
                    int(self.max_value) if self.max_value is not None else None
                ),
            )
        if self.kind == "float":
            return EnvVarLoader.get_float(
                self.env_var,
                float(self.default),
                min_value=self.min_value,
                max_value=self.max_value,
            )
        return EnvVarLoader.get_str(self.env_var, str(self.default))


FIELD_SPECS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        # --- A. Auto-takeover polling throttle ---
        FieldSpec(
            "auto_takeover_enabled",
            "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED",
            True,
            "bool",
            "polling",
        ),
        FieldSpec(
            "auto_takeover_interval_seconds",
            "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_INTERVAL",
            60,
            "float",
            "polling",
            min_value=60,
        ),
        FieldSpec(
            "auto_takeover_limit",
            "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT",
            100,
            "int",
            "polling",
            min_value=1,
        ),
        FieldSpec(
            "max_active_analyses",
            "QWENPAW_PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES",
            1,
            "int",
            "polling",
            min_value=1,
        ),
        # --- B. INOE gateway connection ---
        FieldSpec(
            "inoe_api_base_url",
            "INOE_API_BASE_URL",
            "http://gateway:30080",
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
            30,
            "float",
            "inoe",
            min_value=0.1,
        ),
        # --- C. Query window ---
        FieldSpec(
            "timezone_offset_hours",
            "PORTAL_REAL_ALARM_TIMEZONE_OFFSET",
            8,
            "float",
            "query_window",
            min_value=-12,
            max_value=14,
        ),
        FieldSpec(
            "cache_ttl_seconds",
            "QWENPAW_PORTAL_REAL_ALARM_CACHE_TTL",
            30,
            "float",
            "query_window",
            min_value=0,
        ),
    )
}


def _mask_token(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Build the ``{effective, env, overrides}`` payload for the API.

    Sensitive fields never expose their raw value; they report
    ``{"is_set": bool, "masked": str}`` for both the effective and env
    layers instead.
    """
    overrides = get_overrides(db_path=db_path)
    effective: dict[str, Any] = {}
    env: dict[str, Any] = {}
    override_keys: dict[str, bool] = {}
    groups: dict[str, str] = {}
    for key, spec in FIELD_SPECS.items():
        override_keys[key] = key in overrides
        groups[key] = spec.group
        if spec.sensitive:
            eff_raw = str(spec.resolve(db_path=db_path) or "")
            env_raw = str(spec.env_value() or "")
            effective[key] = {
                "is_set": bool(eff_raw),
                "masked": _mask_token(eff_raw),
            }
            env[key] = {
                "is_set": bool(env_raw),
                "masked": _mask_token(env_raw),
            }
        else:
            effective[key] = spec.resolve(db_path=db_path)
            env[key] = spec.env_value()
    return {
        "effective": effective,
        "env": env,
        "overrides": override_keys,
        "groups": groups,
    }


def _coerce_value(spec: FieldSpec, raw: Any) -> Any:
    """Validate+coerce an incoming PUT value to the field's scalar type.

    Raises ``ValueError`` with a human message on invalid input.
    """
    if spec.kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            low = raw.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off"):
                return False
        raise ValueError(f"{spec.key} must be a boolean")
    if spec.kind in ("int", "float"):
        try:
            num = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{spec.key} must be a number") from exc
        if spec.min_value is not None and num < spec.min_value:
            raise ValueError(f"{spec.key} must be >= {spec.min_value}")
        if spec.max_value is not None and num > spec.max_value:
            raise ValueError(f"{spec.key} must be <= {spec.max_value}")
        return int(num) if spec.kind == "int" else num
    # str
    if not isinstance(raw, str):
        raise ValueError(f"{spec.key} must be a string")
    return raw.strip()


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Validate a partial update and persist it.

    Semantics:
    - Unknown keys are rejected.
    - Sensitive (token) fields: an empty string is a no-op (keep current),
      and the ``CLEAR_SENTINEL`` value deletes the override.
    - Every other provided key is coerced and stored as an override.

    Raises ``ValueError`` on invalid input (mapped to HTTP 400 by caller).
    """
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    to_set: dict[str, Any] = {}
    to_delete: list[str] = []
    for key, raw in body.items():
        spec = FIELD_SPECS.get(key)
        if spec is None:
            raise ValueError(f"Unknown setting: {key}")
        if spec.sensitive:
            if raw == CLEAR_SENTINEL:
                to_delete.append(key)
                continue
            if isinstance(raw, str) and raw.strip() == "":
                # Empty = leave the stored secret untouched.
                continue
        to_set[key] = _coerce_value(spec, raw)
    for key in to_delete:
        delete_override(key, db_path=db_path)
    if to_set:
        set_overrides(to_set, db_path=db_path)


def reset_setting(key: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Drop one field's override so it falls back to env/default."""
    if key not in FIELD_SPECS:
        raise ValueError(f"Unknown setting: {key}")
    delete_override(key, db_path=db_path)
