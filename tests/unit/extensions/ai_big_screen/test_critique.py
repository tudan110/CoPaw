# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen.critique import (
    CRITIQUE_ALLOWED_OPS,
    run_critique,
    summarize_screen_spec,
)
from qwenpaw.extensions.ai_big_screen.intent import ALLOWED_PALETTES

PALETTES = sorted(ALLOWED_PALETTES)
BASE_PALETTE = PALETTES[0]
TARGET_PALETTE = PALETTES[1]


class ScriptedModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def __call__(self, _messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        if not self.responses:
            raise AssertionError("model exhausted")
        return {"text": self.responses.pop(0)}


def _screen() -> dict[str, Any]:
    return {
        "id": "screen-1",
        "name": "工单大屏",
        "theme": {"palette": BASE_PALETTE},
        "components": [
            {
                "id": "comp-1",
                "type": "table",
                "capabilityId": "workorders",
                "pluginId": "workorders",
                "title": "工单明细",
                "queryParams": {"timeRange": "today"},
                "visualConfig": {"palette": BASE_PALETTE},
                "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                "data": {
                    "sourceStatus": "live",
                    "rows": [{"id": "wo-1", "secret": "raw-row"}],
                },
            },
        ],
        "dataBindings": [],
        "aiConversationContext": {"mode": "ai-plan"},
    }


def _critique_json(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "score": 72,
        "issues": ["标题不够具体"],
        "operations": [
            {
                "op": "setComponentTitle",
                "componentId": "comp-1",
                "value": "今日工单明细",
            },
            {
                "op": "setComponentQueryParams",
                "componentId": "comp-1",
                "value": {"timeRange": "7d"},
            },
            {"op": "setThemePalette", "value": TARGET_PALETTE},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class TestRunCritique:
    async def test_applies_visual_ops_and_filters_data_ops(self) -> None:
        screen = _screen()
        info = await run_critique(
            screen,
            model=ScriptedModel([_critique_json()]),
        )
        assert info is not None
        assert info["score"] == 72
        assert info["issuesCount"] == 1
        assert info["applied"] == ["setComponentTitle", "setThemePalette"]
        component = screen["components"][0]
        assert component["title"] == "今日工单明细"
        # the data-affecting op must be filtered, never applied
        assert component["queryParams"] == {"timeRange": "today"}
        assert screen["theme"]["palette"] == TARGET_PALETTE
        assert screen["aiConversationContext"]["critique"] == info

    async def test_invalid_json_skips_silently(self) -> None:
        screen = _screen()
        before = copy.deepcopy(screen)
        info = await run_critique(
            screen,
            model=ScriptedModel(["垃圾输出", "还是垃圾"]),
            max_repair=1,
        )
        assert info is None
        assert screen == before

    async def test_env_off_disables_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AI_BIG_SCREEN_CRITIQUE", "off")
        screen = _screen()
        before = copy.deepcopy(screen)
        model = ScriptedModel([])
        info = await run_critique(screen, model=model)
        assert info is None
        assert model.calls == 0
        assert screen == before

    async def test_out_of_range_score_triggers_repair(self) -> None:
        screen = _screen()
        info = await run_critique(
            screen,
            model=ScriptedModel(
                [
                    _critique_json(score=150),
                    _critique_json(score=88, operations=[]),
                ],
            ),
            max_repair=1,
        )
        assert info is not None
        assert info["score"] == 88

    async def test_clean_screen_no_ops(self) -> None:
        screen = _screen()
        info = await run_critique(
            screen,
            model=ScriptedModel(
                [_critique_json(score=95, issues=[], operations=[])],
            ),
        )
        assert info == {
            "score": 95,
            "issuesCount": 0,
            "issues": [],
            "applied": [],
        }
        assert screen["components"][0]["title"] == "工单明细"

    def test_summary_never_leaks_data_rows(self) -> None:
        summary = summarize_screen_spec(_screen())
        assert "raw-row" not in json.dumps(summary, ensure_ascii=False)
        component = summary["components"][0]
        assert component["sourceStatus"] == "live"
        assert component["type"] == "table"

    def test_summary_includes_row_count_for_density(self) -> None:
        summary = summarize_screen_spec(_screen())
        component = summary["components"][0]
        # the base _screen() fixture seeds one data row → rowCount 1
        assert component["rowCount"] == 1
        assert "composition" in component

    def test_composition_op_is_whitelisted(self) -> None:
        assert "setComponentComposition" in CRITIQUE_ALLOWED_OPS

    def test_whitelist_excludes_data_semantics(self) -> None:
        assert "setComponentQueryParams" not in CRITIQUE_ALLOWED_OPS
        assert "setComponentFields" not in CRITIQUE_ALLOWED_OPS
        assert "addComponent" not in CRITIQUE_ALLOWED_OPS


class TestPipelineWiring:
    @staticmethod
    def _mock_workorders(monkeypatch: pytest.MonkeyPatch) -> None:
        from qwenpaw.extensions.integrations import order_workflow

        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: {
                "source": "live",
                "total": 1,
                "items": [{"id": "wo-1", "title": "磁盘工单"}],
            },
        )

    async def test_llm_path_runs_critique(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.ai_big_screen.pipeline import (
            run_draft_pipeline,
        )

        monkeypatch.delenv("AI_BIG_SCREEN_CRITIQUE", raising=False)
        self._mock_workorders(monkeypatch)
        plan_json = json.dumps(
            {
                "name": "工单大屏",
                "components": [
                    {
                        "title": "工单列表",
                        "capabilityId": "workorders",
                        "visualType": "table",
                        "queryParams": {"timeRange": "today"},
                    },
                ],
            },
            ensure_ascii=False,
        )

        class CritiqueAwareModel:
            """First call: the plan. Second call: reads the real
            component id out of the critic's spec summary — component
            ids carry a random suffix, exactly what a real critic
            must echo back for its ops to land."""

            def __init__(self) -> None:
                self.calls = 0

            async def __call__(
                self,
                messages: list[dict[str, str]],
            ) -> Any:
                self.calls += 1
                if self.calls == 1:
                    return {"text": plan_json}
                content = messages[-1]["content"]
                spec = json.loads(content[content.find("{") :])
                component_id = spec["components"][0]["id"]
                return {
                    "text": json.dumps(
                        {
                            "score": 81,
                            "issues": ["标题可以更具体"],
                            "operations": [
                                {
                                    "op": "setComponentTitle",
                                    "componentId": component_id,
                                    "value": "评审后的工单明细",
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                }

        model = CritiqueAwareModel()
        screen = await run_draft_pipeline(
            prompt="工单处理分析大屏",
            model=model,
        )
        assert model.calls == 2
        critique_ctx = screen["aiConversationContext"]["critique"]
        assert critique_ctx["score"] == 81
        assert critique_ctx["applied"] == ["setComponentTitle"]
        assert "评审后的工单明细" in [c["title"] for c in screen["components"]]

    async def test_fast_path_skips_critique(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.ai_big_screen import pipeline

        self._mock_workorders(monkeypatch)
        calls: list[int] = []

        async def _recorder(*_a: Any, **_kw: Any) -> None:
            calls.append(1)

        monkeypatch.setattr(pipeline, "run_critique", _recorder)
        screen = await pipeline.run_draft_pipeline(
            prompt="查询今日工单",
            model=ScriptedModel([]),
        )
        assert not calls
        assert "critique" not in screen["aiConversationContext"]

    async def test_degraded_plan_skips_critique(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.ai_big_screen import pipeline

        self._mock_workorders(monkeypatch)
        calls: list[int] = []

        async def _recorder(*_a: Any, **_kw: Any) -> None:
            calls.append(1)

        monkeypatch.setattr(pipeline, "run_critique", _recorder)
        screen = await pipeline.run_draft_pipeline(
            prompt="做一个工单处理效率的深度分析大屏",
            model=ScriptedModel(["垃圾输出", "垃圾输出", "垃圾输出"]),
        )
        assert not calls
        assert screen["aiConversationContext"]["degraded"] is True
