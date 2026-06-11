# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

from qwenpaw.extensions.ai_big_screen import intent
from qwenpaw.extensions.ai_big_screen.intent import (
    build_guardrail_plan,
    build_screen_plan,
    extract_lookback_minutes,
    extract_semantic_capability_ids,
    should_use_semantic_fast_path,
)


class SpyModel:
    """Fails the test if the LLM is called on a fast-path prompt."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls = 0

    async def __call__(self, _messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        if not self.responses:
            raise AssertionError("LLM should not be called")
        return {"text": self.responses.pop(0)}


def _llm_plan(components: list[dict[str, Any]], **extra: Any) -> str:
    payload: dict[str, Any] = {
        "name": "AI 运维大屏",
        "description": "测试",
        "theme": {"palette": "aurora"},
        "layout": {"rowHeight": 90},
        "components": components,
        "summary": "测试摘要",
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class TestPromptHeuristics:
    def test_semantic_capability_extraction_order(self) -> None:
        ids = extract_semantic_capability_ids("查询日志和告警，再看下工单")
        assert ids == ["system-logs", "real-alarms", "workorders"]

    def test_simple_query_fast_path(self) -> None:
        assert should_use_semantic_fast_path("查询最近15分钟告警") is True

    def test_analysis_prompt_goes_to_llm(self) -> None:
        assert should_use_semantic_fast_path("做一个告警趋势分析大屏") is False

    def test_lookback_minutes(self) -> None:
        assert extract_lookback_minutes("最近30分钟日志") == 30
        assert extract_lookback_minutes("最近2小时告警") == 120
        assert extract_lookback_minutes("看下日志") == 15


class TestFastPath:
    async def test_simple_query_skips_llm(self) -> None:
        spy = SpyModel()
        plan = await build_screen_plan(
            "查询最近15分钟告警",
            model=spy,
        )
        assert spy.calls == 0
        assert plan.degraded is False
        assert len(plan.components) == 1
        component = plan.components[0]
        assert component.capability_id == "real-alarms"
        assert component.query_params.get("lookbackMinutes") == 15
        assert component.id.startswith("component-1-")

    async def test_log_risk_fast_path(self) -> None:
        spy = SpyModel()
        plan = await build_screen_plan(
            "查询最近15分钟日志，分析高危情况并动态突出",
            model=spy,
        )
        assert spy.calls == 0
        logs = [c for c in plan.components if c.capability_id == "system-logs"]
        assert logs
        assert logs[0].type == "risk-pulse"
        assert logs[0].query_params.get("analysisMode") == "risk_summary"
        assert logs[0].visual_spec.get("kind") == "risk-field"


class TestLlmPathNormalization:
    async def test_unknown_capability_becomes_gap(self) -> None:
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "K8s 集群水位",
                            "capabilityId": "kubernetes-metrics",
                            "visualType": "gauge",
                            "queryParams": {},
                        },
                    ],
                ),
            ],
        )
        plan = await build_screen_plan("做一个集群水位分析大屏", model=model)
        assert model.calls == 1
        gap = plan.components[0]
        assert gap.capability_id == "capability-gap"
        assert gap.query_params.get("suggestedCapabilityId") == (
            "kubernetes-metrics"
        )

    async def test_title_keyword_overrides_wrong_capability(self) -> None:
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "今日待办工单",
                            "capabilityId": "real-alarms",
                            "visualType": "table",
                        },
                    ],
                ),
            ],
        )
        plan = await build_screen_plan("展示今日工单处理分析", model=model)
        assert plan.components[0].capability_id == "workorders"

    async def test_missing_semantic_capability_appended(self) -> None:
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "告警趋势",
                            "capabilityId": "real-alarms",
                            "visualType": "line-chart",
                        },
                    ],
                ),
            ],
        )
        plan = await build_screen_plan(
            "做一个日志和告警的综合分析大屏",
            model=model,
        )
        ids = {c.capability_id for c in plan.components}
        assert "system-logs" in ids
        assert "real-alarms" in ids

    async def test_theme_layout_normalized(self) -> None:
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "告警",
                            "capabilityId": "real-alarms",
                            "visualType": "table",
                        },
                    ],
                    theme={"palette": "neon-explosion", "mode": "light"},
                    layout={"rowHeight": 9999},
                ),
            ],
        )
        plan = await build_screen_plan("告警态势分析", model=model)
        assert plan.theme["palette"] == "industrial"  # fallback
        assert plan.theme["mode"] == "dark"
        assert plan.layout == {
            "type": "grid",
            "columns": 12,
            "rowHeight": 120,
        }

    async def test_unsupported_visual_type_falls_back(self) -> None:
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "工单分析",
                            "capabilityId": "workorders",
                            "visualType": "map-fly",  # not in supportedVisuals
                        },
                    ],
                ),
            ],
        )
        plan = await build_screen_plan("工单分析处理大屏", model=model)
        component = plan.components[0]
        assert component.type == "table"  # first supported visual


class TestDegradedFallback:
    async def test_invalid_llm_output_degrades_to_guardrail(self) -> None:
        model = SpyModel(["不是 JSON", "还不是 JSON", "依旧不是 JSON"])
        plan = await build_screen_plan(
            "做一个日志和告警的综合分析大屏",
            model=model,
            max_repair=2,
        )
        assert plan.degraded is True
        ids = {c.capability_id for c in plan.components}
        assert {"system-logs", "real-alarms"} <= ids

    async def test_guardrail_plan_without_keywords_uses_gap(self) -> None:
        plan = build_guardrail_plan(
            prompt="帮我做一个量子计算监控大屏",
            title="",
        )
        assert plan.components
        assert plan.components[0].capability_id == "capability-gap"


class TestTitleOverride:
    async def test_requested_title_wins(self) -> None:
        spy = SpyModel()
        plan = await build_screen_plan(
            "查询最近15分钟告警",
            title="NOC 一号屏",
            model=spy,
        )
        assert plan.name == "NOC 一号屏"


def test_intent_module_has_no_llm_import_at_top_level() -> None:
    """Keep heavy imports lazy (CLAUDE.md rule)."""
    import inspect

    source = inspect.getsource(intent)
    module_header = source.split("def ", maxsplit=1)[0]
    assert "from qwenpaw.agents" not in module_header
