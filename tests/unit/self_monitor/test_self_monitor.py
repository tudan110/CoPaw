# -*- coding: utf-8 -*-
"""Unit tests for the self-monitor spine (registry/events/store/api).

Design: docs/superpowers/specs/2026-07-02-self-monitoring-design.md
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.extensions.api import self_monitor_api
from qwenpaw.self_monitor.events import EventBus
from qwenpaw.self_monitor.prometheus import render_prometheus
from qwenpaw.self_monitor.registry import (
    COUNT_BUCKETS,
    MetricRegistry,
)
from qwenpaw.self_monitor.store import SelfMonitorStore

# ── registry ─────────────────────────────────────────────────────


def test_counter_accumulates_per_label_set():
    reg = MetricRegistry()
    counter = reg.counter("t_total", "l3", "test")
    counter.inc({"status": "ok"})
    counter.inc({"status": "ok"}, 2)
    counter.inc({"status": "429"})
    samples = {
        (s.labels.get("status"), s.value) for s in reg.snapshot() if s.name == "t_total"
    }
    assert samples == {("ok", 3.0), ("429", 1.0)}


def test_gauge_set_overwrites():
    reg = MetricRegistry()
    gauge = reg.gauge("t_up", "l4", "test")
    gauge.set({"worker": "w1"}, 1)
    gauge.set({"worker": "w1"}, 0)
    (sample,) = [s for s in reg.snapshot() if s.name == "t_up"]
    assert sample.value == 0.0


def test_histogram_flattens_to_cumulative_buckets():
    reg = MetricRegistry()
    hist = reg.histogram("t_iter", "l2", "test", COUNT_BUCKETS)
    for value in (1, 2, 2, 8, 200):  # 200 → only +Inf
        hist.observe(value)
    rows = {
        (s.name, s.labels.get("le")): s.value
        for s in reg.snapshot()
        if s.name.startswith("t_iter")
    }
    assert rows[("t_iter_bucket", "1")] == 1
    assert rows[("t_iter_bucket", "2")] == 3  # cumulative
    assert rows[("t_iter_bucket", "8")] == 4
    assert rows[("t_iter_bucket", "+Inf")] == 5
    assert rows[("t_iter_count", None)] == 5
    assert rows[("t_iter_sum", None)] == 213


def test_get_or_create_is_idempotent():
    reg = MetricRegistry()
    assert reg.counter("t_x", "l1", "h") is reg.counter("t_x")


# ── events ───────────────────────────────────────────────────────


def test_event_dedup_merges_within_window():
    bus = EventBus()
    for _ in range(5):
        bus.emit("llm.rate_limit_storm", severity="warn", dedup_key="k1")
    bus.emit("other", severity="info")
    events, dropped = bus.drain()
    assert dropped == 0
    by_type = {e.type: e for e in events}
    assert by_type["llm.rate_limit_storm"].count == 5
    assert by_type["other"].count == 1
    # window resets after drain — a new row starts
    bus.emit("llm.rate_limit_storm", dedup_key="k1")
    events, _ = bus.drain()
    assert len(events) == 1 and events[0].count == 1


def test_event_queue_full_drops_and_counts():
    bus = EventBus(max_pending=2)
    for i in range(4):
        bus.emit(f"t{i}")  # distinct dedup keys
    events, dropped = bus.drain()
    assert len(events) == 2 and dropped == 2


# ── store ────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path):
    return SelfMonitorStore(tmp_path / "sm.db")


def _seed(
    reg: MetricRegistry, store: SelfMonitorStore, ts: float, worker: str = "w1"
) -> None:
    store.write_rollup(ts, worker, reg.snapshot())


def test_counter_delta_uses_pre_window_baseline(store):
    reg = MetricRegistry()
    counter = reg.counter("t_total", "l3", "t")
    now = time.time()
    counter.inc({}, 3)
    _seed(reg, store, now - 30)
    counter.inc({}, 2)  # cumulative 5
    _seed(reg, store, now - 10)
    # whole window: series born inside → baseline 0 → +5
    assert store.counter_delta("t_total", since=now - 60) == 5.0
    # window opens between snapshots → first row is the baseline
    assert store.counter_delta("t_total", since=now - 20) == 2.0


def test_counter_delta_tolerates_worker_restart(store):
    now = time.time()
    reg1 = MetricRegistry()
    reg1.counter("t_total", "l3", "t").inc({}, 100)
    _seed(reg1, store, now - 40)
    # restart: counter resets to a smaller value
    reg2 = MetricRegistry()
    reg2.counter("t_total", "l3", "t").inc({}, 4)
    _seed(reg2, store, now - 5)
    assert store.counter_delta("t_total", since=now - 60) == 104.0


def test_counter_delta_sums_across_workers(store):
    now = time.time()
    for worker, n in (("w1", 2), ("w2", 3)):
        reg = MetricRegistry()
        reg.counter("t_total", "l3", "t").inc({}, n)
        _seed(reg, store, now - 10, worker)
    assert store.counter_delta("t_total", since=now - 60) == 5.0


def test_latest_samples_ages_out_stale_workers(store):
    now = time.time()
    reg = MetricRegistry()
    reg.gauge("t_up", "l4", "t").set({"worker": "w1"}, 1)
    _seed(reg, store, now - 3600, "w1")  # stale
    _seed(reg, store, now - 5, "w2")  # fresh
    workers = {r["worker_id"] for r in store.latest_samples(max_age_s=180)}
    assert workers == {"w2"}


def test_events_roundtrip_and_prune(store):
    now = time.time()
    from qwenpaw.self_monitor.events import Event

    store.write_events(
        [
            Event(ts=now - 8 * 86400, type="old", severity="info"),
            Event(ts=now, type="component.degraded", severity="error", count=3),
        ]
    )
    store.prune(retention_days=7)
    items = store.query_events()
    assert [e["type"] for e in items] == ["component.degraded"]
    assert store.event_counts(since=now - 60) == {"error": 3}


# ── prometheus rendering ─────────────────────────────────────────


def test_prometheus_render_labels_worker_and_escapes(store):
    reg = MetricRegistry()
    reg.counter("t_total", "l3", "t").inc({"m": 'a"b\\c'}, 1)
    _seed(reg, store, time.time() - 1, "w1")
    text = render_prometheus(store)
    assert "# TYPE t_total counter" in text
    assert r't_total{m="a\"b\\c",worker="w1"} 1' in text


# ── API ──────────────────────────────────────────────────────────


@pytest.fixture()
def client(store, monkeypatch):
    monkeypatch.setattr(self_monitor_api, "_get_store", lambda: store)
    app = FastAPI()
    app.include_router(self_monitor_api.router)
    app.include_router(self_monitor_api.metrics_router)
    return TestClient(app)


def _seed_overview(store):
    reg = MetricRegistry()
    reg.counter("qwenpaw_degrade_events_total", "l3", "t").inc(
        {"component": "ai_big_screen"}, 2
    )
    reg.counter("qwenpaw_chat_turns_total", "l1", "t").inc(
        {"channel": "portal", "status": "success"}, 49
    )
    reg.counter("qwenpaw_chat_turns_total", "l1", "t").inc(
        {"channel": "portal", "status": "error"}, 1
    )
    reg.gauge("qwenpaw_worker_up", "l4", "t").set({"worker": "w1"}, 1)
    reg.gauge("qwenpaw_datasource_up", "l3", "t").set({"source": "zgops"}, 0)
    store.write_rollup(time.time() - 10, "w1", reg.snapshot())


def test_overview_layers_and_kpis(client, store):
    _seed_overview(store)
    data = client.get("/api/portal/self-monitor/overview").json()
    assert data["kpis"]["degradeEvents"] == 2.0
    assert data["kpis"]["workersUp"] == 1
    assert data["kpis"]["chatSuccessRate"] == pytest.approx(0.98)
    l3 = next(l for l in data["layers"] if l["layer"] == "l3")
    assert l3["status"] in ("warn", "crit")
    assert l3["metrics"]["datasources"] == {"zgops": False}


def test_overview_unknown_when_empty(client):
    data = client.get("/api/portal/self-monitor/overview").json()
    assert data["state"] == "unknown"
    assert all(l["status"] == "unknown" for l in data["layers"])


def test_metrics_timeseries_groups_series(client, store):
    _seed_overview(store)
    data = client.get(
        "/api/portal/self-monitor/metrics",
        params={"name": "qwenpaw_chat_turns_total"},
    ).json()
    assert len(data["series"]) == 2
    assert all(s["points"] for s in data["series"])


def test_prometheus_endpoint_gated_by_env(client, store, monkeypatch):
    _seed_overview(store)
    monkeypatch.delenv("QWENPAW_METRICS_ENABLED", raising=False)
    assert client.get("/metrics").status_code == 404
    monkeypatch.setenv("QWENPAW_METRICS_ENABLED", "true")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "qwenpaw_degrade_events_total" in resp.text


def test_health_reports_workers(client, store):
    _seed_overview(store)
    data = client.get("/api/portal/self-monitor/health").json()
    assert data["workers"] == ["w1"]
    assert data["db"]["path"].endswith("sm.db")
