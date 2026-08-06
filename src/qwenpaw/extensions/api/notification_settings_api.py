# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from fastapi import APIRouter, Body, HTTPException

from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.runtime_data_paths import SETTINGS_DB_PATH

router = APIRouter(prefix="/settings", tags=["portal"])

# Notification channels persist in the shared settings database.
_SETTINGS_DB = SETTINGS_DB_PATH
_NAMESPACE = "notification_channels"

_NOTIFICATION_SCOPE_DEFAULT = {
    "push_url": "",
    "dingtalk_webhook_url": "",
    "dingtalk_secret": "",
    "feishu_webhook_url": "",
    "feishu_secret": "",
    "timeout_seconds": 8,
    "mention_all": False,
}
_BUILTIN_NOTIFICATION_SCOPES = ("inspection", "alarm_analyst", "order_workflow")
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
_SCOPE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _validate_scope_name(scope_name: object) -> str:
    if not isinstance(scope_name, str):
        raise HTTPException(
            status_code=400,
            detail="Invalid notification scope, must be a string",
        )
    normalized = scope_name.strip()
    if not _SCOPE_NAME_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid notification scope, use 1-64 letters, numbers, "
                "underscore, hyphen, or dot, and start with a letter"
            ),
        )
    return normalized


def _load() -> dict:
    return {
        "notification_channels": settings_store.get_namespace(
            _NAMESPACE,
            db_path=_SETTINGS_DB,
        ),
    }


def _save(data: dict) -> None:
    channels = data.get("notification_channels")
    if not isinstance(channels, dict):
        channels = {}
    settings_store.replace_namespace(
        _NAMESPACE,
        channels,
        db_path=_SETTINGS_DB,
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
    *,
    strict_unknown_keys: bool,
) -> dict[str, object]:
    if raw_scope is None:
        raw_scope = {}
    if not isinstance(raw_scope, dict):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid notification scope: {scope_name}",
        )

    normalized: dict[str, object] = dict(_NOTIFICATION_SCOPE_DEFAULT)

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

        if strict_unknown_keys:
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


def _normalize_existing_notifications(
    raw_notifications: dict[str, object],
) -> dict[str, dict[str, object]]:
    normalized: dict[str, dict[str, object]] = {}

    for scope_name in _BUILTIN_NOTIFICATION_SCOPES:
        normalized[scope_name] = _normalize_notification_scope(
            scope_name,
            _resolve_raw_notification_scope(raw_notifications, scope_name),
            strict_unknown_keys=False,
        )

    for raw_scope_name, raw_scope_payload in raw_notifications.items():
        try:
            scope_name = _validate_scope_name(raw_scope_name)
        except HTTPException:
            continue
        if scope_name in normalized:
            continue
        if not isinstance(raw_scope_payload, dict):
            continue
        normalized[scope_name] = _normalize_notification_scope(
            scope_name,
            raw_scope_payload,
            strict_unknown_keys=False,
        )

    return normalized


def _get_notification_settings_payload(
    data: dict | None = None,
) -> dict[str, dict[str, object]]:
    payload = data if data is not None else _load()
    raw_notifications = payload.get("notification_channels")
    if not isinstance(raw_notifications, dict):
        raw_notifications = {}

    return _normalize_existing_notifications(raw_notifications)


def _refresh_notification_environ() -> None:
    try:
        from qwenpaw.extensions.integrations.working_secrets import (
            refresh_notification_channels_environ,
        )

        refresh_notification_channels_environ(db_path=_SETTINGS_DB)
    except Exception:  # noqa: BLE001 - settings save must not fail on refresh
        return


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

    normalized_body_scope_names = {
        _validate_scope_name(scope_name): scope_name
        for scope_name in body
    }

    data = _load()
    existing_notifications = data.get("notification_channels")
    if not isinstance(existing_notifications, dict):
        existing_notifications = {}

    for scope_name, raw_scope_name in normalized_body_scope_names.items():
        scope_payload = body[raw_scope_name]
        if scope_payload is not None and not isinstance(scope_payload, dict):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid notification scope: {scope_name}",
            )
        merged_scope = dict(existing_notifications.get(scope_name) or {})
        if not isinstance(merged_scope, dict):
            merged_scope = {}
        merged_scope.update(scope_payload or {})
        existing_notifications[scope_name] = _normalize_notification_scope(
            scope_name,
            merged_scope,
            strict_unknown_keys=True,
        )

    data["notification_channels"] = existing_notifications
    _save(data)
    _refresh_notification_environ()
    return _get_notification_settings_payload(data)


@router.delete(
    "/notification-channels/{scope_name}",
    summary="Delete a portal notification channel scope",
)
async def delete_notification_channel_scope(
    scope_name: str,
) -> dict[str, dict[str, object]]:
    normalized_scope_name = _validate_scope_name(scope_name)
    if normalized_scope_name in _BUILTIN_NOTIFICATION_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Built-in notification scope cannot be deleted: "
                f"{normalized_scope_name}"
            ),
        )

    data = _load()
    existing_notifications = data.get("notification_channels")
    if not isinstance(existing_notifications, dict):
        existing_notifications = {}

    existing_notifications.pop(normalized_scope_name, None)
    data["notification_channels"] = existing_notifications
    _save(data)
    _refresh_notification_environ()
    return _get_notification_settings_payload(data)
