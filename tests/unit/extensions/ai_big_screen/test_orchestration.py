# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.extensions.ai_big_screen.orchestration import (
    assemble_component,
    assemble_screen,
    build_binding,
    build_data_intent_plan,
    build_version,
    build_visual_plan,
    extract_capability_gaps,
)
from qwenpaw.extensions.ai_big_screen.schemas import (
    CapabilityResult,
    PlanComponent,
    ScreenPlan,
)


def _plan_component(**overrides: object) -> PlanComponent:
    payload: dict[str, object] = {
        "id": "component-1-abc123",
        "type": "alarm-stream",
        "title": "实时告警流",
        "description": "最近活动告警",
        "capabilityId": "real-alarms",
        "queryParams": {"limit": 50, "lookbackMinutes": 15},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "visualSpec": {"composition": "primary"},
        "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
    }
    payload.update(overrides)
    return PlanComponent.model_validate(payload)


def _live_result(**overrides: object) -> CapabilityResult:
    payload: dict[str, object] = {
        "capabilityId": "real-alarms",
        "sourceStatus": "live",
        "rows": [{"title": "CPU 高", "eventTime": "10:00", "level": "high"}],
        "total": 1,
    }
    payload.update(overrides)
    return CapabilityResult.model_validate(payload)


class TestAssembleComponent:
    def test_merges_plan_and_data(self) -> None:
        component = assemble_component(_plan_component(), _live_result())
        assert component["id"] == "component-1-abc123"
        assert component["type"] == "alarm-stream"
        assert component["pluginId"] == "real-alarms"
        assert component["capabilityId"] == "real-alarms"
        assert component["data"]["sourceStatus"] == "live"
        assert component["data"]["rows"][0]["title"] == "CPU 高"
        assert component["visualSpec"] == {"composition": "primary"}
        assert component["interactions"] == {
            "selectable": True,
            "selectionMode": "region",
        }
        assert component["refreshInterval"] == 60  # real-alarms policy

    def test_failed_result_keeps_component_with_failed_data(self) -> None:
        failed = CapabilityResult(
            capability_id="real-alarms",
            source_status="failed",
            message="ConnectionError: backend down",
        )
        component = assemble_component(_plan_component(), failed)
        assert component["data"]["sourceStatus"] == "failed"
        assert "backend down" in component["data"]["message"]

    def test_missing_result_yields_empty_data(self) -> None:
        component = assemble_component(_plan_component(), None)
        assert component["data"] == {}


class TestBinding:
    def test_binding_carries_capability_policies(self) -> None:
        component = assemble_component(_plan_component(), _live_result())
        binding = build_binding(component)
        assert binding["componentId"] == "component-1-abc123"
        assert binding["pluginId"] == "real-alarms"
        assert binding["input"] == {"limit": 50, "lookbackMinutes": 15}
        assert binding["refreshPolicy"] == {"intervalSeconds": 60}
        assert binding["cachePolicy"] == {"ttlSeconds": 60}
        assert binding["permissionScope"] == "alarm:read"
        assert binding["sourceDescription"] == "portal-real-alarm-api"


class TestDataIntentPlan:
    def test_intents_reflect_components_and_quality(self) -> None:
        live = assemble_component(_plan_component(), _live_result())
        failed = assemble_component(
            _plan_component(
                id="component-2-def456",
                title="系统日志",
                capabilityId="system-logs",
                type="table",
            ),
            CapabilityResult(
                capability_id="system-logs",
                source_status="failed",
                message="超时",
            ),
        )
        plan = build_data_intent_plan(
            prompt="查询日志和告警",
            components=[live, failed],
            mode="ai-plan",
            source="normalized-components",
        )
        assert plan["version"] == 1
        assert len(plan["intents"]) == 2
        assert plan["intents"][0]["capabilityId"] == "real-alarms"
        assert plan["intents"][0]["dataQuality"] == "live"
        assert plan["intents"][1]["dataQuality"] == "failed"

    def test_gap_intent_carries_gap_fields(self) -> None:
        gap = assemble_component(
            _plan_component(
                id="component-3-gap",
                title="待接入：K8s 水位",
                capabilityId="capability-gap",
                type="table",
                queryParams={
                    "requestedData": "K8s 水位",
                    "reason": "未接入",
                },
            ),
            CapabilityResult(
                capability_id="capability-gap",
                source_status="gap",
            ),
        )
        plan = build_data_intent_plan(
            prompt="K8s 水位",
            components=[gap],
            mode="ai-plan",
            source="normalized-components",
        )
        intent_item = plan["intents"][0]
        assert intent_item["gapReason"] == "未接入"
        assert intent_item["requestedData"] == "K8s 水位"


class TestVisualPlanAndGaps:
    def test_visual_plan_items(self) -> None:
        component = assemble_component(_plan_component(), _live_result())
        plan = build_visual_plan(
            components=[component],
            mode="component-state",
        )
        assert plan["items"][0]["componentId"] == "component-1-abc123"
        assert plan["items"][0]["visualType"] == "alarm-stream"
        assert plan["items"][0]["visualSpec"] == {"composition": "primary"}

    def test_extract_capability_gaps(self) -> None:
        gap = assemble_component(
            _plan_component(
                id="component-3-gap",
                capabilityId="capability-gap",
                type="table",
                queryParams={
                    "requestedData": "K8s 水位",
                    "reason": "未接入",
                    "suggestedSkillName": "k8s-metrics",
                },
            ),
            None,
        )
        gaps = extract_capability_gaps([gap])
        assert gaps == [
            {
                "componentId": "component-3-gap",
                "requestedData": "K8s 水位",
                "reason": "未接入",
                "suggestedSkillName": "k8s-metrics",
                "suggestedApi": "",
            },
        ]


class TestAssembleScreen:
    def _screen(self) -> dict:
        plan = ScreenPlan(
            name="NOC 大屏",
            description="测试",
            summary="摘要",
            theme={"mode": "dark", "palette": "industrial"},
            layout={"type": "grid", "columns": 12, "rowHeight": 84},
            components=[_plan_component()],
        )
        return assemble_screen(
            plan=plan,
            results={"component-1-abc123": _live_result()},
            prompt="查询告警",
            screen_id="screen-test123",
            requested_by="tester",
        )

    def test_legacy_wire_shape(self) -> None:
        screen = self._screen()
        for key in (
            "schemaVersion",
            "id",
            "name",
            "description",
            "owner",
            "status",
            "layout",
            "theme",
            "components",
            "dataBindings",
            "permissions",
            "versions",
            "publishTargets",
            "aiConversationContext",
            "createdAt",
            "updatedAt",
        ):
            assert key in screen, f"missing {key}"
        assert screen["status"] == "draft"
        assert screen["owner"] == "tester"
        assert len(screen["dataBindings"]) == 1
        context = screen["aiConversationContext"]
        assert context["sourcePrompt"] == "查询告警"
        assert context["dataCapabilities"] == ["real-alarms"]
        assert context["dataIntentPlan"]["intents"]
        assert context["visualPlan"]["items"]

    def test_version_snapshot(self) -> None:
        screen = self._screen()
        assert len(screen["versions"]) == 1
        version = screen["versions"][0]
        assert version["versionId"] == "v1"
        assert version["changedByAi"] is True
        assert version["configSnapshot"]["versions"] == []

    def test_banner_title_from_plan_screen_title(self) -> None:
        plan = ScreenPlan(
            name="NOC 大屏",
            screen_title="15分钟告警态势",
            components=[_plan_component()],
        )
        screen = assemble_screen(
            plan=plan,
            results={"component-1-abc123": _live_result()},
            prompt="查询告警",
            screen_id="screen-test123",
        )
        assert screen["title"] == "15分钟告警态势"

    def test_banner_title_falls_back_to_name(self) -> None:
        # A plan with no screenTitle still yields a non-empty banner.
        screen = self._screen()
        assert screen["title"] == "NOC 大屏"

    def test_banner_title_clamped_to_max(self) -> None:
        plan = ScreenPlan(
            name="NOC 大屏",
            screen_title="屏" * 100,
            components=[_plan_component()],
        )
        screen = assemble_screen(
            plan=plan,
            results={"component-1-abc123": _live_result()},
            prompt="查询告警",
            screen_id="screen-test123",
        )
        assert len(screen["title"]) == 60

    def test_degraded_plan_marks_context(self) -> None:
        plan = ScreenPlan(
            name="降级屏",
            components=[_plan_component()],
            degraded=True,
        )
        screen = assemble_screen(
            plan=plan,
            results={},
            prompt="查询告警",
            screen_id="screen-degraded",
            requested_by="tester",
        )
        assert screen["aiConversationContext"]["degraded"] is True


def test_build_version_chains_base() -> None:
    screen = {
        "id": "screen-x",
        "versions": [{"versionId": "v1"}],
        "components": [],
    }
    version = build_version(
        screen=screen,
        version_id="v2",
        summary="patch",
        requested_by="tester",
    )
    assert version["basedOnVersionId"] == "v1"
    assert version["screenId"] == "screen-x"


def test_build_version_carries_summary_and_requested_by() -> None:
    # T-014: every appended version must keep an audit trail (summary +
    # requestedBy), mirroring the legacy changeSummary/changedBy fields.
    version = build_version(
        screen={"id": "screen-x", "versions": [], "components": []},
        version_id="v1",
        summary="改了标题",
        requested_by="tester",
    )
    assert version["summary"] == "改了标题" == version["changeSummary"]
    assert version["requestedBy"] == "tester" == version["changedBy"]


def test_build_version_requested_by_defaults_to_portal() -> None:
    version = build_version(
        screen={"id": "screen-x", "versions": [], "components": []},
        version_id="v1",
        summary="生成草稿",
        requested_by="   ",
    )
    assert version["requestedBy"] == "portal"
