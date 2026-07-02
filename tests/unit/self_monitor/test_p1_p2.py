# -*- coding: utf-8 -*-
"""P1 (alerts/probes/beacon) + P2 (cost/topology/diagnose) unit tests."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.extensions.api import self_monitor_api
from qwenpaw.self_monitor.alerts import AlertEngine, AlertRule, load_rules
from qwenpaw.self_monitor.costs import cost_summary
from qwenpaw.self_monitor.diagnose import (
    gather_snapshot,
    rule_based_diagnosis,
)
from qwenpaw.self_monitor.probes import load_probes
from qwenpaw.self_monitor.registry import MetricRegistry
from qwenpaw.self_monitor.store import SelfMonitorStore
from qwenpaw.self_monitor.topology import build_topology


@pytest.fixture()
def store(tmp_path):
    return SelfMonitorStore(tmp_path / "sm.db")


def _seed_incident(store, now=None):
    """degrade + 429 storm + one healthy worker, two snapshots."""
    now = now or time.time()
    reg = MetricRegistry()
    reg.counter("qwenpaw_degrade_events_total", "l3", "t").inc(
        {"component": "ai_big_screen"}, 3
    )
    reg.counter("qwenpaw_llm_requests_total", "l3", "t").inc(
        {"model": "ctyun:glm", "status": "429"}, 30
    )
    reg.counter("qwenpaw_llm_requests_total", "l3", "t").inc(
        {"model": "ctyun:glm", "status": "ok"}, 100
    )
    reg.gauge("qwenpaw_worker_up", "l4", "t").set({"worker": "w1"}, 1)
    reg.gauge("qwenpaw_datasource_up", "l3", "t").set({"source": "inoe"}, 1)
    store.write_rollup(now - 30, "w1", reg.snapshot())
    store.write_rollup(now - 5, "w1", reg.snapshot())
    return now


# ── alerts ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_fires_and_notifies(store):
    now = _seed_incident(store)
    notes = []

    async def notifier(text):
        notes.append(text)

    engine = AlertEngine(store, notifier=notifier)
    await engine.evaluate(now)
    active_ids = {a["ruleId"] for a in store.active_alerts()}
    assert {"degrade-events", "llm-429-storm"} <= active_ids
    assert any("智观AI 自监控" in n for n in notes)


@pytest.mark.asyncio
async def test_alert_resolves_once_condition_clears(store):
    now = _seed_incident(store)
    engine = AlertEngine(store)
    await engine.evaluate(now)
    assert store.active_alerts()
    # window slides past the incident; only the healthy gauge remains
    reg = MetricRegistry()
    reg.gauge("qwenpaw_worker_up", "l4", "t").set({"worker": "w1"}, 1)
    store.write_rollup(now + 400, "w1", reg.snapshot())
    await engine.evaluate(now + 401)
    assert not [
        a
        for a in store.active_alerts()
        if a["ruleId"] in ("degrade-events", "llm-429-storm")
    ]


@pytest.mark.asyncio
async def test_alert_adopts_existing_row_instead_of_double_firing(store):
    now = _seed_incident(store)
    first = AlertEngine(store)
    await first.evaluate(now)
    count_after_first = len(store.active_alerts())
    second = AlertEngine(store)  # another worker, fresh state
    await second.evaluate(now + 1)
    assert len(store.active_alerts()) == count_after_first


@pytest.mark.asyncio
async def test_alert_for_duration_defers_firing(store):
    now = time.time()
    reg = MetricRegistry()
    reg.gauge("qwenpaw_disk_usage_percent", "l4", "t").set({"path": "working"}, 95)
    store.write_rollup(now - 5, "w1", reg.snapshot())
    rule = AlertRule(
        id="disk-test",
        name="disk",
        layer="l4",
        severity="warn",
        kind="gauge_min",
        metric="qwenpaw_disk_usage_percent",
        op=">=",
        threshold=90,
        for_s=60,
    )
    engine = AlertEngine(store, rules=[rule])
    await engine.evaluate(now)  # breach starts, not yet firing
    assert not store.active_alerts()
    await engine.evaluate(now + 61)  # breach persisted past for_s
    assert [a["ruleId"] for a in store.active_alerts()] == ["disk-test"]


def test_rules_config_override(tmp_path):
    config = tmp_path / "rules.json"
    config.write_text(
        '{"disable": ["cost-budget"], "rules": [{"id": "custom",'
        ' "metric": "qwenpaw_log_errors_total", "threshold": 5}]}',
        encoding="utf-8",
    )
    rules = {r.id for r in load_rules(config)}
    assert "custom" in rules and "cost-budget" not in rules
    assert "degrade-events" in rules  # builtins survive


# ── cost ─────────────────────────────────────────────────────────


def test_cost_summary_prices_and_unpriced(store):
    now = time.time()
    reg = MetricRegistry()
    tokens = reg.counter("qwenpaw_llm_tokens_total", "l3", "t")
    tokens.inc({"provider": "ctyun", "model": "glm", "kind": "prompt"}, 100000)
    tokens.inc({"provider": "ctyun", "model": "glm", "kind": "completion"}, 20000)
    tokens.inc({"provider": "x", "model": "mystery", "kind": "prompt"}, 5000)
    store.write_rollup(now - 5, "w1", reg.snapshot())
    summary = cost_summary(
        store,
        since=now - 60,
        config={
            "currency": "CNY",
            "budgetDaily": 50,
            "prices": {"ctyun:*": {"promptPer1k": 0.01, "completionPer1k": 0.03}},
        },
    )
    assert summary["total"] == pytest.approx(100 * 0.01 + 20 * 0.03)
    assert summary["unpricedModels"] == ["x:mystery"]
    assert summary["budgetDaily"] == 50


def test_cost_summary_unconfigured_is_honest(store):
    summary = cost_summary(store, since=time.time() - 60, config={})
    assert summary["total"] is None and summary["configured"] is False


# ── topology ─────────────────────────────────────────────────────


def test_topology_derives_nodes_and_edges(store):
    _seed_incident(store)
    topo = build_topology(store)
    types = {n["type"] for n in topo["nodes"]}
    assert {"core", "worker", "model", "datasource"} <= types
    model = next(n for n in topo["nodes"] if n["type"] == "model")
    assert model["status"] in ("warn", "crit")  # 429s present
    assert any(
        e["source"].startswith("worker:") and e["target"].startswith("model:")
        for e in topo["edges"]
    )


# ── diagnose (rule-based fallback) ───────────────────────────────


def test_diagnosis_blames_rate_limit_when_degrade_and_429(store):
    _seed_incident(store)
    verdict = rule_based_diagnosis(gather_snapshot(store))
    assert "限流" in verdict["rootCause"]
    assert verdict["confidence"] == "high"


def test_diagnosis_healthy_when_quiet(store):
    now = time.time()
    reg = MetricRegistry()
    reg.gauge("qwenpaw_worker_up", "l4", "t").set({"worker": "w1"}, 1)
    store.write_rollup(now - 5, "w1", reg.snapshot())
    verdict = rule_based_diagnosis(gather_snapshot(store))
    assert verdict["summary"] == "系统健康"


# ── probes loader ────────────────────────────────────────────────


def test_probe_config_extend_and_disable(tmp_path):
    config = tmp_path / "probes.json"
    config.write_text(
        '{"disable": ["portal-index"], "probes": [{"id": "chat-smoke",'
        ' "path": "/api/chat/smoke", "method": "POST", "timeoutS": 30}]}',
        encoding="utf-8",
    )
    probes = {p.id: p for p in load_probes("http://127.0.0.1:1", path=config)}
    assert "portal-index" not in probes
    assert probes["chat-smoke"].url == "http://127.0.0.1:1/api/chat/smoke"
    assert probes["chat-smoke"].method == "POST"


# ── API endpoints ────────────────────────────────────────────────


@pytest.fixture()
def client(store, monkeypatch):
    monkeypatch.setattr(self_monitor_api, "_get_store", lambda: store)
    app = FastAPI()
    app.include_router(self_monitor_api.router)
    return TestClient(app)


def test_alerts_endpoint(client, store):
    store.insert_alert(
        rule_id="r1",
        name="n",
        layer="l3",
        severity="warn",
        value=1,
        threshold=0,
        message="m",
        started_at=time.time(),
    )
    data = client.get("/api/portal/self-monitor/alerts").json()
    assert data["active"][0]["ruleId"] == "r1"


def test_topology_endpoint(client, store):
    _seed_incident(store)
    data = client.get("/api/portal/self-monitor/topology").json()
    assert data["nodes"] and data["edges"]


def test_cost_endpoint(client):
    data = client.get("/api/portal/self-monitor/cost").json()
    assert "total" in data and "configured" in data


def test_beacon_endpoint_whitelists_and_records(client, store, monkeypatch):
    from qwenpaw.self_monitor import events as events_mod

    bus = events_mod.EventBus()
    monkeypatch.setattr(events_mod, "_bus", bus)
    resp = client.post(
        "/api/portal/self-monitor/beacon",
        json={"type": "chunk_error", "message": "boom", "source": "portal:/x"},
    )
    assert resp.json()["accepted"] is True
    resp = client.post(
        "/api/portal/self-monitor/beacon",
        json={"type": "evil-type", "message": "m"},
    )
    assert resp.status_code == 200
    drained, _ = bus.drain()
    types = {e.type for e in drained}
    assert types == {"portal.chunk_error", "portal.frontend_error"}


def test_diagnose_endpoint_falls_back_without_llm(client, store):
    _seed_incident(store)
    data = client.post(
        "/api/portal/self-monitor/diagnose", json={"windowS": 3600}
    ).json()
    assert data["engine"] in ("rule-based", "llm")
    assert data["rootCause"]


# ── big-screen self: capability ─────────────────────────────────


def test_self_capability_and_connection(store, monkeypatch):
    import qwenpaw.self_monitor.store as store_mod
    from qwenpaw.extensions.ai_big_screen.capabilities.descriptors import (
        FETCHERS,
        fetch_self_monitor_overview,
    )
    from qwenpaw.extensions.ai_big_screen.connection_status import (
        connection_status,
    )

    _seed_incident(store)
    original = store_mod.SelfMonitorStore
    monkeypatch.setattr(
        store_mod,
        "SelfMonitorStore",
        lambda *a, **k: store if not a and not k else original(*a, **k),
    )
    result = fetch_self_monitor_overview({"windowS": 3600})
    assert result["sourceStatus"] == "live"
    assert len(result["rows"]) == 4
    assert result["metrics"]["降级事件"] == 3
    assert "self-monitor-overview" in FETCHERS
    status = connection_status("self")
    assert status["configured"] is True
    assert status["label"] == "智观AI 自监控"
