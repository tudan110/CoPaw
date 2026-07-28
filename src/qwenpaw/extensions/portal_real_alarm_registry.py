# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping

from qwenpaw.constant import WORKING_DIR
from qwenpaw.extensions.runtime_data_paths import (
    PORTAL_REAL_ALARM_REGISTRY_DB_PATH as DEFAULT_PORTAL_REAL_ALARM_REGISTRY_DB_PATH,
    PORTAL_REAL_ALARM_REGISTRY_PATH as DEFAULT_PORTAL_REAL_ALARM_REGISTRY_JSON_PATH,
    ensure_extension_data_dir,
)

PORTAL_REAL_ALARM_REGISTRY_VERSION = 1
PORTAL_REAL_ALARM_REGISTRY_PATH = DEFAULT_PORTAL_REAL_ALARM_REGISTRY_DB_PATH
LEGACY_PORTAL_REAL_ALARM_REGISTRY_PATH = WORKING_DIR / "portal_real_alarm_registry.json"
PORTAL_REAL_ALARM_HIDDEN_STATUSES = frozenset(
    {
        "taken_over",
        "analyzing",
        "analyzed",
        "manual_pending",
        "manual_recovered",
        "manual_unrecovered",
        "manual_unknown",
        "resolved",
        "ignored",
        # Recovery verification verdicts after an INOE clear notification.
        # Deliberately NOT hidden: "recurred" — a recurred alarm must
        # surface again so the auto-takeover loop re-analyzes it.
        "recovery_failed",
        "recovery_unknown",
    }
)
_PORTAL_REAL_ALARM_TERMINAL_STATUSES = frozenset(
    {
        "analyzed",
        "manual_pending",
        "manual_recovered",
        "manual_unrecovered",
        "manual_unknown",
        "resolved",
        "ignored",
        "recovery_failed",
        "recovery_unknown",
    }
)
_REGISTRY_LOCK = threading.Lock()
_MIGRATED_DBS: set[str] = set()

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS alarm_records (
    alarm_id TEXT PRIMARY KEY,
    res_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    device_name TEXT NOT NULL DEFAULT '',
    manage_ip TEXT NOT NULL DEFAULT '',
    event_time TEXT NOT NULL DEFAULT '',
    event_last_time TEXT NOT NULL DEFAULT '',
    act_count TEXT NOT NULL DEFAULT '',
    visible_content TEXT NOT NULL DEFAULT '',
    additional_text TEXT NOT NULL DEFAULT '',
    alarm_location TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    session_id TEXT NOT NULL DEFAULT '',
    chat_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    taken_over_at TEXT NOT NULL DEFAULT '',
    handled_at TEXT NOT NULL DEFAULT '',
    last_triggered_at TEXT NOT NULL DEFAULT '',
    resolved_at TEXT NOT NULL DEFAULT '',
    analysis_result TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_alarm_session_id ON alarm_records(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_alarm_chat_id ON alarm_records(chat_id)",
    "CREATE INDEX IF NOT EXISTS idx_alarm_res_id ON alarm_records(res_id)",
    "CREATE INDEX IF NOT EXISTS idx_alarm_status ON alarm_records(status)",
]

# camelCase API key → snake_case DB column
_KEY_TO_COL: dict[str, str] = {
    "alarmId": "alarm_id",
    "resId": "res_id",
    "title": "title",
    "deviceName": "device_name",
    "manageIp": "manage_ip",
    "eventTime": "event_time",
    "eventLastTime": "event_last_time",
    "actCount": "act_count",
    "visibleContent": "visible_content",
    "additionalText": "additional_text",
    "alarmLocation": "alarm_location",
    "status": "status",
    "sessionId": "session_id",
    "chatId": "chat_id",
    "source": "source",
    "verificationStatus": "verification_status",
    "lastError": "last_error",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
    "takenOverAt": "taken_over_at",
    "handledAt": "handled_at",
    "lastTriggeredAt": "last_triggered_at",
    "resolvedAt": "resolved_at",
    "analysisResult": "analysis_result",
}
_COL_TO_KEY: dict[str, str] = {v: k for k, v in _KEY_TO_COL.items()}
_ALL_COLUMNS = list(_KEY_TO_COL.values())


def _default_registry_timezone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        return local_tz
    return timezone(timedelta(hours=8))


def _local_now_iso() -> str:
    return datetime.now(_default_registry_timezone()).isoformat()


def _resolve_registry_path(path: str | Path | None = None) -> Path:
    if path is None:
        return PORTAL_REAL_ALARM_REGISTRY_PATH
    p = Path(path)
    if p.suffix == ".json":
        return p.with_suffix(".db")
    return p


def _coalesce_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _coalesce_count(*values: Any) -> str:
    """Like _coalesce_text but keeps a literal 0 (counts may be zero)."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _alarm_id_from_payload(alarm: Mapping[str, Any] | None) -> str:
    if not isinstance(alarm, Mapping):
        return ""
    return _coalesce_text(alarm.get("alarmId"), alarm.get("id"), alarm.get("alarm_id"))


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a DB row to a camelCase dict matching the legacy API."""
    return {_COL_TO_KEY.get(k, k): row[k] for k in row.keys()}


def _open_db(db_path: Path) -> sqlite3.Connection:
    """Open a short-lived SQLite connection with WAL mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(_CREATE_TABLE_SQL)
    for idx_sql in _CREATE_INDEXES_SQL:
        conn.execute(idx_sql)
    # Migrate: add columns that may not exist in older DBs
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(alarm_records)").fetchall()
    }
    if "analysis_result" not in existing_cols:
        conn.execute(
            "ALTER TABLE alarm_records ADD COLUMN analysis_result TEXT NOT NULL DEFAULT ''"
        )
    if "event_last_time" not in existing_cols:
        conn.execute(
            "ALTER TABLE alarm_records ADD COLUMN event_last_time TEXT NOT NULL DEFAULT ''"
        )
    if "act_count" not in existing_cols:
        conn.execute(
            "ALTER TABLE alarm_records ADD COLUMN act_count TEXT NOT NULL DEFAULT ''"
        )
    if "additional_text" not in existing_cols:
        conn.execute(
            "ALTER TABLE alarm_records ADD COLUMN additional_text TEXT NOT NULL DEFAULT ''"
        )
    if "alarm_location" not in existing_cols:
        conn.execute(
            "ALTER TABLE alarm_records ADD COLUMN alarm_location TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()
    return conn


def _collect_json_sources(db_path: Path) -> list[Path]:
    """Return existing JSON files that may contain alarm records to migrate."""
    sources: list[Path] = []
    json_sibling = db_path.with_suffix(".json")
    if json_sibling.exists():
        sources.append(json_sibling)
    if (
        DEFAULT_PORTAL_REAL_ALARM_REGISTRY_JSON_PATH.exists()
        and DEFAULT_PORTAL_REAL_ALARM_REGISTRY_JSON_PATH.resolve()
        not in {p.resolve() for p in sources}
    ):
        sources.append(DEFAULT_PORTAL_REAL_ALARM_REGISTRY_JSON_PATH)
    if (
        LEGACY_PORTAL_REAL_ALARM_REGISTRY_PATH.exists()
        and LEGACY_PORTAL_REAL_ALARM_REGISTRY_PATH.resolve()
        not in {p.resolve() for p in sources}
    ):
        sources.append(LEGACY_PORTAL_REAL_ALARM_REGISTRY_PATH)
    return sources


def _import_json_records(conn: sqlite3.Connection, json_path: Path) -> int:
    """Import alarm records from a JSON file into the DB. Returns count imported."""
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    alarms = payload.get("alarms")
    if not isinstance(alarms, dict):
        return 0

    count = 0
    for alarm_id, record in alarms.items():
        if not isinstance(record, dict):
            continue
        alarm_id = str(alarm_id).strip()
        if not alarm_id:
            continue
        # Skip if this alarm_id already exists (idempotent)
        existing = conn.execute(
            "SELECT 1 FROM alarm_records WHERE alarm_id = ?", (alarm_id,)
        ).fetchone()
        if existing:
            continue

        values = {col: "" for col in _ALL_COLUMNS}
        values["alarm_id"] = alarm_id
        for camel_key, col in _KEY_TO_COL.items():
            val = _coalesce_text(record.get(camel_key))
            if val:
                values[col] = val

        cols = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO alarm_records ({cols}) VALUES ({placeholders})",
            list(values.values()),
        )
        count += 1
    return count


def _ensure_migrated(db_path: Path) -> None:
    """Migrate legacy JSON files into the SQLite DB if not done yet."""
    db_key = str(db_path.resolve())
    if db_key in _MIGRATED_DBS:
        return
    sources = _collect_json_sources(db_path)
    if not sources:
        _MIGRATED_DBS.add(db_key)
        return

    conn = _open_db(db_path)
    try:
        for json_path in sources:
            _import_json_records(conn, json_path)
        conn.commit()
        for json_path in sources:
            bak_path = json_path.with_suffix(".json.bak")
            try:
                json_path.rename(bak_path)
            except OSError:
                pass
        _MIGRATED_DBS.add(db_key)
    finally:
        conn.close()


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
    merged["eventLastTime"] = _coalesce_text(
        alarm.get("eventLastTime"),
        alarm.get("event_last_time"),
        existing.get("eventLastTime"),
    )
    merged["actCount"] = _coalesce_count(
        alarm.get("actCount"),
        alarm.get("count"),
        alarm.get("act_count"),
        existing.get("actCount"),
    )
    merged["visibleContent"] = _coalesce_text(
        alarm.get("visibleContent"),
        alarm.get("visible_content"),
        existing.get("visibleContent"),
    )
    merged["additionalText"] = _coalesce_text(
        alarm.get("additionalText"),
        alarm.get("additional_text"),
        alarm.get("alarmText"),
        alarm.get("alarmtext"),
        alarm.get("rawMessage"),
        merged.get("visibleContent"),
        existing.get("additionalText"),
    )
    merged["alarmLocation"] = _coalesce_text(
        alarm.get("alarmLocation"),
        alarm.get("alarm_location"),
        alarm.get("location"),
        existing.get("alarmLocation"),
    )
    return merged


def get_alarm_record(
    alarm_id: str,
    *,
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Look up a single alarm record by alarm_id. Returns None if not found."""
    normalized = _coalesce_text(alarm_id)
    if not normalized:
        return None
    db_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _ensure_migrated(db_path)
        conn = _open_db(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM alarm_records WHERE alarm_id = ?",
                (normalized,),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()


def load_alarm_records(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    db_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _ensure_migrated(db_path)
        conn = _open_db(db_path)
        try:
            rows = conn.execute("SELECT * FROM alarm_records").fetchall()
            return {row["alarm_id"]: _row_to_dict(row) for row in rows}
        finally:
            conn.close()


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

    # If pre-loaded records dict is provided, use in-memory lookup (legacy compat)
    if isinstance(records, Mapping):
        return _find_alarm_id_in_records(
            records,
            session_id=session_id,
            chat_id=chat_id,
            res_id=res_id,
        )

    # Use targeted SQL queries
    db_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _ensure_migrated(db_path)
        conn = _open_db(db_path)
        try:
            return _find_alarm_id_sql(
                conn,
                session_id=session_id,
                chat_id=chat_id,
                res_id=res_id,
            )
        finally:
            conn.close()


def _find_alarm_id_in_records(
    entries: Mapping[str, Mapping[str, Any]],
    *,
    session_id: str = "",
    chat_id: str = "",
    res_id: str = "",
) -> str:
    """In-memory lookup matching the legacy JSON behavior."""
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
            matches.sort(
                key=lambda item: _coalesce_text(item[1].get("updatedAt")),
                reverse=True,
            )
            return matches[0][0]

    return ""


def _find_alarm_id_sql(
    conn: sqlite3.Connection,
    *,
    session_id: str = "",
    chat_id: str = "",
    res_id: str = "",
) -> str:
    """Targeted SQL lookup for alarm_id by various identifiers."""
    normalized_session_id = _coalesce_text(session_id)
    normalized_chat_id = _coalesce_text(chat_id)
    normalized_res_id = _coalesce_text(res_id)

    if normalized_session_id:
        row = conn.execute(
            "SELECT alarm_id FROM alarm_records WHERE session_id = ? LIMIT 1",
            (normalized_session_id,),
        ).fetchone()
        if row:
            return row["alarm_id"]

    if normalized_chat_id:
        row = conn.execute(
            "SELECT alarm_id FROM alarm_records WHERE chat_id = ? LIMIT 1",
            (normalized_chat_id,),
        ).fetchone()
        if row:
            return row["alarm_id"]

    if normalized_res_id:
        row = conn.execute(
            "SELECT alarm_id FROM alarm_records WHERE res_id = ? ORDER BY updated_at DESC LIMIT 1",
            (normalized_res_id,),
        ).fetchone()
        if row:
            return row["alarm_id"]

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
    analysis_result: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    db_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _ensure_migrated(db_path)
        conn = _open_db(db_path)
        try:
            resolved_alarm_id = _coalesce_text(alarm_id, _alarm_id_from_payload(alarm))
            if not resolved_alarm_id:
                resolved_alarm_id = _find_alarm_id_sql(
                    conn,
                    session_id=session_id,
                    chat_id=chat_id,
                    res_id=_coalesce_text(
                        res_id,
                        (alarm or {}).get("resId") if isinstance(alarm, Mapping) else "",
                    ),
                )
            if not resolved_alarm_id:
                raise ValueError("alarmId is required")

            now = _local_now_iso()

            # Load existing record
            row = conn.execute(
                "SELECT * FROM alarm_records WHERE alarm_id = ?",
                (resolved_alarm_id,),
            ).fetchone()
            existing = _row_to_dict(row) if row else {}

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

            if analysis_result is not None:
                merged["analysisResult"] = analysis_result
            elif existing.get("analysisResult"):
                merged["analysisResult"] = existing.get("analysisResult")

            # Upsert into DB
            db_values = {}
            for camel_key, col in _KEY_TO_COL.items():
                db_values[col] = str(merged.get(camel_key) or "")

            cols = ", ".join(db_values.keys())
            placeholders = ", ".join("?" for _ in db_values)
            updates = ", ".join(f"{c} = excluded.{c}" for c in db_values.keys() if c != "alarm_id")
            conn.execute(
                f"INSERT INTO alarm_records ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(alarm_id) DO UPDATE SET {updates}",
                list(db_values.values()),
            )
            conn.commit()
            return dict(merged)
        finally:
            conn.close()


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

    # Collect alarm IDs to check
    alarm_ids = []
    for item in items:
        if isinstance(item, dict):
            aid = _alarm_id_from_payload(item)
            if aid:
                alarm_ids.append(aid)

    if not alarm_ids:
        valid_items = [item for item in items if isinstance(item, dict)]
        payload["items"] = valid_items
        payload["total"] = len(valid_items)
        return payload

    # Batch query for hidden statuses
    db_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _ensure_migrated(db_path)
        conn = _open_db(db_path)
        try:
            placeholders = ", ".join("?" for _ in alarm_ids)
            rows = conn.execute(
                f"SELECT alarm_id, status FROM alarm_records "
                f"WHERE alarm_id IN ({placeholders})",
                alarm_ids,
            ).fetchall()
            hidden_ids = {
                row["alarm_id"]
                for row in rows
                if _coalesce_text(row["status"]) in PORTAL_REAL_ALARM_HIDDEN_STATUSES
            }
        finally:
            conn.close()

    visible_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        aid = _alarm_id_from_payload(item)
        if aid in hidden_ids:
            continue
        visible_items.append(item)

    payload["items"] = visible_items
    payload["total"] = len(visible_items)
    return payload


def reset_zombie_analyzing_records(
    *,
    path: str | Path | None = None,
) -> int:
    """Reset records stuck in 'analyzing' status back to allow re-processing.

    Should be called at startup to recover from unclean shutdowns where
    asyncio tasks were lost before completing analysis.
    Returns the number of records reset.
    """
    db_path = _resolve_registry_path(path)
    with _REGISTRY_LOCK:
        _ensure_migrated(db_path)
        conn = _open_db(db_path)
        try:
            now = _local_now_iso()
            cursor = conn.execute(
                "UPDATE alarm_records SET status = 'pending_retry', "
                "updated_at = ?, source = 'startup-zombie-reset' "
                "WHERE status = 'analyzing'",
                (now,),
            )
            count = cursor.rowcount
            conn.commit()
            return count
        finally:
            conn.close()
