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

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...constant import EnvVarLoader
from ...self_monitor.costs import cost_summary, day_start
from ...self_monitor.diagnose import diagnose as run_diagnose
from ...self_monitor.events import emit_event
from ...self_monitor.prometheus import CONTENT_TYPE, render_prometheus
from ...self_monitor.sampler import (
    ROLLUP_INTERVAL_SECONDS,
    SELF_MONITOR_ENABLED,
)
from ...self_monitor.store import SelfMonitorStore
from ...self_monitor.topology import build_topology

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
    ds_up = {
        row["labels"].get("source", ""): bool(row["value"] >= 1.0)
        for row in latest
        if row["name"] == "qwenpaw_datasource_up"
    }
    ds_configured = {
        row["labels"].get("source", ""): bool(row["value"] >= 1.0)
        for row in latest
        if row["name"] == "qwenpaw_datasource_configured"
    }
    # three honest states per source: configured?  probed-reachable?
    # (up is None until the first real probe lands — never faked)
    datasources = {
        source: {
            "configured": ds_configured.get(source, source in ds_up),
            "up": ds_up.get(source),
        }
        for source in sorted(set(ds_up) | set(ds_configured))
        if source
    }
    probes = {
        row["labels"].get("target", ""): bool(row["value"] >= 1.0)
        for row in latest
        if row["name"] == "qwenpaw_probe_up"
    }
    active_alerts = store.active_alerts()
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
        has_data and (chat_total > 0 or bool(probes)),
        crit=(chat_success_rate is not None and chat_success_rate < 0.90)
        or (bool(probes) and not any(probes.values())),
        warn=(chat_success_rate is not None and chat_success_rate < 0.98)
        or any(not up for up in probes.values()),
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
            degrade > 0
            or llm_429 > 20
            or any(
                entry["configured"] and entry["up"] is False
                for entry in datasources.values()
            )
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
                    "probes": probes,
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
        "alertsFiring": len(active_alerts),
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


# ── alerts (P1) ──────────────────────────────────────────────────


@router.get("/alerts")
def self_monitor_alerts(
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    """Firing alerts + recent history from the rule engine."""
    store = _get_store()
    return {
        "active": store.active_alerts(),
        "recent": store.recent_alerts(limit=limit),
    }


# ── topology (P2) ────────────────────────────────────────────────


@router.get("/topology")
def self_monitor_topology(
    window_s: int = Query(default=3600, ge=300, le=7 * 86400),
) -> dict:
    """Runtime dependency graph derived from the rollup labels."""
    return build_topology(_get_store(), window_s=window_s)


# ── cost (P2) ────────────────────────────────────────────────────


@router.get("/cost")
def self_monitor_cost(
    window_s: int | None = Query(default=None, ge=300, le=31 * 86400),
) -> dict:
    """LLM cost over the window (default: since local midnight)."""
    now = time.time()
    since = now - window_s if window_s else day_start(now)
    summary = cost_summary(_get_store(), since=since)
    summary["since"] = int(since)
    summary["generatedAt"] = int(now)
    return summary


# ── diagnosis (P2) ───────────────────────────────────────────────


@router.post("/diagnose")
async def self_monitor_diagnose(
    payload: dict = Body(default_factory=dict),
) -> dict:
    """Root-cause verdict: LLM when configured, rule-based otherwise."""
    try:
        window_s = float(payload.get("windowS") or 3600)
    except (TypeError, ValueError):
        window_s = 3600.0
    window_s = max(300.0, min(window_s, 7 * 86400.0))
    return await run_diagnose(window_s=window_s, store=_get_store())


# ── frontend beacon (P1 白屏/资源异常上报) ───────────────────────

_BEACON_TYPES = {"whitescreen", "chunk_error", "frontend_error"}


@router.post("/beacon")
def self_monitor_beacon(payload: dict = Body(default_factory=dict)) -> dict:
    """Tiny unauthenticated sink for frontend watchdog reports.

    Type-whitelisted and length-capped; the event bus dedup window
    keeps repeat reports from flooding the events table.
    """
    beacon_type = str(payload.get("type") or "frontend_error")
    if beacon_type not in _BEACON_TYPES:
        beacon_type = "frontend_error"
    message = str(payload.get("message") or "")[:300]
    source = str(payload.get("source") or "portal")[:80]
    emit_event(
        f"portal.{beacon_type}",
        severity="warn",
        layer="l1",
        source=source,
        message=message or beacon_type,
        dedup_key=f"beacon|{beacon_type}|{source}",
    )
    return {"accepted": True}


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
