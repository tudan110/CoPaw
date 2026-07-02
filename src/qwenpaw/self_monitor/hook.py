# -*- coding: utf-8 -*-
"""L1/L2 collection hooks — one PRE_EXECUTE / FINALLY pair per turn.

Mirrors the Langfuse hook pair: PRE_EXECUTE stamps a start time into
``ctx.extras``; FINALLY derives duration, terminal status and ReAct
iteration count and feeds the metric registry.  No main-loop code is
touched (design D2/D8) and both hooks are strictly fail-open.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..hooks.base import LifecycleHook
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase

logger = logging.getLogger(__name__)

_T0_KEY = "_qp_self_monitor_t0"


def _terminal_status(error: BaseException | None) -> str:
    if error is None:
        return "success"
    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)):
        return "cancelled"
    if "timeout" in type(error).__name__.lower():
        return "timeout"
    return "error"


class SelfMonitorHook(LifecycleHook):
    """Stamp the turn start time (after ContextVars=10 / Langfuse=12)."""

    phase = Phase.PRE_EXECUTE
    name = "self_monitor"
    priority = 14

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            from .sampler import SELF_MONITOR_ENABLED

            if SELF_MONITOR_ENABLED:
                ctx.extras[_T0_KEY] = time.monotonic()
        except Exception:  # pragma: no cover - fail-open
            logger.debug("self_monitor pre-execute hook failed", exc_info=True)
        return HookResult()


class SelfMonitorFinalizeHook(LifecycleHook):
    """Record turn metrics in FINALLY (after Langfuse cleanup=50)."""

    phase = Phase.FINALLY
    name = "self_monitor_finalize"
    priority = 55

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            t0 = ctx.extras.pop(_T0_KEY, None)
            if t0 is None:
                return HookResult()
            from .registry import get_registry

            duration = max(0.0, time.monotonic() - float(t0))
            status = _terminal_status(ctx.error)
            channel = getattr(ctx.request, "channel", None) or "unknown"
            registry = get_registry()
            registry.counter("qwenpaw_chat_turns_total").inc(
                {"channel": str(channel), "status": status}
            )
            registry.histogram("qwenpaw_chat_turn_duration_seconds").observe(
                duration, {"status": status}
            )
            iterations = _iterations_of(ctx)
            if iterations is not None:
                registry.histogram("qwenpaw_agent_iterations").observe(
                    float(iterations)
                )
        except Exception:  # pragma: no cover - fail-open
            logger.debug("self_monitor finalize hook failed", exc_info=True)
        return HookResult()


def _iterations_of(ctx: HookContext) -> int | None:
    """ReAct iterations consumed this turn, if the agent exposes them."""
    state = getattr(getattr(ctx, "agent", None), "state", None)
    cur_iter = getattr(state, "cur_iter", None)
    if isinstance(cur_iter, int) and cur_iter >= 0:
        return cur_iter + 1  # cur_iter is 0-based
    return None


__all__ = ["SelfMonitorFinalizeHook", "SelfMonitorHook"]
