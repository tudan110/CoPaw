# -*- coding: utf-8 -*-
"""Shared SQLite store for all user-facing extension settings.

Every settings concern (alarm diagnosis, notification channels, ...) used
to keep its own file in its own directory and its own format (JSON here,
SQLite there). This module gives them one home:
``~/.qwenpaw/extensions/settings/settings.db`` — a single SQLite database
with one generic table, partitioned by ``namespace`` so each concern owns
its own keyspace.

    settings(namespace TEXT, key TEXT, value TEXT, updated_at TEXT)

Values are JSON scalars or objects. A reserved ``_meta`` namespace holds
one-time migration flags so legacy files are imported exactly once.

Connections are short-lived (WAL mode); reads are cached per
``(db_path, namespace)`` and the cache entry is dropped on any write to
that namespace.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qwenpaw.extensions.runtime_data_paths import (
    SETTINGS_DB_PATH as DEFAULT_DB_PATH,
)

_META_NAMESPACE = "_meta"

_LOCK = threading.Lock()
# Cache of namespace contents keyed by "<db_path>\x00<namespace>",
# valued as (monotonic_read_time, mapping). Entries expire after a short
# TTL: the app may run several uvicorn worker processes sharing one
# SQLite file, and a write in one worker can only invalidate that
# worker's own cache — without expiry the other workers would serve
# stale settings forever (e.g. a toggle "reverting" on page refresh).
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 2.0

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS settings (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT 'null',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (namespace, key)
)
"""


def _open_db(db_path: Path) -> sqlite3.Connection:
    """Open a short-lived SQLite connection with WAL mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_key(db_path: Path, namespace: str) -> str:
    return f"{db_path}\x00{namespace}"


def _invalidate(db_path: Path, namespace: str) -> None:
    _CACHE.pop(_cache_key(db_path, namespace), None)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _fresh_cached(cache_key: str) -> dict[str, Any] | None:
    cached = _CACHE.get(cache_key)
    if cached is None:
        return None
    read_at, mapping = cached
    if time.monotonic() - read_at >= _CACHE_TTL_SECONDS:
        return None
    return mapping


def get_namespace(
    namespace: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Return all ``{key: value}`` pairs stored under ``namespace``."""
    cache_key = _cache_key(db_path, namespace)
    cached = _fresh_cached(cache_key)
    if cached is not None:
        return dict(cached)
    with _LOCK:
        cached = _fresh_cached(cache_key)
        if cached is not None:
            return dict(cached)
        result: dict[str, Any] = {}
        try:
            conn = _open_db(db_path)
            try:
                rows = conn.execute(
                    "SELECT key, value FROM settings WHERE namespace = ?",
                    (namespace,),
                ).fetchall()
            finally:
                conn.close()
            for row in rows:
                try:
                    result[row["key"]] = json.loads(row["value"])
                except (json.JSONDecodeError, TypeError):
                    continue
        except sqlite3.Error:
            result = {}
        _CACHE[cache_key] = (time.monotonic(), dict(result))
        return dict(result)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def set_values(
    namespace: str,
    partial: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Upsert the given keys into ``namespace``. Empty dict is a no-op."""
    if not partial:
        return
    now = _now_iso()
    with _LOCK:
        conn = _open_db(db_path)
        try:
            conn.executemany(
                """
                INSERT INTO settings (namespace, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        namespace,
                        key,
                        json.dumps(value, ensure_ascii=False),
                        now,
                    )
                    for key, value in partial.items()
                ],
            )
            conn.commit()
        finally:
            conn.close()
        _invalidate(db_path, namespace)


def delete_value(
    namespace: str,
    key: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Remove a single key from ``namespace``."""
    with _LOCK:
        conn = _open_db(db_path)
        try:
            conn.execute(
                "DELETE FROM settings WHERE namespace = ? AND key = ?",
                (namespace, key),
            )
            conn.commit()
        finally:
            conn.close()
        _invalidate(db_path, namespace)


def replace_namespace(
    namespace: str,
    mapping: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Replace the entire contents of ``namespace`` with ``mapping``.

    Used by callers (e.g. notification channels) that always hold the full
    desired state and need removals to take effect.
    """
    now = _now_iso()
    with _LOCK:
        conn = _open_db(db_path)
        try:
            conn.execute(
                "DELETE FROM settings WHERE namespace = ?",
                (namespace,),
            )
            if mapping:
                conn.executemany(
                    """
                    INSERT INTO settings (namespace, key, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (
                            namespace,
                            key,
                            json.dumps(value, ensure_ascii=False),
                            now,
                        )
                        for key, value in mapping.items()
                    ],
                )
            conn.commit()
        finally:
            conn.close()
        _invalidate(db_path, namespace)


# ---------------------------------------------------------------------------
# One-time migration flags (reserved ``_meta`` namespace)
# ---------------------------------------------------------------------------


def is_migrated(flag: str, *, db_path: Path = DEFAULT_DB_PATH) -> bool:
    return bool(get_namespace(_META_NAMESPACE, db_path=db_path).get(flag))


def mark_migrated(flag: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    set_values(_META_NAMESPACE, {flag: True}, db_path=db_path)
