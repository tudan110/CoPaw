# -*- coding: utf-8 -*-
"""SQLite-backed storage for alarm analyst cards.

Cards were previously stored inside QwenPaw session-state JSON files.
This module keeps them in a dedicated SQLite database so that card data
survives session lifecycle changes, loads faster, and can be queried
independently.

DB location: ``~/.qwenpaw/extensions/portal_real_alarm/alarm_analyst_cards.db``
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qwenpaw.extensions.runtime_data_paths import (
    PORTAL_ALARM_ANALYST_CARDS_DB_PATH as DEFAULT_DB_PATH,
)

_LOCK = threading.Lock()

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS alarm_analyst_cards (
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    card_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, message_id)
)
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_card_session_id ON alarm_analyst_cards(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_card_chat_id ON alarm_analyst_cards(chat_id)",
]


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
    conn.commit()
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_card(
    chat_id: str,
    message_id: str,
    card: dict[str, Any],
    *,
    session_id: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Insert or replace a single card."""
    card_json = json.dumps(card, ensure_ascii=False)
    with _LOCK:
        conn = _open_db(db_path)
        try:
            conn.execute(
                """
                INSERT INTO alarm_analyst_cards
                    (chat_id, message_id, session_id, card_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    card_json = excluded.card_json,
                    session_id = CASE
                        WHEN excluded.session_id != '' THEN excluded.session_id
                        ELSE alarm_analyst_cards.session_id
                    END
                """,
                (chat_id, message_id, session_id, card_json, _now_iso()),
            )
            conn.commit()
        finally:
            conn.close()


def save_cards_bulk(
    records: dict[str, dict[str, dict]],
    *,
    session_id: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Batch-insert cards from the nested ``{chat_id: {message_id: card}}`` structure.

    Returns the number of rows upserted.
    """
    rows: list[tuple[str, str, str, str, str]] = []
    now = _now_iso()
    for cid, msgs in records.items():
        if not isinstance(msgs, dict):
            continue
        for mid, card in msgs.items():
            if not isinstance(card, dict):
                continue
            rows.append((cid, mid, session_id, json.dumps(card, ensure_ascii=False), now))

    if not rows:
        return 0

    with _LOCK:
        conn = _open_db(db_path)
        try:
            conn.executemany(
                """
                INSERT INTO alarm_analyst_cards
                    (chat_id, message_id, session_id, card_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    card_json = excluded.card_json,
                    session_id = CASE
                        WHEN excluded.session_id != '' THEN excluded.session_id
                        ELSE alarm_analyst_cards.session_id
                    END
                """,
                rows,
            )
            conn.commit()
            return len(rows)
        finally:
            conn.close()


def load_cards_for_chat(
    chat_id: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, dict]:
    """Return ``{message_id: card_dict}`` for a given *chat_id*."""
    with _LOCK:
        conn = _open_db(db_path)
        try:
            rows = conn.execute(
                "SELECT message_id, card_json FROM alarm_analyst_cards WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        finally:
            conn.close()

    result: dict[str, dict] = {}
    for row in rows:
        try:
            result[row["message_id"]] = json.loads(row["card_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def load_all_cards_for_session(
    session_id: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, dict[str, dict]]:
    """Return the full nested ``{chat_id: {message_id: card}}`` structure
    for every card belonging to *session_id*.
    """
    with _LOCK:
        conn = _open_db(db_path)
        try:
            rows = conn.execute(
                "SELECT chat_id, message_id, card_json FROM alarm_analyst_cards WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()

    result: dict[str, dict[str, dict]] = {}
    for row in rows:
        try:
            card = json.loads(row["card_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        result.setdefault(row["chat_id"], {})[row["message_id"]] = card
    return result
