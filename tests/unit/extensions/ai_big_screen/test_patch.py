# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen.patch import apply_patch


class FakeModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def __call__(self, _messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        return {"text": self.responses.pop(0)}


def _ops(operations: list[dict[str, Any]], summary: str = "变更") -> str:
    return json.dumps(
        {"summary": summary, "operations": operations},
        ensure_ascii=False,
    )


def _screen() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "id": "screen-x",
        "name": "测试屏",
        "description": "",
        "owner": "tester",
        "status": "draft",
        "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
        "theme": {"mode": "dark", "palette": "industrial"},
        "components": [
            {
                "id": "comp-alarms",
                "type": "alarm-stream",
                "title": "告警流",
                "description": "",
                "pluginId": "real-alarms",
                "capabilityId": "real-alarms",
                "queryParams": {"limit": 50},
                "visualConfig": {
                    "palette": "industrial",
                    "emphasis": "standard",
                },
                "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                "data": {"sourceStatus": "live", "rows": [{"title": "a"}]},
            },
            {
                "id": "comp-logs",
                "type": "table",
                "title": "系统日志",
                "description": "",
                "pluginId": "system-logs",
                "capabilityId": "system-logs",
                "queryParams": {"lookbackMinutes": 15, "limit": 50},
                "visualConfig": {
                    "palette": "industrial",
                    "emphasis": "standard",
                },
                "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 4},
                "data": {"sourceStatus": "live", "rows": [{"message": "m"}]},
            },
        ],
        "dataBindings": [
            {"id": "binding-keep1", "componentId": "comp-alarms"},
            {"id": "binding-keep2", "componentId": "comp-logs"},
        ],
        "permissions": {"visibility": "private", "roles": []},
        "versions": [{"versionId": "v1"}],
        "publishTargets": [],
        "aiConversationContext": {"sourcePrompt": "初始 prompt"},
        "createdAt": "2026-01-01T00:00:00",
        "updatedAt": "2026-01-01T00:00:00",
    }


def _block_all_fetches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make every capability fetch fail loudly if invoked."""
    from qwenpaw.extensions.ai_big_screen.capabilities import descriptors

    invoked: list[str] = []

    def _make(name: str):
        def _boom(_params: Any) -> dict[str, Any]:
            invoked.append(name)
            raise AssertionError(f"unexpected fetch: {name}")

        return _boom

    for capability_id in list(descriptors.FETCHERS):
        monkeypatch.setitem(
            descriptors.FETCHERS,
            capability_id,
            _make(capability_id),
        )
    return invoked


def _allow_log_fetch(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from qwenpaw.extensions.ai_big_screen.capabilities import descriptors

    calls: list[dict[str, Any]] = []

    def _fake(params: Any) -> dict[str, Any]:
        calls.append(dict(params))
        return {
            "sourceStatus": "live",
            "rows": [{"message": "refetched"}],
            "total": 1,
        }

    monkeypatch.setitem(descriptors.FETCHERS, "system-logs", _fake)
    return calls


class TestVisualOnlyPatch:
    async def test_title_change_no_refetch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invoked = _block_all_fetches(monkeypatch)
        screen = _screen()
        outcome = await apply_patch(
            screen=screen,
            instruction="把告警流标题改成实时告警监控",
            selected_component_ids=["comp-alarms"],
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "setComponentTitle",
                                "componentId": "comp-alarms",
                                "value": "实时告警监控",
                            },
                        ],
                    ),
                ],
            ),
        )
        assert not invoked  # 数据不动
        components = {c["id"]: c for c in outcome["screen"]["components"]}
        assert components["comp-alarms"]["title"] == "实时告警监控"
        # original data preserved
        assert components["comp-alarms"]["data"]["rows"] == [{"title": "a"}]

    async def test_ops_outside_selection_dropped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        outcome = await apply_patch(
            screen=_screen(),
            instruction="把告警流标题改一下",
            selected_component_ids=["comp-alarms"],
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "setComponentTitle",
                                "componentId": "comp-alarms",
                                "value": "新告警标题",
                            },
                            {
                                "op": "setComponentTitle",
                                "componentId": "comp-logs",
                                "value": "越权改名",
                            },
                        ],
                    ),
                ],
            ),
        )
        components = {c["id"]: c for c in outcome["screen"]["components"]}
        assert components["comp-alarms"]["title"] == "新告警标题"
        assert components["comp-logs"]["title"] == "系统日志"  # untouched

    async def test_theme_palette_whitelisted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        outcome = await apply_patch(
            screen=_screen(),
            instruction="整体换成领导驾驶舱风格",
            model=FakeModel(
                [
                    _ops(
                        [{"op": "setThemePalette", "value": "executive"}],
                    ),
                ],
            ),
        )
        assert outcome["screen"]["theme"]["palette"] == "executive"


class TestDataAffectingPatch:
    async def test_query_param_change_refetches_only_target(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)  # alarms must NOT refetch
        log_calls = _allow_log_fetch(monkeypatch)
        outcome = await apply_patch(
            screen=_screen(),
            instruction="日志改成最近60分钟",
            selected_component_ids=["comp-logs"],
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "setComponentQueryParams",
                                "componentId": "comp-logs",
                                "value": {"lookbackMinutes": 60},
                            },
                        ],
                    ),
                ],
            ),
        )
        assert len(log_calls) == 1
        assert log_calls[0]["lookbackMinutes"] == 60
        components = {c["id"]: c for c in outcome["screen"]["components"]}
        assert components["comp-logs"]["data"]["rows"] == [
            {"message": "refetched"},
        ]
        assert components["comp-logs"]["queryParams"]["lookbackMinutes"] == 60

    async def test_add_component_fetches_its_data(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        log_calls = _allow_log_fetch(monkeypatch)
        outcome = await apply_patch(
            screen=_screen(),
            instruction="再加一个日志风险分析模块",
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "addComponent",
                                "value": {
                                    "title": "日志风险分析",
                                    "capabilityId": "system-logs",
                                    "visualType": "table",
                                    "queryParams": {
                                        "lookbackMinutes": 30,
                                        "limit": 50,
                                    },
                                },
                            },
                        ],
                    ),
                ],
            ),
        )
        assert len(log_calls) == 1
        screen = outcome["screen"]
        assert len(screen["components"]) == 3
        new_component = screen["components"][-1]
        assert new_component["capabilityId"] == "system-logs"
        assert new_component["data"]["rows"] == [{"message": "refetched"}]
        assert len(screen["dataBindings"]) == 3


class TestDryRunPreview:
    async def test_preview_mutates_copy_only_no_version(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import copy as _copy

        _block_all_fetches(monkeypatch)
        screen = _screen()
        before = _copy.deepcopy(screen)
        outcome = await apply_patch(
            screen=screen,
            instruction="把告警流标题改成实时告警，整体换成驾驶舱风格",
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "setComponentTitle",
                                "componentId": "comp-alarms",
                                "value": "实时告警",
                            },
                            {"op": "setThemePalette", "value": "executive"},
                        ],
                    ),
                ],
            ),
            dry_run=True,
        )
        assert screen == before  # 原资产完全不动
        assert outcome["preview"] is True
        assert outcome["version"] is None
        preview_screen = outcome["screen"]
        assert preview_screen["theme"]["palette"] == "executive"
        assert preview_screen["versions"] == [{"versionId": "v1"}]
        by_id = {c["id"]: c for c in preview_screen["components"]}
        assert by_id["comp-alarms"]["title"] == "实时告警"

        diff = {(d["componentId"], d["field"]): d for d in outcome["diff"]}
        title_diff = diff[("comp-alarms", "title")]
        assert title_diff["before"] == "告警流"
        assert title_diff["after"] == "实时告警"
        theme_diff = diff[("", "theme.palette")]
        assert theme_diff["before"] == "industrial"
        assert theme_diff["after"] == "executive"

    async def test_preview_query_param_change_diffs_and_refetches_copy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        log_calls = _allow_log_fetch(monkeypatch)
        screen = _screen()
        outcome = await apply_patch(
            screen=screen,
            instruction="日志改成最近60分钟",
            selected_component_ids=["comp-logs"],
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "setComponentQueryParams",
                                "componentId": "comp-logs",
                                "value": {"lookbackMinutes": 60},
                            },
                        ],
                    ),
                ],
            ),
            dry_run=True,
        )
        # 预览取的是真数据（拷贝上），原件数据/参数不动
        assert len(log_calls) == 1
        assert screen["components"][1]["queryParams"]["lookbackMinutes"] == 15
        assert screen["components"][1]["data"]["rows"] == [{"message": "m"}]
        preview_logs = {c["id"]: c for c in outcome["screen"]["components"]}[
            "comp-logs"
        ]
        assert preview_logs["data"]["rows"] == [{"message": "refetched"}]
        params_diff = [
            d
            for d in outcome["diff"]
            if d["componentId"] == "comp-logs" and d["field"] == "queryParams"
        ]
        assert params_diff
        assert params_diff[0]["after"]["lookbackMinutes"] == 60

    async def test_preview_add_component_appears_in_diff(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        _allow_log_fetch(monkeypatch)
        screen = _screen()
        outcome = await apply_patch(
            screen=screen,
            instruction="再加一个日志风险分析模块",
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "addComponent",
                                "value": {
                                    "title": "日志风险分析",
                                    "capabilityId": "system-logs",
                                    "visualType": "table",
                                    "queryParams": {"lookbackMinutes": 30},
                                },
                            },
                        ],
                    ),
                ],
            ),
            dry_run=True,
        )
        assert len(screen["components"]) == 2  # 原件不动
        assert len(outcome["screen"]["components"]) == 3
        added = [
            d
            for d in outcome["diff"]
            if d["field"] == "component" and d["before"] is None
        ]
        assert len(added) == 1
        assert added[0]["after"]["capabilityId"] == "system-logs"

    async def test_real_patch_has_no_preview_keys_in_wire_shape(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        outcome = await apply_patch(
            screen=_screen(),
            instruction="换驾驶舱风格",
            model=FakeModel(
                [_ops([{"op": "setThemePalette", "value": "executive"}])],
            ),
        )
        assert set(outcome) == {"screen", "version", "summary"}


class TestVersioningAndContext:
    async def test_version_appended_and_bindings_preserved(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        outcome = await apply_patch(
            screen=_screen(),
            instruction="改标题",
            selected_component_ids=["comp-alarms"],
            model=FakeModel(
                [
                    _ops(
                        [
                            {
                                "op": "setComponentTitle",
                                "componentId": "comp-alarms",
                                "value": "X",
                            },
                        ],
                        summary="改了标题",
                    ),
                ],
            ),
        )
        screen = outcome["screen"]
        assert [v["versionId"] for v in screen["versions"]] == ["v1", "v2"]
        assert outcome["version"]["basedOnVersionId"] == "v1"
        assert outcome["summary"] == "改了标题"
        binding_ids = {
            b["componentId"]: b["id"] for b in screen["dataBindings"]
        }
        assert binding_ids["comp-alarms"] == "binding-keep1"
        context = screen["aiConversationContext"]
        assert context["lastInstruction"] == "改标题"
        assert context["selectedComponentIds"] == ["comp-alarms"]

    async def test_degraded_patch_makes_no_changes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _block_all_fetches(monkeypatch)
        original_titles = [c["title"] for c in _screen()["components"]]
        outcome = await apply_patch(
            screen=_screen(),
            instruction="搞点神秘操作",
            model=FakeModel(["不是 JSON", "也不是", "还不是"]),
        )
        screen = outcome["screen"]
        assert [c["title"] for c in screen["components"]] == original_titles
        assert "未生成" in outcome["summary"] or "降级" in outcome["summary"]

    async def test_unknown_selected_component_raises(self) -> None:
        with pytest.raises(ValueError):
            await apply_patch(
                screen=_screen(),
                instruction="改标题",
                selected_component_ids=["comp-nope"],
                model=FakeModel([]),
            )

    async def test_empty_instruction_raises(self) -> None:
        with pytest.raises(ValueError):
            await apply_patch(
                screen=_screen(),
                instruction="  ",
                model=FakeModel([]),
            )
