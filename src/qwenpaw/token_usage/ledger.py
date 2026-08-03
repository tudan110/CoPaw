# -*- coding: utf-8 -*-
"""Multi-process-safe durable storage for token usage."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .buffer import _UsageEvent

logger = logging.getLogger(__name__)

_LEGACY_IMPORT_MARKER = "legacy_json_import_v1"


class TokenUsageLedger:
    """A SQLite ledger shared by all application worker processes."""

    def __init__(self, path: Path, legacy_json_path: Path) -> None:
        self.path = path
        self.legacy_json_path = legacy_json_path
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.path), timeout=10, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def initialize(self) -> None:
        """Create the ledger and import the legacy JSON exactly once."""
        if self._initialized:
            return
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_usage_ledger (
                    usage_date TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    call_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (usage_date, provider_id, model_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_usage_ledger_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            migrated = conn.execute(
                "SELECT 1 FROM token_usage_ledger_meta WHERE key = ?",
                (_LEGACY_IMPORT_MARKER,),
            ).fetchone()
            if not migrated:
                self._import_legacy_json(conn)
                conn.execute(
                    "INSERT INTO token_usage_ledger_meta (key, value) "
                    "VALUES (?, ?)",
                    (_LEGACY_IMPORT_MARKER, "complete"),
                )
            conn.commit()
            self._initialized = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _import_legacy_json(self, conn: sqlite3.Connection) -> None:
        if not self.legacy_json_path.exists():
            return
        try:
            raw = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("token_usage: legacy import skipped: %s", exc)
            return
        if not isinstance(raw, dict):
            return
        rows: list[tuple[str, str, str, int, int, int]] = []
        for usage_date, models in raw.items():
            if not isinstance(models, dict):
                continue
            for composite, entry in models.items():
                if not isinstance(entry, dict):
                    continue
                provider = str(entry.get("provider_id") or "")
                model = str(entry.get("model_name") or composite)
                rows.append(
                    (
                        str(usage_date),
                        provider,
                        model,
                        int(entry.get("prompt_tokens") or 0),
                        int(entry.get("completion_tokens") or 0),
                        int(entry.get("call_count") or 0),
                    )
                )
        self._upsert_rows(conn, rows)

    @staticmethod
    def _upsert_rows(
        conn: sqlite3.Connection,
        rows: list[tuple[str, str, str, int, int, int]],
    ) -> None:
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO token_usage_ledger (
                usage_date, provider_id, model_name,
                prompt_tokens, completion_tokens, call_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(usage_date, provider_id, model_name) DO UPDATE SET
                prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens
                    + excluded.completion_tokens,
                call_count = call_count + excluded.call_count
            """,
            rows,
        )

    def record_many(self, events: list[_UsageEvent]) -> None:
        """Atomically add worker usage without replacing other rows."""
        if not events:
            return
        self.initialize()
        totals: dict[tuple[str, str, str], list[int]] = {}
        for event in events:
            key = (event.date_str, event.provider_id, event.model_name)
            row = totals.setdefault(key, [0, 0, 0])
            row[0] += event.prompt_tokens
            row[1] += event.completion_tokens
            row[2] += 1
        rows = [(*key, *values) for key, values in totals.items()]
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._upsert_rows(conn, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def export_data(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Return a fresh, JSON-compatible snapshot of the shared ledger."""
        self.initialize()
        conn = self._connect()
        try:
            result: dict[str, dict[str, dict[str, Any]]] = {}
            for row in conn.execute(
                """
                SELECT usage_date, provider_id, model_name,
                       prompt_tokens, completion_tokens, call_count
                FROM token_usage_ledger
                ORDER BY usage_date, provider_id, model_name
                """
            ):
                provider = str(row["provider_id"])
                model = str(row["model_name"])
                key = f"{provider}:{model}" if provider else model
                result.setdefault(str(row["usage_date"]), {})[key] = {
                    "provider_id": provider,
                    "model_name": model,
                    "prompt_tokens": int(row["prompt_tokens"]),
                    "completion_tokens": int(row["completion_tokens"]),
                    "call_count": int(row["call_count"]),
                }
            return result
        finally:
            conn.close()
