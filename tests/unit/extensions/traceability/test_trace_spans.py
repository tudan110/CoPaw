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

    only_tools = client.get(
        "/api/portal/traces/spans?span_type=tool_call"
    ).json()
    assert [s["name"] for s in only_tools["items"]] == ["query_alarm"]
