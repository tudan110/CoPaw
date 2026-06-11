# -*- coding: utf-8 -*-
"""SQLite store for INOE alarm-clear notification events.

When the INOE platform clears an alarm it notifies us through
``POST /api/portal/real-alarms/clear-notifications``. Each notification
becomes one row here; the recovery-verification background loop then
drives the row through its lifecycle:

    pending -> verifying -> observing -> recovered
                         -> (retry: back to pending)
                         -> unrecovered / unknown / recurred

Scheduling (initial delay, retries, observation window) is entirely
DB-driven via ``next_verify_at`` so pending work survives restarts. The
table lives in the same database file as the alarm registry
(``portal_real_alarm_registry.db``).
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

from qwenpaw.extensions.runtime_data_paths import (
    PORTAL_REAL_ALARM_REGISTRY_DB_PATH as DEFAULT_CLEAR_EVENTS_DB_PATH,
)

# Event statuses that still need work from the verification loop.
ALARM_CLEAR_ACTIVE_STATUSES = frozenset({"pending", "verifying", "observing"})
# Final statuses; the loop never touches these again.
ALARM_CLEAR_TERMINAL_STATUSES = frozenset(
    {"recovered", "unrecovered", "unknown", "recurred"},
)

_EVENTS_LOCK = threading.Lock()

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS alarm_clear_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alarm_id TEXT NOT NULL,
    res_id TEXT NOT NULL DEFAULT '',
    clear_time TEXT NOT NULL DEFAULT '',
    clear_type TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    metric_type TEXT NOT NULL DEFAULT '',
    raw_payload TEXT NOT NULL DEFAULT '',
    verify_status TEXT NOT NULL DEFAULT 'pending',
    verify_attempts INTEGER NOT NULL DEFAULT 0,
    next_verify_at TEXT NOT NULL DEFAULT '',
    verify_result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_clear_events_alarm_id "
    "ON alarm_clear_events(alarm_id)",
    "CREATE INDEX IF NOT EXISTS idx_clear_events_due "
    "ON alarm_clear_events(verify_status, next_verify_at)",
]

# snake_case DB column -> camelCase API key
_COL_TO_KEY: dict[str, str] = {
    "id": "id",
    "alarm_id": "alarmId",
    "res_id": "resId",
    "clear_time": "clearTime",
    "clear_type": "clearType",
    "operator": "operator",
    "reason": "reason",
    "metric_type": "metricType",
    "raw_payload": "rawPayload",
    "verify_status": "verifyStatus",
    "verify_attempts": "verifyAttempts",
    "next_verify_at": "nextVerifyAt",
    "verify_result": "verifyResult",
    "created_at": "createdAt",
    "updated_at": "updatedAt",
}

# Columns update_clear_event() may write.
_UPDATABLE_COLUMNS = frozenset(
    {
        "res_id",
        "clear_time",
        "clear_type",
        "operator",
        "reason",
        "metric_type",
        "raw_payload",
        "verify_status",
        "verify_attempts",
        "next_verify_at",
        "verify_result",
    },
)


def _default_events_timezone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        return local_tz
    return timezone(timedelta(hours=8))


def local_now() -> datetime:
    return datetime.now(_default_events_timezone())


def _local_now_iso() -> str:
    return local_now().isoformat()


def _resolve_db_path(path: str | Path | None = None) -> Path:
    if path is None:
        return DEFAULT_CLEAR_EVENTS_DB_PATH
    return Path(path)


def _open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(_CREATE_TABLE_SQL)
    for idx_sql in _CREATE_INDEXES_SQL:
        conn.execute(idx_sql)
    conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {_COL_TO_KEY.get(k, k): row[k] for k in row.keys()}


def record_clear_notification(
    *,
    alarm_id: str,
    res_id: str = "",
    clear_time: str = "",
    clear_type: str = "",
    operator: str = "",
    reason: str = "",
    metric_type: str = "",
    raw_payload: str = "",
    next_verify_at: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist a clear notification, deduplicating per alarm.

    If an active (pending/verifying/observing) event already exists for
    the alarm, its notification fields are refreshed in place and no new
    row is created — repeated pushes from INOE therefore cannot pile up
    verification work. The returned dict carries ``deduped: True`` in
    that case.
    """
    normalized_alarm_id = str(alarm_id or "").strip()
    if not normalized_alarm_id:
        raise ValueError("alarm_id is required")

    db_path = _resolve_db_path(path)
    now = _local_now_iso()
    with _EVENTS_LOCK:
        conn = _open_db(db_path)
        try:
            placeholders = ", ".join("?" for _ in ALARM_CLEAR_ACTIVE_STATUSES)
            row = conn.execute(
                "SELECT * FROM alarm_clear_events "
                f"WHERE alarm_id = ? AND verify_status IN ({placeholders}) "
                "ORDER BY id DESC LIMIT 1",
                (normalized_alarm_id, *sorted(ALARM_CLEAR_ACTIVE_STATUSES)),
            ).fetchone()

            if row is not None:
                conn.execute(
                    "UPDATE alarm_clear_events SET "
                    "res_id = CASE WHEN ? != '' THEN ? ELSE res_id END, "
                    "clear_time = CASE WHEN ? != '' THEN ? "
                    "ELSE clear_time END, "
                    "clear_type = CASE WHEN ? != '' THEN ? "
                    "ELSE clear_type END, "
                    "operator = CASE WHEN ? != '' THEN ? ELSE operator END, "
                    "reason = CASE WHEN ? != '' THEN ? ELSE reason END, "
                    "metric_type = CASE WHEN ? != '' THEN ? "
                    "ELSE metric_type END, "
                    "raw_payload = CASE WHEN ? != '' THEN ? "
                    "ELSE raw_payload END, "
                    "updated_at = ? "
                    "WHERE id = ?",
                    (
                        res_id,
                        res_id,
                        clear_time,
                        clear_time,
                        clear_type,
                        clear_type,
                        operator,
                        operator,
                        reason,
                        reason,
                        metric_type,
                        metric_type,
                        raw_payload,
                        raw_payload,
                        now,
                        row["id"],
                    ),
                )
                conn.commit()
                refreshed = conn.execute(
                    "SELECT * FROM alarm_clear_events WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                result = _row_to_dict(refreshed)
                result["deduped"] = True
                return result

            cursor = conn.execute(
                "INSERT INTO alarm_clear_events ("
                "alarm_id, res_id, clear_time, clear_type, operator, "
                "reason, metric_type, raw_payload, verify_status, "
                "verify_attempts, next_verify_at, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)",
                (
                    normalized_alarm_id,
                    str(res_id or "").strip(),
                    str(clear_time or "").strip(),
                    str(clear_type or "").strip(),
                    str(operator or "").strip(),
                    str(reason or "").strip(),
                    str(metric_type or "").strip(),
                    raw_payload or "",
                    str(next_verify_at or "").strip() or now,
                    now,
                    now,
                ),
            )
            conn.commit()
            created = conn.execute(
                "SELECT * FROM alarm_clear_events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            result = _row_to_dict(created)
            result["deduped"] = False
            return result
        finally:
            conn.close()


def fetch_due_clear_events(
    *,
    now_iso: str = "",
    limit: int = 5,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return active events whose ``next_verify_at`` has passed.

    ISO timestamps with a fixed-offset timezone compare correctly as
    strings within the same offset, which holds here because all rows
    are written with the local timezone.
    """
    db_path = _resolve_db_path(path)
    effective_now = str(now_iso or "").strip() or _local_now_iso()
    with _EVENTS_LOCK:
        conn = _open_db(db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM alarm_clear_events "
                "WHERE verify_status IN ('pending', 'observing') "
                "AND next_verify_at != '' AND next_verify_at <= ? "
                "ORDER BY next_verify_at ASC LIMIT ?",
                (effective_now, max(1, int(limit))),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()


def get_clear_event(
    event_id: int,
    *,
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    db_path = _resolve_db_path(path)
    with _EVENTS_LOCK:
        conn = _open_db(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM alarm_clear_events WHERE id = ?",
                (int(event_id),),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()


def update_clear_event(
    event_id: int,
    *,
    path: str | Path | None = None,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update writable columns of one event. Returns the updated row."""
    updates: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in _UPDATABLE_COLUMNS:
            raise ValueError(f"Unknown alarm_clear_events column: {key}")
        updates[key] = value
    if not updates:
        return get_clear_event(event_id, path=path)

    updates["updated_at"] = _local_now_iso()
    db_path = _resolve_db_path(path)
    with _EVENTS_LOCK:
        conn = _open_db(db_path)
        try:
            assignments = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE alarm_clear_events SET {assignments} WHERE id = ?",
                (*updates.values(), int(event_id)),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM alarm_clear_events WHERE id = ?",
                (int(event_id),),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()


def list_clear_events(
    *,
    alarm_id: str = "",
    limit: int = 50,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    db_path = _resolve_db_path(path)
    with _EVENTS_LOCK:
        conn = _open_db(db_path)
        try:
            normalized = str(alarm_id or "").strip()
            if normalized:
                rows = conn.execute(
                    "SELECT * FROM alarm_clear_events WHERE alarm_id = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (normalized, max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alarm_clear_events "
                    "ORDER BY id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()


def reset_zombie_verifying_events(
    *,
    path: str | Path | None = None,
) -> int:
    """Reset events stuck in 'verifying' back to 'pending'.

    Called at startup to recover from unclean shutdowns where the
    verification loop died mid-event. Returns the number reset.
    """
    db_path = _resolve_db_path(path)
    with _EVENTS_LOCK:
        conn = _open_db(db_path)
        try:
            now = _local_now_iso()
            cursor = conn.execute(
                "UPDATE alarm_clear_events SET verify_status = 'pending', "
                "next_verify_at = ?, updated_at = ? "
                "WHERE verify_status = 'verifying'",
                (now, now),
            )
            count = cursor.rowcount
            conn.commit()
            return count
        finally:
            conn.close()
