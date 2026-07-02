# -*- coding: utf-8 -*-
"""SQLite persistence for self-monitoring (design D3/D7).

``~/.qwenpaw/self_monitor.db`` (WAL) holds two tables:

* ``metric_rollup`` — periodic snapshots of every worker's in-process
  registry, tagged with ``worker_id``.  This is simultaneously the
  history for the built-in console *and* the cross-worker aggregation
  point for the ``/metrics`` Prometheus exposition.
* ``events`` — drained discrete signals from the event bus.

Counters are cumulative per worker; window queries use
:meth:`SelfMonitorStore.counter_delta`, which tolerates counter resets
(worker restarts) the same way PromQL ``increase()`` does.

Write paths swallow every failure (monitoring must never break the
monitored — see ai_big_screen/telemetry.py for the precedent); read
paths return empty results on error.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..constant import WORKING_DIR
from .events import Event
from .registry import MetricSample

logger = logging.getLogger(__name__)

DB_FILENAME = "self_monitor.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_rollup (
    ts INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    layer TEXT NOT NULL DEFAULT '',
    labels_json TEXT NOT NULL DEFAULT '{}',
    value REAL NOT NULL DEFAULT 0,
    worker_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_metric_rollup_name_ts
    ON metric_rollup(name, ts);
CREATE INDEX IF NOT EXISTS idx_metric_rollup_ts ON metric_rollup(ts);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    layer TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    labels_json TEXT NOT NULL DEFAULT '{}',
    message TEXT NOT NULL DEFAULT '',
    dedup_key TEXT NOT NULL DEFAULT '',
    count INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, ts);
CREATE INDEX IF NOT EXISTS idx_events_severity_ts
    ON events(severity, ts);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    layer TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'warn',
    state TEXT NOT NULL DEFAULT 'firing',
    value REAL NOT NULL DEFAULT 0,
    threshold REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    started_at INTEGER NOT NULL,
    resolved_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts(state, started_at);
"""


def default_db_path() -> Path:
    return WORKING_DIR / DB_FILENAME


class SelfMonitorStore:
    """Thin per-operation-connection SQLite wrapper (WAL mode)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.executescript(_SCHEMA)
        return connection

    # ── writes (swallow failures) ────────────────────────────────

    def write_rollup(
        self, ts: float, worker_id: str, samples: Iterable[MetricSample]
    ) -> bool:
        try:
            rows = [
                (
                    int(ts),
                    s.name,
                    s.kind,
                    s.layer,
                    json.dumps(s.labels, ensure_ascii=False, sort_keys=True),
                    float(s.value),
                    worker_id,
                )
                for s in samples
            ]
            if not rows:
                return True
            with self._connect() as connection:
                connection.executemany(
                    "INSERT INTO metric_rollup "
                    "(ts, name, kind, layer, labels_json, value, worker_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            return True
        except Exception:
            logger.warning("self_monitor rollup write failed", exc_info=True)
            return False

    def write_events(self, events: Iterable[Event]) -> bool:
        try:
            rows = [
                (
                    int(e.ts),
                    e.type,
                    e.severity,
                    e.layer,
                    e.source,
                    json.dumps(e.labels, ensure_ascii=False, sort_keys=True),
                    e.message,
                    e.dedup_key,
                    int(e.count),
                )
                for e in events
            ]
            if not rows:
                return True
            with self._connect() as connection:
                connection.executemany(
                    "INSERT INTO events (ts, type, severity, layer, "
                    "source, labels_json, message, dedup_key, count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            return True
        except Exception:
            logger.warning("self_monitor events write failed", exc_info=True)
            return False

    # ── reads (return empty on failure) ──────────────────────────

    def query_metrics(
        self, name: str, *, since: float, until: float | None = None, limit: int = 5000
    ) -> list[dict[str, Any]]:
        """Raw rollup rows for one metric name, oldest first."""
        try:
            until_ts = int(until if until is not None else time.time())
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT ts, name, kind, layer, labels_json, value,"
                    " worker_id FROM metric_rollup"
                    " WHERE name = ? AND ts >= ? AND ts <= ?"
                    " ORDER BY ts ASC LIMIT ?",
                    (name, int(since), until_ts, max(1, limit)),
                ).fetchall()
        except Exception:
            logger.warning("self_monitor metrics read failed", exc_info=True)
            return []
        return [_rollup_row_to_dict(row) for row in rows]

    def latest_samples(
        self,
        *,
        max_age_s: float = 180.0,
    ) -> list[dict[str, Any]]:
        """Latest row per (name, labels, worker) newer than the cutoff.

        This is the working set for both the Prometheus exposition and
        the overview: stale workers age out after ``max_age_s``.
        """
        try:
            cutoff = int(time.time() - max_age_s)
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT ts, name, kind, layer, labels_json, value,"
                    " worker_id FROM metric_rollup WHERE ts >= ?"
                    " AND ts = (SELECT MAX(m2.ts) FROM metric_rollup m2"
                    "  WHERE m2.name = metric_rollup.name"
                    "  AND m2.labels_json = metric_rollup.labels_json"
                    "  AND m2.worker_id = metric_rollup.worker_id)"
                    " ORDER BY name ASC",
                    (cutoff,),
                ).fetchall()
        except Exception:
            logger.warning("self_monitor latest read failed", exc_info=True)
            return []
        return [_rollup_row_to_dict(row) for row in rows]

    def counter_delta(
        self,
        name: str,
        *,
        since: float,
        until: float | None = None,
        label_filter: Mapping[str, str] | None = None,
    ) -> float:
        """Windowed increase of a cumulative counter across workers.

        PromQL ``increase()`` semantics: each (worker, labels) series is
        walked from a baseline — the last sample *before* the window, or
        0 for a series born inside it (per-process counters start at 0)
        — summing positive deltas and treating drops as counter resets
        (worker restarts).
        """
        rows = self.query_metrics(name, since=since, until=until)
        baselines = self._baselines(name, before=since)
        totals: dict[tuple[str, str], float] = {}
        prev: dict[tuple[str, str], float] = {}
        for row in rows:
            if label_filter and any(
                row["labels"].get(k) != v for k, v in label_filter.items()
            ):
                continue
            key = (row["worker_id"], json.dumps(row["labels"], sort_keys=True))
            if key not in prev:
                prev[key] = baselines.get(key, 0.0)
                totals[key] = 0.0
            value = row["value"]
            if value >= prev[key]:
                totals[key] += value - prev[key]
            else:  # counter reset (worker restart)
                totals[key] += value
            prev[key] = value
        return sum(totals.values())

    def _baselines(
        self,
        name: str,
        *,
        before: float,
    ) -> dict[tuple[str, str], float]:
        """Latest pre-window value per (worker, labels) series."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT worker_id, labels_json, value, MAX(ts)"
                    " FROM metric_rollup WHERE name = ? AND ts < ?"
                    " GROUP BY worker_id, labels_json",
                    (name, int(before)),
                ).fetchall()
        except Exception:
            logger.warning("self_monitor baseline read failed", exc_info=True)
            return {}
        out: dict[tuple[str, str], float] = {}
        for worker_id, labels_json, value, _ts in rows:
            labels = _loads_labels(labels_json)
            out[(worker_id, json.dumps(labels, sort_keys=True))] = float(value)
        return out

    def gauge_sum(
        self,
        name: str,
        *,
        max_age_s: float = 180.0,
        label_filter: Mapping[str, str] | None = None,
    ) -> float | None:
        """Sum of the freshest gauge value per series, or None if no
        fresh sample exists."""
        rows = [
            r for r in self.latest_samples(max_age_s=max_age_s) if r["name"] == name
        ]
        if label_filter:
            rows = [
                r
                for r in rows
                if all(r["labels"].get(k) == v for k, v in label_filter.items())
            ]
        if not rows:
            return None
        return sum(r["value"] for r in rows)

    def query_events(
        self,
        *,
        type: str | None = None,  # noqa: A002
        severity: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            clauses, params = ["1=1"], []
            if type:
                clauses.append("type = ?")
                params.append(type)
            if severity:
                clauses.append("severity = ?")
                params.append(severity)
            if since is not None:
                clauses.append("ts >= ?")
                params.append(int(since))
            if until is not None:
                clauses.append("ts <= ?")
                params.append(int(until))
            params.append(max(1, min(int(limit), 1000)))
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT ts, type, severity, layer, source,"
                    " labels_json, message, dedup_key, count FROM events"
                    f" WHERE {' AND '.join(clauses)}"
                    " ORDER BY ts DESC, id DESC LIMIT ?",
                    params,
                ).fetchall()
        except Exception:
            logger.warning("self_monitor events read failed", exc_info=True)
            return []
        return [
            {
                "ts": row[0],
                "type": row[1],
                "severity": row[2],
                "layer": row[3],
                "source": row[4],
                "labels": _loads_labels(row[5]),
                "message": row[6],
                "dedupKey": row[7],
                "count": row[8],
            }
            for row in rows
        ]

    def event_counts(self, *, since: float) -> dict[str, int]:
        """Per-severity event counts (dedup-merged counts summed)."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT severity, SUM(count) FROM events"
                    " WHERE ts >= ? GROUP BY severity",
                    (int(since),),
                ).fetchall()
        except Exception:
            logger.warning("self_monitor event counts failed", exc_info=True)
            return {}
        return {str(row[0]): int(row[1] or 0) for row in rows}

    # ── maintenance ──────────────────────────────────────────────

    def prune(self, retention_days: float) -> None:
        try:
            cutoff = int(time.time() - retention_days * 86400)
            with self._connect() as connection:
                connection.execute("DELETE FROM metric_rollup WHERE ts < ?", (cutoff,))
                connection.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        except Exception:
            logger.warning("self_monitor prune failed", exc_info=True)

    def db_size_bytes(self) -> int:
        try:
            return self.path.stat().st_size if self.path.exists() else 0
        except OSError:
            return 0

    # ── gauge/counter aggregation helpers (alerts, costs, topology) ─

    def gauge_agg(
        self,
        name: str,
        *,
        agg: str = "sum",
        max_age_s: float = 180.0,
        label_filter: Mapping[str, str] | None = None,
    ) -> float | None:
        """Aggregate the freshest gauge value per series (sum|min|max),
        or None when no fresh sample exists (rules stay dormant)."""
        rows = [
            r for r in self.latest_samples(max_age_s=max_age_s) if r["name"] == name
        ]
        if label_filter:
            rows = [
                r
                for r in rows
                if all(r["labels"].get(k) == v for k, v in label_filter.items())
            ]
        if not rows:
            return None
        values = [r["value"] for r in rows]
        if agg == "min":
            return min(values)
        if agg == "max":
            return max(values)
        return sum(values)

    def counter_deltas(
        self,
        name: str,
        *,
        since: float,
        until: float | None = None,
        per_worker: bool = False,
    ) -> list[dict[str, Any]]:
        """Windowed increase per label set (optionally per worker),
        with the same reset-aware baseline walk as counter_delta."""
        rows = self.query_metrics(name, since=since, until=until)
        baselines = self._baselines(name, before=since)
        totals: dict[tuple[str, str], float] = {}
        prev: dict[tuple[str, str], float] = {}
        labels_of: dict[tuple[str, str], dict[str, str]] = {}
        for row in rows:
            series_key = (
                row["worker_id"],
                json.dumps(row["labels"], sort_keys=True),
            )
            if series_key not in prev:
                prev[series_key] = baselines.get(series_key, 0.0)
                totals[series_key] = 0.0
                labels_of[series_key] = row["labels"]
            value = row["value"]
            if value >= prev[series_key]:
                totals[series_key] += value - prev[series_key]
            else:  # counter reset
                totals[series_key] += value
            prev[series_key] = value
        if per_worker:
            return [
                {
                    "labels": labels_of[key],
                    "worker_id": key[0],
                    "delta": delta,
                }
                for key, delta in totals.items()
            ]
        merged: dict[str, dict[str, Any]] = {}
        for (worker_id, labels_json), delta in totals.items():
            del worker_id
            entry = merged.setdefault(
                labels_json,
                {"labels": _loads_labels(labels_json), "delta": 0.0},
            )
            entry["delta"] += delta
        return list(merged.values())

    # ── alerts ───────────────────────────────────────────────────

    def insert_alert(
        self,
        *,
        rule_id: str,
        name: str,
        layer: str,
        severity: str,
        value: float,
        threshold: float,
        message: str,
        started_at: float,
    ) -> int | None:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO alerts (rule_id, name, layer, severity,"
                    " state, value, threshold, message, started_at)"
                    " VALUES (?, ?, ?, ?, 'firing', ?, ?, ?, ?)",
                    (
                        rule_id,
                        name,
                        layer,
                        severity,
                        float(value),
                        float(threshold),
                        message,
                        int(started_at),
                    ),
                )
                return int(cursor.lastrowid)
        except Exception:
            logger.warning("self_monitor alert insert failed", exc_info=True)
            return None

    def touch_alert(self, alert_id: int | None, value: float) -> None:
        if alert_id is None:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE alerts SET value = ? WHERE id = ?",
                    (float(value), int(alert_id)),
                )
        except Exception:
            logger.debug("self_monitor alert touch failed", exc_info=True)

    def resolve_alert(
        self, alert_id: int | None, *, resolved_at: float, value: float
    ) -> bool:
        """Mark firing→resolved; returns True only for the transition
        that actually changed the row (multi-worker notify guard)."""
        if alert_id is None:
            return False
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE alerts SET state = 'resolved',"
                    " resolved_at = ?, value = ?"
                    " WHERE id = ? AND state = 'firing'",
                    (int(resolved_at), float(value), int(alert_id)),
                )
                return cursor.rowcount > 0
        except Exception:
            logger.warning("self_monitor alert resolve failed", exc_info=True)
            return False

    def active_alerts(self) -> list[dict[str, Any]]:
        return self._alert_rows("WHERE state = 'firing'", ())

    def recent_alerts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._alert_rows(
            "ORDER BY started_at DESC, id DESC LIMIT ?", (max(1, limit),)
        )

    def _alert_rows(self, clause: str, params: tuple) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT id, rule_id, name, layer, severity, state,"
                    " value, threshold, message, started_at, resolved_at"
                    f" FROM alerts {clause}",
                    params,
                ).fetchall()
        except Exception:
            logger.warning("self_monitor alerts read failed", exc_info=True)
            return []
        return [
            {
                "id": row[0],
                "ruleId": row[1],
                "name": row[2],
                "layer": row[3],
                "severity": row[4],
                "state": row[5],
                "value": row[6],
                "threshold": row[7],
                "message": row[8],
                "startedAt": row[9],
                "resolvedAt": row[10],
            }
            for row in rows
        ]


def _loads_labels(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _rollup_row_to_dict(row: tuple) -> dict[str, Any]:
    return {
        "ts": row[0],
        "name": row[1],
        "kind": row[2],
        "layer": row[3],
        "labels": _loads_labels(row[4]),
        "value": row[5],
        "worker_id": row[6],
    }


__all__ = ["DB_FILENAME", "SelfMonitorStore", "default_db_path"]
