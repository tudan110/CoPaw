"""Apply an image seed's managed files to an existing working directory.

The synchronizer intentionally has a narrow allowlist. It never walks a PVC
looking for files to delete: only paths declared by ``seed-manifest.json`` can
be updated, and target-only files remain untouched.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from uuid import uuid4

from qwenpaw.agents.skill_system.store import (
    _file_write_lock,
    _lock_path_for,
)

SEED_MANIFEST_NAME = "seed-manifest.json"
STATE_NAME = ".qwenpaw-managed-sync.json"
SYNC_DIR_NAME = ".qwenpaw-managed-sync"
PROTECTED_SKILL_PARTS = {"builtin_kb", "data"}
PRESERVED_SKILL_ENTRY_FIELDS = {
    "auto_update",
    "auto_update_synced_hash",
    "auto_update_targets",
    "config",
    "installed_from",
    "tags",
}
MANAGED_AGENT_FIELDS = {
    "description",
    "id",
    "name",
    "system_prompt_files",
    "workspace_dir",
}
WORKSPACE_PREFIX = Path("workspaces")


class ManagedSyncError(RuntimeError):
    """Raised when a managed seed cannot be safely synchronized."""


@dataclass(frozen=True)
class SyncAction:
    """One planned synchronization operation."""

    action: str
    kind: str
    path: str
    reason: str
    source_hash: str | None = None
    target_hash: str | None = None


@dataclass
class SyncResult:
    """Serializable plan/apply result."""

    seed_id: str
    target: str
    dry_run: bool
    actions: list[SyncAction] = field(default_factory=list)
    report_path: str | None = None
    backup_path: str | None = None

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for action in self.actions:
            counts[action.action] = counts.get(action.action, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "target": self.target,
            "dry_run": self.dry_run,
            "summary": self.summary(),
            "report_path": self.report_path,
            "backup_path": self.backup_path,
            "actions": [asdict(action) for action in self.actions],
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagedSyncError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManagedSyncError(f"Expected JSON object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    _write_bytes_atomic(
        path,
        (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8"),
    )


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _safe_relative(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or not value or ".." in candidate.parts:
        raise ManagedSyncError(f"Unsafe seed path: {value}")
    return candidate


def _safe_child(root: Path, relative: str) -> Path:
    path = (root / _safe_relative(relative)).resolve()
    root_resolved = root.resolve()
    if not path.is_relative_to(root_resolved):
        raise ManagedSyncError(f"Path escapes root: {relative}")
    return path


def _is_protected_skill_path(relative: Path) -> bool:
    return (
        relative.name == ".env"
        or relative.name == ".master_key"
        or bool(PROTECTED_SKILL_PARTS.intersection(relative.parts))
    )


def _load_manifest(seed: Path) -> dict[str, Any]:
    manifest = _read_json(seed / SEED_MANIFEST_NAME, {})
    if manifest.get("schema_version") != "qwenpaw-seed.v2":
        raise ManagedSyncError(
            "Unsupported seed manifest. Rebuild the image with a "
            "qwenpaw-seed.v2 manifest."
        )
    if not isinstance(manifest.get("managed_files"), dict):
        raise ManagedSyncError("Seed manifest has no managed_files object")
    if not isinstance(manifest.get("managed_skills"), dict):
        raise ManagedSyncError("Seed manifest has no managed_skills object")
    if not isinstance(manifest.get("seed_id"), str):
        raise ManagedSyncError("Seed manifest has no seed_id")
    return manifest


def _target_needs_bootstrap(target: Path) -> bool:
    return not (target / "config.json").is_file()


def _install_seed_into_empty_target(seed: Path, target: Path) -> None:
    """Install a complete seed only into an empty target mount."""
    existing = [
        path
        for path in target.iterdir()
        if path.name != ".qwenpaw_restore.lock"
    ]
    if existing:
        raise ManagedSyncError(
            "Target has no config.json but is not empty; refusing to mix a "
            "full seed with an unknown PVC layout."
        )
    created: list[Path] = []
    try:
        for source_path in sorted(seed.rglob("*")):
            relative = source_path.relative_to(seed)
            destination = _safe_child(target, str(relative))
            if source_path.is_symlink():
                raise ManagedSyncError(f"Refusing symbolic link seed path: {source_path}")
            if source_path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                created.append(destination)
            elif source_path.is_file():
                _copy_seed_file(source_path, destination)
                created.append(destination)
    except Exception:
        for created_path in reversed(created):
            with contextlib.suppress(FileNotFoundError, OSError):
                if created_path.is_dir():
                    created_path.rmdir()
                else:
                    created_path.unlink()
        raise


def _skill_root_for(relative: Path) -> Path | None:
    parts = relative.parts
    if len(parts) < 5 or parts[0] != "workspaces" or parts[2] != "skills":
        return None
    return Path(*parts[:4])


def _workspace_for(relative: Path) -> str | None:
    if len(relative.parts) < 2 or relative.parts[0] != "workspaces":
        return None
    return relative.parts[1]


def _target_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise ManagedSyncError(f"Refusing symbolic link target: {path}")
    if not path.is_file():
        raise ManagedSyncError(f"Expected file target: {path}")
    return _sha256(path)


def _managed_file_entries(
    manifest: dict[str, Any],
) -> Iterable[tuple[Path, dict[str, str]]]:
    for raw_relative, entry in manifest["managed_files"].items():
        if not isinstance(entry, dict):
            raise ManagedSyncError(f"Invalid managed entry: {raw_relative}")
        kind = entry.get("kind")
        source_hash = entry.get("sha256")
        if kind not in {
            "agent_config",
            "skill_file",
            "skill_manifest",
            "workspace_file",
        } or not isinstance(source_hash, str):
            raise ManagedSyncError(f"Invalid managed metadata: {raw_relative}")
        relative = _safe_relative(raw_relative)
        if kind == "skill_file" and _is_protected_skill_path(relative):
            raise ManagedSyncError(f"Protected path declared managed: {raw_relative}")
        yield relative, {"kind": kind, "sha256": source_hash}


def _plan(manifest: dict[str, Any], seed: Path, target: Path) -> list[SyncAction]:
    actions: list[SyncAction] = []
    grouped_skill_files: dict[Path, list[tuple[Path, dict[str, str]]]] = {}

    for relative, entry in _managed_file_entries(manifest):
        skill_root = _skill_root_for(relative)
        if entry["kind"] == "skill_file" and skill_root is not None:
            grouped_skill_files.setdefault(skill_root, []).append((relative, entry))
            continue
        source = _safe_child(seed, str(relative))
        if not source.is_file() or source.is_symlink():
            raise ManagedSyncError(f"Invalid seed file: {source}")
        target_file = _safe_child(target, str(relative))
        current_hash = _target_hash(target_file)
        action = "add" if current_hash is None else "update"
        if current_hash == entry["sha256"]:
            action = "unchanged"
        actions.append(
            SyncAction(
                action=action,
                kind=entry["kind"],
                path=str(relative),
                reason="managed_seed",
                source_hash=entry["sha256"],
                target_hash=current_hash,
            )
        )

    for skill_root, entries in sorted(grouped_skill_files.items()):
        destination = _safe_child(target, str(skill_root))
        current_hash = _tree_hash(destination, entries)
        source_hash = manifest["managed_skills"][str(skill_root)]["tree_sha256"]
        action = "add" if not destination.exists() else "update"
        if current_hash == source_hash:
            action = "unchanged"
        actions.append(
            SyncAction(
                action=action,
                kind="skill_tree",
                path=str(skill_root),
                reason="managed_seed",
                source_hash=source_hash,
                target_hash=current_hash,
            )
        )

    return actions


def _tree_hash(
    root: Path,
    entries: list[tuple[Path, dict[str, str]]],
) -> str | None:
    if not root.exists():
        return None
    digest = hashlib.sha256()
    for relative, _entry in sorted(entries):
        source_relative = relative.relative_to(_skill_root_for(relative) or relative)
        candidate = root / source_relative
        digest.update(str(source_relative).encode("utf-8"))
        digest.update(b"\0")
        if candidate.is_file() and not candidate.is_symlink():
            digest.update(_sha256(candidate).encode("ascii"))
        else:
            digest.update(b"missing")
        digest.update(b"\n")
    return digest.hexdigest()


def _backup_file(path: Path, target: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    relative = path.resolve().relative_to(target.resolve())
    backup = backup_root / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        def ignore(directory: str, names: list[str]) -> set[str]:
            relative = Path(directory).relative_to(path)
            ignored: set[str] = set()
            for name in names:
                candidate = relative / name
                if _is_protected_skill_path(candidate):
                    ignored.add(name)
            return ignored

        shutil.copytree(path, backup, symlinks=False, ignore=ignore)
    else:
        shutil.copy2(path, backup)


def _backup_managed_skill_files(
    destination: Path,
    target: Path,
    backup_root: Path,
    skill_root: Path,
    entries: list[tuple[Path, dict[str, str]]],
) -> None:
    for relative, _entry in entries:
        in_skill = relative.relative_to(skill_root)
        _backup_file(destination / in_skill, target, backup_root)


def _restore_touched(
    touched: list[Path],
    target: Path,
    backup_root: Path,
) -> None:
    for path in reversed(touched):
        relative = path.resolve().relative_to(target.resolve())
        backup = backup_root / relative
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        if backup.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            if backup.is_dir():
                shutil.copytree(backup, path, symlinks=False)
            else:
                shutil.copy2(backup, path)


def _copy_seed_file(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ManagedSyncError(f"Refusing symbolic link seed file: {source}")
    _write_bytes_atomic(destination, source.read_bytes())


def _replace_skill_tree(
    seed: Path,
    target: Path,
    skill_root: Path,
    entries: list[tuple[Path, dict[str, str]]],
) -> None:
    source_root = _safe_child(seed, str(skill_root))
    destination = _safe_child(target, str(skill_root))
    if destination.exists() and destination.is_symlink():
        raise ManagedSyncError(
            f"Refusing symbolic link skill target: {destination}"
        )

    stage = destination.with_name(f".{destination.name}.managed-stage-{uuid4().hex}")
    old = destination.with_name(f".{destination.name}.managed-old-{uuid4().hex}")
    try:
        if destination.exists():
            shutil.copytree(destination, stage, symlinks=False)
        else:
            stage.mkdir(parents=True)
        for relative, _entry in entries:
            in_skill = relative.relative_to(skill_root)
            source_file = _safe_child(source_root, str(in_skill))
            if not source_file.is_file() or source_file.is_symlink():
                raise ManagedSyncError(f"Invalid seed skill file: {source_file}")
            _copy_seed_file(source_file, stage / in_skill)
        if destination.exists():
            os.replace(destination, old)
        os.replace(stage, destination)
        shutil.rmtree(old, ignore_errors=True)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(stage)
        if old.exists() and not destination.exists():
            os.replace(old, destination)
        raise


def _merge_agent_config(seed_file: Path, target_file: Path) -> dict[str, Any]:
    source = _read_json(seed_file, {})
    target = _read_json(target_file, {})
    if not target_file.exists():
        return source
    merged = dict(target)
    for field in MANAGED_AGENT_FIELDS:
        if field in source:
            merged[field] = source[field]
    return merged


def _merge_skill_manifest(
    seed_file: Path,
    target_file: Path,
    managed_skill_names: set[str],
) -> dict[str, Any]:
    source = _read_json(seed_file, {"skills": {}})
    target = _read_json(target_file, {"skills": {}})
    merged = dict(target)
    source_skills = source.get("skills", {})
    target_skills = merged.setdefault("skills", {})
    if not isinstance(source_skills, dict) or not isinstance(target_skills, dict):
        raise ManagedSyncError(f"Invalid skill manifest: {target_file}")

    for name in managed_skill_names:
        entry = source_skills.get(name)
        if not isinstance(entry, dict):
            continue
        next_entry = dict(entry)
        existing = target_skills.get(name)
        if isinstance(existing, dict):
            for field in PRESERVED_SKILL_ENTRY_FIELDS:
                if field in existing:
                    next_entry[field] = existing[field]
        target_skills[name] = next_entry
    merged.setdefault("schema_version", source.get("schema_version"))
    return merged


def _write_skill_manifest(path: Path, payload: dict[str, Any]) -> None:
    with _file_write_lock(_lock_path_for(path)):
        payload = dict(payload)
        payload["version"] = max(
            int(payload.get("version", 0)) + 1,
            int(time.time() * 1000),
        )
        _write_json_atomic(path, payload)


def _state_path(target: Path) -> Path:
    return target / STATE_NAME


def _report_path(target: Path, seed_id: str) -> Path:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return target / SYNC_DIR_NAME / "reports" / f"{timestamp}-{seed_id[:12]}.json"


def _state_payload(manifest: dict[str, Any], actions: list[SyncAction]) -> dict[str, Any]:
    return {
        "schema_version": "qwenpaw-managed-sync.v1",
        "seed_id": manifest["seed_id"],
        "source_commit": manifest.get("source_commit", "unknown"),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "entries": {
            action.path: {
                "kind": action.kind,
                "seed_hash": action.source_hash,
            }
            for action in actions
            if action.action in {"add", "update", "unchanged"}
        },
    }


def sync_managed_seed(
    seed: Path,
    target: Path,
    *,
    apply: bool = False,
    report_path: Path | None = None,
) -> SyncResult:
    """Plan or apply direct managed-file synchronization from a seed."""
    seed = seed.resolve()
    target = target.resolve()
    if seed == target:
        raise ManagedSyncError("Seed and target directories must differ")
    if not seed.is_dir():
        raise ManagedSyncError(f"Seed directory does not exist: {seed}")
    if not target.is_dir():
        raise ManagedSyncError(f"Target directory does not exist: {target}")

    manifest = _load_manifest(seed)
    bootstrap_needed = _target_needs_bootstrap(target)
    actions = (
        [
            SyncAction(
                action="bootstrap",
                kind="working_seed",
                path=".",
                reason="target_missing_config",
            )
        ]
        if bootstrap_needed
        else _plan(manifest, seed, target)
    )
    result = SyncResult(
        seed_id=manifest["seed_id"],
        target=str(target),
        dry_run=not apply,
        actions=actions,
    )
    selected_report = report_path or _report_path(target, manifest["seed_id"])

    if not apply:
        return result

    if bootstrap_needed:
        with _file_write_lock(target / ".qwenpaw_restore.lock"):
            _install_seed_into_empty_target(seed, target)
            result.report_path = str(selected_report)
            report = result.as_dict()
            _write_json_atomic(selected_report, report)
            _write_json_atomic(
                target / SYNC_DIR_NAME / "reports" / "latest.json",
                report,
            )
            _write_json_atomic(
                _state_path(target),
                _state_payload(manifest, actions),
            )
        return result

    backup_root = (
        target
        / SYNC_DIR_NAME
        / "backups"
        / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    grouped_skill_files: dict[Path, list[tuple[Path, dict[str, str]]]] = {}
    managed_skill_names: dict[str, set[str]] = {}
    changed_skill_roots = {
        _safe_relative(action.path)
        for action in actions
        if action.kind == "skill_tree" and action.action in {"add", "update"}
    }
    changed_skill_manifests = {
        _safe_relative(action.path)
        for action in actions
        if action.kind == "skill_manifest" and action.action in {"add", "update"}
    }

    for relative, entry in _managed_file_entries(manifest):
        skill_root = _skill_root_for(relative)
        if entry["kind"] == "skill_file" and skill_root is not None:
            grouped_skill_files.setdefault(skill_root, []).append((relative, entry))
            workspace = _workspace_for(relative)
            if workspace is not None:
                managed_skill_names.setdefault(workspace, set()).add(skill_root.name)

    with _file_write_lock(target / ".qwenpaw_restore.lock"):
        touched: list[Path] = []
        try:
            for action in actions:
                if action.action == "unchanged":
                    continue
                relative = _safe_relative(action.path)
                if action.kind in {"skill_tree", "skill_manifest"}:
                    continue
                source = _safe_child(seed, str(relative))
                destination = _safe_child(target, str(relative))
                _backup_file(destination, target, backup_root)
                touched.append(destination)
                if action.kind == "agent_config":
                    merged = _merge_agent_config(source, destination)
                    _write_json_atomic(destination, merged)
                else:
                    _copy_seed_file(source, destination)

            for skill_root, entries in grouped_skill_files.items():
                if skill_root not in changed_skill_roots:
                    continue
                destination = _safe_child(target, str(skill_root))
                _backup_managed_skill_files(
                    destination,
                    target,
                    backup_root,
                    skill_root,
                    entries,
                )
                _replace_skill_tree(seed, target, skill_root, entries)

            for workspace, names in managed_skill_names.items():
                manifest_relative = Path("workspaces") / workspace / "skill.json"
                if manifest_relative not in changed_skill_manifests:
                    continue
                source = seed / manifest_relative
                destination = target / manifest_relative
                if not source.is_file():
                    continue
                _backup_file(destination, target, backup_root)
                touched.append(destination)
                _write_skill_manifest(
                    destination,
                    _merge_skill_manifest(source, destination, names),
                )

            result.backup_path = str(backup_root) if backup_root.exists() else None
            result.report_path = str(selected_report)
            report = result.as_dict()
            _write_json_atomic(selected_report, report)
            _write_json_atomic(
                target / SYNC_DIR_NAME / "reports" / "latest.json",
                report,
            )
            _write_json_atomic(
                _state_path(target),
                _state_payload(manifest, actions),
            )
        except Exception:
            _restore_touched(touched, target, backup_root)
            raise

    return result
