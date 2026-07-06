# -*- coding: utf-8 -*-
"""llm_call span pipeline: index aggregation + trends/spans endpoints."""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from qwenpaw.extensions.traceability import trace_store

    monkeypatch.setattr(trace_store, "_TRACE_DIR", tmp_path)
    monkeypatch.setattr(trace_store, "_INDEX_PATH", tmp_path / "_index.json")
    return trace_store


async def _seed(store):
    await store.record_event(
        "s1",
        "user_message",
        {"text": "查告警", "preview": "查告警"},
        agent_id="gateway",
        channel="portal",
        index_extra={"title": "查告警"},
    )
    await store.record_event(
        "s1",
        "llm_call",
        {
            "model": "ctyun:glm-5.1",
            "status": "ok",
            "duration_ms": 5940,
            "prompt_tokens": 15631,
            "completion_tokens": 114,
            "ttft_ms": 2500,
        },
        agent_id="gateway",
        index_extra={"add_tokens": 15745},
    )
    await store.record_event(
        "s1",
        "tool_call",
        {"tool_name": "query_alarm", "duration_ms": 450, "outcome": "ok"},
        agent_id="gateway",
    )
    await store.record_event(
        "s1",
        "llm_call",
        {
            "model": "ctyun:glm-5.1",
            "status": "ok",
            "duration_ms": 9530,
            "prompt_tokens": 15774,
            "completion_tokens": 88,
        },
        agent_id="gateway",
        index_extra={"add_tokens": 15862},
    )


@pytest.mark.asyncio
async def test_index_aggregates_llm_calls_and_tokens(store):
    await _seed(store)
    entry = store.list_sessions()["items"][0]
    assert entry["llm_call_count"] == 2
    assert entry["tool_call_count"] == 1
    assert entry["total_tokens"] == 15745 + 15862


@pytest.mark.asyncio
async def test_trends_and_spans_endpoints(store):
    await _seed(store)
    from qwenpaw.extensions.api import traces_backend

    importlib.reload(traces_backend)
    app = FastAPI()
    app.include_router(traces_backend.router)
    client = TestClient(app)

    trends = client.get("/api/portal/traces/trends?window_s=86400").json()
    assert trends["points"]
    assert trends["points"][-1]["traces"] == 1
    assert trends["points"][-1]["tokens"] == 31607

    spans = client.get("/api/portal/traces/spans").json()
    assert len(spans["items"]) == 3
    llm_rows = [s for s in spans["items"] if s["type"] == "llm_call"]
    assert all(s["name"] == "ctyun:glm-5.1" for s in llm_rows)
    assert {s["ttftMs"] for s in llm_rows} == {2500.0, None}

    only_tools = client.get("/api/portal/traces/spans?span_type=tool_call").json()
    assert [s["name"] for s in only_tools["items"]] == ["query_alarm"]


@pytest.mark.asyncio
async def test_streaming_llm_call_survives_consumer_break(store, monkeypatch, tmp_path):
    """agentscope consumers break on ``is_last`` then aclose() — the
    llm_call span must still be emitted (regression: it used to sit
    after ``async for`` and never ran for real chats)."""
    from agentscope.message import TextBlock
    from agentscope.model._model_response import ChatResponse

    import qwenpaw.app.agent_context as agent_context
    from qwenpaw.providers.retry_chat_model import RetryChatModel

    class FakeUsage:
        input_tokens = 1000
        output_tokens = 50

    class FakeInner:
        model = "glm-5.1"
        _provider_id = "ctyun"
        stream = True

        async def __call__(self, *args, **kwargs):
            async def gen():
                for i in range(3):
                    last = i == 2
                    response = ChatResponse(
                        content=[TextBlock(type="text", text=f"c{i}")],
                        is_last=last,
                    )
                    if last:
                        response.usage = FakeUsage()
                    yield response

            return gen()

    agent_context.set_current_session_id("stream-break")
    agent_context.set_current_agent_id("gateway")
    model = RetryChatModel(FakeInner())

    # __call__ runs in the agent task (contextvars set)…
    gen = await model(stream=True)

    # …but consumption + the generator's finally run in a response-
    # streaming task where the contextvars are UNSET (Starlette
    # behaviour). The span must survive via the __call__ snapshot.
    import asyncio as _asyncio

    async def _consume_without_context():
        agent_context.set_current_session_id("")
        agent_context.set_current_agent_id("")
        async for chunk in gen:
            if getattr(chunk, "is_last", False):
                break  # the real-world consumption pattern
        await gen.aclose()

    await _asyncio.get_running_loop().create_task(_consume_without_context())
    await _asyncio.sleep(0.3)  # let the fire-and-forget task land

    detail = store.read_session("stream-break")
    llm = [e for e in detail.get("events", []) if e.get("type") == "llm_call"]
    assert len(llm) == 1
    assert llm[0]["status"] == "ok"
    assert llm[0]["prompt_tokens"] == 1000
    assert llm[0]["completion_tokens"] == 50
    assert llm[0]["ttft_ms"] is not None


@pytest.mark.asyncio
async def test_streaming_llm_call_uses_model_instance_slot(store):
    """Real runtime topology: NO task in the pipeline carries the agent
    contextvars (Runtime.run is an async generator driven by varying
    tasks). Runtime.run plants the trace context on the model instance;
    the span must be emitted from that slot alone."""
    from agentscope.message import TextBlock
    from agentscope.model._model_response import ChatResponse

    import qwenpaw.app.agent_context as agent_context
    from qwenpaw.providers.retry_chat_model import RetryChatModel

    class FakeUsage:
        input_tokens = 321
        output_tokens = 17

    class FakeInner:
        model = "mock-glm"
        _provider_id = "mock"
        stream = True

        async def __call__(self, *args, **kwargs):
            async def gen():
                for i in range(2):
                    last = i == 1
                    response = ChatResponse(
                        content=[TextBlock(type="text", text=f"c{i}")],
                        is_last=last,
                    )
                    if last:
                        response.usage = FakeUsage()
                    yield response

            return gen()

    # contextvars empty EVERYWHERE — the real pipeline shape
    agent_context.set_current_session_id("")
    agent_context.set_current_agent_id("")
    model = RetryChatModel(FakeInner())
    # what Runtime.run does before executing the agent
    model._qp_trace_ctx = {
        "session_id": "slot-session",
        "agent_id": "gateway",
        "user_id": "t",
        "channel": "console",
    }

    gen = await model(stream=True)
    async for chunk in gen:
        if getattr(chunk, "is_last", False):
            break
    await gen.aclose()
    import asyncio as _asyncio

    await _asyncio.sleep(0.3)

    detail = store.read_session("slot-session")
    llm = [e for e in detail.get("events", []) if e.get("type") == "llm_call"]
    assert len(llm) == 1
    assert llm[0]["prompt_tokens"] == 321
    assert llm[0]["completion_tokens"] == 17
    assert llm[0]["agent_id"] == "gateway"


@pytest.mark.asyncio
async def test_tool_call_emit_uses_instance_ctx_and_object_shape(store):
    """Tool traces died twice over: contextvars are unset in the
    pipeline task (same as llm_call), and agentscope 2.0 passes a
    ToolCallBlock OBJECT where the old code expected a dict (.get()
    raised, fields silently emptied). Emit must work from the planted
    trace_ctx with attribute access."""
    import qwenpaw.app.agent_context as agent_context
    from qwenpaw.extensions.traceability.install import _emit_tool_call

    class FakeToolCallBlock:
        id = "call_1"
        name = "execute_shell_command"
        input = '{"command": "echo hi"}'

    agent_context.set_current_session_id("")  # pipeline task shape
    await _emit_tool_call(
        FakeToolCallBlock(),
        outcome="ok",
        started_at=0.0,
        trace_ctx={
            "session_id": "tool-slot",
            "agent_id": "gateway",
            "user_id": "t",
            "channel": "console",
        },
    )
    detail = store.read_session("tool-slot")
    tools = [e for e in detail.get("events", []) if e.get("type") == "tool_call"]
    assert len(tools) == 1
    assert tools[0]["tool_name"] == "execute_shell_command"
    assert tools[0]["tool_call_id"] == "call_1"
    assert tools[0]["args"] == '{"command": "echo hi"}'
    assert tools[0]["agent_id"] == "gateway"
