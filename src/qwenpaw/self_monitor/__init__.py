# -*- coding: utf-8 -*-
"""Self-monitoring: the lens turned back on QwenPaw itself.

Layered vitals (L1 experience / L2 agent / L3 dependencies / L4 host),
an in-process metric registry rolled up to SQLite (built-in closed loop
+ Prometheus ``/metrics`` export from the same data), and an event bus
for discrete incident signals.

Design: docs/superpowers/specs/2026-07-02-self-monitoring-design.md

Instrumentation surface (single-line, fail-open):

    from qwenpaw.self_monitor import get_registry, emit_event
    get_registry().counter("qwenpaw_llm_requests_total").inc(
        {"status": "429"})
    emit_event("component.degraded", severity="error", layer="l3",
               source="ai_big_screen", message="fell back to template")
"""

from .events import Event, EventBus, emit_event, get_event_bus
from .registry import (
    Counter,
    Gauge,
    Histogram,
    MetricRegistry,
    MetricSample,
    get_registry,
)
from .sampler import (
    SELF_MONITOR_ENABLED,
    SelfMonitorService,
    get_self_monitor,
)
from .store import SelfMonitorStore, default_db_path

__all__ = [
    "SELF_MONITOR_ENABLED",
    "Counter",
    "Event",
    "EventBus",
    "Gauge",
    "Histogram",
    "MetricRegistry",
    "MetricSample",
    "SelfMonitorService",
    "SelfMonitorStore",
    "default_db_path",
    "emit_event",
    "get_event_bus",
    "get_registry",
    "get_self_monitor",
]
