from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

LEGACY_SCOPE_ALIASES = {
    "alarm_analyst": ("order_create",),
    "order_workflow": ("order_create",),
}


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
    for settings_file in (
        working_dir / "extensions" / "notifications" / "settings.json",
        working_dir / "settings.json",
    ):
        try:
            payload = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        notifications = payload.get("notification_channels")
        if isinstance(notifications, dict):
            return notifications
    return {}


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
