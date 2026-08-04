# -*- coding: utf-8 -*-
"""Schema-validated LLM calls with bounded repair and honest fallback.

Replaces the legacy pattern of "describe JSON in the prompt and
greedy-slice ``{...}`` out of the reply". Strategy (spec §6):

1. parse + schema-validate the reply (``parser`` raises on violation);
2. on failure feed the exact error back to the model and retry, at most
   ``max_repair`` times, each attempt under an ``asyncio.wait_for``
   timeout;
3. when attempts are exhausted, call ``fallback`` (guardrail-generated
   minimal plan) and mark the result ``degraded`` — never fake success.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ProviderError

T = TypeVar("T")

CONFIGURE_LLM_MESSAGE = "未配置默认大模型，请先到“模型配置”里设置默认 LLM 后再生成或修改 AI 大屏。"

_REPAIR_INSTRUCTION = (
    "你上一次的回复无法通过 JSON Schema 校验，错误如下：\n{error}\n"
    "请重新输出严格符合要求的 JSON 对象，不要输出任何解释、Markdown 或代码块围栏。"
)

ModelCallable = Callable[[list[dict[str, str]]], Awaitable[Any]]


@dataclass
class StructuredCallResult(Generic[T]):
    """Outcome of a structured LLM call."""

    value: T
    degraded: bool
    attempts: int
    last_error: str = ""


def _get_field(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _extract_model_text(payload: Any) -> str:
    """Best-effort text extraction from agentscope model payloads.

    Reasoning models stream content as typed blocks — a ``thinking`` block
    plus a ``text`` block. Only the ``text`` block is the answer; a naive
    extractor would concatenate the thinking block's repr and break JSON
    parsing (every structured call then degraded). So: text blocks yield
    their text, any other typed block yields nothing, and response wrappers
    are unwrapped into their content.
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "".join(
            text
            for text in (_extract_model_text(item) for item in payload)
            if text
        )
    # Response wrappers (ChatResponse is a dict subclass) carry the blocks in
    # ``content`` — unwrap that FIRST, before the block-type check, because
    # the wrapper itself may also have a ``type`` field.
    content = _get_field(payload, "content")
    if content:
        return _extract_model_text(content)
    block_type = _get_field(payload, "type")
    if block_type == "text":
        return str(_get_field(payload, "text") or "")
    if isinstance(block_type, str):
        # thinking / tool_use / media block — carries no answer text
        return ""
    for key in ("response", "message", "text"):
        value = _get_field(payload, key)
        if value:
            return _extract_model_text(value)
    return ""


async def _consume_model_response(
    model: ModelCallable,
    messages: list[dict[str, str]],
) -> str:
    response = await model(messages)
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            text = _extract_model_text(chunk)
            if text:
                accumulated = text
        return accumulated
    return _extract_model_text(response)


def create_pipeline_model(
    model_slot: ModelSlotConfig | None = None,
    *,
    use_global_default: bool = False,
) -> ModelCallable:
    """Create a chat model for pipeline calls.

    Maps provider-configuration errors to operator-actionable messages.
    Imported lazily to keep module import light (CLAUDE.md rule).

    The agentscope ``ChatModelBase`` expects ``Msg`` objects (it applies the
    formatter internally); the pipeline speaks the simpler ``list[dict]``
    shape. This wraps the model so the pipeline's role/content dicts are
    converted to ``Msg`` before the call — without it every generation and
    patch failed with "Expected Msg object, got dict" and silently degraded
    to the keyword guardrail (the whole LLM decision layer was dead).
    """
    from agentscope.message import Msg, TextBlock

    from qwenpaw.agents import model_factory

    try:
        model, _formatter = model_factory.create_model_and_formatter(
            # ``""`` is a deliberate sentinel accepted by the factory: it
            # bypasses the request/current-Agent lookup and reaches the
            # system global model branch. Keep ordinary pipeline callers'
            # legacy Agent-aware behaviour unless they opt in explicitly.
            agent_id="" if use_global_default else None,
            model_slot=model_slot,
        )
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        if isinstance(exc, ProviderError):
            if "No active model configured" in message:
                raise ValueError(CONFIGURE_LLM_MESSAGE) from exc
            prefix = "综合功能模型" if model_slot else "默认大模型"
            raise ValueError(f"{prefix}不可用：{message}") from exc
        prefix = "综合功能模型" if model_slot else "默认大模型"
        raise ValueError(f"{prefix}初始化失败：{message}") from exc

    async def _call(messages: list[dict[str, str]]) -> Any:
        msgs = [
            Msg(
                name=str(message.get("role") or "user"),
                role=str(message.get("role") or "user"),
                content=[
                    TextBlock(
                        type="text",
                        text=str(message.get("content") or ""),
                    ),
                ],
            )
            for message in messages
        ]
        return await model(msgs)

    return _call


async def structured_call(
    model: ModelCallable,
    messages: list[dict[str, str]],
    *,
    parser: Callable[[str], T],
    max_repair: int = 2,
    timeout: float = 120.0,
    fallback: Callable[[], T] | None = None,
    retry_backoff: float = 1.5,
) -> StructuredCallResult[T]:
    """Call ``model`` until ``parser`` accepts the reply.

    ``parser`` must raise (``ValueError`` / pydantic ``ValidationError``)
    on bad payloads; the error text is fed back verbatim on the next
    repair round. Total attempts = 1 + ``max_repair``.

    A transport/timeout failure (as opposed to a parser rejection) means
    ``model`` already exhausted its own backed-off retries — or hit a
    fast non-retryable/429 short-circuit — before raising here. Retrying
    the exact same call again with zero delay just burns the whole
    repair budget in milliseconds without giving a transient rate limit
    any window to clear, so those two branches (not the parser-repair
    one, which wants an immediate retry with the corrected prompt) wait
    ``retry_backoff`` seconds before the next round.
    """
    conversation = [dict(message) for message in messages]
    last_error = ""
    attempts = 0

    for _round in range(max_repair + 1):
        attempts += 1
        try:
            reply = await asyncio.wait_for(
                _consume_model_response(model, conversation),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            last_error = f"模型响应超时（>{timeout}s）"
            # A timeout at this (already generous) per-attempt budget means
            # the generation is genuinely too slow — heavy inline content,
            # a stalled provider — not a transient blip (the model wrapper
            # already retried those internally). Retrying the identical
            # prompt just burns another full timeout window, turning one
            # slow request into minutes of dead wait. Go straight to the
            # fallback with a single clean attempt spent, rather than
            # 1+max_repair timeout windows.
            break
        except Exception as exc:  # provider/transport errors
            last_error = str(exc).strip() or exc.__class__.__name__
            if _round < max_repair:
                await asyncio.sleep(retry_backoff * attempts)
            continue

        try:
            value = parser(reply)
        except Exception as exc:
            last_error = str(exc).strip() or exc.__class__.__name__
            conversation.append({"role": "assistant", "content": reply})
            conversation.append(
                {
                    "role": "user",
                    "content": _REPAIR_INSTRUCTION.format(
                        error=last_error[:2000],
                    ),
                },
            )
            continue

        return StructuredCallResult(
            value=value,
            degraded=False,
            attempts=attempts,
            last_error="",
        )

    if fallback is not None:
        return StructuredCallResult(
            value=fallback(),
            degraded=True,
            attempts=attempts,
            last_error=last_error,
        )
    raise ValueError(
        f"大模型未能生成符合要求的结构化结果：{last_error or '未知错误'}",
    )
