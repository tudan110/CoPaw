# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.extensions.ai_big_screen.schemas import (
    CapabilityResult,
    PatchOperation,
    PatchPlan,
    PlanComponent,
    ScreenPlan,
    parse_screen_plan,
)


class TestCapabilityResult:
    def test_source_status_enum(self) -> None:
        for status in ("live", "empty", "failed", "gap"):
            result = CapabilityResult(
                capability_id="real-alarms",
                source_status=status,
            )
            assert result.source_status == status

    def test_rejects_unknown_status(self) -> None:
        with pytest.raises(ValidationError):
            CapabilityResult(
                capability_id="real-alarms",
                source_status="unavailable",  # legacy value must be mapped
            )

    def test_to_legacy_data_shape(self) -> None:
        result = CapabilityResult(
            capability_id="system-logs",
            source_status="live",
            rows=[{"time": "10:00", "message": "boot"}],
            columns=[{"key": "time", "label": "时间"}],
            total=1,
            message="",
        )
        data = result.to_legacy_data()
        assert data["sourceStatus"] == "live"
        assert data["rows"] == [{"time": "10:00", "message": "boot"}]
        assert data["columns"][0]["key"] == "time"
        assert data["total"] == 1


class TestScreenPlan:
    def test_accepts_camel_case_llm_payload(self) -> None:
        plan = ScreenPlan.model_validate(
            {
                "name": "运维大屏",
                "components": [
                    {
                        "id": "c1",
                        "type": "table",
                        "title": "告警",
                        "capabilityId": "real-alarms",
                        "queryParams": {"limit": 10},
                    },
                ],
            },
        )
        assert plan.name == "运维大屏"
        assert plan.components[0].capability_id == "real-alarms"
        assert plan.components[0].query_params == {"limit": 10}

    def test_defaults(self) -> None:
        plan = ScreenPlan.model_validate(
            {"name": "x", "components": [{"id": "c1"}]},
        )
        component = plan.components[0]
        assert component.type == "table"
        assert component.title == ""
        assert component.visual_spec == {}
        assert plan.degraded is False
        assert plan.summary == ""

    def test_drops_components_without_id(self) -> None:
        plan = ScreenPlan.model_validate(
            {
                "name": "x",
                "components": [
                    {"type": "table"},
                    {"id": "", "type": "table"},
                    {"id": "ok", "type": "table"},
                ],
            },
        )
        assert [c.id for c in plan.components] == ["ok"]

    def test_component_id_sanitized_length(self) -> None:
        plan = ScreenPlan.model_validate(
            {"name": "x", "components": [{"id": "a" * 500}]},
        )
        assert len(plan.components[0].id) <= 64


class TestParseScreenPlan:
    def test_parses_fenced_json(self) -> None:
        text = (
            '前言\n```json\n{"name": "屏", "components": [{"id": "c1"}]}\n```\n尾注'
        )
        plan = parse_screen_plan(text)
        assert plan.name == "屏"
        assert plan.components[0].id == "c1"

    def test_parses_bare_json(self) -> None:
        plan = parse_screen_plan('{"name": "屏", "components": []}')
        assert plan.name == "屏"

    def test_invalid_json_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_screen_plan("这不是 JSON")

    def test_schema_violation_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_screen_plan('{"name": "屏", "components": "not-a-list"}')


class TestPatchPlan:
    def test_operation_whitelist(self) -> None:
        plan = PatchPlan.model_validate(
            {
                "operations": [
                    {
                        "op": "setComponentTitle",
                        "componentId": "c1",
                        "value": "新标题",
                    },
                ],
                "summary": "改标题",
            },
        )
        assert plan.operations[0].op == "setComponentTitle"
        assert plan.operations[0].component_id == "c1"

    def test_rejects_unknown_operation(self) -> None:
        with pytest.raises(ValidationError):
            PatchOperation.model_validate(
                {"op": "executeArbitraryJs", "componentId": "c1"},
            )

    def test_all_legacy_operations_accepted(self) -> None:
        for op in (
            "addComponent",
            "setThemePalette",
            "setComponentPalette",
            "setComponentType",
            "setComponentLayout",
            "setComponentTitle",
            "setComponentQueryParams",
            "setComponentFields",
        ):
            operation = PatchOperation.model_validate(
                {"op": op, "componentId": "c1", "value": {}},
            )
            assert operation.op == op


class TestPlanComponent:
    def test_round_trips_camel_case(self) -> None:
        component = PlanComponent.model_validate(
            {
                "id": "c1",
                "capabilityId": "workorders",
                "queryParams": {"timeRange": "today"},
                "visualSpec": {"kind": "signal-stream"},
                "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
            },
        )
        dumped = component.model_dump(by_alias=True)
        assert dumped["capabilityId"] == "workorders"
        assert dumped["queryParams"] == {"timeRange": "today"}
        assert dumped["visualSpec"] == {"kind": "signal-stream"}
        assert dumped["layoutPosition"] == {"x": 0, "y": 0, "w": 6, "h": 4}
