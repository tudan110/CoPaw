# -*- coding: utf-8 -*-
"""Dependency topology (design P2, UModel 简化版).

Derives the runtime graph 智观AI 核心 → workers → models plus
core → datasources entirely from the rollup — no separate discovery:
who talks to what (and how healthily) is already encoded in the metric
labels the taps produce.

Statuses: model edges degrade by 429/error ratio, datasource nodes by
the configured/up gauge, workers by heartbeat freshness.
"""

from __future__ import annotations

import time
from typing import Any

from .store import SelfMonitorStore

CORE_ID = "core"


def build_topology(
    store: SelfMonitorStore, *, window_s: float = 3600.0
) -> dict[str, Any]:
    now = time.time()
    latest = store.latest_samples()
    nodes: list[dict[str, Any]] = [
        {
            "id": CORE_ID,
            "type": "core",
            "label": "智观AI",
            "status": "ok",
        }
    ]
    edges: list[dict[str, Any]] = []

    workers = sorted(
        {
            row["worker_id"]
            for row in latest
            if row["name"] == "qwenpaw_worker_up" and row["value"] >= 1.0
        }
    )
    for worker in workers:
        nodes.append(
            {
                "id": f"worker:{worker}",
                "type": "worker",
                "label": worker.split(":")[-1],
                "title": worker,
                "status": "ok",
            }
        )
        edges.append({"source": CORE_ID, "target": f"worker:{worker}", "value": 1})

    # model edges: per-worker request increases, split ok vs 429/error
    request_rows = store.counter_deltas(
        "qwenpaw_llm_requests_total",
        since=now - window_s,
        per_worker=True,
    )
    model_totals: dict[str, dict[str, float]] = {}
    edge_totals: dict[tuple[str, str], float] = {}
    for row in request_rows:
        model = str(row["labels"].get("model") or "unknown")
        status = str(row["labels"].get("status") or "ok")
        worker = str(row.get("worker_id") or "")
        stats = model_totals.setdefault(model, {"ok": 0.0, "bad": 0.0})
        stats["ok" if status == "ok" else "bad"] += row["delta"]
        if worker in workers:
            key = (f"worker:{worker}", f"model:{model}")
            edge_totals[key] = edge_totals.get(key, 0.0) + row["delta"]

    for model, stats in sorted(model_totals.items()):
        total = stats["ok"] + stats["bad"]
        if total <= 0:
            continue
        ratio = stats["bad"] / total
        status = "crit" if ratio > 0.2 else "warn" if ratio > 0 else "ok"
        nodes.append(
            {
                "id": f"model:{model}",
                "type": "model",
                "label": model,
                "status": status,
                "requests": int(total),
                "errorRatio": round(ratio, 3),
            }
        )
    for (source, target), value in sorted(edge_totals.items()):
        if value > 0:
            edges.append({"source": source, "target": target, "value": int(value)})

    for row in latest:
        if row["name"] != "qwenpaw_datasource_up":
            continue
        source_id = str(row["labels"].get("source") or "")
        if not source_id:
            continue
        up = row["value"] >= 1.0
        nodes.append(
            {
                "id": f"ds:{source_id}",
                "type": "datasource",
                "label": source_id,
                "status": "ok" if up else "crit",
            }
        )
        edges.append({"source": CORE_ID, "target": f"ds:{source_id}", "value": 1})

    return {
        "generatedAt": int(now),
        "windowS": window_s,
        "nodes": _dedup_nodes(nodes),
        "edges": edges,
    }


def _dedup_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for node in nodes:
        seen.setdefault(str(node["id"]), node)
    return list(seen.values())


__all__ = ["build_topology"]
