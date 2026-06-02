from __future__ import annotations

import json
import tempfile
import threading
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping

from qwenpaw.extensions.runtime_data_paths import (
    AI_BIG_SCREEN_REGISTRY_PATH as DEFAULT_AI_BIG_SCREEN_REGISTRY_PATH,
    ensure_extension_data_dir,
)

AI_BIG_SCREEN_REGISTRY_VERSION = 1
AI_BIG_SCREEN_REGISTRY_PATH = DEFAULT_AI_BIG_SCREEN_REGISTRY_PATH
_REGISTRY_LOCK = threading.Lock()


def _default_registry_timezone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        return local_tz
    return timezone(timedelta(hours=8))


def _local_now_iso() -> str:
    return datetime.now(_default_registry_timezone()).isoformat()


def _default_registry_payload() -> dict[str, Any]:
    return {
        "version": AI_BIG_SCREEN_REGISTRY_VERSION,
        "updatedAt": "",
        "items": [],
    }


def _resolve_registry_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else AI_BIG_SCREEN_REGISTRY_PATH


def _read_registry_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_registry_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_registry_payload()
    if not isinstance(payload, dict):
        return _default_registry_payload()
    payload.setdefault("version", AI_BIG_SCREEN_REGISTRY_VERSION)
    payload.setdefault("updatedAt", "")
    items = payload.get("items")
    payload["items"] = items if isinstance(items, list) else []
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    ensure_extension_data_dir(path.parent)
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


def list_screens(
    *,
    limit: int = 50,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        items = [dict(item) for item in payload.get("items", []) if isinstance(item, dict)]
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return items[:limit] if limit > 0 else items


def get_screen(
    *,
    screen_id: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_id = str(screen_id or "").strip()
    if not normalized_id:
        raise ValueError("screenId 不能为空")

    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        for item in payload.get("items", []):
            if (
                isinstance(item, dict)
                and str(item.get("id") or "").strip() == normalized_id
            ):
                return dict(item)
    raise ValueError(f"未找到大屏：{normalized_id}")


def delete_screen(
    *,
    screen_id: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_id = str(screen_id or "").strip()
    if not normalized_id:
        raise ValueError("screenId 不能为空")

    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        deleted: dict[str, Any] | None = None
        next_items: list[dict[str, Any]] = []
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id == normalized_id and deleted is None:
                deleted = dict(item)
                continue
            next_items.append(dict(item))

        if deleted is None:
            raise ValueError(f"未找到大屏：{normalized_id}")

        payload["items"] = next_items
        payload["version"] = AI_BIG_SCREEN_REGISTRY_VERSION
        payload["updatedAt"] = _local_now_iso()
        _write_json_atomic(registry_path, payload)
    return deleted


def save_screen(
    *,
    screen: Mapping[str, Any],
    requested_by: str = "portal",
    path: str | Path | None = None,
) -> dict[str, Any]:
    screen_id = str(screen.get("id") or "").strip()
    if not screen_id:
        raise ValueError("screen.id 不能为空")

    now = _local_now_iso()
    normalized = dict(screen)
    normalized.setdefault("createdAt", now)
    normalized["updatedAt"] = now
    normalized["updatedBy"] = str(requested_by or "portal").strip() or "portal"
    normalized.setdefault("status", "draft")
    normalized.setdefault("versions", [])
    normalized.setdefault("publishTargets", [])

    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
            payload["items"] = items
        replaced = False
        next_items: list[dict[str, Any]] = []
        for item in items:
            if (
                isinstance(item, dict)
                and str(item.get("id") or "").strip() == screen_id
            ):
                next_items.append(normalized)
                replaced = True
            elif isinstance(item, dict):
                next_items.append(dict(item))
        if not replaced:
            next_items.insert(0, normalized)
        payload["items"] = next_items
        payload["version"] = AI_BIG_SCREEN_REGISTRY_VERSION
        payload["updatedAt"] = now
        _write_json_atomic(registry_path, payload)
    return normalized
