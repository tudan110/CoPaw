# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen.pipeline import (
    DRAFT_STAGES,
    run_draft_pipeline,
)


class FakeModel:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls = 0

    async def __call__(self, _messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        if not self.responses:
            raise AssertionError("LLM should not be called")
        return {"text": self.responses.pop(0)}


def _mock_workorders(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    from qwenpaw.extensions.integrations import order_workflow

    calls: list[int] = []

    def _fake(**_kw: Any) -> dict[str, Any]:
        calls.append(1)
        return {
            "source": "live",
            "total": 2,
            "items": [
                {"id": "wo-1", "title": "磁盘工单", "status": "todo"},
                {"id": "wo-2", "title": "网络工单", "status": "done"},
            ],
            "stats": {"todo": 1},
        }

    monkeypatch.setattr(order_workflow, "query_order_workorders", _fake)
    return calls


class TestDraftPipeline:
    async def test_stages_progress_in_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _mock_workorders(monkeypatch)
        stages: list[str] = []
        screen = await run_draft_pipeline(
            prompt="查询今日工单",
            model=FakeModel(),
            on_stage=lambda stage, _msg: stages.append(stage),
        )
        assert stages == list(DRAFT_STAGES)
        assert screen["id"].startswith("screen-")

    async def test_screen_has_legacy_shape_and_real_data(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _mock_workorders(monkeypatch)
        screen = await run_draft_pipeline(
            prompt="查询今日工单",
            title="工单大屏",
            requested_by="tester",
            model=FakeModel(),
        )
        assert screen["name"] == "工单大屏"
        assert screen["owner"] == "tester"
        component = screen["components"][0]
        assert component["capabilityId"] == "workorders"
        assert component["data"]["sourceStatus"] == "live"
        assert component["data"]["rows"][0]["id"] == "wo-1"
        assert screen["dataBindings"][0]["pluginId"] == "workorders"
        assert screen["versions"][0]["versionId"] == "v1"
        intents = screen["aiConversationContext"]["dataIntentPlan"]["intents"]
        assert intents[0]["dataQuality"] == "live"

    async def test_fetch_once_across_same_capability_components(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = _mock_workorders(monkeypatch)
        plan_json = json.dumps(
            {
                "name": "工单大屏",
                "components": [
                    {
                        "title": "工单总数",
                        "capabilityId": "workorders",
                        "visualType": "metric-card",
                        "queryParams": {"timeRange": "today", "limit": 20},
                    },
                    {
                        "title": "工单列表",
                        "capabilityId": "workorders",
                        "visualType": "table",
                        "queryParams": {"timeRange": "today", "limit": 20},
                    },
                ],
            },
            ensure_ascii=False,
        )
        screen = await run_draft_pipeline(
            prompt="工单处理分析大屏",
            model=FakeModel([plan_json]),
        )
        workorder_components = [
            c
            for c in screen["components"]
            if c["capabilityId"] == "workorders"
        ]
        assert len(workorder_components) == 2
        assert len(calls) == 1  # fetch-once shared both components

    async def test_failed_capability_does_not_block_screen(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.integrations import (
            order_workflow,
            portal_real_alarms,
            working_secrets,
        )

        monkeypatch.setattr(
            working_secrets,
            "ensure_working_secrets_loaded",
            lambda: None,
        )
        monkeypatch.setattr(
            portal_real_alarms,
            "query_portal_real_alarms",
            lambda **_kw: (_ for _ in ()).throw(
                ConnectionError("alarm api down"),
            ),
        )
        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: {
                "source": "live",
                "items": [{"id": "wo-1", "title": "x"}],
            },
        )
        screen = await run_draft_pipeline(
            prompt="查询工单和告警",
            model=FakeModel(),
        )
        by_capability = {c["capabilityId"]: c for c in screen["components"]}
        assert by_capability["real-alarms"]["data"]["sourceStatus"] == "failed"
        assert "alarm api down" in (
            by_capability["real-alarms"]["data"]["message"]
        )
        assert by_capability["workorders"]["data"]["sourceStatus"] == "live"

    async def test_degraded_plan_marks_context(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _mock_workorders(monkeypatch)
        screen = await run_draft_pipeline(
            prompt="做一个工单处理效率的深度分析大屏",
            model=FakeModel(["垃圾输出", "垃圾输出", "垃圾输出"]),
        )
        assert screen["aiConversationContext"]["degraded"] is True
        assert screen["components"]

    async def test_empty_prompt_raises(self) -> None:
        with pytest.raises(ValueError):
            await run_draft_pipeline(prompt="   ", model=FakeModel())


class TestRefreshScreenData:
    @staticmethod
    def _screen() -> dict[str, Any]:
        return {
            "id": "screen-x",
            "name": "刷新测试",
            "layout": {"type": "grid"},
            "theme": {"mode": "dark"},
            "components": [
                {
                    "id": "c-wo",
                    "type": "table",
                    "capabilityId": "workorders",
                    "pluginId": "workorders",
                    "queryParams": {"timeRange": "today", "limit": 20},
                    "visualSpec": {"composition": "primary"},
                    "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                    "data": {"sourceStatus": "live", "rows": [{"id": "old"}]},
                },
                {
                    "id": "c-wo-2",
                    "type": "metric-card",
                    "capabilityId": "workorders",
                    "pluginId": "workorders",
                    "queryParams": {"timeRange": "today", "limit": 20},
                    "visualSpec": {},
                    "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 4},
                    "data": {"sourceStatus": "live", "rows": [{"id": "old"}]},
                },
            ],
            "versions": [{"versionId": "v1"}],
        }

    async def test_refresh_updates_data_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.ai_big_screen.pipeline import (
            refresh_screen_data,
        )

        calls = _mock_workorders(monkeypatch)
        screen = self._screen()
        before_layout = dict(screen["components"][0]["layoutPosition"])
        refreshed = await refresh_screen_data(screen)
        by_id = {c["id"]: c for c in refreshed["components"]}
        assert by_id["c-wo"]["data"]["rows"][0]["id"] == "wo-1"  # 新数据
        assert by_id["c-wo"]["layoutPosition"] == before_layout  # 版式不动
        assert by_id["c-wo"]["visualSpec"] == {"composition": "primary"}
        assert refreshed["versions"] == [{"versionId": "v1"}]  # 无新版本
        assert len(calls) == 1  # fetch-once 共享两个组件

    async def test_refresh_failure_becomes_failed_badge(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.ai_big_screen.pipeline import (
            refresh_screen_data,
        )
        from qwenpaw.extensions.integrations import order_workflow

        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: (_ for _ in ()).throw(
                ConnectionError("refresh outage"),
            ),
        )
        refreshed = await refresh_screen_data(self._screen())
        component = refreshed["components"][0]
        assert component["data"]["sourceStatus"] == "failed"
        assert "refresh outage" in component["data"]["message"]
