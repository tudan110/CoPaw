# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from qwenpaw.constant import WORKING_DIR
from qwenpaw.extensions.runtime_data_paths import (
    NOTIFICATIONS_DATA_DIR,
    NOTIFICATIONS_SETTINGS_PATH,
    ensure_extension_data_dir,
)

router = APIRouter(prefix="/settings", tags=["portal"])

_SETTINGS_FILE = NOTIFICATIONS_SETTINGS_PATH
_LEGACY_SETTINGS_FILE = WORKING_DIR / "settings.json"

_NOTIFICATION_SCOPE_DEFAULTS = {
    "inspection": {
        "push_url": "",
        "dingtalk_webhook_url": "",
        "dingtalk_secret": "",
        "feishu_webhook_url": "",
        "feishu_secret": "",
        "timeout_seconds": 8,
        "mention_all": False,
    },
    "alarm_analyst": {
        "push_url": "",
        "dingtalk_webhook_url": "",
        "dingtalk_secret": "",
        "feishu_webhook_url": "",
        "feishu_secret": "",
        "timeout_seconds": 8,
        "mention_all": False,
    },
    "order_workflow": {
        "push_url": "",
        "dingtalk_webhook_url": "",
        "dingtalk_secret": "",
        "feishu_webhook_url": "",
        "feishu_secret": "",
        "timeout_seconds": 8,
        "mention_all": False,
    },
}
_NOTIFICATION_SCOPE_LEGACY_FALLBACKS = {
    "alarm_analyst": ("order_create",),
    "order_workflow": ("order_create",),
}
_NOTIFICATION_STRING_KEYS = {
    "push_url",
    "dingtalk_webhook_url",
    "dingtalk_secret",
    "feishu_webhook_url",
    "feishu_secret",
}
_NOTIFICATION_INT_KEYS = {"timeout_seconds"}
_NOTIFICATION_BOOL_KEYS = {"mention_all"}
_DEPRECATED_NOTIFICATION_KEYS = {"dingtalk_keyword"}


def _load_json(path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _load() -> dict:
    data = _load_json(_SETTINGS_FILE)
    if isinstance(data.get("notification_channels"), dict):
        return data

    legacy_data = _load_json(_LEGACY_SETTINGS_FILE)
    if isinstance(legacy_data.get("notification_channels"), dict):
        return {
            "notification_channels": legacy_data["notification_channels"],
        }
    return data


def _save(data: dict) -> None:
    ensure_extension_data_dir(NOTIFICATIONS_DATA_DIR)
    _SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        "utf-8",
    )


def _parse_bool(value: object, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise HTTPException(
        status_code=400,
        detail=f"Invalid {field_name}, must be a boolean",
    )


def _normalize_notification_scope(
    scope_name: str,
    raw_scope: object,
) -> dict[str, object]:
    if raw_scope is None:
        raw_scope = {}
    if not isinstance(raw_scope, dict):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid notification scope: {scope_name}",
        )

    defaults = _NOTIFICATION_SCOPE_DEFAULTS[scope_name]
    normalized: dict[str, object] = dict(defaults)

    for key, value in raw_scope.items():
        if key in _DEPRECATED_NOTIFICATION_KEYS:
            continue

        if key in _NOTIFICATION_STRING_KEYS:
            if value is None:
                normalized[key] = ""
            elif isinstance(value, str):
                normalized[key] = value.strip()
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid {scope_name}.{key}, must be a string",
                )
            continue

        if key in _NOTIFICATION_INT_KEYS:
            try:
                normalized_value = int(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid {scope_name}.{key}, must be an integer",
                ) from exc
            if normalized_value <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid {scope_name}.{key}, must be greater than 0",
                )
            normalized[key] = normalized_value
            continue

        if key in _NOTIFICATION_BOOL_KEYS:
            normalized[key] = _parse_bool(
                value,
                field_name=f"{scope_name}.{key}",
            )
            continue

        raise HTTPException(
            status_code=400,
            detail=f"Unsupported notification setting: {scope_name}.{key}",
        )

    return normalized


def _resolve_raw_notification_scope(
    raw_notifications: dict[str, object],
    scope_name: str,
) -> object:
    if scope_name in raw_notifications:
        return raw_notifications.get(scope_name)

    for legacy_scope in _NOTIFICATION_SCOPE_LEGACY_FALLBACKS.get(scope_name, ()):
        if legacy_scope in raw_notifications:
            return raw_notifications.get(legacy_scope)
    return None


def _get_notification_settings_payload(
    data: dict | None = None,
) -> dict[str, dict[str, object]]:
    payload = data if data is not None else _load()
    raw_notifications = payload.get("notification_channels")
    if not isinstance(raw_notifications, dict):
        raw_notifications = {}

    return {
        scope_name: _normalize_notification_scope(
            scope_name,
            _resolve_raw_notification_scope(raw_notifications, scope_name),
        )
        for scope_name in _NOTIFICATION_SCOPE_DEFAULTS
    }


@router.get("/notification-channels", summary="Get portal notification channel settings")
async def get_notification_channels() -> dict[str, dict[str, object]]:
    return _get_notification_settings_payload()


@router.put("/notification-channels", summary="Update portal notification channel settings")
async def put_notification_channels(
    body: dict = Body(
        ...,
        description='e.g. {"inspection": {"push_url": "http://..."}}',
    ),
) -> dict[str, dict[str, object]]:
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid notification settings body",
        )

    for scope_name in body:
        if scope_name not in _NOTIFICATION_SCOPE_DEFAULTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported notification scope: {scope_name}",
            )

    data = _load()
    existing_notifications = data.get("notification_channels")
    if not isinstance(existing_notifications, dict):
        existing_notifications = {}

    for scope_name, scope_payload in body.items():
        merged_scope = dict(existing_notifications.get(scope_name) or {})
        if not isinstance(merged_scope, dict):
            merged_scope = {}
        merged_scope.update(scope_payload or {})
        existing_notifications[scope_name] = _normalize_notification_scope(
            scope_name,
            merged_scope,
        )

    data["notification_channels"] = existing_notifications
    _save(data)
    return _get_notification_settings_payload(data)
