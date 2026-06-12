# -*- coding: utf-8 -*-
"""SQLite persistence for big-screen assets and draft tasks (M1).

Replaces the legacy ``registry.json`` single-file lock and the
in-memory per-worker draft-task dict. Every call opens a short-lived
WAL connection, so state is consistent across uvicorn workers and
survives restarts. The full wire payload is stored as JSON per row;
hot columns (status/updated_at) are mirrored for ordering and purge.
``migrate_from_registry`` imports the legacy registry.json once into
an empty database.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping

from qwenpaw.extensions.runtime_data_paths import (
    AI_BIG_SCREEN_DB_PATH as DEFAULT_DB_PATH,
    AI_BIG_SCREEN_REGISTRY_PATH as DEFAULT_REGISTRY_PATH,
    ensure_extension_data_dir,
)

_FINISHED_TASK_STATUSES = ("succeeded", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS screens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_screens_updated_at
    ON screens(updated_at DESC);
CREATE TABLE IF NOT EXISTS screen_versions (
    screen_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    PRIMARY KEY (screen_id, version_id)
);
CREATE TABLE IF NOT EXISTS draft_tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
"""


def _default_tz() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        return local_tz
    return timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(_default_tz())


def _now_iso() -> str:
    return _now().isoformat()


def now_iso() -> str:
    """Public clock helper shared by sibling persistence modules."""
    return _now_iso()


def _resolve_db_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else DEFAULT_DB_PATH


_DEFAULT_MIGRATION_DONE = False


def _connect(path: str | Path | None) -> sqlite3.Connection:
    global _DEFAULT_MIGRATION_DONE
    db_path = _resolve_db_path(path)
    ensure_extension_data_dir(db_path.parent)
    connection = sqlite3.connect(str(db_path), timeout=15)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    connection.executescript(_SCHEMA)
    if path is None and not _DEFAULT_MIGRATION_DONE:
        # One-time per process: import the legacy registry.json into an
        # empty default database. Explicit paths (tests) skip this.
        _DEFAULT_MIGRATION_DONE = True
        try:
            _migrate_into(connection, DEFAULT_REGISTRY_PATH)
        except Exception:  # migration must never block normal use
            pass
    return connection


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Public connection helper for sibling persistence modules
    (telemetry etc.) that add their own tables to the same database."""
    return _connect(path)


def _dump(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _load(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# screens + versions
# ---------------------------------------------------------------------------


def _upsert_screen_unlocked(
    connection: sqlite3.Connection,
    screen: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO screens (
            id, name, status, created_at, updated_at, updated_by, payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            status=excluded.status,
            created_at=excluded.created_at,
            updated_at=excluded.updated_at,
            updated_by=excluded.updated_by,
            payload=excluded.payload
        """,
        (
            str(screen.get("id") or ""),
            str(screen.get("name") or ""),
            str(screen.get("status") or "draft"),
            str(screen.get("createdAt") or ""),
            str(screen.get("updatedAt") or ""),
            str(screen.get("updatedBy") or ""),
            _dump(screen),
        ),
    )
    for version in screen.get("versions") or []:
        if not isinstance(version, dict):
            continue
        version_id = str(version.get("versionId") or "").strip()
        if not version_id:
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO screen_versions (
                screen_id, version_id, created_at, summary, payload
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(screen.get("id") or ""),
                version_id,
                str(version.get("createdAt") or ""),
                str(version.get("changeSummary") or ""),
                _dump(version),
            ),
        )


def save_screen(
    *,
    screen: Mapping[str, Any],
    requested_by: str = "portal",
    path: str | Path | None = None,
) -> dict[str, Any]:
    screen_id = str(screen.get("id") or "").strip()
    if not screen_id:
        raise ValueError("screen.id 不能为空")

    now = _now_iso()
    normalized = dict(screen)
    normalized.setdefault("createdAt", now)
    normalized["updatedAt"] = now
    normalized["updatedBy"] = str(requested_by or "portal").strip() or "portal"
    normalized.setdefault("status", "draft")
    normalized.setdefault("versions", [])
    normalized.setdefault("publishTargets", [])

    with _connect(path) as connection:
        _upsert_screen_unlocked(connection, normalized)
    return normalized


def get_screen(
    *,
    screen_id: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_id = str(screen_id or "").strip()
    if not normalized_id:
        raise ValueError("screenId 不能为空")
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT payload FROM screens WHERE id = ?",
            (normalized_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"未找到大屏：{normalized_id}")
    return _load(row[0])


def list_screens(
    *,
    limit: int = 50,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT payload FROM screens ORDER BY updated_at DESC"
    args: tuple[Any, ...] = ()
    if limit > 0:
        query += " LIMIT ?"
        args = (limit,)
    with _connect(path) as connection:
        rows = connection.execute(query, args).fetchall()
    return [_load(row[0]) for row in rows]


def delete_screen(
    *,
    screen_id: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    deleted = get_screen(screen_id=screen_id, path=path)
    normalized_id = str(screen_id or "").strip()
    with _connect(path) as connection:
        connection.execute(
            "DELETE FROM screens WHERE id = ?",
            (normalized_id,),
        )
        connection.execute(
            "DELETE FROM screen_versions WHERE screen_id = ?",
            (normalized_id,),
        )
    return deleted


def list_screen_versions(
    *,
    screen_id: str,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT payload FROM screen_versions
            WHERE screen_id = ?
            ORDER BY created_at ASC, version_id ASC
            """,
            (str(screen_id or "").strip(),),
        ).fetchall()
    return [_load(row[0]) for row in rows]


# ---------------------------------------------------------------------------
# draft tasks (cross-worker)
# ---------------------------------------------------------------------------


def create_task(
    *,
    task: Mapping[str, Any],
    path: str | Path | None = None,
) -> dict[str, Any]:
    payload = dict(task)
    task_id = str(payload.get("taskId") or "").strip()
    if not task_id:
        raise ValueError("taskId 不能为空")
    payload.setdefault("createdAt", _now_iso())
    payload.setdefault("updatedAt", payload["createdAt"])
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO draft_tasks (
                task_id, status, stage, created_at, updated_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                str(payload.get("status") or "queued"),
                str(payload.get("stage") or "queued"),
                str(payload.get("createdAt") or ""),
                str(payload.get("updatedAt") or ""),
                _dump(payload),
            ),
        )
    return payload


def get_task(
    *,
    task_id: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_id = str(task_id or "").strip()
    if not normalized_id:
        raise ValueError("未找到生成任务：")
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT payload FROM draft_tasks WHERE task_id = ?",
            (normalized_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"未找到生成任务：{normalized_id}")
    return _load(row[0])


def update_task(
    *,
    task_id: str,
    updates: Mapping[str, Any],
    path: str | Path | None = None,
) -> None:
    """Merge ``updates`` into the task payload; no-op when missing."""
    normalized_id = str(task_id or "").strip()
    if not normalized_id:
        return
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT payload FROM draft_tasks WHERE task_id = ?",
            (normalized_id,),
        ).fetchone()
        if row is None:
            return
        payload = _load(row[0])
        payload.update(dict(updates))
        payload["updatedAt"] = _now_iso()
        connection.execute(
            """
            UPDATE draft_tasks
            SET status = ?, stage = ?, updated_at = ?, payload = ?
            WHERE task_id = ?
            """,
            (
                str(payload.get("status") or "queued"),
                str(payload.get("stage") or "queued"),
                str(payload.get("updatedAt") or ""),
                _dump(payload),
                normalized_id,
            ),
        )


def purge_tasks(
    *,
    ttl_seconds: int = 24 * 3600,
    path: str | Path | None = None,
) -> int:
    """Remove finished tasks older than ``ttl_seconds``."""
    cutoff = (_now() - timedelta(seconds=max(0, ttl_seconds))).isoformat()
    placeholders = ", ".join("?" for _ in _FINISHED_TASK_STATUSES)
    with _connect(path) as connection:
        cursor = connection.execute(
            f"""
            DELETE FROM draft_tasks
            WHERE status IN ({placeholders}) AND updated_at < ?
            """,
            (*_FINISHED_TASK_STATUSES, cutoff),
        )
    return int(cursor.rowcount or 0)


# ---------------------------------------------------------------------------
# one-time migration from registry.json
# ---------------------------------------------------------------------------


def _migrate_into(connection: sqlite3.Connection, source: Path) -> int:
    existing = connection.execute(
        "SELECT COUNT(*) FROM screens",
    ).fetchone()[0]
    if existing:
        return 0
    if not source.is_file():
        return 0
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    items = payload.get("items") if isinstance(payload, dict) else None
    migrated = 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if not str(item.get("id") or "").strip():
            continue
        _upsert_screen_unlocked(connection, dict(item))
        migrated += 1
    connection.commit()
    return migrated


def migrate_from_registry(
    *,
    registry_path: str | Path | None = None,
    path: str | Path | None = None,
) -> int:
    """Import legacy registry.json into an EMPTY database.

    Returns the number of screens migrated (0 when the database already
    has rows or the registry file is absent/corrupt) — idempotent.
    """
    source = (
        Path(registry_path)
        if registry_path is not None
        else DEFAULT_REGISTRY_PATH
    )
    with _connect(path) as connection:
        return _migrate_into(connection, source)
