# -*- coding: utf-8 -*-
"""Background service: L4 sampling, pull-taps and the rollup loop.

Started from the app lifespan (mirrors ``TokenUsageManager.start``).
Every ``QWENPAW_SELF_MONITOR_ROLLUP_INTERVAL`` seconds the loop:

1. samples host/process resources via psutil (L4),
2. pulls gauge-style state from the LLM rate limiters and the big-screen
   datasource checkers (L3),
3. snapshots the in-process ``MetricRegistry`` into the SQLite rollup
   (tagged with this worker's id — the cross-worker aggregation point),
4. drains the event bus into the ``events`` table.

Everything is best-effort: a failing tick increments
``qwenpaw_self_monitor_rollup_failures_total`` and the loop keeps going
(design D8 — the monitor must never take the monitored down with it).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time

from ..constant import WORKING_DIR, EnvVarLoader
from .events import emit_event, get_event_bus
from .registry import get_registry
from .store import SelfMonitorStore

logger = logging.getLogger(__name__)

SELF_MONITOR_ENABLED = EnvVarLoader.get_bool("QWENPAW_SELF_MONITOR_ENABLED", True)
ROLLUP_INTERVAL_SECONDS = EnvVarLoader.get_float(
    "QWENPAW_SELF_MONITOR_ROLLUP_INTERVAL", 15.0, min_value=1.0, max_value=3600.0
)
RETENTION_DAYS = EnvVarLoader.get_float(
    "QWENPAW_SELF_MONITOR_RETENTION_DAYS", 7.0, min_value=0.25, max_value=365.0
)
_DISK_HIGH_PERCENT = 90.0
_PRUNE_INTERVAL_SECONDS = 3600.0

# Datasources probed via the big-screen connection checkers (L3).
_DATASOURCES = ("inoe", "n9e", "zgops", "order")


class _LogErrorCounterHandler(logging.Handler):
    """Counts ERROR/CRITICAL records on the qwenpaw namespace logger."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            if record.levelno >= logging.ERROR:
                level = "critical" if record.levelno >= logging.CRITICAL else "error"
                get_registry().counter("qwenpaw_log_errors_total").inc({"level": level})
        except Exception:  # pragma: no cover - never recurse into logging
            pass


class SelfMonitorService:
    """Owns the rollup/prune loops for this worker process."""

    def __init__(
        self, store: SelfMonitorStore | None = None, worker_id: str | None = None
    ) -> None:
        self.store = store or SelfMonitorStore()
        self.worker_id = worker_id or _default_worker_id()
        self._rollup_task: asyncio.Task | None = None
        self._prune_task: asyncio.Task | None = None
        self._probe_task: asyncio.Task | None = None
        self._process = None  # lazy psutil.Process
        # P1: alert engine + probes ride on this service's loops.
        from .alerts import AlertEngine

        self.alert_engine = AlertEngine(self.store)

    def set_notifier(self, notifier) -> None:
        """Wire the channel push callable (async text -> None)."""
        self.alert_engine.set_notifier(notifier)

    # ── lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        if not SELF_MONITOR_ENABLED:
            logger.info("self_monitor disabled via env; not starting")
            return
        if self._rollup_task is not None:
            return
        _install_log_handler()
        self._rollup_task = asyncio.create_task(
            self._rollup_loop(), name="self-monitor-rollup"
        )
        self._prune_task = asyncio.create_task(
            self._prune_loop(), name="self-monitor-prune"
        )
        from .probes import PROBES_ENABLED

        if PROBES_ENABLED:
            self._probe_task = asyncio.create_task(
                self._probe_loop(), name="self-monitor-probes"
            )
        logger.info(
            "self_monitor started (worker=%s interval=%.0fs db=%s)",
            self.worker_id,
            ROLLUP_INTERVAL_SECONDS,
            self.store.path,
        )

    async def stop(self) -> None:
        for task in (self._rollup_task, self._prune_task, self._probe_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._rollup_task = None
        self._prune_task = None
        self._probe_task = None
        # Final flush so shutdown-adjacent samples/events are not lost.
        self._flush_once()

    # ── loops ────────────────────────────────────────────────────

    async def _rollup_loop(self) -> None:
        while True:
            try:
                self._sample_l4()
                self._pull_limiters()
                self._pull_datasources()
                self._flush_once()
                # Rules read the freshly-flushed rollup, so every worker
                # evaluates the same cross-worker truth (double-firing is
                # prevented by the recovered active-alert map).
                await self.alert_engine.evaluate()
            except asyncio.CancelledError:
                raise
            except Exception:
                get_registry().counter(
                    "qwenpaw_self_monitor_rollup_failures_total"
                ).inc()
                logger.warning("self_monitor rollup tick failed", exc_info=True)
            await asyncio.sleep(ROLLUP_INTERVAL_SECONDS)

    async def _prune_loop(self) -> None:
        while True:
            try:
                self.store.prune(RETENTION_DAYS)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("self_monitor prune tick failed", exc_info=True)
            await asyncio.sleep(_PRUNE_INTERVAL_SECONDS)

    async def _probe_loop(self) -> None:
        from .probes import PROBE_INTERVAL_SECONDS, ProbeRunner

        runner = ProbeRunner()
        # Let the app finish binding its port before the first pass.
        await asyncio.sleep(min(10.0, PROBE_INTERVAL_SECONDS))
        while True:
            try:
                await runner.run_once()
                await self._probe_datasources()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("self_monitor probe tick failed", exc_info=True)
            await asyncio.sleep(PROBE_INTERVAL_SECONDS)

    def _flush_once(self) -> None:
        now = time.time()
        registry = get_registry()
        registry.gauge("qwenpaw_worker_heartbeat_timestamp").set(
            {"worker": self.worker_id}, now
        )
        registry.gauge("qwenpaw_worker_up").set({"worker": self.worker_id}, 1.0)
        if not self.store.write_rollup(now, self.worker_id, registry.snapshot()):
            registry.counter("qwenpaw_self_monitor_rollup_failures_total").inc()
        events, dropped = get_event_bus().drain()
        if dropped:
            registry.counter("qwenpaw_self_monitor_events_dropped_total").inc(n=dropped)
        if events:
            self.store.write_events(events)

    # ── collectors ───────────────────────────────────────────────

    def _sample_l4(self) -> None:
        registry = get_registry()
        try:
            import psutil

            if self._process is None:
                self._process = psutil.Process()
            worker = {"worker": self.worker_id}
            registry.gauge("qwenpaw_process_cpu_percent").set(
                worker, self._process.cpu_percent(interval=None)
            )
            registry.gauge("qwenpaw_process_memory_rss_bytes").set(
                worker, float(self._process.memory_info().rss)
            )
            usage = psutil.disk_usage(str(WORKING_DIR))
            registry.gauge("qwenpaw_disk_usage_percent").set(
                {"path": "working"}, float(usage.percent)
            )
            if usage.percent >= _DISK_HIGH_PERCENT:
                emit_event(
                    "resource.high",
                    severity="warn",
                    layer="l4",
                    source=self.worker_id,
                    message=(
                        f"working-dir volume at {usage.percent:.0f}%"
                        f" (threshold {_DISK_HIGH_PERCENT:.0f}%)"
                    ),
                    dedup_key="resource.high|disk|working",
                )
        except Exception:
            logger.debug("self_monitor psutil sampling failed", exc_info=True)
        registry.gauge("qwenpaw_sqlite_size_bytes").set(
            {"db": "self_monitor"}, float(self.store.db_size_bytes())
        )

    def _pull_limiters(self) -> None:
        """Gauge-style state from the per-model LLM rate limiters."""
        try:
            from ..providers import rate_limiter as rl

            registry = get_registry()
            for key, limiter in list(rl._limiters.items()):  # noqa: SLF001
                stats = limiter.stats()
                labels = {"limiter": key or "default"}
                registry.gauge("qwenpaw_llm_limiter_paused").set(
                    labels, 1.0 if stats.get("is_paused") else 0.0
                )
                registry.gauge("qwenpaw_llm_limiter_rate_limited").set(
                    labels, float(stats.get("total_rate_limited") or 0)
                )
                registry.gauge("qwenpaw_llm_limiter_in_flight").set(
                    labels, float(stats.get("current_in_flight") or 0)
                )
        except Exception:
            logger.debug("self_monitor limiter pull failed", exc_info=True)

    def _pull_datasources(self) -> None:
        """Configuration status only (`qwenpaw_datasource_configured`).

        Whether the source is actually REACHABLE is probed for real by
        `_probe_datasources` on the probe cadence — configuration
        presence must never masquerade as liveness (that was the
        "fake data" smell: n9e showed ok merely because its env vars
        existed)."""
        try:
            from ..extensions.ai_big_screen.connection_status import (
                connection_status,
            )
        except Exception:
            return
        registry = get_registry()
        for source in _DATASOURCES:
            try:
                status = connection_status(source)
                configured = bool(status.get("configured"))
                registry.gauge("qwenpaw_datasource_configured").set(
                    {"source": source}, 1.0 if configured else 0.0
                )
            except Exception:
                logger.debug(
                    "self_monitor datasource pull failed: %s", source, exc_info=True
                )

    async def _probe_datasources(self) -> None:
        """Real reachability probes for the configured datasources.

        GET the configured base URL: any HTTP response < 500 counts as
        reachable (4xx just means we knocked without credentials);
        connect errors / timeouts / 5xx mean down. Unconfigured sources
        get no `qwenpaw_datasource_up` sample at all — absence of data
        is reported as absence, not as red."""
        env_of = {
            # keep in sync with extensions.ai_big_screen.connection_status
            "inoe": "INOE_API_BASE_URL",
            "n9e": "N9E_API_BASE_URL",
            "zgops": "ZGOPS_BASE_URL",
            "order": "ORDER_API_BASE_URL",
        }
        registry = get_registry()
        try:
            import os

            import httpx

            configured_bases = {}
            for source, env_name in env_of.items():
                base = str(os.environ.get(env_name) or "").strip()
                if source == "order" and not base:
                    # order falls back to the INOE gateway when it has no
                    # dedicated base — mirror connection_status semantics
                    # so "configured" order never sits at 探测中 forever.
                    base = str(os.environ.get("INOE_API_BASE_URL") or "").strip()
                latest_conf = registry.gauge("qwenpaw_datasource_configured").current(
                    {"source": source}
                )
                if base and (latest_conf is None or latest_conf >= 1.0):
                    configured_bases[source] = base
            if not configured_bases:
                return
            async with httpx.AsyncClient(follow_redirects=True) as client:
                for source, base in configured_bases.items():
                    up, reason = False, ""
                    try:
                        response = await client.get(base, timeout=4.0)
                        up = response.status_code < 500
                        if not up:
                            reason = f"HTTP {response.status_code}"
                    except Exception as exc:
                        reason = type(exc).__name__
                    registry.gauge("qwenpaw_datasource_up").set(
                        {"source": source}, 1.0 if up else 0.0
                    )
                    if not up:
                        emit_event(
                            "datasource.down",
                            severity="warn",
                            layer="l3",
                            source=source,
                            message=f"{source} 探测不可达: {reason}",
                            dedup_key=f"datasource.down|{source}",
                        )
        except Exception:  # pragma: no cover - probes are fail-open
            logger.debug("self_monitor datasource probe failed", exc_info=True)


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


_log_handler_installed = False


def _install_log_handler() -> None:
    """Attach the ERROR counter to the qwenpaw namespace logger once."""
    global _log_handler_installed
    if _log_handler_installed:
        return
    try:
        from ..utils.logging import LOG_NAMESPACE

        logging.getLogger(LOG_NAMESPACE).addHandler(
            _LogErrorCounterHandler(level=logging.ERROR)
        )
        _log_handler_installed = True
    except Exception:  # pragma: no cover
        logger.debug("self_monitor log handler install failed", exc_info=True)


_service: SelfMonitorService | None = None


def get_self_monitor() -> SelfMonitorService:
    """Return the process-wide singleton service (not yet started)."""
    global _service
    if _service is None:
        _service = SelfMonitorService()
    return _service


__all__ = [
    "RETENTION_DAYS",
    "ROLLUP_INTERVAL_SECONDS",
    "SELF_MONITOR_ENABLED",
    "SelfMonitorService",
    "get_self_monitor",
]
