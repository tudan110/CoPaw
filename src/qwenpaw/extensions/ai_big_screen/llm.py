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


def _extract_model_text(payload: Any) -> str:
    """Best-effort text extraction from agentscope model payloads."""
    if isinstance(payload, str):
        return payload
    if payload is None:
        return ""
    if isinstance(payload, list):
        return "\n".join(
            filter(None, (_extract_model_text(item) for item in payload)),
        )
    keys = ("text", "content", "response", "message")
    if isinstance(payload, dict):
        candidates = (payload.get(key) for key in keys)
    else:
        candidates = (getattr(payload, key, None) for key in keys)
    for value in candidates:
        if value:
            return _extract_model_text(value)
    return "" if isinstance(payload, dict) else str(payload)


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


def create_pipeline_model() -> ModelCallable:
    """Create the active chat model for pipeline calls.

    Maps provider-configuration errors to operator-actionable messages.
    Imported lazily to keep module import light (CLAUDE.md rule).
    """
    from qwenpaw.agents import model_factory

    try:
        model, _formatter = model_factory.create_model_and_formatter()
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        if isinstance(exc, ProviderError):
            if "No active model configured" in message:
                raise ValueError(CONFIGURE_LLM_MESSAGE) from exc
            raise ValueError(f"默认大模型不可用：{message}") from exc
        raise ValueError(f"默认大模型初始化失败：{message}") from exc
    return model


async def structured_call(
    model: ModelCallable,
    messages: list[dict[str, str]],
    *,
    parser: Callable[[str], T],
    max_repair: int = 2,
    timeout: float = 120.0,
    fallback: Callable[[], T] | None = None,
) -> StructuredCallResult[T]:
    """Call ``model`` until ``parser`` accepts the reply.

    ``parser`` must raise (``ValueError`` / pydantic ``ValidationError``)
    on bad payloads; the error text is fed back verbatim on the next
    repair round. Total attempts = 1 + ``max_repair``.
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
            continue
        except Exception as exc:  # provider/transport errors
            last_error = str(exc).strip() or exc.__class__.__name__
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
