from __future__ import annotations

import json
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping
import shutil

from qwenpaw.constant import WORKING_DIR
from qwenpaw.extensions.runtime_data_paths import (
    NL_CUSTOMIZATION_ACTIVE_PATH as DEFAULT_NL_CUSTOMIZATION_ACTIVE_PATH,
    NL_CUSTOMIZATION_BUNDLE_DIR as DEFAULT_NL_CUSTOMIZATION_BUNDLE_DIR,
    NL_CUSTOMIZATION_REGISTRY_PATH as DEFAULT_NL_CUSTOMIZATION_REGISTRY_PATH,
    ensure_extension_data_dir,
)

NL_CUSTOMIZATION_REGISTRY_VERSION = 1
NL_CUSTOMIZATION_REGISTRY_PATH = DEFAULT_NL_CUSTOMIZATION_REGISTRY_PATH
NL_CUSTOMIZATION_BUNDLE_DIR = DEFAULT_NL_CUSTOMIZATION_BUNDLE_DIR
NL_CUSTOMIZATION_ACTIVE_PATH = DEFAULT_NL_CUSTOMIZATION_ACTIVE_PATH
LEGACY_NL_CUSTOMIZATION_REGISTRY_PATH = WORKING_DIR / "nl_customization_registry.json"
LEGACY_NL_CUSTOMIZATION_BUNDLE_DIR = WORKING_DIR / "nl_customization_bundles"
LEGACY_NL_CUSTOMIZATION_ACTIVE_PATH = WORKING_DIR / "nl_customization_active.json"
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
        "activeApps": [],
        "activeVersionId": "",
        "appliedAt": "",
        "activePath": "",
        "items": [],
    }


def _resolve_registry_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else NL_CUSTOMIZATION_REGISTRY_PATH


def _resolve_bundle_dir(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else NL_CUSTOMIZATION_BUNDLE_DIR


def _resolve_active_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else NL_CUSTOMIZATION_ACTIVE_PATH


def _resolve_bundle_path(
    record: Mapping[str, Any],
    bundle_dir: Path,
) -> Path:
    bundle_text = str(record.get("bundlePath") or "").strip()
    if bundle_text:
        bundle_path = Path(bundle_text).expanduser()
        return bundle_path
    return bundle_dir / f"{record.get('versionId')}.json"


def _resolve_listed_at(record: Mapping[str, Any]) -> str:
    listed_at = str(record.get("listedAt") or "").strip()
    if listed_at:
        return listed_at
    return str(record.get("installedAt") or "").strip()


def _migrate_legacy_storage(
    registry_path: Path,
    bundle_dir: Path,
    active_path: Path,
) -> None:
    if (
        registry_path != DEFAULT_NL_CUSTOMIZATION_REGISTRY_PATH
        or bundle_dir != DEFAULT_NL_CUSTOMIZATION_BUNDLE_DIR
        or active_path != DEFAULT_NL_CUSTOMIZATION_ACTIVE_PATH
    ):
        return

    ensure_extension_data_dir(registry_path.parent)
    ensure_extension_data_dir(bundle_dir.parent)
    ensure_extension_data_dir(active_path.parent)

    if (
        LEGACY_NL_CUSTOMIZATION_REGISTRY_PATH.exists()
        and not registry_path.exists()
    ):
        shutil.move(
            str(LEGACY_NL_CUSTOMIZATION_REGISTRY_PATH),
            str(registry_path),
        )

    if LEGACY_NL_CUSTOMIZATION_ACTIVE_PATH.exists() and not active_path.exists():
        shutil.move(
            str(LEGACY_NL_CUSTOMIZATION_ACTIVE_PATH),
            str(active_path),
        )

    if LEGACY_NL_CUSTOMIZATION_BUNDLE_DIR.exists() and not bundle_dir.exists():
        shutil.move(
            str(LEGACY_NL_CUSTOMIZATION_BUNDLE_DIR),
            str(bundle_dir),
        )


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
    active_apps = payload.get("activeApps")
    payload["activeApps"] = active_apps if isinstance(active_apps, list) else []
    payload.setdefault("activeVersionId", "")
    payload.setdefault("appliedAt", "")
    payload.setdefault("activePath", "")
    return payload


def _build_active_apps(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    active_apps = payload.get("activeApps")
    if isinstance(active_apps, list):
        normalized: list[dict[str, Any]] = []
        for item in active_apps:
            if not isinstance(item, dict):
                continue
            app_id = str(item.get("appId") or "").strip()
            version_id = str(item.get("versionId") or "").strip()
            if not app_id or not version_id:
                continue
            normalized.append(
                {
                    "appId": app_id,
                    "versionId": version_id,
                    "appliedAt": str(item.get("appliedAt") or "").strip(),
                    "activePath": str(item.get("activePath") or "").strip(),
                },
            )
        if normalized:
            return normalized

    legacy_version_id = str(payload.get("activeVersionId") or "").strip()
    if not legacy_version_id:
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    matched = next(
        (
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("versionId") or "").strip() == legacy_version_id
        ),
        None,
    )
    if not isinstance(matched, dict):
        return []
    app_id = str(matched.get("appId") or "").strip()
    if not app_id:
        return []
    return [
        {
            "appId": app_id,
            "versionId": legacy_version_id,
            "appliedAt": str(payload.get("appliedAt") or "").strip(),
            "activePath": str(payload.get("activePath") or "").strip(),
        },
    ]


def _build_active_app_map(payload: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    return {
        str(item.get("appId") or "").strip(): item
        for item in _build_active_apps(payload)
        if str(item.get("appId") or "").strip()
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
        _migrate_legacy_storage(
            registry_path,
            NL_CUSTOMIZATION_BUNDLE_DIR,
            NL_CUSTOMIZATION_ACTIVE_PATH,
        )
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        active_app_map = _build_active_app_map(payload)
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            version_id = str(item.get("versionId") or "")
            app_id = str(item.get("appId") or "").strip()
            normalized_item = dict(item)
            listed_at = _resolve_listed_at(normalized_item)
            normalized_item["listedAt"] = listed_at
            normalized_item["installedAt"] = listed_at
            active_entry = active_app_map.get(app_id or "")
            normalized_item["isActive"] = bool(
                active_entry
                and str(active_entry.get("versionId") or "") == version_id
            )
            normalized_item["appliedAt"] = (
                str(active_entry.get("appliedAt") or "")
                if normalized_item["isActive"] and active_entry
                else ""
            )
            normalized_item["activePath"] = (
                str(active_entry.get("activePath") or "")
                if normalized_item["isActive"] and active_entry
                else ""
            )
            normalized_item["isListed"] = bool(listed_at)
            normalized_item["isInstalled"] = bool(listed_at)
            normalized.append(normalized_item)
        normalized.sort(key=lambda item: str(item.get("publishedAt") or ""), reverse=True)
        if limit > 0:
            return normalized[:limit]
        return normalized


def get_published_customization(
    *,
    version_id: str,
    path: str | Path | None = None,
    bundle_dir: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = _resolve_registry_path(path)
    resolved_bundle_dir = _resolve_bundle_dir(bundle_dir)
    normalized_version_id = str(version_id or "").strip()
    if not normalized_version_id:
        raise ValueError("versionId 不能为空")

    with _REGISTRY_LOCK:
        _migrate_legacy_storage(
            registry_path,
            resolved_bundle_dir,
            NL_CUSTOMIZATION_ACTIVE_PATH,
        )
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            items = []

        record = next(
            (
                dict(item)
                for item in items
                if isinstance(item, dict)
                and str(item.get("versionId") or "") == normalized_version_id
            ),
            None,
        )
        if record is None:
            raise ValueError(f"未找到版本 {normalized_version_id}")

        bundle_path = _resolve_bundle_path(record, resolved_bundle_dir)
        if not bundle_path.exists():
            raise ValueError(f"版本文件不存在：{bundle_path}")

        bundle_payload = _read_json_file(bundle_path)
        preview = bundle_payload.get("preview")
        if not isinstance(preview, dict):
            raise ValueError(f"版本文件内容不完整：{bundle_path}")
        preview = dict(preview)
        preview["appId"] = str(record.get("appId") or "").strip()

        active_app_map = _build_active_app_map(payload)
        listed_at = _resolve_listed_at(record)
        active_entry = active_app_map.get(str(record.get("appId") or "").strip())
        record["listedAt"] = listed_at
        record["installedAt"] = listed_at
        record["isListed"] = bool(listed_at)
        record["isInstalled"] = bool(listed_at)
        record["isActive"] = bool(
            active_entry
            and str(active_entry.get("versionId") or "") == normalized_version_id
        )
        record["appliedAt"] = (
            str(active_entry.get("appliedAt") or "")
            if record["isActive"] and active_entry
            else ""
        )
        record["activePath"] = (
            str(active_entry.get("activePath") or "")
            if record["isActive"] and active_entry
            else ""
        )

        return {
            "versionId": normalized_version_id,
            "record": record,
            "preview": preview,
            "bundlePath": str(bundle_path.resolve()),
        }


def delete_published_customization(
    *,
    version_id: str,
    path: str | Path | None = None,
    bundle_dir: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = _resolve_registry_path(path)
    resolved_bundle_dir = _resolve_bundle_dir(bundle_dir)
    normalized_version_id = str(version_id or "").strip()
    if not normalized_version_id:
        raise ValueError("versionId 不能为空")

    with _REGISTRY_LOCK:
        _migrate_legacy_storage(
            registry_path,
            resolved_bundle_dir,
            NL_CUSTOMIZATION_ACTIVE_PATH,
        )
        payload = _read_registry_unlocked(registry_path)
        active_versions = {
            str(item.get("versionId") or "").strip()
            for item in _build_active_apps(payload)
        }
        if normalized_version_id in active_versions:
            raise ValueError("当前生效版本不允许删除，请先切换到其他版本。")

        items = payload.get("items")
        if not isinstance(items, list):
            items = []
            payload["items"] = items

        record_to_delete = next(
            (
                dict(item)
                for item in items
                if isinstance(item, dict)
                and str(item.get("versionId") or "") == normalized_version_id
            ),
            None,
        )
        if record_to_delete is None:
            raise ValueError(f"未找到版本 {normalized_version_id}")

        bundle_path = _resolve_bundle_path(record_to_delete, resolved_bundle_dir)
        payload["items"] = [
            item
            for item in items
            if not (
                isinstance(item, dict)
                and str(item.get("versionId") or "") == normalized_version_id
            )
        ]
        payload["version"] = NL_CUSTOMIZATION_REGISTRY_VERSION
        payload["updatedAt"] = _local_now_iso()
        _write_json_atomic(registry_path, payload)

    try:
        bundle_path.unlink()
    except FileNotFoundError:
        pass

    return {
        "versionId": normalized_version_id,
        "deleted": True,
        "bundlePath": str(bundle_path.resolve()),
        "record": record_to_delete,
    }


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
    _migrate_legacy_storage(
        registry_path,
        resolved_bundle_dir,
        NL_CUSTOMIZATION_ACTIVE_PATH,
    )
    now = _local_now_iso()
    version_id = f"nlc-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    title = str(title_override or preview.get("title") or "自然语言定制方案").strip()
    intent = preview.get("intent") if isinstance(preview.get("intent"), Mapping) else {}
    matched_template = (
        preview.get("matchedTemplate")
        if isinstance(preview.get("matchedTemplate"), Mapping)
        else {}
    )
    bundle = preview.get("bundle") if isinstance(preview.get("bundle"), Mapping) else {}
    portal_config = bundle.get("portal") if isinstance(bundle.get("portal"), Mapping) else {}
    app_metadata = _build_app_metadata(
        title=title,
        prompt=str(preview.get("prompt") or "").strip(),
        intent=intent if isinstance(intent, Mapping) else {},
        matched_template=matched_template if isinstance(matched_template, Mapping) else {},
        portal_config=portal_config if isinstance(portal_config, Mapping) else {},
        app_id_override=str(preview.get("appId") or "").strip(),
    )
    record = {
        "versionId": version_id,
        "appId": app_metadata["appId"],
        "title": title,
        "description": app_metadata["description"],
        "prompt": str(preview.get("prompt") or "").strip(),
        "scenarioType": str(intent.get("scenarioType") or ""),
        "targetType": str(intent.get("targetType") or ""),
        "matchedTemplateId": str(matched_template.get("templateId") or ""),
        "matchedSkillId": str(matched_template.get("skillId") or ""),
        "displayTargets": app_metadata["displayTargets"],
        "launchEmployeeId": app_metadata["launchEmployeeId"],
        "launchPrompt": app_metadata["launchPrompt"],
        "requestedBy": str(requested_by or "portal").strip() or "portal",
        "publishedAt": now,
        "listedAt": "",
        "installedAt": "",
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


def apply_published_customization(
    *,
    version_id: str,
    requested_by: str = "",
    path: str | Path | None = None,
    bundle_dir: str | Path | None = None,
    active_path: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = _resolve_registry_path(path)
    resolved_bundle_dir = _resolve_bundle_dir(bundle_dir)
    resolved_active_path = _resolve_active_path(active_path)
    _migrate_legacy_storage(
        registry_path,
        resolved_bundle_dir,
        resolved_active_path,
    )
    normalized_version_id = str(version_id or "").strip()
    if not normalized_version_id:
        raise ValueError("versionId 不能为空")

    with _REGISTRY_LOCK:
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
            payload["items"] = items

        record = next(
            (
                dict(item)
                for item in items
                if isinstance(item, dict)
                and str(item.get("versionId") or "") == normalized_version_id
            ),
            None,
        )
        if record is None:
            raise ValueError(f"未找到版本 {normalized_version_id}")

        bundle_path = _resolve_bundle_path(record, resolved_bundle_dir)
        if not bundle_path.exists():
            raise ValueError(f"版本文件不存在：{bundle_path}")

        bundle_payload = _read_json_file(bundle_path)
        preview = bundle_payload.get("preview")
        if not isinstance(preview, Mapping):
            raise ValueError(f"版本文件内容不完整：{bundle_path}")

        now = _local_now_iso()
        effective_bundle = preview.get("bundle") if isinstance(preview.get("bundle"), Mapping) else {}
        active_payload = {
            "version": NL_CUSTOMIZATION_REGISTRY_VERSION,
            "versionId": normalized_version_id,
            "appliedAt": now,
            "requestedBy": str(requested_by or "portal").strip() or "portal",
            "record": record,
            "preview": preview,
            "effectiveBundle": effective_bundle,
        }
        _write_json_atomic(resolved_active_path, active_payload)

        app_id = str(record.get("appId") or "").strip()
        updated_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            if (
                app_id
                and str(next_item.get("appId") or "").strip() == app_id
                and
                str(next_item.get("versionId") or "") != normalized_version_id
            ):
                next_item["listedAt"] = ""
                next_item["installedAt"] = ""
            if str(next_item.get("versionId") or "") == normalized_version_id:
                listed_at = _resolve_listed_at(next_item)
                next_item["listedAt"] = listed_at
                next_item["installedAt"] = listed_at
            updated_items.append(next_item)
        active_apps = [
            item
            for item in _build_active_apps(payload)
            if str(item.get("appId") or "").strip() != app_id
        ]
        active_apps.append(
            {
                "appId": app_id,
                "versionId": normalized_version_id,
                "appliedAt": now,
                "activePath": str(resolved_active_path.resolve()),
            },
        )
        payload["items"] = updated_items
        payload["activeApps"] = active_apps
        payload["version"] = NL_CUSTOMIZATION_REGISTRY_VERSION
        payload["activeVersionId"] = normalized_version_id
        payload["appliedAt"] = now
        payload["activePath"] = str(resolved_active_path.resolve())
        payload["updatedAt"] = now
        _write_json_atomic(registry_path, payload)

    applied_record = next(
        (
            dict(item)
            for item in payload["items"]
            if isinstance(item, dict)
            and str(item.get("versionId") or "") == normalized_version_id
        ),
        dict(record),
    )
    applied_record["isActive"] = True
    applied_record["listedAt"] = _resolve_listed_at(applied_record)
    applied_record["installedAt"] = applied_record["listedAt"]
    applied_record["isListed"] = bool(applied_record["listedAt"])
    applied_record["isInstalled"] = bool(applied_record["listedAt"])
    applied_record["appliedAt"] = now
    applied_record["activePath"] = str(resolved_active_path.resolve())
    return {
        "versionId": normalized_version_id,
        "appliedAt": now,
        "activePath": str(resolved_active_path.resolve()),
        "record": applied_record,
    }


def get_active_customization(
    *,
    path: str | Path | None = None,
    active_path: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = _resolve_registry_path(path)
    resolved_active_path = _resolve_active_path(active_path)
    with _REGISTRY_LOCK:
        _migrate_legacy_storage(
            registry_path,
            NL_CUSTOMIZATION_BUNDLE_DIR,
            resolved_active_path,
        )
        payload = _read_registry_unlocked(registry_path)
        active_version_id = str(payload.get("activeVersionId") or "")
        applied_at = str(payload.get("appliedAt") or "")
        active_path_text = str(payload.get("activePath") or "")

        if not active_version_id:
            return {
                "activeVersionId": "",
                "appliedAt": "",
                "activePath": "",
                "record": None,
                "preview": None,
                "effectiveBundle": {},
            }

        active_payload = _read_json_file(resolved_active_path)
        record = active_payload.get("record")
        preview = active_payload.get("preview")
        effective_bundle = active_payload.get("effectiveBundle")
        if not isinstance(record, dict):
            items = payload.get("items")
            if isinstance(items, list):
                record = next(
                    (
                        dict(item)
                        for item in items
                        if isinstance(item, dict)
                        and str(item.get("versionId") or "") == active_version_id
                    ),
                    None,
                )
        if isinstance(record, dict):
            matched_record = next(
                (
                    dict(item)
                    for item in (payload.get("items") or [])
                    if isinstance(item, dict)
                    and str(item.get("versionId") or "") == active_version_id
                ),
                None,
            )
            if isinstance(matched_record, dict):
                record.update(matched_record)
            listed_at = _resolve_listed_at(record)
            record["listedAt"] = listed_at
            record["installedAt"] = listed_at
            record["isListed"] = bool(listed_at)
            record["isInstalled"] = bool(listed_at)
            record["isActive"] = True
            record["appliedAt"] = applied_at
            record["activePath"] = active_path_text or str(resolved_active_path.resolve())

        return {
            "activeVersionId": active_version_id,
            "appliedAt": applied_at,
            "activePath": active_path_text or str(resolved_active_path.resolve()),
            "record": record if isinstance(record, dict) else None,
            "preview": preview if isinstance(preview, dict) else None,
            "effectiveBundle": effective_bundle if isinstance(effective_bundle, dict) else {},
        }


def list_installed_customization_apps(
    *,
    limit: int = 50,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _migrate_legacy_storage(
            registry_path,
            NL_CUSTOMIZATION_BUNDLE_DIR,
            NL_CUSTOMIZATION_ACTIVE_PATH,
        )
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            return []

        active_app_map = _build_active_app_map(payload)
        installed_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            listed_at = _resolve_listed_at(item)
            if not listed_at:
                continue
            normalized_item = dict(item)
            app_id = str(normalized_item.get("appId") or "").strip()
            active_entry = active_app_map.get(app_id or "")
            normalized_item["listedAt"] = listed_at
            normalized_item["installedAt"] = listed_at
            normalized_item["isListed"] = True
            normalized_item["isInstalled"] = True
            normalized_item["isActive"] = bool(
                active_entry
                and str(active_entry.get("versionId") or "") == str(item.get("versionId") or "")
            )
            installed_items.append(normalized_item)

        installed_items.sort(key=lambda item: str(item.get("listedAt") or ""), reverse=True)
        if limit > 0:
            return installed_items[:limit]
        return installed_items


def update_customization_app_listing(
    *,
    version_id: str,
    listed: bool,
    requested_by: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _migrate_legacy_storage(
            registry_path,
            NL_CUSTOMIZATION_BUNDLE_DIR,
            NL_CUSTOMIZATION_ACTIVE_PATH,
        )
        payload = _read_registry_unlocked(registry_path)
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
            payload["items"] = items

        normalized_version_id = str(version_id or "").strip()
        if not normalized_version_id:
            raise ValueError("versionId 不能为空")

        target_record = next(
            (
                dict(item)
                for item in items
                if isinstance(item, dict)
                and str(item.get("versionId") or "") == normalized_version_id
            ),
            None,
        )
        if target_record is None:
            raise ValueError(f"未找到版本 {normalized_version_id}")

        app_id = str(target_record.get("appId") or "").strip()
        active_entry = _build_active_app_map(payload).get(app_id or "")
        if listed and (
            not active_entry
            or str(active_entry.get("versionId") or "").strip() != normalized_version_id
        ):
            raise ValueError("请先应用该版本，再上架到应用中心。")

        now = _local_now_iso()
        listed_at = now if listed else ""
        updated_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            if (
                listed
                and app_id
                and str(next_item.get("appId") or "").strip() == app_id
                and str(next_item.get("versionId") or "") != normalized_version_id
            ):
                next_item["listedAt"] = ""
                next_item["installedAt"] = ""
            if str(next_item.get("versionId") or "") == normalized_version_id:
                next_item["listedAt"] = listed_at
                next_item["installedAt"] = listed_at
                next_item["listingUpdatedBy"] = str(requested_by or "portal").strip() or "portal"
            updated_items.append(next_item)

        payload["items"] = updated_items
        payload["version"] = NL_CUSTOMIZATION_REGISTRY_VERSION
        payload["updatedAt"] = now
        _write_json_atomic(registry_path, payload)

    record = next(
        (
            dict(item)
            for item in updated_items
            if isinstance(item, dict)
            and str(item.get("versionId") or "") == normalized_version_id
        ),
        target_record,
    )
    record["listedAt"] = _resolve_listed_at(record)
    record["installedAt"] = record["listedAt"]
    record["isListed"] = bool(record["listedAt"])
    record["isInstalled"] = bool(record["listedAt"])
    record["isActive"] = bool(
        active_entry
        and str(active_entry.get("versionId") or "").strip() == normalized_version_id
    )
    return {
        "versionId": normalized_version_id,
        "listed": bool(record["listedAt"]),
        "listedAt": record["listedAt"],
        "record": record,
    }


def _build_app_metadata(
    *,
    title: str,
    prompt: str,
    intent: Mapping[str, Any],
    matched_template: Mapping[str, Any],
    portal_config: Mapping[str, Any],
    app_id_override: str = "",
) -> dict[str, Any]:
    scenario_type = str(intent.get("scenarioType") or "generic")
    skill_id = str(matched_template.get("skillId") or "")
    target_type = str(intent.get("targetType") or "")
    display_targets = [
        str(item).strip()
        for item in (portal_config.get("displayTargets") or [])
        if str(item).strip()
    ] or ["assistant-entry"]
    launch_employee_id = _resolve_launch_employee_id(skill_id=skill_id, scenario_type=scenario_type)
    description = str(portal_config.get("cardTitle") or "").strip() or f"面向 {target_type or '通用'} 场景的定制应用"
    launch_prompt = (
        f"请按《{title}》应用方案执行：{prompt}"
        if prompt
        else f"请按《{title}》应用方案执行。"
    )
    app_identity = f"{title}|{skill_id or scenario_type}|{launch_employee_id}"
    return {
        "appId": app_id_override or f"nl-app-{uuid.uuid5(uuid.NAMESPACE_URL, app_identity).hex[:12]}",
        "description": description,
        "displayTargets": display_targets,
        "launchEmployeeId": launch_employee_id,
        "launchPrompt": launch_prompt,
    }


def _resolve_launch_employee_id(*, skill_id: str, scenario_type: str) -> str:
    if skill_id == "inspection-analyst" or scenario_type == "inspection":
        return "inspection"
    if skill_id == "alarm-analysis" or scenario_type == "alert-analysis":
        return "fault"
    if skill_id == "workorder-dispatch" or scenario_type == "workorder":
        return "order"
    if scenario_type == "portal-dashboard":
        return "query"
    return "query"
