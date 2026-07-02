# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

from qwenpaw.extensions.ai_big_screen import intent
from qwenpaw.extensions.ai_big_screen.intent import (
    DEFAULT_SCREEN_NAME,
    MAX_SCREEN_TITLE_LENGTH,
    build_guardrail_plan,
    build_screen_plan,
    clamp_screen_title,
    derive_screen_title,
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

    def test_uncovered_clause_falls_back_to_llm(self) -> None:
        # "南京天气" matches no capability — must leave the keyword
        # fast-path so the unknown ask reaches the LLM instead of being
        # silently dropped.
        assert should_use_semantic_fast_path("查询15分钟系统日志，南京天气") is False

    def test_all_known_clauses_keep_fast_path(self) -> None:
        # every clause maps to a known capability → fast-path stays
        assert should_use_semantic_fast_path("查询日志和告警") is True
        assert should_use_semantic_fast_path("查询最近15分钟告警") is True


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

    async def test_log_query_defaults_to_latest_non_empty(self) -> None:
        # A quiet log index must still show real (historical) data, so
        # the default search walks back to the latest non-empty window
        # rather than returning empty for "last 15 minutes".
        spy = SpyModel()
        plan = await build_screen_plan("查询最近15分钟系统日志", model=spy)
        assert spy.calls == 0
        log = next(
            c for c in plan.components if c.capability_id == "system-logs"
        )
        assert log.query_params.get("searchStrategy") == "latest_non_empty"


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

    def test_topology_component_born_with_visible_style(self) -> None:
        component = intent.normalize_plan_component(
            {
                "title": "应用拓扑",
                "capabilityId": "topology-impact",
                "visualType": "graph",
            },
            index=0,
            inferred_lookback_minutes=15,
        )
        style = component.visual_spec.get("style", {})
        assert style.get("sizeScale") == 1.3
        assert style.get("lineOpacity") == 75
        assert style.get("emphasis") == "strong"

    def test_explicit_style_is_preserved_not_overridden(self) -> None:
        component = intent.normalize_plan_component(
            {
                "title": "应用拓扑",
                "capabilityId": "topology-impact",
                "visualType": "graph",
                "visualSpec": {"style": {"sizeScale": 1.1}},
            },
            index=0,
            inferred_lookback_minutes=15,
        )
        assert component.visual_spec["style"]["sizeScale"] == 1.1

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


class TestComposedCreation:
    async def test_composed_blueprint_survives_normalization(self) -> None:
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "告警核心舱",
                            "capabilityId": "real-alarms",
                            "visualType": "composed",
                            "visualSpec": {
                                "composition": "primary",
                                "blueprint": {
                                    "layout": "columns",
                                    "cells": [
                                        {
                                            "element": {
                                                "kind": "value",
                                                "style": "flip",
                                                "bind": {"value": "total"},
                                            },
                                        },
                                        {
                                            "element": {
                                                "kind": "chart",
                                                "chart": "donut",
                                                "bind": {
                                                    "name": "level",
                                                    "value": "value",
                                                },
                                            },
                                        },
                                    ],
                                },
                            },
                        },
                    ],
                ),
            ],
        )
        plan = await build_screen_plan("做一个告警态势创作大屏", model=model)
        component = plan.components[0]
        assert component.type == "composed"
        blueprint = component.visual_spec.get("blueprint")
        assert blueprint is not None
        assert [c["element"]["kind"] for c in blueprint["cells"]] == [
            "value",
            "chart",
        ]


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


class TestWebLiveRouting:
    def test_extract_web_live_requests(self) -> None:
        assert intent.extract_web_live_requests(
            "查询最近工单，告警以及南京天气",
        ) == ["南京天气"]
        assert intent.extract_web_live_requests("查询工单和告警") == []
        reqs = intent.extract_web_live_requests("上海天气，美元汇率")
        assert "上海天气" in reqs and any("汇率" in r for r in reqs)

    def test_guardrail_builds_web_live_component(self) -> None:
        # The confirmed root cause: the degraded/guardrail path dropped
        # weather because it only knew internal capabilities.
        plan = intent.build_guardrail_plan(
            prompt="查询最近工单，告警以及南京天气",
            title="",
            degraded=True,
        )
        caps = [(c.type, c.capability_id) for c in plan.components]
        assert ("table", "web-live-data") in caps
        weather = next(
            c for c in plan.components if c.capability_id == "web-live-data"
        )
        assert weather.query_params.get("query") == "南京天气"

    def test_public_web_infers_but_internal_wins_collision(self) -> None:
        assert (
            intent._infer_component_capability_id({"title": "南京天气"})
            == "web-live-data"
        )
        # internal keyword must win a collision (not mis-route to the web)
        assert (
            intent._infer_component_capability_id({"title": "资讯中心告警"})
            == "real-alarms"
        )

    def test_unknown_weather_capability_reroutes_not_gapped(self) -> None:
        pc = intent.normalize_plan_component(
            {
                "title": "南京天气",
                "capabilityId": "weather",  # not a real capability id
                "visualType": "metric-kpi",
            },
            index=0,
            inferred_lookback_minutes=15,
        )
        assert pc.capability_id == "web-live-data"  # not capability-gap
        assert pc.query_params.get("query") == "南京天气"


class TestUncoveredClauseCompleteness:
    """_fill_uncovered_clauses is a general post-hoc completeness patch,
    not a topic-specific keyword list — these deliberately avoid weather
    (already covered by TestWebLiveRouting) to prove the mechanism
    generalizes to any unregistered data ask."""

    def test_guardrail_flags_unregistered_clause_as_gap(self) -> None:
        plan = intent.build_guardrail_plan(
            prompt="查询最近工单，告警以及库存管理系统的库存周转率",
            title="",
        )
        caps = [c.capability_id for c in plan.components]
        assert "workorders" in caps
        assert "real-alarms" in caps
        gap = next(
            c for c in plan.components if c.capability_id == "capability-gap"
        )
        assert "库存周转率" in gap.query_params.get("requestedData", "")

    def test_guardrail_fully_covered_prompt_has_no_gap(self) -> None:
        plan = intent.build_guardrail_plan(
            prompt="查询工单和告警",
            title="",
        )
        caps = [c.capability_id for c in plan.components]
        assert "capability-gap" not in caps

    async def test_llm_path_patches_clause_llm_forgot(self) -> None:
        # The LLM only answered "工单" and silently dropped the other
        # clause — normalization must catch what the guardrail's own
        # routing (_has_uncovered_request) flagged before the call.
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "工单",
                            "capabilityId": "workorders",
                            "visualType": "table",
                        },
                    ],
                ),
            ],
        )
        plan = await build_screen_plan(
            "查询工单，以及库存管理系统的库存周转率",
            model=model,
        )
        assert model.calls == 1
        gap = next(
            c for c in plan.components if c.capability_id == "capability-gap"
        )
        assert "库存周转率" in gap.query_params.get("requestedData", "")

    async def test_llm_path_no_gap_when_already_complete(self) -> None:
        model = SpyModel(
            [
                _llm_plan(
                    [
                        {
                            "title": "工单",
                            "capabilityId": "workorders",
                            "visualType": "table",
                        },
                        {
                            "title": "告警",
                            "capabilityId": "real-alarms",
                            "visualType": "table",
                        },
                    ],
                ),
            ],
        )
        plan = await build_screen_plan("查询工单和告警", model=model)
        caps = {c.capability_id for c in plan.components}
        assert "capability-gap" not in caps


class TestScreenTitleHeuristic:
    def test_strips_leading_verb(self) -> None:
        title = derive_screen_title("查询最近15分钟告警")
        assert title
        assert "查询" not in title
        assert "最近15分钟告警" == title

    def test_strips_big_screen_noun(self) -> None:
        title = derive_screen_title("做一个日志和告警的综合分析大屏")
        assert title
        assert "大屏" not in title
        assert "综合分析" in title

    def test_override_wins(self) -> None:
        assert derive_screen_title("查询告警", "NOC 一号屏") == "NOC 一号屏"

    def test_empty_after_strip_falls_back_to_default(self) -> None:
        assert derive_screen_title("大屏") == DEFAULT_SCREEN_NAME

    def test_heuristic_truncates_to_20(self) -> None:
        title = derive_screen_title("告警" * 40)
        assert 0 < len(title) <= 20

    def test_clamp_bounds_to_max(self) -> None:
        clamped = clamp_screen_title("屏" * 100)
        assert len(clamped) == MAX_SCREEN_TITLE_LENGTH


class TestScreenTitlePlan:
    async def test_llm_screen_title_lands_on_plan(self) -> None:
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
                    screenTitle="核心告警态势",
                ),
            ],
        )
        plan = await build_screen_plan(
            "做一个日志和告警的综合分析大屏",
            model=model,
        )
        assert plan.screen_title == "核心告警态势"

    async def test_llm_without_screen_title_uses_heuristic(self) -> None:
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
                ),
            ],
        )
        plan = await build_screen_plan(
            "做一个日志和告警的综合分析大屏",
            model=model,
        )
        assert plan.screen_title
        assert "大屏" not in plan.screen_title

    async def test_requested_title_wins_screen_title(self) -> None:
        spy = SpyModel()
        plan = await build_screen_plan(
            "查询最近15分钟告警",
            title="NOC 一号屏",
            model=spy,
        )
        assert plan.screen_title == "NOC 一号屏"

    def test_guardrail_screen_title_non_empty(self) -> None:
        plan = build_guardrail_plan(
            prompt="帮我做一个量子计算监控大屏",
            title="",
        )
        assert plan.screen_title
        assert "监控大屏" not in plan.screen_title

    async def test_degraded_fallback_screen_title_non_empty(self) -> None:
        model = SpyModel(["不是 JSON", "还不是 JSON", "依旧不是 JSON"])
        plan = await build_screen_plan(
            "做一个日志和告警的综合分析大屏",
            model=model,
            max_repair=2,
        )
        assert plan.degraded is True
        assert plan.screen_title
