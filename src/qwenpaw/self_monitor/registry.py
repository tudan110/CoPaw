# -*- coding: utf-8 -*-
"""In-process metric registry — the collection half of self-monitoring.

One ``MetricRegistry`` per worker process.  Instrumentation sites call
``get_registry().counter(name).inc(...)`` (O(1), thread-safe, never
raises to callers); a background rollup loop periodically calls
``snapshot()`` and persists the flattened samples to SQLite, which is
the aggregation point across workers (design doc D3/D7,
docs/superpowers/specs/2026-07-02-self-monitoring-design.md).

Metric names follow Prometheus conventions with a ``qwenpaw_`` prefix.
Layers: l1 (experience) / l2 (agent) / l3 (dependencies) / l4 (host).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Iterable, Mapping

logger = logging.getLogger(__name__)

LabelKey = tuple[tuple[str, str], ...]

# Default histogram buckets (seconds) for latency-style metrics.
DURATION_BUCKETS: tuple[float, ...] = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
)
# Buckets for small discrete counts (ReAct iterations and friends).
COUNT_BUCKETS: tuple[float, ...] = (
    1,
    2,
    3,
    5,
    8,
    13,
    21,
    34,
    55,
    100,
)


def _label_key(labels: Mapping[str, str] | None) -> LabelKey:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


@dataclass
class MetricSample:
    """One flattened sample as persisted to the ``metric_rollup`` table.

    Histograms are flattened into ``<name>_bucket`` (cumulative, with an
    ``le`` label), ``<name>_sum`` and ``<name>_count`` rows so a single
    numeric ``value`` column fits every metric kind.
    """

    name: str
    kind: str  # counter | gauge | histogram
    layer: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0


class _MetricBase:
    kind = ""

    def __init__(
        self, name: str, layer: str, help_text: str, lock: threading.Lock
    ) -> None:
        self.name = name
        self.layer = layer
        self.help = help_text
        self._lock = lock
        self._samples: dict[LabelKey, float] = {}

    def _samples_snapshot(self) -> list[MetricSample]:
        return [
            MetricSample(
                name=self.name,
                kind=self.kind,
                layer=self.layer,
                labels=dict(key),
                value=value,
            )
            for key, value in self._samples.items()
        ]


class Counter(_MetricBase):
    """Monotonic per-process counter.  Resets on worker restart — the
    consumers (PromQL ``rate()`` / ``counter_delta`` in the store) both
    tolerate counter resets by design."""

    kind = "counter"

    def inc(self, labels: Mapping[str, str] | None = None, n: float = 1.0) -> None:
        try:
            key = _label_key(labels)
            with self._lock:
                self._samples[key] = self._samples.get(key, 0.0) + n
        except Exception:  # pragma: no cover - must never break callers
            logger.debug("self_monitor counter inc failed", exc_info=True)


class Gauge(_MetricBase):
    """Point-in-time value (worker RSS, datasource up/down, …)."""

    kind = "gauge"

    def set(self, labels: Mapping[str, str] | None = None, value: float = 0.0) -> None:
        try:
            key = _label_key(labels)
            with self._lock:
                self._samples[key] = float(value)
        except Exception:  # pragma: no cover
            logger.debug("self_monitor gauge set failed", exc_info=True)

    def inc(self, labels: Mapping[str, str] | None = None, n: float = 1.0) -> None:
        try:
            key = _label_key(labels)
            with self._lock:
                self._samples[key] = self._samples.get(key, 0.0) + n
        except Exception:  # pragma: no cover
            logger.debug("self_monitor gauge inc failed", exc_info=True)


class Histogram:
    """Fixed-bucket histogram (Prometheus semantics).

    Stores per-label-set bucket counts plus sum/count; ``snapshot()``
    emits *cumulative* bucket values so the flattened rows are directly
    renderable in the Prometheus exposition format.
    """

    kind = "histogram"

    def __init__(
        self,
        name: str,
        layer: str,
        help_text: str,
        buckets: tuple[float, ...],
        lock: threading.Lock,
    ) -> None:
        self.name = name
        self.layer = layer
        self.help = help_text
        self.buckets = tuple(sorted(float(b) for b in buckets))
        self._lock = lock
        # key -> [bucket_counts..., sum, count]
        self._samples: dict[LabelKey, list[float]] = {}

    def observe(self, value: float, labels: Mapping[str, str] | None = None) -> None:
        try:
            value = float(value)
            key = _label_key(labels)
            with self._lock:
                state = self._samples.get(key)
                if state is None:
                    state = [0.0] * (len(self.buckets) + 2)
                    self._samples[key] = state
                for i, bound in enumerate(self.buckets):
                    if value <= bound:
                        state[i] += 1
                        break
                state[-2] += value  # sum
                state[-1] += 1  # count
        except Exception:  # pragma: no cover
            logger.debug("self_monitor histogram observe failed", exc_info=True)

    def _samples_snapshot(self) -> list[MetricSample]:
        out: list[MetricSample] = []
        for key, state in self._samples.items():
            base = dict(key)
            cumulative = 0.0
            for i, bound in enumerate(self.buckets):
                cumulative += state[i]
                out.append(
                    MetricSample(
                        name=f"{self.name}_bucket",
                        kind="histogram",
                        layer=self.layer,
                        labels={**base, "le": _format_bound(bound)},
                        value=cumulative,
                    )
                )
            out.append(
                MetricSample(
                    name=f"{self.name}_bucket",
                    kind="histogram",
                    layer=self.layer,
                    labels={**base, "le": "+Inf"},
                    value=state[-1],
                )
            )
            out.append(
                MetricSample(
                    name=f"{self.name}_sum",
                    kind="histogram",
                    layer=self.layer,
                    labels=base,
                    value=state[-2],
                )
            )
            out.append(
                MetricSample(
                    name=f"{self.name}_count",
                    kind="histogram",
                    layer=self.layer,
                    labels=base,
                    value=state[-1],
                )
            )
        return out


def _format_bound(bound: float) -> str:
    return str(int(bound)) if float(bound).is_integer() else repr(bound)


class MetricRegistry:
    """Process-wide registry.  ``counter()``/``gauge()``/``histogram()``
    are get-or-create; layer/help are taken from the first creation so
    later call sites may omit them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: dict[str, Counter | Gauge | Histogram] = {}

    def counter(self, name: str, layer: str = "", help_text: str = "") -> Counter:
        return self._get_or_create(Counter, name, layer, help_text)

    def gauge(self, name: str, layer: str = "", help_text: str = "") -> Gauge:
        return self._get_or_create(Gauge, name, layer, help_text)

    def histogram(
        self,
        name: str,
        layer: str = "",
        help_text: str = "",
        buckets: tuple[float, ...] = DURATION_BUCKETS,
    ) -> Histogram:
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = Histogram(name, layer, help_text, buckets, self._lock)
                self._metrics[name] = metric
        if not isinstance(metric, Histogram):  # pragma: no cover
            raise TypeError(f"metric {name!r} already registered as " f"{metric.kind}")
        return metric

    def _get_or_create(self, cls: type, name: str, layer: str, help_text: str):
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = cls(name, layer, help_text, self._lock)
                self._metrics[name] = metric
        if not isinstance(metric, cls):  # pragma: no cover
            raise TypeError(f"metric {name!r} already registered as " f"{metric.kind}")
        return metric

    def snapshot(self) -> list[MetricSample]:
        """Flatten every metric into rollup-ready samples."""
        with self._lock:
            metrics: Iterable = list(self._metrics.values())
        out: list[MetricSample] = []
        for metric in metrics:
            out.extend(metric._samples_snapshot())  # noqa: SLF001
        return out


_registry: MetricRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> MetricRegistry:
    """Return the process-wide singleton ``MetricRegistry``."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                registry = MetricRegistry()
                _declare_builtin_metrics(registry)
                _registry = registry
    return _registry


def _declare_builtin_metrics(reg: MetricRegistry) -> None:
    """Pre-declare the P0 metric catalogue (design doc §5.1) so that
    layer/help metadata is consistent regardless of which call site
    touches a metric first."""
    # L1 — experience
    reg.counter(
        "qwenpaw_chat_turns_total",
        "l1",
        "Agent chat turns by channel and terminal status",
    )
    reg.histogram(
        "qwenpaw_chat_turn_duration_seconds",
        "l1",
        "End-to-end duration of one agent turn",
        DURATION_BUCKETS,
    )
    # L2 — agent/application
    reg.histogram(
        "qwenpaw_agent_iterations",
        "l2",
        "ReAct iterations consumed per turn",
        COUNT_BUCKETS,
    )
    reg.counter(
        "qwenpaw_governance_decisions_total",
        "l2",
        "Tool-guard decisions by outcome " "(allow|ask|deny|timeout)",
    )
    # L3 — dependencies
    reg.counter(
        "qwenpaw_llm_requests_total",
        "l3",
        "LLM requests by terminal status (ok|429|error)",
    )
    reg.counter(
        "qwenpaw_llm_retries_total",
        "l3",
        "LLM retry attempts after a retryable failure",
    )
    reg.histogram(
        "qwenpaw_llm_request_duration_seconds",
        "l3",
        "Latency of a single LLM call",
        DURATION_BUCKETS,
    )
    reg.counter(
        "qwenpaw_degrade_events_total",
        "l3",
        "Any component falling back to a degraded/template path",
    )
    reg.counter(
        "qwenpaw_llm_tokens_total",
        "l3",
        "Token usage mirrored from the token_usage manager",
    )
    reg.counter(
        "qwenpaw_bigscreen_generation_total",
        "l3",
        "Big-screen generations by kind and degraded flag",
    )
    reg.gauge(
        "qwenpaw_datasource_up", "l3", "External datasource configured/reachable (1|0)"
    )
    reg.gauge(
        "qwenpaw_llm_limiter_paused",
        "l3",
        "Rate limiter currently in 429 cooldown (1|0)",
    )
    reg.gauge(
        "qwenpaw_llm_limiter_rate_limited",
        "l3",
        "Cumulative 429 hits seen by the rate limiter",
    )
    reg.gauge(
        "qwenpaw_llm_limiter_in_flight", "l3", "In-flight LLM calls under the limiter"
    )
    # L4 — host/process
    reg.gauge("qwenpaw_worker_up", "l4", "Worker process liveness (1)")
    reg.gauge(
        "qwenpaw_worker_heartbeat_timestamp",
        "l4",
        "Unix time of the worker's last rollup",
    )
    reg.gauge("qwenpaw_process_cpu_percent", "l4", "Process CPU percent (psutil)")
    reg.gauge(
        "qwenpaw_process_memory_rss_bytes", "l4", "Process resident memory (psutil)"
    )
    reg.gauge(
        "qwenpaw_disk_usage_percent",
        "l4",
        "Disk usage percent of the working-dir volume",
    )
    reg.gauge(
        "qwenpaw_sqlite_size_bytes", "l4", "Size of self-monitor SQLite databases"
    )
    reg.counter(
        "qwenpaw_log_errors_total", "l4", "ERROR/CRITICAL records on the qwenpaw logger"
    )
    # L1 — synthetic probes (P1 拨测)
    reg.gauge(
        "qwenpaw_probe_up",
        "l1",
        "Synthetic probe target reachable (1|0)",
    )
    reg.histogram(
        "qwenpaw_probe_duration_seconds",
        "l1",
        "Synthetic probe round-trip time",
        DURATION_BUCKETS,
    )
    # L3 — streaming first-token latency (slot request → first chunk)
    reg.histogram(
        "qwenpaw_llm_first_token_seconds",
        "l3",
        "From limiter slot request to first streamed chunk",
        DURATION_BUCKETS,
    )
    # alerting (P1) — currently firing alerts by severity
    reg.gauge(
        "qwenpaw_alerts_firing",
        "l4",
        "Alerts currently in firing state",
    )
    # self-monitoring of the monitor (fail-open accounting)
    reg.counter(
        "qwenpaw_self_monitor_events_dropped_total",
        "l4",
        "Events dropped because the in-memory queue was full",
    )
    reg.counter(
        "qwenpaw_self_monitor_rollup_failures_total",
        "l4",
        "Rollup flush attempts that raised",
    )


__all__ = [
    "COUNT_BUCKETS",
    "DURATION_BUCKETS",
    "Counter",
    "Gauge",
    "Histogram",
    "MetricRegistry",
    "MetricSample",
    "get_registry",
]
