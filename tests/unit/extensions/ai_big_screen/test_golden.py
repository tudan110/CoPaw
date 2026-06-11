# -*- coding: utf-8 -*-
"""Golden regression for the big-screen pipeline (P2 acceptance).

Migrated from the legacy golden-prompt behaviours: capability routing,
query != analysis, no fake data, honest failure adjudication, and
patch locality. All cases run with mocked LLM/integrations so they are
deterministic.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen.intent import build_screen_plan
from qwenpaw.extensions.ai_big_screen.patch import apply_patch
from qwenpaw.extensions.ai_big_screen.pipeline import run_draft_pipeline


class ForbiddenModel:
    """Asserts the prompt resolves without any LLM call."""

    async def __call__(self, _messages: list[dict[str, str]]) -> Any:
        raise AssertionError("golden fast-path must not call the LLM")


class FakeModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    async def __call__(self, _messages: list[dict[str, str]]) -> Any:
        return {"text": self.responses.pop(0)}


# ---------------------------------------------------------------------------
# golden 1: capability routing (semantic fast-path)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "expected_capabilities"),
    [
        ("查询最近15分钟告警", {"real-alarms"}),
        ("查询日志和告警", {"system-logs", "real-alarms"}),
        ("查询今日工单", {"workorders"}),
        ("查看CMDB资源", {"cmdb-resources"}),
        ("查询拓扑影响范围", {"topology-impact"}),
        (
            "查询日志、告警和工单",
            {"system-logs", "real-alarms", "workorders"},
        ),
    ],
)
async def test_golden_capability_routing(
    prompt: str,
    expected_capabilities: set[str],
) -> None:
    plan = await build_screen_plan(prompt, model=ForbiddenModel())
    assert {c.capability_id for c in plan.components} == (
        expected_capabilities
    )
    assert plan.degraded is False


# ---------------------------------------------------------------------------
# golden 2: query != analysis (logs stay plain unless risk explicitly asked)
# ---------------------------------------------------------------------------


async def test_golden_plain_log_query_is_not_risk_analysis() -> None:
    plan = await build_screen_plan(
        "查询最近15分钟系统日志",
        model=ForbiddenModel(),
    )
    log_component = next(
        c for c in plan.components if c.capability_id == "system-logs"
    )
    assert log_component.type != "risk-pulse"
    assert log_component.query_params.get("analysisMode") in ("", None)


async def test_golden_explicit_risk_ask_enables_analysis() -> None:
    plan = await build_screen_plan(
        "查询最近15分钟日志，分析高危情况并动态突出",
        model=ForbiddenModel(),
    )
    log_component = next(
        c for c in plan.components if c.capability_id == "system-logs"
    )
    assert log_component.type == "risk-pulse"
    assert log_component.query_params.get("analysisMode") == "risk_summary"


async def test_golden_dmax_visual_types_survive_normalization() -> None:
    """Regression: capability supportedVisuals must include the D-max
    palette — the legacy whitelist squashed every LLM-chosen type
    (flip-number/donut/alarm-stream/...) down to table, which is why
    generated screens looked like the old template."""
    plan_json = json.dumps(
        {
            "name": "态势大屏",
            "components": [
                {
                    "title": "告警总数",
                    "capabilityId": "real-alarms",
                    "visualType": "flip-number",
                },
                {
                    "title": "分级占比",
                    "capabilityId": "real-alarms",
                    "visualType": "donut",
                },
                {
                    "title": "实时告警流",
                    "capabilityId": "real-alarms",
                    "visualType": "alarm-stream",
                },
                {
                    "title": "工单达成率",
                    "capabilityId": "workorders",
                    "visualType": "gauge",
                },
                {
                    "title": "资源水位",
                    "capabilityId": "cmdb-resources",
                    "visualType": "liquid-ball",
                },
            ],
        },
        ensure_ascii=False,
    )
    plan = await build_screen_plan(
        "做一个炫酷的多视角运维态势分析大屏",
        model=FakeModel([plan_json]),
    )
    types = [c.type for c in plan.components]
    assert "flip-number" in types
    assert "donut" in types
    assert "alarm-stream" in types
    assert "gauge" in types
    assert "liquid-ball" in types
    assert "table" not in types[:5]


async def test_golden_llm_cannot_force_risk_on_plain_query() -> None:
    """Even if the model claims risk-pulse, a plain query stays plain."""
    plan_json = json.dumps(
        {
            "name": "日志屏",
            "components": [
                {
                    "title": "系统日志",
                    "capabilityId": "system-logs",
                    "visualType": "risk-pulse",
                    "queryParams": {"analysisMode": "risk_summary"},
                },
            ],
        },
        ensure_ascii=False,
    )
    plan = await build_screen_plan(
        "做一个普通的系统日志大屏，最近15分钟即可",
        model=FakeModel([plan_json]),
    )
    log_component = next(
        c for c in plan.components if c.capability_id == "system-logs"
    )
    assert log_component.type != "risk-pulse"
    assert log_component.query_params.get("analysisMode") in ("", None)


# ---------------------------------------------------------------------------
# golden 3: no fake data — non-live workorder source is blocked
# ---------------------------------------------------------------------------


async def test_golden_no_fake_workorder_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.integrations import order_workflow

    monkeypatch.setattr(
        order_workflow,
        "query_order_workorders",
        lambda **_kw: {
            "source": "mock",
            "items": [{"id": "fake-1", "title": "假工单"}],
        },
    )
    screen = await run_draft_pipeline(
        prompt="查询今日工单",
        model=ForbiddenModel(),
    )
    component = screen["components"][0]
    assert component["data"]["sourceStatus"] == "failed"
    assert component["data"]["rows"] in ([], None)


# ---------------------------------------------------------------------------
# golden 4: backend failure is failed, not empty
# ---------------------------------------------------------------------------


async def test_golden_backend_outage_is_failed_not_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.integrations import (
        portal_real_alarms,
        working_secrets,
    )

    monkeypatch.setattr(
        working_secrets,
        "ensure_working_secrets_loaded",
        lambda: None,
    )

    def _down(**_kw: Any) -> dict[str, Any]:
        raise ConnectionError("backend outage")

    monkeypatch.setattr(
        portal_real_alarms,
        "query_portal_real_alarms",
        _down,
    )
    screen = await run_draft_pipeline(
        prompt="查询最近15分钟告警",
        model=ForbiddenModel(),
    )
    component = screen["components"][0]
    assert component["data"]["sourceStatus"] == "failed"
    intents = screen["aiConversationContext"]["dataIntentPlan"]["intents"]
    assert intents[0]["dataQuality"] == "failed"


# ---------------------------------------------------------------------------
# golden 5: patch locality — only the selected component changes
# ---------------------------------------------------------------------------


async def test_golden_patch_only_touches_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.ai_big_screen.capabilities import descriptors

    def _no_fetch(_params: Any) -> dict[str, Any]:
        raise AssertionError("visual patch must not refetch")

    for capability_id in list(descriptors.FETCHERS):
        monkeypatch.setitem(descriptors.FETCHERS, capability_id, _no_fetch)

    screen = {
        "schemaVersion": 1,
        "id": "screen-golden",
        "name": "golden",
        "owner": "tester",
        "status": "draft",
        "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
        "theme": {"mode": "dark", "palette": "industrial"},
        "components": [
            {
                "id": "comp-a",
                "type": "table",
                "title": "A",
                "pluginId": "real-alarms",
                "capabilityId": "real-alarms",
                "queryParams": {},
                "visualConfig": {},
                "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                "data": {"sourceStatus": "live", "rows": []},
            },
            {
                "id": "comp-b",
                "type": "table",
                "title": "B",
                "pluginId": "system-logs",
                "capabilityId": "system-logs",
                "queryParams": {},
                "visualConfig": {},
                "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 4},
                "data": {"sourceStatus": "live", "rows": []},
            },
        ],
        "dataBindings": [],
        "versions": [{"versionId": "v1"}],
        "publishTargets": [],
        "aiConversationContext": {},
    }
    outcome = await apply_patch(
        screen=screen,
        instruction="把所有组件标题都加上前缀",
        selected_component_ids=["comp-a"],
        model=FakeModel(
            [
                json.dumps(
                    {
                        "summary": "批量改名",
                        "operations": [
                            {
                                "op": "setComponentTitle",
                                "componentIds": ["comp-a", "comp-b"],
                                "value": "改过的标题",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
            ],
        ),
    )
    components = {c["id"]: c for c in outcome["screen"]["components"]}
    assert components["comp-a"]["title"] == "改过的标题"
    assert components["comp-b"]["title"] == "B"
