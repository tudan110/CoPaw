# -*- coding: utf-8 -*-
"""可追溯中心埋点安装 (traceability instrumentation install).

Runtime 2.0(上游 PR #5078)重构后，老的 ``app/runner/runner.py`` 与
``agents/tool_guard_mixin.py`` 被删除，写在这两个类里的可追溯埋点随之
失效。本模块在**不入侵 qwenpaw 核心代码**的前提下把埋点挂回新架构——
做法与 :mod:`qwenpaw.extensions.security` 一致：仅在 ``app/_app.py`` 启动
时调用一次 :func:`install_traceability`，内部用 ``setattr`` 包裹核心方法。

三处包裹（均幂等、各自 try/except、失败只记日志绝不阻断启动）：

* ``QwenPawAgent._acting`` —— 复刻 ``tool_call`` 事件（工具名 / 入参 /
  成败 / 耗时）。
* ``HookRegistry.run`` —— 在 ``PRE_DISPATCH`` 发 ``user_message``、在
  ``ON_ERROR`` 发 ``error`` / ``cancelled``。这本是上游指定的扩展点，但
  内置 hook 列表在 ``lifespan`` 里被硬赋值覆盖、且本安装在 import 期先于
  ``lifespan`` 执行，故改用方法包裹以规避时序问题。
* ``AgentExecutor.run`` —— 累积助手最终文本后发 ``agent_reply``
  （``QwenPawAgent.memory`` 在新架构是墓碑 ``None``，只能在流式层捕获）。

已知降级：``skill_trigger`` 落在核心 slash 分发
(``_skill_fallback_handler``)，包裹已注册命令引用风险高，暂不复刻——
``/<skill>`` 输入仍由 ``user_message`` 记录，时间线不丢这步；工具 guard
严重级在新 ``GuardedFunctionTool`` 中与 ``_acting`` 解耦取不到，故
``tool_call`` 暂不带 guard 字段。
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["install_traceability"]

# 取消 / 中断时写入时间线的终结标记文案。
_CANCELLED_MSG = "任务被取消或中断，本次运行未产出最终回复。"

# Marker attribute used to make every patch idempotent — repeated
# ``install_traceability()`` calls (e.g. across test imports) are no-ops.
_PATCH_MARK = "_qp_trace_patched"


async def _emit(
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None,
    *,
    agent_id: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    index_extra: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget trace emit. Never propagates errors to the caller."""
    if not session_id:
        return
    try:
        from qwenpaw.extensions.traceability import trace_store

        await trace_store.record_event(
            session_id,
            event_type,
            payload,
            agent_id=agent_id or None,
            user_id=user_id or None,
            channel=channel or None,
            index_extra=index_extra,
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug("trace emit failed (%s)", event_type, exc_info=True)


def install_traceability() -> None:
    """Install all traceability instrumentation. Never raises."""
    try:
        _install_tool_trace()
    except Exception:  # pragma: no cover - defensive
        logger.exception("traceability: tool-trace install failed")

    try:
        _install_lifecycle_trace()
    except Exception:  # pragma: no cover - defensive
        logger.exception("traceability: lifecycle-trace install failed")

    try:
        _install_reply_trace()
    except Exception:  # pragma: no cover - defensive
        logger.exception("traceability: reply-trace install failed")


# ---------------------------------------------------------------------------
# 1) tool_call —— 包裹 QwenPawAgent._acting
# ---------------------------------------------------------------------------


def _install_tool_trace() -> None:
    from qwenpaw.agents.react_agent import QwenPawAgent

    if getattr(QwenPawAgent, _PATCH_MARK, False):
        return

    # MRO-resolved original (QwenPawAgent doesn't define _acting itself; it
    # comes from CodingModeMixin / agentscope ReActAgent). Captured before
    # the setattr below so the wrapper can re-enter it.
    _orig_acting = QwenPawAgent._acting  # type: ignore[attr-defined]

    # agentscope 2.0's ``_acting`` is an ASYNC GENERATOR that yields tool
    # chunks/responses — not a coroutine returning a value. The wrapper must
    # itself be an async generator: pass each chunk through untouched and
    # emit the trace once the stream finishes (or on error).
    async def _traced_acting(self: Any, tool_call: Any) -> Any:
        started = time.time()
        # Runtime.run plants the trace context on the agent's model
        # instance (object attributes cross tasks). _acting runs in a
        # pipeline task where the agent contextvars are UNSET — reading
        # them here silently dropped every tool_call since the Runtime
        # 2.0 rework (same failure mode as the llm_call spans).
        trace_ctx = getattr(getattr(self, "model", None), "_qp_trace_ctx", None)
        try:
            async for chunk in _orig_acting(self, tool_call):
                yield chunk
        except Exception as exc:  # noqa: BLE001 - re-raised after tracing
            await _emit_tool_call(
                tool_call,
                outcome="error",
                started_at=started,
                error=f"{type(exc).__name__}: {exc}",
                trace_ctx=trace_ctx,
            )
            raise
        await _emit_tool_call(
            tool_call,
            outcome="ok",
            started_at=started,
            trace_ctx=trace_ctx,
        )

    setattr(QwenPawAgent, "_acting", _traced_acting)
    setattr(QwenPawAgent, _PATCH_MARK, True)
    logger.debug("traceability: QwenPawAgent._acting wrapped")


async def _emit_tool_call(
    tool_call: Any,
    *,
    outcome: str,
    started_at: float,
    error: str | None = None,
    trace_ctx: dict | None = None,
) -> None:
    """Build + emit a ``tool_call`` event. Never raises.

    ``trace_ctx`` is the model-instance snapshot planted by Runtime.run;
    the contextvars remain only as a fallback for direct callers.
    """
    try:
        from qwenpaw.app.agent_context import (
            get_current_agent_id,
            get_current_channel,
            get_current_session_id,
            get_current_user_id,
        )

        ctx = trace_ctx or {}
        session_id = str(ctx.get("session_id") or get_current_session_id() or "")
        if not session_id:
            return

        def _get(key: str) -> Any:
            # agentscope 2.0 passes a ToolCallBlock OBJECT (id/name/input
            # attributes); the pre-rework dict shape is kept as fallback.
            try:
                if isinstance(tool_call, dict):
                    return tool_call.get(key)
                return getattr(tool_call, key, None)
            except Exception:  # pylint: disable=broad-except
                return None

        payload: dict[str, Any] = {
            "tool_call_id": _get("id"),
            "tool_name": str(_get("name") or ""),
            "args": _get("input"),
            "outcome": outcome,
            "duration_ms": int((time.time() - started_at) * 1000),
        }
        if error is not None:
            payload["error"] = error

        await _emit(
            session_id,
            "tool_call",
            payload,
            agent_id=str(ctx.get("agent_id") or get_current_agent_id() or "") or None,
            user_id=str(ctx.get("user_id") or get_current_user_id() or "") or None,
            channel=str(ctx.get("channel") or get_current_channel() or "") or None,
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug("tool_call trace build failed", exc_info=True)


# ---------------------------------------------------------------------------
# 2) user_message / error / cancelled —— 包裹 HookRegistry.run
# ---------------------------------------------------------------------------


def _install_lifecycle_trace() -> None:
    from qwenpaw.runtime.hooks import HookRegistry
    from qwenpaw.runtime.phases import Phase

    if getattr(HookRegistry, _PATCH_MARK, False):
        return

    _orig_run = HookRegistry.run

    async def _traced_run(self: Any, phase: Any, ctx: Any) -> Any:
        if phase == Phase.PRE_DISPATCH:
            await _emit_user_message(ctx)
        result = await _orig_run(self, phase, ctx)
        if phase == Phase.ON_ERROR:
            await _emit_error(ctx)
        return result

    setattr(HookRegistry, "run", _traced_run)
    setattr(HookRegistry, _PATCH_MARK, True)
    logger.debug("traceability: HookRegistry.run wrapped")


async def _emit_user_message(ctx: Any) -> None:
    """Record the user-side input as the opening event of a turn."""
    try:
        from qwenpaw.runtime.message_convert import _get_last_user_text

        session_id = str(getattr(ctx, "session_id", "") or "")
        query = _get_last_user_text(getattr(ctx, "input_msgs", []) or [])
        if not session_id or not query:
            return
        request = getattr(ctx, "request", None)
        await _emit(
            session_id,
            "user_message",
            {"text": query},
            agent_id=str(getattr(ctx, "agent_id", "") or "") or None,
            user_id=str(getattr(request, "user_id", "") or "") or None,
            channel=str(getattr(request, "channel", "") or "") or None,
            index_extra={"title": query, "preview": query},
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug("user_message trace failed", exc_info=True)


async def _emit_error(ctx: Any) -> None:
    """Record a terminal error / cancellation marker for the timeline."""
    try:
        import asyncio

        err = getattr(ctx, "error", None)
        if err is None:
            return
        session_id = str(getattr(ctx, "session_id", "") or "")
        if not session_id:
            return
        request = getattr(ctx, "request", None)
        agent_id = str(getattr(ctx, "agent_id", "") or "") or None
        user_id = str(getattr(request, "user_id", "") or "") or None
        channel = str(getattr(request, "channel", "") or "") or None

        if isinstance(err, (asyncio.CancelledError, KeyboardInterrupt)):
            await _emit(
                session_id,
                "cancelled",
                {"message": _CANCELLED_MSG},
                agent_id=agent_id,
                user_id=user_id,
                channel=channel,
            )
            return

        await _emit(
            session_id,
            "error",
            {
                "exception_type": type(err).__name__,
                "message": str(err)[:512],
            },
            agent_id=agent_id,
            user_id=user_id,
            channel=channel,
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug("error trace failed", exc_info=True)


# ---------------------------------------------------------------------------
# 3) agent_reply —— 包裹 AgentExecutor.run
# ---------------------------------------------------------------------------


def _install_reply_trace() -> None:
    from qwenpaw.runtime.executor import AgentExecutor

    if getattr(AgentExecutor, _PATCH_MARK, False):
        return

    _orig_run = AgentExecutor.run

    async def _traced_exec_run(self: Any, msgs: Any) -> Any:
        texts: list[str] = []
        async for obj in _orig_run(self, msgs):
            try:
                _maybe_collect_reply_text(self, obj, texts)
            except Exception:  # pylint: disable=broad-except
                pass
            yield obj
        try:
            await _emit_agent_reply(self, "".join(texts).strip())
        except Exception:  # pylint: disable=broad-except
            logger.debug("agent_reply trace failed", exc_info=True)

    setattr(AgentExecutor, "run", _traced_exec_run)
    setattr(AgentExecutor, _PATCH_MARK, True)
    logger.debug("traceability: AgentExecutor.run wrapped")


def _maybe_collect_reply_text(
    executor: Any,
    obj: Any,
    texts: list[str],
) -> None:
    """Accumulate finalized assistant text blocks, excluding reasoning.

    The envelope emits each text block twice (streaming deltas + one final
    non-delta chunk carrying the full block text). We keep only the final
    non-delta chunks, and drop reasoning blocks by matching ``msg_id``
    against the envelope's tracked reasoning message ids.
    """
    if type(obj).__name__ != "TextContent":
        return
    if getattr(obj, "delta", True) is not False:
        return
    msg_id = getattr(obj, "msg_id", None)
    envelope = getattr(executor, "_envelope", None)
    reasoning_ids = set()
    if envelope is not None:
        blocks = getattr(envelope, "_reasoning_blocks", {}) or {}
        reasoning_ids = {
            b.get("msg_id") for b in blocks.values() if isinstance(b, dict)
        }
    if msg_id in reasoning_ids:
        return
    text = getattr(obj, "text", "") or ""
    if text:
        texts.append(text)


async def _emit_agent_reply(executor: Any, reply: str) -> None:
    if not reply:
        return
    from qwenpaw.app.agent_context import (
        get_current_agent_id,
        get_current_channel,
        get_current_session_id,
        get_current_user_id,
    )

    session_id = str(get_current_session_id() or "")
    if not session_id:
        # Fall back to the envelope's session id when contextvars are unset.
        envelope = getattr(executor, "_envelope", None)
        response = getattr(envelope, "_response", None)
        session_id = str(getattr(response, "session_id", "") or "")
    if not session_id:
        return

    await _emit(
        session_id,
        "agent_reply",
        {"text": reply, "role": "assistant"},
        agent_id=str(get_current_agent_id() or "") or None,
        user_id=str(get_current_user_id() or "") or None,
        channel=str(get_current_channel() or "") or None,
    )
