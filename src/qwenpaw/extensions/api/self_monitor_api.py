# -*- coding: utf-8 -*-
"""Self-monitor read APIs + Prometheus exposition (design §5.5/§5.7).

* ``/api/portal/self-monitor/*`` — JSON consumed by the portal console
  (overview / metrics timeseries / events / health).  Read-only; every
  answer is computed from the SQLite rollup so multi-worker deployments
  return one consistent view regardless of which worker serves the
  request.
* ``/metrics`` — Prometheus text for external scrapers (n9e/Grafana).
  Off by default; enable with ``QWENPAW_METRICS_ENABLED=true`` and keep
  it intranet-only or behind auth (design §8).
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...constant import EnvVarLoader
from ...self_monitor.prometheus import CONTENT_TYPE, render_prometheus
from ...self_monitor.sampler import (
    ROLLUP_INTERVAL_SECONDS,
    SELF_MONITOR_ENABLED,
)
from ...self_monitor.store import SelfMonitorStore

router = APIRouter(prefix="/api/portal/self-monitor", tags=["portal", "self-monitor"])
metrics_router = APIRouter(tags=["self-monitor"])

_WINDOW_SECONDS_DEFAULT = 3600
# A worker whose heartbeat is older than this is considered gone.
_FRESH_SECONDS = max(60.0, ROLLUP_INTERVAL_SECONDS * 4)


def _get_store() -> SelfMonitorStore:
    """Indirection point so tests can monkeypatch the store path."""
    return SelfMonitorStore()


# ── overview ─────────────────────────────────────────────────────


@router.get("/overview")
def self_monitor_overview(
    window_s: int = Query(default=_WINDOW_SECONDS_DEFAULT, ge=60, le=7 * 86400),
) -> dict:
    """Four-layer health + headline KPIs for the console."""
    store = _get_store()
    now = time.time()
    since = now - window_s

    degrade = store.counter_delta("qwenpaw_degrade_events_total", since=since)
    llm_429 = store.counter_delta(
        "qwenpaw_llm_requests_total", since=since, label_filter={"status": "429"}
    )
    llm_total = store.counter_delta("qwenpaw_llm_requests_total", since=since)
    retries = store.counter_delta("qwenpaw_llm_retries_total", since=since)
    chat_total = store.counter_delta("qwenpaw_chat_turns_total", since=since)
    chat_success = store.counter_delta(
        "qwenpaw_chat_turns_total", since=since, label_filter={"status": "success"}
    )
    gov_timeout = store.counter_delta(
        "qwenpaw_governance_decisions_total",
        since=since,
        label_filter={"decision": "timeout"},
    )
    gov_deny = store.counter_delta(
        "qwenpaw_governance_decisions_total",
        since=since,
        label_filter={"decision": "deny"},
    )
    log_errors = store.counter_delta("qwenpaw_log_errors_total", since=since)

    latest = store.latest_samples(max_age_s=_FRESH_SECONDS)
    workers = sorted(
        {
            row["worker_id"]
            for row in latest
            if row["name"] == "qwenpaw_worker_up" and row["value"] >= 1.0
        }
    )
    datasources = {
        row["labels"].get("source", ""): bool(row["value"] >= 1.0)
        for row in latest
        if row["name"] == "qwenpaw_datasource_up"
    }
    rss_by_worker = {
        row["worker_id"]: row["value"]
        for row in latest
        if row["name"] == "qwenpaw_process_memory_rss_bytes"
    }
    disk_rows = [
        row["value"] for row in latest if row["name"] == "qwenpaw_disk_usage_percent"
    ]
    disk_percent = max(disk_rows) if disk_rows else None

    chat_success_rate = chat_success / chat_total if chat_total > 0 else None
    has_data = bool(latest)

    l1 = _status(
        has_data and chat_total > 0,
        crit=(chat_success_rate is not None and chat_success_rate < 0.90),
        warn=(chat_success_rate is not None and chat_success_rate < 0.98),
    )
    l2 = _status(
        has_data,
        crit=False,
        warn=gov_timeout > 0,
    )
    l3 = _status(
        has_data,
        crit=degrade > 5,
        warn=(
            degrade > 0 or llm_429 > 20 or any(not up for up in datasources.values())
        ),
    )
    l4 = _status(
        has_data,
        crit=not workers,
        warn=(disk_percent is not None and disk_percent >= 90) or log_errors > 50,
    )
    order = {"ok": 0, "unknown": 1, "warn": 2, "crit": 3}
    state = max((l1, l2, l3, l4), key=lambda s: order[s])

    return {
        "generatedAt": int(now),
        "windowS": window_s,
        "enabled": SELF_MONITOR_ENABLED,
        "state": state,
        "layers": [
            {
                "layer": "l1",
                "status": l1,
                "metrics": {
                    "chatTurns": chat_total,
                    "chatSuccessRate": chat_success_rate,
                },
            },
            {
                "layer": "l2",
                "status": l2,
                "metrics": {
                    "governanceTimeouts": gov_timeout,
                    "governanceDenies": gov_deny,
                },
            },
            {
                "layer": "l3",
                "status": l3,
                "metrics": {
                    "degradeEvents": degrade,
                    "llm429": llm_429,
                    "llmRequests": llm_total,
                    "llmRetries": retries,
                    "datasources": datasources,
                },
            },
            {
                "layer": "l4",
                "status": l4,
                "metrics": {
                    "workersUp": len(workers),
                    "workers": workers,
                    "rssBytesByWorker": rss_by_worker,
                    "diskUsagePercent": disk_percent,
                    "logErrors": log_errors,
                },
            },
        ],
        "kpis": {
            "degradeEvents": degrade,
            "llm429": llm_429,
            "workersUp": len(workers),
            "chatSuccessRate": chat_success_rate,
        },
        "eventCounts": store.event_counts(since=now - 86400),
    }


def _status(has_data: bool, *, crit: bool, warn: bool) -> str:
    if not has_data:
        return "unknown"
    if crit:
        return "crit"
    if warn:
        return "warn"
    return "ok"


# ── timeseries ───────────────────────────────────────────────────


@router.get("/metrics")
def self_monitor_metrics(
    name: str = Query(min_length=1, max_length=200),
    since: float | None = Query(default=None, ge=0),
    until: float | None = Query(default=None, ge=0),
    limit: int = Query(default=5000, ge=1, le=20000),
) -> dict:
    """Raw rollup series for one metric, grouped by (labels, worker)."""
    store = _get_store()
    since_ts = since if since is not None else time.time() - 3600
    rows = store.query_metrics(name, since=since_ts, until=until, limit=limit)
    series: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (json.dumps(row["labels"], sort_keys=True), row["worker_id"])
        entry = series.get(key)
        if entry is None:
            entry = {
                "name": name,
                "labels": row["labels"],
                "worker": row["worker_id"],
                "kind": row["kind"],
                "layer": row["layer"],
                "points": [],
            }
            series[key] = entry
        entry["points"].append([row["ts"], row["value"]])
    return {"name": name, "series": list(series.values())}


# ── events ───────────────────────────────────────────────────────


@router.get("/events")
def self_monitor_events(
    type: str | None = Query(default=None, max_length=100),  # noqa: A002
    severity: str | None = Query(default=None, max_length=20),
    since: float | None = Query(default=None, ge=0),
    until: float | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    store = _get_store()
    items = store.query_events(
        type=type, severity=severity, since=since, until=until, limit=limit
    )
    return {"items": items}


# ── health ───────────────────────────────────────────────────────


@router.get("/health")
def self_monitor_health() -> dict:
    """Liveness+ view: does not depend on anything heavier than the
    rollup DB, so it stays answerable while the rest degrades."""
    store = _get_store()
    latest = store.latest_samples(max_age_s=_FRESH_SECONDS)
    workers = sorted(
        {
            row["worker_id"]
            for row in latest
            if row["name"] == "qwenpaw_worker_up" and row["value"] >= 1.0
        }
    )
    return {
        "status": "ok" if (not SELF_MONITOR_ENABLED or workers) else "stale",
        "enabled": SELF_MONITOR_ENABLED,
        "workers": workers,
        "rollupIntervalS": ROLLUP_INTERVAL_SECONDS,
        "db": {
            "path": str(store.path),
            "sizeBytes": store.db_size_bytes(),
        },
    }


# ── Prometheus exposition ────────────────────────────────────────


@metrics_router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    """Prometheus text exposition; 404 unless explicitly enabled."""
    if not EnvVarLoader.get_bool("QWENPAW_METRICS_ENABLED", False):
        raise HTTPException(
            status_code=404,
            detail="metrics export disabled " "(set QWENPAW_METRICS_ENABLED=true)",
        )
    body = render_prometheus(_get_store())
    return PlainTextResponse(content=body, media_type=CONTENT_TYPE)


__all__ = ["metrics_router", "router"]
