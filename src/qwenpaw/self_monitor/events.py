# -*- coding: utf-8 -*-
"""Event bus — the discrete-signal half of self-monitoring (design D4).

Metrics answer "how much"; events answer "what happened":
``worker.restart``, ``llm.rate_limit_storm``, ``component.degraded``,
``governance.deny_timeout``, ``datasource.down``, ``resource.high``, …

Producers call :func:`emit_event` (synchronous, O(1), never raises).
Events are buffered in memory, deduplicated within a sliding window
(``dedup_key`` → merged ``count``) so an incident storm becomes one row
with a counter instead of thousands, and drained to SQLite by the
sampler's rollup loop.  When the buffer is full events are dropped and
accounted for — the monitor must never back-pressure the monitored
(design D8, fail-open).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Severity vocabulary (aligned with the events table CHECK-less column).
SEVERITIES = ("info", "warn", "error", "critical")

_MAX_PENDING = 1000
_DEDUP_WINDOW_SECONDS = 300.0


@dataclass
class Event:
    """One discrete monitoring signal."""

    ts: float
    type: str
    severity: str = "info"
    layer: str = ""
    source: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    message: str = ""
    dedup_key: str = ""
    count: int = 1


class EventBus:
    """In-memory buffer with window dedup; drained by the sampler."""

    def __init__(
        self,
        max_pending: int = _MAX_PENDING,
        dedup_window: float = _DEDUP_WINDOW_SECONDS,
    ) -> None:
        self._lock = threading.Lock()
        self._pending: list[Event] = []
        self._max_pending = max_pending
        self._dedup_window = dedup_window
        # dedup_key -> pending Event still eligible for merging
        self._recent: dict[str, Event] = {}
        self._dropped = 0

    def emit(
        self,
        type: str,
        *,  # noqa: A002 - mirrors the event field
        severity: str = "info",
        layer: str = "",
        source: str = "",
        message: str = "",
        labels: dict[str, str] | None = None,
        dedup_key: str = "",
        ts: float | None = None,
    ) -> None:
        """Record one event.  Never raises; drops when full."""
        try:
            now = ts if ts is not None else time.time()
            if severity not in SEVERITIES:
                severity = "info"
            key = dedup_key or f"{type}|{source}|{message[:80]}"
            with self._lock:
                merged = self._recent.get(key)
                if merged is not None and now - merged.ts <= self._dedup_window:
                    # Same signal inside the suppression window: merge.
                    merged.count += 1
                    merged.ts = now
                    return
                if len(self._pending) >= self._max_pending:
                    self._dropped += 1
                    return
                event = Event(
                    ts=now,
                    type=str(type),
                    severity=severity,
                    layer=layer,
                    source=source,
                    labels=dict(labels or {}),
                    message=message,
                    dedup_key=key,
                )
                self._pending.append(event)
                self._recent[key] = event
        except Exception:  # pragma: no cover - fail-open by contract
            logger.debug("self_monitor event emit failed", exc_info=True)

    def drain(self) -> tuple[list[Event], int]:
        """Return (pending events, dropped-since-last-drain) and reset.

        Once drained an event row is persisted; later duplicates within
        the window start a fresh row (documented trade-off — keeps the
        hot path lock-cheap and the store append-only).
        """
        with self._lock:
            events, self._pending = self._pending, []
            dropped, self._dropped = self._dropped, 0
            self._recent.clear()
            return events, dropped


_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-wide singleton ``EventBus``."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus


def emit_event(type: str, **kwargs) -> None:  # noqa: A002
    """Module-level convenience over ``get_event_bus().emit``."""
    get_event_bus().emit(type, **kwargs)


__all__ = ["Event", "EventBus", "SEVERITIES", "emit_event", "get_event_bus"]
