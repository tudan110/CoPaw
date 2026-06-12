# -*- coding: utf-8 -*-
"""Generation telemetry (M2): make "智能" measurable.

Every draft/refresh/patch records one event row (stage timings, LLM
attempts, degraded flag, per-capability statuses, component types,
total duration). ``summarize`` aggregates the recent window into the
operational quality signals: success rate, degraded rate, capability
failure rates, average duration. Recording must never break the
generation path — every write failure is swallowed (logged).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from qwenpaw.extensions.ai_big_screen import store

_LOGGER = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS generation_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 0,
    degraded INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
"""


def _connect(path: str | Path | None) -> sqlite3.Connection:
    connection = store.connect(path)
    connection.executescript(_SCHEMA)
    return connection


def record_generation(
    event: Mapping[str, Any],
    *,
    path: str | Path | None = None,
) -> None:
    """Persist one generation event; swallows every failure."""
    try:
        payload = dict(event)
        payload.setdefault("createdAt", store.now_iso())
        with _connect(path) as connection:
            connection.execute(
                """
                INSERT INTO generation_metrics (
                    kind, created_at, success, degraded, duration_ms, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(payload.get("kind") or ""),
                    str(payload.get("createdAt") or ""),
                    1 if payload.get("success") else 0,
                    1 if payload.get("degraded") else 0,
                    int(payload.get("durationMs") or 0),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )
    except Exception:  # telemetry must never break generation
        _LOGGER.warning("big-screen telemetry write failed", exc_info=True)


def recent_events(
    *,
    limit: int = 100,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    try:
        with _connect(path) as connection:
            rows = connection.execute(
                """
                SELECT payload FROM generation_metrics
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
    except Exception:
        _LOGGER.warning("big-screen telemetry read failed", exc_info=True)
        return []
    events: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed = json.loads(row[0])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def summarize(
    *,
    limit: int = 100,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Aggregate the most recent ``limit`` events into quality signals."""
    events = recent_events(limit=limit, path=path)
    total = len(events)
    if total == 0:
        return {
            "total": 0,
            "successRate": 0.0,
            "degradedRate": 0.0,
            "avgDurationMs": 0.0,
            "capabilityFailureRates": {},
            "kinds": {},
        }
    successes = sum(1 for event in events if event.get("success"))
    degraded = sum(1 for event in events if event.get("degraded"))
    durations = [int(event.get("durationMs") or 0) for event in events]

    capability_totals: dict[str, int] = {}
    capability_failures: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for event in events:
        kind = str(event.get("kind") or "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1
        statuses = event.get("capabilityStatuses")
        if not isinstance(statuses, dict):
            continue
        for capability_id, status in statuses.items():
            key = str(capability_id)
            capability_totals[key] = capability_totals.get(key, 0) + 1
            if str(status) == "failed":
                capability_failures[key] = capability_failures.get(key, 0) + 1

    return {
        "total": total,
        "successRate": successes / total,
        "degradedRate": degraded / total,
        "avgDurationMs": sum(durations) / total,
        "capabilityFailureRates": {
            capability_id: capability_failures.get(capability_id, 0) / count
            for capability_id, count in capability_totals.items()
        },
        "kinds": kinds,
    }
