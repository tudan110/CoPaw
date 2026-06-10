# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from qwenpaw.exceptions import ProviderError
from qwenpaw.extensions.ai_big_screen import llm
from qwenpaw.extensions.ai_big_screen.llm import structured_call
from qwenpaw.extensions.ai_big_screen.schemas import (
    ScreenPlan,
    parse_screen_plan,
)

_VALID = '{"name": "屏", "components": [{"id": "c1"}]}'
_FENCED = f"说明\n```json\n{_VALID}\n```"
_INVALID = "抱歉，我无法生成 JSON。"


class FakeModel:
    """Async model double returning canned responses in order."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def __call__(self, messages: list[dict[str, str]]) -> Any:
        self.calls.append([dict(m) for m in messages])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if response == "__hang__":
            await asyncio.sleep(30)
        return {"text": response}


def _messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是设计师，输出 JSON"},
        {"role": "user", "content": "生成告警大屏"},
    ]


def _fallback() -> ScreenPlan:
    return ScreenPlan.model_validate(
        {"name": "降级屏", "components": [{"id": "fb-1"}], "degraded": True},
    )


async def test_valid_first_attempt() -> None:
    model = FakeModel([_VALID])
    result = await structured_call(
        model,
        _messages(),
        parser=parse_screen_plan,
    )
    assert result.value.name == "屏"
    assert result.degraded is False
    assert result.attempts == 1


async def test_fenced_json_accepted() -> None:
    model = FakeModel([_FENCED])
    result = await structured_call(
        model,
        _messages(),
        parser=parse_screen_plan,
    )
    assert result.value.components[0].id == "c1"


async def test_repair_retry_feeds_back_error() -> None:
    model = FakeModel([_INVALID, _VALID])
    result = await structured_call(
        model,
        _messages(),
        parser=parse_screen_plan,
        max_repair=2,
    )
    assert result.value.name == "屏"
    assert result.attempts == 2
    # the repair round must carry the previous reply + the parse error
    repair_messages = model.calls[1]
    assert repair_messages[-2]["role"] == "assistant"
    assert _INVALID in repair_messages[-2]["content"]
    assert repair_messages[-1]["role"] == "user"
    assert "JSON" in repair_messages[-1]["content"]


async def test_exhausted_repairs_uses_fallback_and_marks_degraded() -> None:
    model = FakeModel([_INVALID, _INVALID, _INVALID])
    result = await structured_call(
        model,
        _messages(),
        parser=parse_screen_plan,
        max_repair=2,
        fallback=_fallback,
    )
    assert result.degraded is True
    assert result.value.name == "降级屏"
    assert result.attempts == 3


async def test_exhausted_repairs_without_fallback_raises() -> None:
    model = FakeModel([_INVALID, _INVALID, _INVALID])
    with pytest.raises(ValueError):
        await structured_call(
            model,
            _messages(),
            parser=parse_screen_plan,
            max_repair=2,
        )


async def test_timeout_counts_as_failure() -> None:
    model = FakeModel(["__hang__"])
    result = await structured_call(
        model,
        _messages(),
        parser=parse_screen_plan,
        max_repair=0,
        timeout=0.05,
        fallback=_fallback,
    )
    assert result.degraded is True


async def test_model_exception_counts_as_failure() -> None:
    model = FakeModel([RuntimeError("boom"), _VALID])
    result = await structured_call(
        model,
        _messages(),
        parser=parse_screen_plan,
        max_repair=1,
    )
    assert result.value.name == "屏"
    assert result.attempts == 2


async def test_create_pipeline_model_maps_unconfigured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise ProviderError("No active model configured")

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter",
        _raise,
    )
    with pytest.raises(ValueError) as excinfo:
        llm.create_pipeline_model()
    assert "默认大模型" in str(excinfo.value) or "模型配置" in str(
        excinfo.value,
    )
