# -*- coding: utf-8 -*-
"""Reusable engine for DB-backed model-provider settings.

The Qiming and Xingchen OpenAI-compatible adapters used to read their
connection + credentials only from environment variables (``.env``). This
module makes those a settings-page concern, mirroring
:mod:`inoe_settings_store` but *parametrised* by namespace + field specs so
the two providers share one implementation instead of copying ~150 lines
each.

Resolution order for every field::

    settings-page override (DB)  ->  env (QWENPAW_*, with COPAW_* fallback)
                                 ->  hard-coded default

Unlike the INOE store, provider adapters run **in the main process** and
read their config fresh on each request, so there is no materialisation to
``os.environ`` and no post-save refresh: :func:`resolve_text` reads the DB
directly.

The :class:`FieldSpec`, :func:`coerce_value`, :func:`mask_token` and
``CLEAR_SENTINEL`` are reused from :mod:`diagnosis_settings_store`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

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

__all__ = [
    "CLEAR_SENTINEL",
    "FieldSpec",
    "spec_by_env",
    "resolve",
    "resolve_text",
    "build_payload",
    "apply_update",
    "reset_setting",
    "has_override",
    "set_overrides",
]


def spec_by_env(specs: dict[str, FieldSpec]) -> dict[str, FieldSpec]:
    """Index field specs by their ``env_var`` (for adapter lookups)."""
    return {spec.env_var: spec for spec in specs.values()}


def _typed_override(spec: FieldSpec, raw: Any) -> Any:
    """Coerce a stored override value to the field's type, clamping bounds.

    Same semantics as ``inoe_settings_store._typed_override``.
    """
    if spec.kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
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


def resolve(
    spec: FieldSpec,
    *,
    namespace: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Any:
    """DB override > env (QWENPAW_/COPAW_) > default, typed."""
    overrides = settings_store.get_namespace(namespace, db_path=db_path)
    if spec.key in overrides:
        return _typed_override(spec, overrides[spec.key])
    return spec.env_value()


def resolve_text(
    specs_by_env: dict[str, FieldSpec],
    env_var: str,
    *,
    namespace: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Resolve one field as a string, keyed by its env var name.

    Adapters call this from ``_read_env`` with the canonical ``QWENPAW_*``
    name. Returns ``""`` for env vars that are not modelled as a FieldSpec,
    so the adapter's own legacy ``os.getenv`` fallback still handles them.
    """
    spec = specs_by_env.get(env_var)
    if spec is None:
        return ""
    value = resolve(spec, namespace=namespace, db_path=db_path)
    return "" if value is None else str(value).strip()


def has_override(
    key: str,
    *,
    namespace: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Whether ``key`` has a settings-page override."""
    return key in settings_store.get_namespace(namespace, db_path=db_path)


def set_overrides(
    partial: dict[str, Any],
    *,
    namespace: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Write raw override values into the namespace (test convenience)."""
    settings_store.set_values(namespace, partial, db_path=db_path)


def build_payload(
    specs: dict[str, FieldSpec],
    *,
    namespace: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Build the ``{effective, env, overrides, groups}`` payload.

    Same shape as :func:`diagnosis_settings_store.build_settings_payload`
    so the portal reuses one ``DiagnosisSettingsPayload`` type. Sensitive
    fields are masked in both the effective and env layers.
    """
    overrides = settings_store.get_namespace(namespace, db_path=db_path)
    effective: dict[str, Any] = {}
    env: dict[str, Any] = {}
    override_keys: dict[str, bool] = {}
    groups: dict[str, str] = {}
    for key, spec in specs.items():
        override_keys[key] = key in overrides
        groups[key] = spec.group
        if spec.sensitive:
            eff_raw = str(resolve(spec, namespace=namespace, db_path=db_path)
                          or "")
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
            effective[key] = resolve(
                spec, namespace=namespace, db_path=db_path
            )
            env[key] = spec.env_value()
    return {
        "effective": effective,
        "env": env,
        "overrides": override_keys,
        "groups": groups,
    }


def apply_update(
    specs: dict[str, FieldSpec],
    body: dict[str, Any],
    *,
    namespace: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Validate a partial update and persist it into the namespace.

    Sensitive fields: an empty string is a no-op (keep current), and
    ``CLEAR_SENTINEL`` deletes the override. Unknown keys are rejected.
    Raises ``ValueError`` on invalid input (mapped to HTTP 400 by caller).
    """
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    to_set: dict[str, Any] = {}
    to_delete: list[str] = []
    for key, raw in body.items():
        spec = specs.get(key)
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
        settings_store.delete_value(namespace, key, db_path=db_path)
    if to_set:
        settings_store.set_values(namespace, to_set, db_path=db_path)


def reset_setting(
    specs: dict[str, FieldSpec],
    key: str,
    *,
    namespace: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Drop one field's override so it falls back to env/default."""
    if key not in specs:
        raise ValueError(f"Unknown setting: {key}")
    settings_store.delete_value(namespace, key, db_path=db_path)
