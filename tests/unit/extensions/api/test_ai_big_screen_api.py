# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import inspect
import sys
import time

from fastapi import FastAPI, HTTPException

from qwenpaw.extensions import ai_big_screen_registry as registry
from qwenpaw.extensions.api import ai_big_screen_service
from qwenpaw.extensions.integrations import nightingale_logs
from qwenpaw.extensions.integrations import order_workflow
from qwenpaw.extensions.api.ai_big_screen_api import (
    delete_ai_big_screen,
    generate_ai_big_screen_draft,
    get_ai_big_screen,
    list_ai_big_screens,
    list_ai_big_screen_plugins,
    patch_ai_big_screen,
    publish_ai_big_screen,
    router as ai_big_screen_router,
    save_ai_big_screen,
)
from qwenpaw.extensions.api.portal_backend import router as portal_backend_router
from qwenpaw.extensions.api.ai_big_screen_models import (
    AiBigScreenDraftRequest,
    AiBigScreenPatchRequest,
    AiBigScreenPublishRequest,
    AiBigScreenSaveRequest,
)


def _patch_registry_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        registry,
        "AI_BIG_SCREEN_REGISTRY_PATH",
        tmp_path / "ai_big_screen" / "registry.json",
    )


def _await_if_needed(value):
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _methods_by_path(routes) -> dict[str, set[str]]:
    methods: dict[str, set[str]] = {}
    for route in routes:
        path = getattr(route, "path", "")
        route_methods = getattr(route, "methods", None)
        if not path or not route_methods:
            continue
        methods.setdefault(path, set()).update(route_methods)
    return methods


def _default_draft_plan() -> dict:
    return {
        "name": "15分钟运维态势大屏",
        "description": "围绕日志、告警和资源信息生成的实时运维态势大屏。",
        "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
        "components": [
            {
                "title": "15分钟系统日志",
                "description": "最近 15 分钟系统运行日志。",
                "capabilityId": "system-logs",
                "visualType": "table",
                "queryParams": {"lookbackMinutes": 15, "limit": 50},
                "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
            },
            {
                "title": "15分钟系统告警",
                "description": "最近 15 分钟活动告警。",
                "capabilityId": "real-alarms",
                "visualType": "table",
                "queryParams": {"lookbackMinutes": 15, "limit": 50},
                "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 4},
            },
            {
                "title": "CMDB 资源信息",
                "description": "CMDB/资源概览和资产状态。",
                "capabilityId": "cmdb-resources",
                "visualType": "metric-card",
                "queryParams": {"scope": "all"},
                "layoutPosition": {"x": 0, "y": 4, "w": 4, "h": 3},
            },
            {
                "title": "今日工单",
                "description": "今日告警工单和处置状态。",
                "capabilityId": "workorders",
                "visualType": "table",
                "queryParams": {"timeRange": "today", "limit": 20},
                "layoutPosition": {"x": 4, "y": 4, "w": 8, "h": 3},
            },
        ],
        "summary": "已组合系统日志、系统告警、今日工单和 CMDB 资源信息。",
    }


def _patch_draft_plan(monkeypatch, plan: dict | None = None) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return dict(plan or _default_draft_plan())

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        if capability_id == "system-logs":
            return {
                "source": "zhiguan-log-service",
                "sourceStatus": "live",
                "columns": [
                    {"key": "time", "label": "时间"},
                    {"key": "message", "label": "日志内容"},
                ],
                "rows": [{"time": "12:00:00", "message": "service ready"}],
            }
        if capability_id == "real-alarms":
            return {
                "source": "portal-real-alarm-api",
                "sourceStatus": "live",
                "columns": [
                    {"key": "eventTime", "label": "时间"},
                    {"key": "title", "label": "告警"},
                ],
                "rows": [{"eventTime": "12:01:00", "title": "CPU 高"}],
            }
        if capability_id == "cmdb-resources":
            return {
                "source": "portal-asset-overview-api",
                "sourceStatus": "live",
                "value": 32,
                "unit": "项",
                "trend": "来自 CMDB/资源接口",
            }
        if capability_id == "workorders":
            return {
                "source": "portal-order-workflow-api",
                "sourceStatus": "live",
                "columns": [
                    {"key": "workorderNo", "label": "工单号"},
                    {"key": "title", "label": "标题"},
                ],
                "rows": [{"workorderNo": "WO-1", "title": "CPU 高"}],
            }
        return {"source": "unsupported", "sourceStatus": "unavailable"}

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan, raising=False)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute, raising=False)
    return calls


def _patch_ai_plan(monkeypatch, plan: dict) -> None:
    async def _fake_plan(**kwargs):
        return ai_big_screen_service._normalize_patch_plan(
            plan,
            screen=kwargs["screen"],
            selected_component_id=kwargs["selected_component_id"],
        )

    monkeypatch.setattr(ai_big_screen_service, "_build_patch_plan_with_ai", _fake_plan)


def test_ai_big_screen_generate_persist_publish_and_get(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    _patch_draft_plan(monkeypatch)

    draft_response = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="我想要一个大屏，包含15分钟的系统日志、系统告警和CMDB资源信息",
            requestedBy="portal-test",
        ),
    ))

    draft_screen = draft_response.screen
    assert draft_screen["status"] == "draft"
    assert draft_screen["name"] == "15分钟运维态势大屏"
    assert draft_screen["versions"][0]["versionId"] == "v1"
    assert len(draft_screen["components"]) >= 3
    plugin_ids = {item["pluginId"] for item in draft_screen["dataBindings"]}
    assert {"system-logs", "real-alarms", "cmdb-resources"}.issubset(
        plugin_ids,
    )

    save_response = save_ai_big_screen(
        AiBigScreenSaveRequest(screen=draft_screen, requestedBy="portal-test"),
    )
    saved_screen = save_response.screen
    screen_id = saved_screen["id"]
    assert registry.AI_BIG_SCREEN_REGISTRY_PATH.exists()

    publish_response = publish_ai_big_screen(
        screen_id,
        AiBigScreenPublishRequest(requestedBy="portal-test", visibility="internal"),
    )
    assert publish_response.screen["status"] == "published"
    target_types = {item["type"] for item in publish_response.publishTargets}
    assert {"external-link", "iframe", "portal-center"}.issubset(target_types)
    assert any(item["url"] == "/big-screens" for item in publish_response.publishTargets)

    detail_response = get_ai_big_screen(screen_id)
    detail = detail_response.screen
    assert detail["id"] == screen_id
    assert detail["status"] == "published"
    assert len(detail["publishTargets"]) >= 2


def test_ai_big_screen_saved_asset_can_be_deleted(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    draft_screen = {
        "id": "screen-delete-test",
        "name": "可删除大屏",
        "components": [
            {
                "id": "component-delete-test",
                "title": "删除测试指标",
                "type": "metric-card",
            },
        ],
    }
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(screen=draft_screen, requestedBy="portal-test"),
    ).screen
    screen_id = saved_screen["id"]

    delete_response = delete_ai_big_screen(screen_id)

    assert delete_response.deleted is True
    assert delete_response.screenId == screen_id
    assert all(item["id"] != screen_id for item in list_ai_big_screens().items)
    try:
        get_ai_big_screen(screen_id)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("deleted AI big screen should not be readable")


def test_ai_big_screen_patch_component_visual_config(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    _patch_draft_plan(monkeypatch)
    _patch_ai_plan(
        monkeypatch,
        {
            "summary": "颜色调整为暖色；标题改为今日重点风险",
            "operations": [
                {
                    "type": "setComponentPalette",
                    "palette": "warm",
                },
                {
                    "type": "setComponentTitle",
                    "title": "今日重点风险",
                },
            ],
        },
    )

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="我想要一个大屏，包含15分钟的系统日志、系统告警和CMDB资源信息",
            requestedBy="portal-test",
        ),
    )).screen
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(screen=draft_screen, requestedBy="portal-test"),
    ).screen

    screen_id = saved_screen["id"]
    selected_component_id = saved_screen["components"][0]["id"]
    patch_response = asyncio.run(
        patch_ai_big_screen(
            screen_id,
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId=selected_component_id,
                instruction="颜色暖一点，标题改成今日重点风险",
                requestedBy="portal-test",
            ),
        ),
    )

    patched_screen = patch_response.screen
    assert patch_response.version["versionId"] == "v2"
    assert "今日重点风险" in patch_response.summary
    assert patched_screen["versions"][0]["versionId"] == "v1"
    assert patched_screen["versions"][1]["versionId"] == "v2"

    selected_component = next(
        item
        for item in patched_screen["components"]
        if item["id"] == selected_component_id
    )
    assert selected_component["title"] == "今日重点风险"
    assert selected_component["visualConfig"]["palette"] == "warm"
    assert (
        patched_screen["versions"][0]["configSnapshot"]["components"][0]["title"]
        != selected_component["title"]
    )


def test_ai_big_screen_patch_aesthetic_instruction_changes_visible_style(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    _patch_draft_plan(monkeypatch)
    _patch_ai_plan(
        monkeypatch,
        {
            "summary": "视觉风格调整为领导驾驶舱风格",
            "operations": [
                {
                    "type": "setThemePalette",
                    "palette": "executive",
                },
                {
                    "type": "setComponentPalette",
                    "componentIds": "*",
                    "palette": "executive",
                    "emphasis": "strong",
                },
            ],
        },
    )

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="我想要一个大屏，包含15分钟的系统日志、系统告警和CMDB资源信息",
            requestedBy="portal-test",
        ),
    )).screen
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(screen=draft_screen, requestedBy="portal-test"),
    ).screen

    patch_response = asyncio.run(
        patch_ai_big_screen(
            saved_screen["id"],
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId=saved_screen["components"][0]["id"],
                instruction="这个大屏太丑了，帮我修改一下颜色，让它更适合领导看",
                requestedBy="portal-test",
            ),
        ),
    )

    patched_screen = patch_response.screen
    assert "视觉风格调整为领导驾驶舱风格" in patch_response.summary
    assert patched_screen["theme"]["palette"] == "executive"
    assert all(
        item["visualConfig"]["palette"] == "executive"
        for item in patched_screen["components"]
    )
    assert all(
        item["visualConfig"]["emphasis"] == "strong"
        for item in patched_screen["components"]
    )


def test_ai_big_screen_patch_appends_log_risk_component_without_replacing_existing(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    base_component = {
        "id": "component-workorders",
        "title": "待办工单",
        "type": "table",
        "pluginId": "workorders",
        "capabilityId": "workorders",
        "queryParams": {"timeRange": "today", "limit": 20},
        "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "data": {
            "source": "portal-order-workflow-api",
            "sourceStatus": "live",
            "rows": [{"workorderNo": "WO-1", "title": "CPU 高"}],
        },
    }
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(
            screen={
                "schemaVersion": 1,
                "id": "screen-append-risk",
                "name": "可叠加大屏",
                "status": "draft",
                "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
                "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
                "components": [base_component],
                "dataBindings": [ai_big_screen_service._build_binding(base_component)],
                "versions": [
                    {
                        "versionId": "v1",
                        "screenId": "screen-append-risk",
                        "configSnapshot": {},
                        "changeSummary": "初始版本",
                    },
                ],
            },
            requestedBy="portal-test",
        ),
    ).screen

    async def _fake_patch_plan(**kwargs):
        return ai_big_screen_service._normalize_patch_plan(
            {
                "summary": "追加系统日志高危情况分析模块",
                "operations": [],
            },
            screen=kwargs["screen"],
            selected_component_id=kwargs["selected_component_id"],
            instruction=kwargs["instruction"],
        )

    execute_calls: list[tuple[str, dict]] = []

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        execute_calls.append((capability_id, dict(query_params)))
        return {
            "source": "zhiguan-log-service",
            "sourceStatus": "live",
            "visualKind": "risk-pulse",
            "riskScore": 91,
            "rows": [
                {
                    "time": "2026-06-03 15:10:00",
                    "level": "ERROR",
                    "message": "Redis timeout",
                    "riskScore": 91,
                    "riskReason": "timeout",
                },
            ],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_patch_plan_with_ai", _fake_patch_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)

    patch_response = asyncio.run(
        patch_ai_big_screen(
            saved_screen["id"],
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId="",
                instruction="帮我加入一个分析系统日志有哪些高危情况模块",
                requestedBy="portal-test",
            ),
        ),
    )

    patched_screen = patch_response.screen
    assert [component["id"] for component in patched_screen["components"][:1]] == ["component-workorders"]
    assert patched_screen["components"][0]["data"]["rows"][0]["workorderNo"] == "WO-1"
    assert len(patched_screen["components"]) == 2
    added_component = patched_screen["components"][1]
    assert added_component["pluginId"] == "system-logs"
    assert added_component["type"] == "risk-pulse"
    assert added_component["queryParams"]["analysisMode"] == "risk_summary"
    assert added_component["data"]["riskScore"] == 91
    assert len(patched_screen["dataBindings"]) == 2
    assert execute_calls == [("system-logs", added_component["queryParams"])]


def test_ai_big_screen_patch_aligns_selected_component_layout_with_left(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    left_component = {
        "id": "component-left",
        "title": "左侧系统日志",
        "type": "table",
        "pluginId": "system-logs",
        "capabilityId": "system-logs",
        "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 5},
        "queryParams": {"lookbackMinutes": 15, "limit": 10},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "data": {"sourceStatus": "empty", "rows": []},
    }
    right_component = {
        "id": "component-right",
        "title": "右侧系统告警",
        "type": "table",
        "pluginId": "real-alarms",
        "capabilityId": "real-alarms",
        "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 3},
        "queryParams": {"limit": 10},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "data": {"sourceStatus": "empty", "rows": []},
    }
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(
            screen={
                "schemaVersion": 1,
                "id": "screen-layout-align",
                "name": "布局调整大屏",
                "status": "draft",
                "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
                "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
                "components": [left_component, right_component],
                "dataBindings": [
                    ai_big_screen_service._build_binding(left_component),
                    ai_big_screen_service._build_binding(right_component),
                ],
                "versions": [
                    {
                        "versionId": "v1",
                        "screenId": "screen-layout-align",
                        "configSnapshot": {},
                        "changeSummary": "初始版本",
                    },
                ],
            },
            requestedBy="portal-test",
        ),
    ).screen

    async def _fake_patch_plan(**kwargs):
        return ai_big_screen_service._normalize_patch_plan(
            {
                "summary": "调整右侧组件尺寸，使其与左侧平齐",
                "operations": [],
            },
            screen=kwargs["screen"],
            selected_component_id=kwargs["selected_component_id"],
            instruction=kwargs["instruction"],
        )

    monkeypatch.setattr(ai_big_screen_service, "_build_patch_plan_with_ai", _fake_patch_plan)

    patch_response = asyncio.run(
        patch_ai_big_screen(
            saved_screen["id"],
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId="component-right",
                instruction="右侧内容尺寸很别扭，帮我改成和左侧对齐，长度也平齐",
                requestedBy="portal-test",
            ),
        ),
    )

    right = next(
        component
        for component in patch_response.screen["components"]
        if component["id"] == "component-right"
    )
    assert right["layoutPosition"] == {"x": 6, "y": 0, "w": 6, "h": 5}
    assert "无法设置组件长度" not in patch_response.summary


def test_ai_big_screen_patch_adds_workorder_field_and_rehydrates_data(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    workorder_component = {
        "id": "component-workorders",
        "title": "今日工单",
        "type": "table",
        "pluginId": "workorders",
        "capabilityId": "workorders",
        "queryParams": {"timeRange": "today", "limit": 10},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "data": {
            "source": "portal-order-workflow-api",
            "sourceStatus": "live",
            "columns": [
                {"key": "workorderNo", "label": "工单号"},
                {"key": "title", "label": "标题"},
            ],
            "rows": [{"workorderNo": "TASK-1", "title": "代码工单"}],
        },
    }
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(
            screen={
                "schemaVersion": 1,
                "id": "screen-workorder-field",
                "name": "工单大屏",
                "status": "draft",
                "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
                "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
                "components": [workorder_component],
                "dataBindings": [ai_big_screen_service._build_binding(workorder_component)],
                "versions": [
                    {
                        "versionId": "v1",
                        "screenId": "screen-workorder-field",
                        "configSnapshot": {},
                        "changeSummary": "初始版本",
                    },
                ],
            },
            requestedBy="portal-test",
        ),
    ).screen

    async def _fake_patch_plan(**kwargs):
        return ai_big_screen_service._normalize_patch_plan(
            {"summary": "", "operations": []},
            screen=kwargs["screen"],
            selected_component_id=kwargs["selected_component_id"],
            instruction=kwargs["instruction"],
        )

    captured = {}

    def _fake_query_order_workorders(*, limit, time_range):
        captured["limit"] = limit
        captured["time_range"] = time_range
        return {
            "source": "live",
            "provider": "portal-order-workflow-api",
            "total": 1,
            "items": [
                {
                    "workorderNo": "TASK-1",
                    "title": "代码工单",
                    "status": "待处理",
                    "severity": "--",
                    "eventTime": "2026-06-03 10:00:00",
                    "starter": "xiaok",
                },
            ],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_patch_plan_with_ai", _fake_patch_plan)
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.order_workflow.query_order_workorders",
        _fake_query_order_workorders,
    )

    patch_response = asyncio.run(
        patch_ai_big_screen(
            saved_screen["id"],
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId="component-workorders",
                instruction="增加流程发起人字段",
                requestedBy="portal-test",
            ),
        ),
    )

    patched_component = patch_response.screen["components"][0]
    assert captured == {"limit": 10, "time_range": "today"}
    assert patched_component["queryParams"]["fields"] == ["workorderNo", "title", "starter"]
    assert {"key": "starter", "label": "流程发起人"} in patched_component["data"]["columns"]
    assert patched_component["data"]["rows"][0]["starter"] == "xiaok"
    assert patch_response.screen["dataBindings"][0]["input"]["fields"][-1] == "starter"


def test_ai_big_screen_field_patch_switches_workorder_stream_to_table(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    workorder_component = {
        "id": "component-workorders",
        "title": "待办工单流转",
        "type": "status-stream",
        "pluginId": "workorders",
        "capabilityId": "workorders",
        "queryParams": {"timeRange": "today", "limit": 10},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "data": {
            "source": "portal-order-workflow-api",
            "sourceStatus": "live",
            "columns": [
                {"key": "workorderNo", "label": "工单号"},
                {"key": "title", "label": "标题"},
            ],
            "rows": [{"workorderNo": "TASK-1", "title": "代码工单"}],
        },
    }
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(
            screen={
                "schemaVersion": 1,
                "id": "screen-workorder-stream-field",
                "name": "工单大屏",
                "status": "draft",
                "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
                "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
                "components": [workorder_component],
                "dataBindings": [ai_big_screen_service._build_binding(workorder_component)],
                "versions": [
                    {
                        "versionId": "v1",
                        "screenId": "screen-workorder-stream-field",
                        "configSnapshot": {},
                        "changeSummary": "初始版本",
                    },
                ],
            },
            requestedBy="portal-test",
        ),
    ).screen

    async def _fake_patch_plan(**kwargs):
        return ai_big_screen_service._normalize_patch_plan(
            {"summary": "", "operations": []},
            screen=kwargs["screen"],
            selected_component_id=kwargs["selected_component_id"],
            instruction=kwargs["instruction"],
        )

    def _fake_query_order_workorders(*, limit, time_range):
        return {
            "source": "live",
            "provider": "portal-order-workflow-api",
            "total": 1,
            "items": [
                {
                    "workorderNo": "TASK-1",
                    "title": "代码工单",
                    "status": "待处理",
                    "severity": "--",
                    "eventTime": "2026-06-03 10:00:00",
                    "starter": "xiaok",
                    "taskId": "task-9",
                    "procInsId": "proc-8",
                    "processName": "代码工单流程",
                    "taskName": "人工处理",
                },
            ],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_patch_plan_with_ai", _fake_patch_plan)
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.order_workflow.query_order_workorders",
        _fake_query_order_workorders,
    )

    patch_response = asyncio.run(
        patch_ai_big_screen(
            saved_screen["id"],
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId="component-workorders",
                instruction="增加任务编号、流程实例ID、流程名称、任务节点和流程发起人字段",
                requestedBy="portal-test",
            ),
        ),
    )

    patched_component = patch_response.screen["components"][0]
    assert patched_component["type"] == "table"
    assert patched_component["queryParams"]["fields"] == [
        "workorderNo",
        "title",
        "status",
        "severity",
        "eventTime",
        "starter",
        "taskName",
        "processName",
        "taskId",
        "procInsId",
    ]
    assert {"key": "taskId", "label": "任务编号"} in patched_component["data"]["columns"]
    assert {"key": "procInsId", "label": "流程实例"} in patched_component["data"]["columns"]
    assert {"key": "processName", "label": "流程名称"} in patched_component["data"]["columns"]
    assert {"key": "taskName", "label": "任务节点"} in patched_component["data"]["columns"]
    assert {"key": "starter", "label": "流程发起人"} in patched_component["data"]["columns"]
    assert patched_component["data"]["rows"][0]["taskId"] == "task-9"
    assert patched_component["data"]["rows"][0]["procInsId"] == "proc-8"


def test_nightingale_logs_latest_non_empty_searches_backwards(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeNightingaleModule:
        class nc:
            @staticmethod
            def format_ms(value):
                return "2026-05-20 10:00:00" if value else "--"

        @staticmethod
        def _do_search(args):
            calls.append((args.from_time, args.to_time))
            if args.from_time == "now-30d" and args.to_time == "now-14d":
                return {
                    "code": 200,
                    "data": {
                        "total": 1,
                        "rows": [
                            {
                                "ts_ms": 1779252000000,
                                "level": "INFO",
                                "host": "node-1",
                                "service": "n9e",
                                "message": "historical log",
                            },
                        ],
                    },
                }
            return {"code": 200, "data": {"total": 0, "rows": []}}

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.working_secrets.ensure_working_secrets_loaded",
        lambda: None,
    )
    monkeypatch.setattr(
        nightingale_logs,
        "_load_nightingale_log_module",
        lambda: FakeNightingaleModule,
    )

    payload = nightingale_logs.query_nightingale_logs(
        limit=5,
        lookback_minutes=15,
        query="",
        search_strategy="latest_non_empty",
        max_lookback_days=45,
    )

    assert payload["sourceStatus"] == "live"
    assert payload["searchStrategy"] == "latest_non_empty"
    assert payload["resolvedTimeRange"] == {"from": "now-30d", "to": "now-14d"}
    assert payload["rows"][0]["message"] == "historical log"
    assert calls == [
        ("now-15m", "now"),
        ("now-1h", "now"),
        ("now-6h", "now"),
        ("now-1d", "now"),
        ("now-7d", "now"),
        ("now-14d", "now-7d"),
        ("now-30d", "now-14d"),
    ]


def test_ai_big_screen_patch_latest_non_empty_log_rehydrates_data(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    log_component = {
        "id": "component-system-logs",
        "title": "系统日志",
        "type": "table",
        "pluginId": "system-logs",
        "capabilityId": "system-logs",
        "queryParams": {"lookbackMinutes": 15, "limit": 10},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "data": {
            "source": "zhiguan-log-service",
            "sourceStatus": "empty",
            "columns": [{"key": "time", "label": "时间"}],
            "rows": [],
        },
    }
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(
            screen={
                "schemaVersion": 1,
                "id": "screen-latest-log",
                "name": "日志大屏",
                "status": "draft",
                "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
                "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
                "components": [log_component],
                "dataBindings": [ai_big_screen_service._build_binding(log_component)],
                "versions": [
                    {
                        "versionId": "v1",
                        "screenId": "screen-latest-log",
                        "configSnapshot": {},
                        "changeSummary": "初始版本",
                    },
                ],
            },
            requestedBy="portal-test",
        ),
    ).screen

    async def _fake_patch_plan(**kwargs):
        return ai_big_screen_service._normalize_patch_plan(
            {
                "summary": "查询最后一次有系统日志的数据",
                "operations": [
                    {
                        "type": "setComponentTitle",
                        "componentIds": [kwargs["selected_component_id"]],
                        "title": "最后一次有系统日志的数据",
                    },
                ],
            },
            screen=kwargs["screen"],
            selected_component_id=kwargs["selected_component_id"],
            instruction=kwargs["instruction"],
        )

    captured = {}

    def _fake_query_nightingale_logs(**kwargs):
        captured.update(kwargs)
        return {
            "source": "zhiguan-log-service",
            "sourceStatus": "live",
            "searchStrategy": "latest_non_empty",
            "resolvedTimeRange": {"from": "now-30d", "to": "now-14d"},
            "total": 1,
            "rows": [
                {
                    "time": "2026-05-20 10:00:00",
                    "level": "INFO",
                    "host": "node-1",
                    "service": "n9e",
                    "message": "historical log",
                },
            ],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_patch_plan_with_ai", _fake_patch_plan)
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.nightingale_logs.query_nightingale_logs",
        _fake_query_nightingale_logs,
    )

    patch_response = asyncio.run(
        patch_ai_big_screen(
            saved_screen["id"],
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId="component-system-logs",
                instruction="查询到最后一次有系统日志的数据并且展示",
                requestedBy="portal-test",
            ),
        ),
    )

    patched_component = patch_response.screen["components"][0]
    assert captured["search_strategy"] == "latest_non_empty"
    assert captured["max_lookback_days"] == 45
    assert patched_component["title"] == "最后一次有系统日志的数据"
    assert patched_component["queryParams"]["searchStrategy"] == "latest_non_empty"
    assert patched_component["data"]["sourceStatus"] == "live"
    assert patched_component["data"]["rows"][0]["message"] == "historical log"
    assert patch_response.screen["dataBindings"][0]["input"]["searchStrategy"] == "latest_non_empty"


def test_ai_big_screen_patch_uses_ai_data_planner_after_empty_result(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    log_component = {
        "id": "component-system-logs",
        "title": "系统日志",
        "type": "table",
        "pluginId": "system-logs",
        "capabilityId": "system-logs",
        "queryParams": {"lookbackMinutes": 15, "limit": 10},
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
        "data": {
            "source": "zhiguan-log-service",
            "sourceStatus": "empty",
            "columns": [{"key": "time", "label": "时间"}],
            "rows": [],
        },
    }
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(
            screen={
                "schemaVersion": 1,
                "id": "screen-ai-data-planner",
                "name": "日志大屏",
                "status": "draft",
                "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
                "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
                "components": [log_component],
                "dataBindings": [ai_big_screen_service._build_binding(log_component)],
                "versions": [
                    {
                        "versionId": "v1",
                        "screenId": "screen-ai-data-planner",
                        "configSnapshot": {},
                        "changeSummary": "初始版本",
                    },
                ],
            },
            requestedBy="portal-test",
        ),
    ).screen

    async def _fake_patch_plan(**kwargs):
        return ai_big_screen_service._normalize_patch_plan(
            {
                "summary": "查询最后一次有系统日志的数据",
                "operations": [
                    {
                        "type": "setComponentTitle",
                        "componentIds": [kwargs["selected_component_id"]],
                        "title": "最后一次有系统日志的数据",
                    },
                ],
            },
            screen=kwargs["screen"],
            selected_component_id=kwargs["selected_component_id"],
            instruction=kwargs["instruction"],
        )

    execute_calls: list[tuple[str, dict]] = []
    planner_calls: list[dict] = []

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        execute_calls.append((capability_id, dict(query_params)))
        if len(execute_calls) == 1:
            return {
                "source": "zhiguan-log-service",
                "sourceStatus": "empty",
                "columns": [{"key": "time", "label": "时间"}],
                "rows": [],
                "message": "当前策略未命中日志",
            }
        return {
            "source": "zhiguan-log-service",
            "sourceStatus": "live",
            "columns": [
                {"key": "time", "label": "时间"},
                {"key": "message", "label": "日志内容"},
            ],
            "rows": [{"time": "2026-05-20 10:00:00", "message": "historical log"}],
            "resolvedTimeRange": {"from": "2026-05-01 00:00:00", "to": "2026-06-01 00:00:00"},
        }

    async def _fake_data_plan(**kwargs):
        planner_calls.append(kwargs)
        return {
            "action": "retry",
            "reason": "当前策略为空，用户明确要求查到历史有数据窗口，改查 5 月。",
            "queryParams": {
                "searchStrategy": "single_window",
                "timeMode": "absolute",
                "fromTime": "2026-05-01 00:00:00",
                "toTime": "2026-06-01 00:00:00",
            },
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_patch_plan_with_ai", _fake_patch_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)
    monkeypatch.setattr(ai_big_screen_service, "_build_data_query_plan_with_ai", _fake_data_plan, raising=False)

    patch_response = asyncio.run(
        patch_ai_big_screen(
            saved_screen["id"],
            AiBigScreenPatchRequest(
                baseVersionId="v1",
                selectedComponentId="component-system-logs",
                instruction="查询到最后一次有系统日志的数据并且展示，我记得5月有数据",
                requestedBy="portal-test",
            ),
        ),
    )

    patched_component = patch_response.screen["components"][0]
    assert execute_calls[0][1]["searchStrategy"] == "latest_non_empty"
    assert execute_calls[1][1]["fromTime"] == "2026-05-01 00:00:00"
    assert execute_calls[1][1]["toTime"] == "2026-06-01 00:00:00"
    assert planner_calls[0]["observations"][0]["sourceStatus"] == "empty"
    assert patched_component["queryParams"]["timeMode"] == "absolute"
    assert patched_component["data"]["sourceStatus"] == "live"
    assert patched_component["data"]["rows"][0]["message"] == "historical log"
    assert len(patched_component["dataPlanningTrace"]) == 2


def test_ai_big_screen_plugins_route_returns_builtin_catalog() -> None:
    response = list_ai_big_screen_plugins()

    capabilities = response.items
    domains = {item["domain"] for item in capabilities}
    assert {"log", "alarm", "workorder", "resource"}.issubset(domains)
    capability_ids = {item["id"] for item in capabilities}
    assert "system-logs" in capability_ids
    assert "real-alarms" in capability_ids
    assert "workorders" in capability_ids
    assert "cmdb-resources" in capability_ids
    system_logs = next(item for item in capabilities if item["id"] == "system-logs")
    assert system_logs["dataSource"] == "zhiguan-log-service"
    assert system_logs.get("skillName") == "nightingale-log"
    assert "QwenPaw" in system_logs["description"]
    assert "运行日志" in system_logs["description"]
    assert "后端运行日志" not in system_logs["description"]
    workorders = next(item for item in capabilities if item["id"] == "workorders")
    assert workorders["dataSource"] == "portal-order-workflow-api"
    assert workorders.get("skillName") == "order-workflow"


def test_ai_big_screen_draft_combines_logs_alarms_and_cmdb(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls = _patch_draft_plan(monkeypatch)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="我想要一个大屏，包含15分钟的系统日志、系统告警，以及cmdb中的资源信息",
            requestedBy="portal-test",
        ),
    )).screen

    capability_ids = {item["pluginId"] for item in draft_screen["dataBindings"]}
    assert {"system-logs", "real-alarms", "cmdb-resources"}.issubset(capability_ids)
    assert {"system-logs", "real-alarms", "cmdb-resources"}.issubset({item[0] for item in calls})
    assert any(
        capability_id == "system-logs" and query_params["lookbackMinutes"] == 15
        for capability_id, query_params in calls
    )
    assert any(
        capability_id == "real-alarms" and query_params["lookbackMinutes"] == 15
        for capability_id, query_params in calls
    )
    assert all(
        component["data"].get("sourceStatus") in {"live", "empty", "unavailable"}
        for component in draft_screen["components"]
    )
    assert all(
        component["data"].get("source") != "builtin-sample"
        for component in draft_screen["components"]
    )


def test_ai_big_screen_real_alarm_capability_uses_minute_window(monkeypatch) -> None:
    captured = {}

    def _fake_query_portal_real_alarms(*, limit, lookback_minutes, alarm_status=None):
        captured["limit"] = limit
        captured["lookback_minutes"] = lookback_minutes
        captured["alarm_status"] = alarm_status
        return {
            "source": "live",
            "total": 1,
            "items": [
                {
                    "eventTime": "2026-06-02 16:00:00",
                    "level": "critical",
                    "title": "CPU 高",
                    "deviceName": "node-1",
                    "manageIp": "10.0.0.1",
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms.query_portal_real_alarms",
        _fake_query_portal_real_alarms,
    )

    data = ai_big_screen_service._execute_data_capability(
        "real-alarms",
        {"lookbackMinutes": 15, "limit": 7},
    )

    assert captured == {"limit": 7, "lookback_minutes": 15, "alarm_status": None}
    assert data["source"] == "portal-real-alarm-api"
    assert data["sourceStatus"] == "live"
    assert data["rows"][0]["title"] == "CPU 高"


def test_ai_big_screen_real_alarm_capability_uses_current_window_without_time(
    monkeypatch,
) -> None:
    captured = {}

    def _fake_query_portal_real_alarms(*, limit, lookback_minutes, alarm_status=None):
        captured["limit"] = limit
        captured["lookback_minutes"] = lookback_minutes
        captured["alarm_status"] = alarm_status
        return {
            "source": "live",
            "total": 1,
            "items": [
                {
                    "eventTime": "2026-06-02 16:00:00",
                    "level": "critical",
                    "title": "CPU 高",
                    "deviceName": "node-1",
                    "manageIp": "10.0.0.1",
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms.query_portal_real_alarms",
        _fake_query_portal_real_alarms,
    )

    data = ai_big_screen_service._execute_data_capability(
        "real-alarms",
        {"limit": 7},
    )

    assert captured == {"limit": 7, "lookback_minutes": None, "alarm_status": None}
    assert data["source"] == "portal-real-alarm-api"
    assert data["sourceStatus"] == "live"
    assert data["trend"] == "当前活动告警"


def test_ai_big_screen_real_alarm_capability_passes_explicit_alarm_status(
    monkeypatch,
) -> None:
    captured = {}

    def _fake_query_portal_real_alarms(*, limit, lookback_minutes, alarm_status=None):
        captured["limit"] = limit
        captured["lookback_minutes"] = lookback_minutes
        captured["alarm_status"] = alarm_status
        return {"source": "live", "total": 0, "items": []}

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms.query_portal_real_alarms",
        _fake_query_portal_real_alarms,
    )

    ai_big_screen_service._execute_data_capability(
        "real-alarms",
        {"limit": 7, "alarmStatus": "1"},
    )

    assert captured == {"limit": 7, "lookback_minutes": None, "alarm_status": "1"}


def test_ai_big_screen_prompt_time_window_does_not_leak_to_current_alarm(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return {
            "name": "运维查询大屏",
            "description": "查询工单、日志和当前告警。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "15分钟系统日志",
                    "capabilityId": "system-logs",
                    "visualType": "table",
                    "queryParams": {},
                    "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                },
                {
                    "title": "当前系统告警",
                    "capabilityId": "real-alarms",
                    "visualType": "table",
                    "queryParams": {},
                    "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 4},
                },
            ],
            "summary": "组合日志和当前告警。",
        }

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        return {"source": capability_id, "sourceStatus": "empty", "rows": []}

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)

    _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="查询代码工单，15分钟系统日志和当前系统的告警信息。",
            requestedBy="portal-test",
        ),
    ))

    params_by_capability = {capability_id: params for capability_id, params in calls}
    assert params_by_capability["system-logs"]["lookbackMinutes"] == 15
    assert "lookbackMinutes" not in params_by_capability["real-alarms"]


def test_ai_big_screen_current_alarm_draft_removes_model_time_window(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return {
            "name": "当前告警大屏",
            "description": "展示当前活动告警。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "当前系统告警",
                    "description": "当前有哪些活动告警。",
                    "capabilityId": "real-alarms",
                    "visualType": "table",
                    "queryParams": {"lookbackMinutes": 15, "limit": 50},
                    "layoutPosition": {"x": 0, "y": 0, "w": 12, "h": 4},
                },
            ],
            "summary": "展示当前告警。",
        }

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        return {
            "source": capability_id,
            "sourceStatus": "live",
            "total": 5948,
            "value": 5948,
            "rows": [{"title": "CPU 高"}],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="当前有哪些告警",
            requestedBy="portal-test",
        ),
    )).screen

    alarm_calls = [query_params for capability_id, query_params in calls if capability_id == "real-alarms"]
    assert alarm_calls
    assert "lookbackMinutes" not in alarm_calls[0]
    alarm_component = draft_screen["components"][0]
    assert "lookbackMinutes" not in alarm_component["queryParams"]
    assert alarm_component["data"]["total"] == 5948


def test_ai_big_screen_realtime_alarm_draft_removes_model_time_window(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return {
            "name": "实时运维大屏",
            "description": "展示待办工单、实时告警和系统日志。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "实时告警",
                    "description": "实时告警信息。",
                    "capabilityId": "real-alarms",
                    "visualType": "table",
                    "queryParams": {"lookbackMinutes": 15, "limit": 50},
                    "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                },
            ],
            "summary": "展示实时告警。",
        }

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        return {
            "source": capability_id,
            "sourceStatus": "live",
            "total": 5960,
            "value": 5960,
            "rows": [{"title": "Redis每秒操作次数越限"}],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="给我查询待办工单，实时告警以及系统日志。",
            requestedBy="portal-test",
        ),
    )).screen

    alarm_calls = [query_params for capability_id, query_params in calls if capability_id == "real-alarms"]
    assert alarm_calls
    assert "lookbackMinutes" not in alarm_calls[0]
    alarm_component = next(component for component in draft_screen["components"] if component["pluginId"] == "real-alarms")
    assert "lookbackMinutes" not in alarm_component["queryParams"]
    assert alarm_component["data"]["total"] == 5960


def test_ai_big_screen_realtime_alarm_draft_removes_model_builtin_alarm_filters(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return {
            "name": "实时运维大屏",
            "description": "展示待办工单和实时告警。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "实时告警",
                    "description": "实时告警信息。",
                    "capabilityId": "real-alarms",
                    "visualType": "table",
                    "queryParams": {
                        "lookbackMinutes": 15,
                        "alarmStatus": "1",
                        "alarmstatus": "1",
                        "limit": 50,
                    },
                    "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                },
            ],
            "summary": "展示实时告警。",
        }

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        return {
            "source": capability_id,
            "sourceStatus": "live",
            "total": 5995,
            "value": 5995,
            "rows": [{"title": "CPU等待IO时间过长"}],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="查询待办工单、实时告警。",
            requestedBy="portal-test",
        ),
    )).screen

    alarm_calls = [query_params for capability_id, query_params in calls if capability_id == "real-alarms"]
    assert alarm_calls
    assert alarm_calls[0] == {
        "limit": 50,
        "fields": ["eventTime", "level", "title", "deviceName", "manageIp"],
    }
    alarm_component = next(component for component in draft_screen["components"] if component["pluginId"] == "real-alarms")
    assert alarm_component["queryParams"] == alarm_calls[0]
    assert alarm_component["data"]["total"] == 5995


def test_ai_big_screen_corrects_workorder_component_bound_to_alarm_capability(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return {
            "name": "实时运维大屏",
            "description": "展示实时告警和待办工单。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "待办工单统计",
                    "description": "今日待办处理工单的数量汇总与关键指标。",
                    "capabilityId": "real-alarms",
                    "visualType": "status-stream",
                    "queryParams": {"limit": 6},
                    "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                },
                {
                    "title": "实时告警",
                    "description": "当前实时告警列表。",
                    "capabilityId": "real-alarms",
                    "visualType": "status-stream",
                    "queryParams": {"limit": 6},
                    "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 4},
                },
            ],
            "summary": "组合实时告警和待办工单。",
        }

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        if capability_id == "workorders":
            return {
                "source": "portal-order-workflow-api",
                "sourceStatus": "live",
                "total": 1,
                "value": 1,
                "unit": "单",
                "rows": [{"workorderNo": "WO-1", "title": "待处理数据库工单"}],
            }
        if capability_id == "real-alarms":
            return {
                "source": "portal-real-alarm-api",
                "sourceStatus": "live",
                "total": 5998,
                "value": 5998,
                "unit": "起",
                "rows": [{"title": "系统 CPU 使用率过高"}],
            }
        return {"source": capability_id, "sourceStatus": "unavailable", "rows": []}

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="查询实时告警、待办工单。",
            requestedBy="portal-test",
        ),
    )).screen

    workorder_component = next(
        component for component in draft_screen["components"] if component["title"] == "待办工单统计"
    )
    alarm_component = next(component for component in draft_screen["components"] if component["title"] == "实时告警")

    assert workorder_component["capabilityId"] == "workorders"
    assert workorder_component["pluginId"] == "workorders"
    assert workorder_component["type"] == "table"
    assert workorder_component["data"]["source"] == "portal-order-workflow-api"
    assert workorder_component["data"]["rows"][0]["title"] == "待处理数据库工单"
    assert alarm_component["capabilityId"] == "real-alarms"
    assert ("workorders", workorder_component["queryParams"]) in calls
    assert any(capability_id == "real-alarms" for capability_id, _ in calls)


def test_ai_big_screen_log_risk_prompt_prefers_dynamic_risk_visual(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return {
            "name": "日志风险大屏",
            "description": "分析系统日志高危情况。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "系统日志高危情况",
                    "description": "分析系统日志有哪些高危情况，并动态突出危险部分。",
                    "capabilityId": "system-logs",
                    "visualType": "table",
                    "queryParams": {"lookbackMinutes": 15, "limit": 50},
                    "layoutPosition": {"x": 0, "y": 0, "w": 12, "h": 4},
                },
            ],
            "summary": "分析系统日志高危情况。",
        }

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        return {
            "source": "zhiguan-log-service",
            "sourceStatus": "live",
            "visualKind": "risk-pulse",
            "riskScore": 88,
            "rows": [
                {
                    "time": "2026-06-03 14:00:00",
                    "level": "ERROR",
                    "message": "database timeout",
                    "riskScore": 88,
                    "riskReason": "timeout",
                },
            ],
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)
    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _fake_execute)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="分析系统日志有哪些高危情况，并且进行动态渲染突出危险部分。",
            requestedBy="portal-test",
        ),
    )).screen

    log_component = draft_screen["components"][0]
    assert log_component["type"] == "risk-pulse"
    assert log_component["queryParams"]["analysisMode"] == "risk_summary"
    assert log_component["visualConfig"]["emphasis"] == "strong"
    assert log_component["visualSpec"]["kind"] == "risk-field"
    assert log_component["visualSpec"]["motion"] == "pulse"
    assert log_component["visualSpec"]["bindings"]["severity"] == "riskLevel"
    assert calls[0][1]["analysisMode"] == "risk_summary"


def test_ai_big_screen_visual_spec_is_sanitized_and_preserved(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)

    async def _fake_plan(**kwargs):
        return {
            "name": "自由视觉大屏",
            "description": "使用安全视觉规格。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "风险日志场",
                    "description": "根据日志风险分动态呈现。",
                    "capabilityId": "system-logs",
                    "visualType": "risk-pulse",
                    "queryParams": {"analysisMode": "risk_summary", "limit": 20},
                    "layoutPosition": {"x": 0, "y": 0, "w": 12, "h": 4},
                    "visualSpec": {
                        "version": 1,
                        "kind": "risk-field",
                        "motion": "scan",
                        "density": "showcase",
                        "bindings": {
                            "time": "time",
                            "message": "message",
                            "severity": "riskLevel",
                            "value": "riskScore",
                            "onClick": "alert(1)",
                        },
                        "highlightRules": [
                            {"field": "riskScore", "operator": ">=", "value": 88, "tone": "critical"},
                            {"field": "message", "operator": "contains", "value": "<script>", "tone": "warm"},
                        ],
                        "layers": [
                            {"type": "score", "source": "rows"},
                            {"type": "list", "source": "rows", "limit": 5},
                            {"type": "iframe", "source": "javascript:alert(1)"},
                        ],
                        "script": "alert(1)",
                        "html": "<img onerror=alert(1)>",
                    },
                },
            ],
            "summary": "使用安全视觉规格。",
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)
    monkeypatch.setattr(
        ai_big_screen_service,
        "_execute_data_capability",
        lambda capability_id, query_params: {"source": capability_id, "sourceStatus": "live", "rows": []},
    )

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(prompt="做一个有想象力的日志风险大屏", requestedBy="portal-test"),
    )).screen

    visual_spec = draft_screen["components"][0]["visualSpec"]
    assert visual_spec["kind"] == "risk-field"
    assert visual_spec["motion"] == "scan"
    assert visual_spec["bindings"] == {
        "time": "time",
        "message": "message",
        "severity": "riskLevel",
        "value": "riskScore",
    }
    assert visual_spec["highlightRules"][0] == {
        "field": "riskScore",
        "operator": ">=",
        "value": 88,
        "tone": "critical",
    }
    assert visual_spec["layers"] == [
        {"type": "score", "source": "rows"},
        {"type": "list", "source": "rows", "limit": 5},
    ]
    serialized = str(visual_spec)
    assert "script" not in serialized
    assert "iframe" not in serialized
    assert "alert" not in serialized


def test_ai_big_screen_system_log_capability_uses_nightingale_provider(monkeypatch) -> None:
    captured = {}

    def _fake_query_nightingale_logs(**kwargs):
        limit = kwargs["limit"]
        lookback_minutes = kwargs["lookback_minutes"]
        query = kwargs["query"]
        captured["limit"] = limit
        captured["lookback_minutes"] = lookback_minutes
        captured["query"] = query
        captured["search_strategy"] = kwargs["search_strategy"]
        return {
            "source": "zhiguan-log-service",
            "sourceStatus": "live",
            "total": 1,
            "rows": [
                {
                    "time": "2026-06-03 10:00:00",
                    "level": "INFO",
                    "host": "node-1",
                    "service": "nginx",
                    "message": "request ok",
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.nightingale_logs.query_nightingale_logs",
        _fake_query_nightingale_logs,
    )

    data = ai_big_screen_service._execute_data_capability(
        "system-logs",
        {"lookbackMinutes": 15, "limit": 7, "query": "level:INFO"},
    )

    assert captured == {
        "limit": 7,
        "lookback_minutes": 15,
        "query": "level:INFO",
        "search_strategy": "single_window",
    }
    assert data["source"] == "zhiguan-log-service"
    assert data["sourceStatus"] == "live"
    assert data["rows"][0]["message"] == "request ok"


def test_ai_big_screen_system_log_risk_analysis_scores_high_risk_rows(monkeypatch) -> None:
    def _fake_query_nightingale_logs(**kwargs):
        return {
            "source": "zhiguan-log-service",
            "sourceStatus": "live",
            "total": 2,
            "rows": [
                {
                    "time": "2026-06-03 10:00:00",
                    "level": "INFO",
                    "message": "service ready",
                },
                {
                    "time": "2026-06-03 10:01:00",
                    "level": "ERROR",
                    "message": "database timeout failed",
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.nightingale_logs.query_nightingale_logs",
        _fake_query_nightingale_logs,
    )

    data = ai_big_screen_service._execute_data_capability(
        "system-logs",
        {"lookbackMinutes": 15, "limit": 10, "analysisMode": "risk_summary"},
    )

    assert data["visualKind"] == "risk-pulse"
    assert data["analysisMode"] == "risk_summary"
    assert data["riskScore"] >= 80
    assert data["rows"][0]["message"] == "database timeout failed"
    assert data["rows"][0]["riskLevel"] in {"high", "critical"}
    assert data["rows"][0]["riskReason"]
    assert data["total"] == 1


def test_ai_big_screen_workorder_capability_uses_order_workflow_provider(monkeypatch) -> None:
    captured = {}

    def _fake_query_order_workorders(*, limit, time_range):
        captured["limit"] = limit
        captured["time_range"] = time_range
        return {
            "source": "live",
            "provider": "portal-order-workflow-api",
            "total": 1,
            "items": [
                {
                    "workorderNo": "WO-20260602-001",
                    "title": "CPU 高",
                    "status": "待处理",
                    "severity": "严重",
                    "eventTime": "2026-06-02 16:05:00",
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.order_workflow.query_order_workorders",
        _fake_query_order_workorders,
    )

    data = ai_big_screen_service._execute_data_capability(
        "workorders",
        {"timeRange": "today", "limit": 6},
    )

    assert captured == {"limit": 6, "time_range": "today"}
    assert data["source"] == "portal-order-workflow-api"
    assert data["sourceStatus"] == "live"
    assert data["timeRange"] == "today"
    assert data["rows"][0]["workorderNo"] == "WO-20260602-001"


def test_order_workflow_loader_registers_dynamic_module_for_dataclass(
    monkeypatch,
    tmp_path,
) -> None:
    script = tmp_path / "client.py"
    script.write_text(
        "\n".join(
            [
                "from dataclasses import dataclass",
                "@dataclass(slots=True)",
                "class OrderWorkflowConfig:",
                "    base_url: str = ''",
                "class OrderWorkflowClient:",
                "    def get_workorder_stats(self):",
                "        return {'data': {}}",
                "    def list_todo_workorders(self, page_num=1, page_size=10):",
                "        return {'total': 0, 'rows': []}",
            ],
        ),
        encoding="utf-8",
    )
    order_workflow._load_order_client_module.cache_clear()
    sys.modules.pop("qwenpaw_order_workflow_client", None)
    monkeypatch.setattr(order_workflow, "_resolve_order_client_script", lambda: script)

    module = order_workflow._load_order_client_module()

    assert module.OrderWorkflowConfig().base_url == ""
    assert "qwenpaw_order_workflow_client" in sys.modules
    order_workflow._load_order_client_module.cache_clear()


def test_ai_big_screen_workorder_capability_blocks_mock_alarm_rows(monkeypatch) -> None:
    def _fake_query_order_workorders(*, limit, time_range):
        return {
            "source": "mock",
            "total": 3,
            "items": [
                {
                    "workorderNo": "WO-20260328-916673",
                    "title": "应用接口响应超时",
                    "status": "处理中",
                    "severity": "一级告警",
                    "eventTime": "2026-03-28 09:01:08",
                },
                {
                    "workorderNo": "WO-20260328-301441",
                    "title": "数据库存在慢SQL",
                    "status": "处理中",
                    "severity": "一级告警",
                    "eventTime": "2026-03-28 09:01:08",
                },
            ],
        }

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.order_workflow.query_order_workorders",
        _fake_query_order_workorders,
    )

    data = ai_big_screen_service._execute_data_capability(
        "workorders",
        {"timeRange": "today", "limit": 6},
    )

    assert data["source"] == "portal-order-workflow-api"
    assert data["sourceStatus"] == "unavailable"
    assert data["rows"] == []
    assert "mock/sample" in data["message"]
    serialized = str(data)
    assert "WO-20260328-916673" not in serialized
    assert "应用接口响应超时" not in serialized
    assert "数据库存在慢SQL" not in serialized


def test_ai_big_screen_unknown_capability_becomes_gap_plan(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)

    async def _fake_plan(**kwargs):
        return {
            "name": "成本态势大屏",
            "description": "包含尚未接入的云成本数据。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [
                {
                    "title": "云成本预算",
                    "description": "展示云资源成本、预算消耗和超预算风险。",
                    "capabilityId": "cloud-costs",
                    "visualType": "bar-chart",
                    "queryParams": {"period": "today"},
                    "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                },
            ],
            "summary": "云成本能力尚未接入，保留接入方案位置。",
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="我想要一个大屏，包含今日云成本预算",
            requestedBy="portal-test",
        ),
    )).screen

    gap_component = draft_screen["components"][0]
    assert gap_component["pluginId"] == "capability-gap"
    assert gap_component["data"]["sourceStatus"] == "unavailable"
    assert gap_component["data"]["source"] == "ai-capability-planning"
    assert "云成本预算" in gap_component["title"]
    assert "cloud-costs" in gap_component["queryParams"]["reason"]
    assert draft_screen["aiConversationContext"]["capabilityGaps"][0]["requestedData"] == "云成本预算"
    serialized = str(gap_component["data"])
    assert "当前没有可复用的真实数据能力" in serialized
    assert "模拟数据" in serialized


def test_ai_big_screen_empty_plan_becomes_gap_plan(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)

    async def _fake_plan(**kwargs):
        return {
            "name": "未知数据大屏",
            "description": "模型没有返回可用组件。",
            "theme": {"mode": "dark", "palette": "industrial", "density": "dashboard"},
            "components": [],
            "summary": "",
        }

    monkeypatch.setattr(ai_big_screen_service, "_build_screen_plan_with_ai", _fake_plan)

    prompt = "展示一个尚未接入的新业务指标"
    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(prompt=prompt, requestedBy="portal-test"),
    )).screen

    assert len(draft_screen["components"]) == 1
    gap_component = draft_screen["components"][0]
    assert gap_component["pluginId"] == "capability-gap"
    assert gap_component["data"]["sourceStatus"] == "unavailable"
    assert gap_component["data"]["rows"][0]["value"] == prompt[:80]


def test_ai_big_screen_draft_combines_logs_alarms_workorders_and_cmdb(
    monkeypatch,
    tmp_path,
) -> None:
    _patch_registry_path(monkeypatch, tmp_path)
    calls = _patch_draft_plan(monkeypatch)

    draft_screen = _await_if_needed(generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="我想要一个大屏，包含15分钟的系统日志、系统告警、今日工单和CMDB中的资源信息",
            requestedBy="portal-test",
        ),
    )).screen

    capability_ids = {item["pluginId"] for item in draft_screen["dataBindings"]}
    assert {"system-logs", "real-alarms", "workorders", "cmdb-resources"}.issubset(capability_ids)
    assert {"system-logs", "real-alarms", "workorders", "cmdb-resources"}.issubset(
        {item[0] for item in calls},
    )
    workorder_component = next(
        component for component in draft_screen["components"] if component["pluginId"] == "workorders"
    )
    assert workorder_component["queryParams"]["timeRange"] == "today"
    assert workorder_component["data"]["source"] == "portal-order-workflow-api"


def test_ai_big_screen_hydrates_data_capabilities_concurrently(monkeypatch) -> None:
    def _slow_execute(capability_id: str, query_params: dict) -> dict:
        time.sleep(0.08)
        return {"source": capability_id, "sourceStatus": "live"}

    monkeypatch.setattr(ai_big_screen_service, "_execute_data_capability", _slow_execute)
    components = [
        {
            "id": f"component-{index}",
            "pluginId": capability_id,
            "capabilityId": capability_id,
            "queryParams": {},
        }
        for index, capability_id in enumerate(
            ["system-logs", "real-alarms", "workorders", "cmdb-resources"],
            start=1,
        )
    ]

    started = time.monotonic()
    hydrated = asyncio.run(ai_big_screen_service._hydrate_components_with_data(components))
    elapsed = time.monotonic() - started

    assert [item["id"] for item in hydrated] == [item["id"] for item in components]
    assert elapsed < 0.24


def test_ai_big_screen_router_registers_contract_paths() -> None:
    app = FastAPI()
    app.include_router(ai_big_screen_router, prefix="/api/portal")
    paths = {route.path for route in app.routes}
    methods = _methods_by_path(app.routes)

    assert "/api/portal/ai-big-screens" in paths
    assert "/api/portal/ai-big-screens/draft" in paths
    assert "/api/portal/ai-big-screens/plugins" in paths
    assert "/api/portal/ai-big-screens/{screen_id}" in paths
    assert "/api/portal/ai-big-screens/{screen_id}/patch" in paths
    assert "/api/portal/ai-big-screens/{screen_id}/publish" in paths
    assert "DELETE" in methods["/api/portal/ai-big-screens/{screen_id}"]


def test_portal_backend_includes_ai_big_screen_router() -> None:
    paths = {route.path for route in portal_backend_router.routes}
    methods = _methods_by_path(portal_backend_router.routes)

    assert "/api/portal/ai-big-screens" in paths
    assert "/api/portal/ai-big-screens/draft" in paths
    assert "/api/portal/ai-big-screens/plugins" in paths
    assert "DELETE" in methods["/api/portal/ai-big-screens/{screen_id}"]
