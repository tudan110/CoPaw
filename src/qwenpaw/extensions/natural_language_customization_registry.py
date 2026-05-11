from __future__ import annotations

import json
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping

from qwenpaw.constant import WORKING_DIR

NL_CUSTOMIZATION_REGISTRY_VERSION = 1
NL_CUSTOMIZATION_REGISTRY_PATH = WORKING_DIR / "nl_customization_registry.json"
NL_CUSTOMIZATION_BUNDLE_DIR = WORKING_DIR / "nl_customization_bundles"
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
        "version": NL_CUSTOMIZATION_REGISTRY_VERSION,
        "updatedAt": "",
        "items": [],
    }


def _resolve_registry_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else NL_CUSTOMIZATION_REGISTRY_PATH


def _resolve_bundle_dir(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else NL_CUSTOMIZATION_BUNDLE_DIR


def _read_registry_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_registry_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_registry_payload()
    if not isinstance(payload, dict):
        return _default_registry_payload()
    items = payload.get("items")
    if not isinstance(items, list):
        payload["items"] = []
    payload.setdefault("version", NL_CUSTOMIZATION_REGISTRY_VERSION)
    payload.setdefault("updatedAt", "")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def list_published_customizations(
    *,
    limit: int = 20,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        normalized = [item for item in items if isinstance(item, dict)]
        normalized.sort(key=lambda item: str(item.get("publishedAt") or ""), reverse=True)
        if limit > 0:
            return normalized[:limit]
        return normalized


def publish_customization(
    *,
    preview: Mapping[str, Any],
    requested_by: str = "",
    title_override: str = "",
    path: str | Path | None = None,
    bundle_dir: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = _resolve_registry_path(path)
    resolved_bundle_dir = _resolve_bundle_dir(bundle_dir)
    now = _local_now_iso()
    version_id = f"nlc-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    title = str(title_override or preview.get("title") or "自然语言定制方案").strip()
    intent = preview.get("intent") if isinstance(preview.get("intent"), Mapping) else {}
    matched_template = (
        preview.get("matchedTemplate")
        if isinstance(preview.get("matchedTemplate"), Mapping)
        else {}
    )
    record = {
        "versionId": version_id,
        "title": title,
        "prompt": str(preview.get("prompt") or "").strip(),
        "scenarioType": str(intent.get("scenarioType") or ""),
        "targetType": str(intent.get("targetType") or ""),
        "matchedTemplateId": str(matched_template.get("templateId") or ""),
        "matchedSkillId": str(matched_template.get("skillId") or ""),
        "requestedBy": str(requested_by or "portal").strip() or "portal",
        "publishedAt": now,
        "warningCount": len(preview.get("warnings") or []),
        "bundlePath": str((resolved_bundle_dir / f"{version_id}.json").resolve()),
        "summaryMarkdown": str(preview.get("summaryMarkdown") or "").strip(),
    }
    bundle_payload = {
        "versionId": version_id,
        "publishedAt": now,
        "record": record,
        "preview": preview,
    }

    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
            payload["items"] = items
        items.insert(0, record)
        payload["version"] = NL_CUSTOMIZATION_REGISTRY_VERSION
        payload["updatedAt"] = now

        bundle_path = resolved_bundle_dir / f"{version_id}.json"
        _write_json_atomic(bundle_path, bundle_payload)
        _write_json_atomic(registry_path, payload)

    return {
        "versionId": version_id,
        "publishedAt": now,
        "bundlePath": str(bundle_path.resolve()),
        "record": record,
    }
