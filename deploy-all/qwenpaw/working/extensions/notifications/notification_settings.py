from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

LEGACY_SCOPE_ALIASES = {
    "alarm_analyst": ("order_create",),
    "order_workflow": ("order_create",),
}
_NOTIFICATION_NAMESPACE = "notification_channels"


def _resolve_working_dir(start_path: Path) -> Path | None:
    for env_name in ("QWENPAW_WORKING_DIR", "COPAW_WORKING_DIR"):
        raw = os.getenv(env_name, "").strip()
        if raw:
            return Path(raw).expanduser()

    current = start_path if start_path.is_dir() else start_path.parent
    for parent in [current, *current.parents]:
        if (parent / "workspaces").is_dir():
            return parent
    return None


def _load_notification_channels(working_dir: Path) -> dict[str, Any]:
    db_path = working_dir / "extensions" / "settings" / "settings.db"
    try:
        connection = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        try:
            rows = connection.execute(
                "SELECT key, value FROM settings WHERE namespace = ?",
                (_NOTIFICATION_NAMESPACE,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}

    channels: dict[str, Any] = {}
    for scope_name, raw_value in rows:
        try:
            payload = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(scope_name, str) and isinstance(payload, dict):
            channels[scope_name] = payload
    return channels


def _load_notification_scope(scope: str, *, start_path: Path) -> dict[str, Any]:
    working_dir = _resolve_working_dir(start_path)
    if working_dir is None:
        return {}

    notifications = _load_notification_channels(working_dir)
    scope_payload = notifications.get(scope)
    if isinstance(scope_payload, dict):
        return scope_payload

    for legacy_scope in LEGACY_SCOPE_ALIASES.get(scope, ()):
        legacy_payload = notifications.get(legacy_scope)
        if isinstance(legacy_payload, dict):
            return legacy_payload
    return {}


def resolve_notification_text(
    scope: str,
    key: str,
    *,
    env_keys: list[str] | tuple[str, ...],
    start_path: Path,
    default: str = "",
) -> str:
    scope_payload = _load_notification_scope(scope, start_path=start_path)
    if key in scope_payload:
        value = scope_payload.get(key)
        return str(value or "").strip()

    for env_key in env_keys:
        if env_key in os.environ:
            return str(os.getenv(env_key) or "").strip()
    return default


def resolve_notification_int(
    scope: str,
    key: str,
    *,
    env_keys: list[str] | tuple[str, ...],
    start_path: Path,
    default: int,
) -> int:
    scope_payload = _load_notification_scope(scope, start_path=start_path)
    if key in scope_payload:
        raw_value = scope_payload.get(key)
        if raw_value in (None, ""):
            return default
        return int(raw_value)

    for env_key in env_keys:
        if env_key in os.environ:
            raw_env = str(os.getenv(env_key) or "").strip()
            if raw_env:
                return int(raw_env)
    return default


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def resolve_notification_bool(
    scope: str,
    key: str,
    *,
    env_keys: list[str] | tuple[str, ...],
    start_path: Path,
    default: bool,
) -> bool:
    scope_payload = _load_notification_scope(scope, start_path=start_path)
    if key in scope_payload:
        return _parse_bool(scope_payload.get(key), default=default)

    for env_key in env_keys:
        if env_key in os.environ:
            return _parse_bool(os.getenv(env_key), default=default)
    return default
