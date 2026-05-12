# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import threading
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping
import shutil

from qwenpaw.constant import WORKING_DIR
from qwenpaw.extensions.runtime_data_paths import (
    PORTAL_REAL_ALARM_REGISTRY_PATH as DEFAULT_PORTAL_REAL_ALARM_REGISTRY_PATH,
    ensure_extension_data_dir,
)

PORTAL_REAL_ALARM_REGISTRY_VERSION = 1
PORTAL_REAL_ALARM_REGISTRY_PATH = DEFAULT_PORTAL_REAL_ALARM_REGISTRY_PATH
LEGACY_PORTAL_REAL_ALARM_REGISTRY_PATH = WORKING_DIR / "portal_real_alarm_registry.json"
PORTAL_REAL_ALARM_HIDDEN_STATUSES = frozenset(
    {
        "taken_over",
        "analyzing",
        "manual_pending",
        "manual_recovered",
        "manual_unrecovered",
        "manual_unknown",
        "resolved",
        "ignored",
    }
)
_PORTAL_REAL_ALARM_TERMINAL_STATUSES = frozenset(
    {
        "manual_pending",
        "manual_recovered",
        "manual_unrecovered",
        "manual_unknown",
        "resolved",
        "ignored",
    }
)
_REGISTRY_LOCK = threading.Lock()


def _default_registry_timezone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        return local_tz
    return timezone(timedelta(hours=8))


def _local_now_iso() -> str:
    return datetime.now(_default_registry_timezone()).isoformat()


def _resolve_registry_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else PORTAL_REAL_ALARM_REGISTRY_PATH


def _migrate_legacy_registry_path(path: Path) -> None:
    if path.exists() or path != DEFAULT_PORTAL_REAL_ALARM_REGISTRY_PATH:
        return
    legacy_path = LEGACY_PORTAL_REAL_ALARM_REGISTRY_PATH
    if not legacy_path.exists():
        return
    ensure_extension_data_dir(path.parent)
    shutil.move(str(legacy_path), str(path))


def _default_registry_payload() -> dict[str, Any]:
    return {
        "version": PORTAL_REAL_ALARM_REGISTRY_VERSION,
        "updatedAt": "",
        "alarms": {},
    }


def _coalesce_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _alarm_id_from_payload(alarm: Mapping[str, Any] | None) -> str:
    if not isinstance(alarm, Mapping):
        return ""
    return _coalesce_text(alarm.get("alarmId"), alarm.get("id"), alarm.get("alarm_id"))


def _merge_alarm_metadata(
    existing: dict[str, Any],
    alarm: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(alarm, Mapping):
        return dict(existing)

    merged = dict(existing)
    merged["alarmId"] = _coalesce_text(
        _alarm_id_from_payload(alarm),
        existing.get("alarmId"),
    )
    merged["resId"] = _coalesce_text(
        alarm.get("resId"),
        alarm.get("res_id"),
        existing.get("resId"),
    )
    merged["title"] = _coalesce_text(alarm.get("title"), existing.get("title"))
    merged["deviceName"] = _coalesce_text(
        alarm.get("deviceName"),
        alarm.get("device_name"),
        existing.get("deviceName"),
    )
    merged["manageIp"] = _coalesce_text(
        alarm.get("manageIp"),
        alarm.get("manage_ip"),
        existing.get("manageIp"),
    )
    merged["eventTime"] = _coalesce_text(
        alarm.get("eventTime"),
        alarm.get("event_time"),
        existing.get("eventTime"),
    )
    merged["visibleContent"] = _coalesce_text(
        alarm.get("visibleContent"),
        alarm.get("visible_content"),
        existing.get("visibleContent"),
    )
    return merged


def _read_registry_unlocked(path: Path) -> dict[str, Any]:
    _migrate_legacy_registry_path(path)
    if not path.exists():
        return _default_registry_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_registry_payload()
    if not isinstance(payload, dict):
        return _default_registry_payload()
    records = payload.get("alarms")
    if not isinstance(records, dict):
        payload["alarms"] = {}
    payload.setdefault("version", PORTAL_REAL_ALARM_REGISTRY_VERSION)
    payload.setdefault("updatedAt", "")
    return payload


def _write_registry_unlocked(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["version"] = PORTAL_REAL_ALARM_REGISTRY_VERSION
    payload["updatedAt"] = _local_now_iso()
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_alarm_records(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        alarms = payload.get("alarms")
        return dict(alarms) if isinstance(alarms, dict) else {}


def find_alarm_id(
    *,
    alarm_id: str = "",
    session_id: str = "",
    chat_id: str = "",
    res_id: str = "",
    path: str | Path | None = None,
    records: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    normalized_alarm_id = _coalesce_text(alarm_id)
    if normalized_alarm_id:
        return normalized_alarm_id

    entries = records if isinstance(records, Mapping) else load_alarm_records(path)
    normalized_session_id = _coalesce_text(session_id)
    normalized_chat_id = _coalesce_text(chat_id)
    normalized_res_id = _coalesce_text(res_id)

    if normalized_session_id:
        for candidate_alarm_id, entry in entries.items():
            if _coalesce_text((entry or {}).get("sessionId")) == normalized_session_id:
                return str(candidate_alarm_id)

    if normalized_chat_id:
        for candidate_alarm_id, entry in entries.items():
            if _coalesce_text((entry or {}).get("chatId")) == normalized_chat_id:
                return str(candidate_alarm_id)

    if normalized_res_id:
        matches: list[tuple[str, Mapping[str, Any]]] = []
        for candidate_alarm_id, entry in entries.items():
            if _coalesce_text((entry or {}).get("resId")) == normalized_res_id:
                matches.append((str(candidate_alarm_id), entry or {}))
        if matches:
            matches.sort(key=lambda item: _coalesce_text(item[1].get("updatedAt")), reverse=True)
            return matches[0][0]

    return ""


def update_alarm_record(
    *,
    alarm: Mapping[str, Any] | None = None,
    alarm_id: str = "",
    status: str = "",
    session_id: str = "",
    chat_id: str = "",
    res_id: str = "",
    source: str = "",
    verification_status: str = "",
    last_error: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        records = payload.get("alarms")
        if not isinstance(records, dict):
            records = {}
            payload["alarms"] = records

        resolved_alarm_id = find_alarm_id(
            alarm_id=_coalesce_text(alarm_id, _alarm_id_from_payload(alarm)),
            session_id=session_id,
            chat_id=chat_id,
            res_id=_coalesce_text(res_id, (alarm or {}).get("resId") if isinstance(alarm, Mapping) else ""),
            records=records,
        )
        if not resolved_alarm_id:
            raise ValueError("alarmId is required")

        now = _local_now_iso()
        existing = dict(records.get(resolved_alarm_id) or {})
        merged = _merge_alarm_metadata(existing, alarm)
        merged["alarmId"] = resolved_alarm_id
        merged["createdAt"] = _coalesce_text(existing.get("createdAt"), now)
        merged["updatedAt"] = now

        if session_id:
            merged["sessionId"] = _coalesce_text(session_id)
        elif existing.get("sessionId"):
            merged["sessionId"] = existing.get("sessionId")

        if chat_id:
            merged["chatId"] = _coalesce_text(chat_id)
        elif existing.get("chatId"):
            merged["chatId"] = existing.get("chatId")

        if res_id:
            merged["resId"] = _coalesce_text(res_id, merged.get("resId"))

        if source:
            merged["source"] = _coalesce_text(source)
        elif existing.get("source"):
            merged["source"] = existing.get("source")

        current_status = _coalesce_text(existing.get("status"))
        requested_status = _coalesce_text(status, current_status, "new")
        if (
            current_status in _PORTAL_REAL_ALARM_TERMINAL_STATUSES
            and requested_status in {"taken_over", "analyzing"}
        ):
            requested_status = current_status

        merged["status"] = requested_status

        if requested_status in {"taken_over", "analyzing"}:
            merged["takenOverAt"] = _coalesce_text(existing.get("takenOverAt"), now)
            merged["handledAt"] = _coalesce_text(existing.get("handledAt"), now)
        elif requested_status in PORTAL_REAL_ALARM_HIDDEN_STATUSES:
            merged["handledAt"] = _coalesce_text(existing.get("handledAt"), now)

        if requested_status == "analyzing":
            merged["lastTriggeredAt"] = now

        if requested_status in {"manual_recovered", "resolved"}:
            merged["resolvedAt"] = _coalesce_text(existing.get("resolvedAt"), now)

        if verification_status:
            merged["verificationStatus"] = _coalesce_text(verification_status)
        elif existing.get("verificationStatus"):
            merged["verificationStatus"] = existing.get("verificationStatus")

        if last_error is not None:
            merged["lastError"] = _coalesce_text(last_error)
        elif existing.get("lastError"):
            merged["lastError"] = existing.get("lastError")

        records[resolved_alarm_id] = merged
        _write_registry_unlocked(registry_path, payload)
        return dict(merged)


def filter_visible_alarms(
    alarms_payload: Mapping[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    payload = dict(alarms_payload or {})
    items = payload.get("items") or []
    if not isinstance(items, list):
        payload["items"] = []
        payload["total"] = 0
        return payload

    records = load_alarm_records(path)
    visible_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        alarm_id = _alarm_id_from_payload(item)
        status = _coalesce_text((records.get(alarm_id) or {}).get("status"))
        if status in PORTAL_REAL_ALARM_HIDDEN_STATUSES:
            continue
        visible_items.append(item)

    payload["items"] = visible_items
    payload["total"] = len(visible_items)
    return payload
