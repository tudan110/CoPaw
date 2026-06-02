# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import inspect

from fastapi import FastAPI

from qwenpaw.extensions import ai_big_screen_registry as registry
from qwenpaw.extensions.api import ai_big_screen_service
from qwenpaw.extensions.api.ai_big_screen_api import (
    generate_ai_big_screen_draft,
    get_ai_big_screen,
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
        ],
        "summary": "已组合系统日志、系统告警和 CMDB 资源信息。",
    }


def _patch_draft_plan(monkeypatch, plan: dict | None = None) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    async def _fake_plan(**kwargs):
        return dict(plan or _default_draft_plan())

    def _fake_execute(capability_id: str, query_params: dict) -> dict:
        calls.append((capability_id, dict(query_params)))
        if capability_id == "system-logs":
            return {
                "source": "backend-log",
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


def test_ai_big_screen_plugins_route_returns_builtin_catalog() -> None:
    response = list_ai_big_screen_plugins()

    capabilities = response.items
    domains = {item["domain"] for item in capabilities}
    assert {"log", "alarm", "resource"}.issubset(domains)
    capability_ids = {item["id"] for item in capabilities}
    assert "system-logs" in capability_ids
    assert "real-alarms" in capability_ids
    assert "cmdb-resources" in capability_ids


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
    assert {item[0] for item in calls} == {"system-logs", "real-alarms", "cmdb-resources"}
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

    def _fake_query_portal_real_alarms(*, limit, lookback_minutes):
        captured["limit"] = limit
        captured["lookback_minutes"] = lookback_minutes
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

    assert captured == {"limit": 7, "lookback_minutes": 15}
    assert data["source"] == "portal-real-alarm-api"
    assert data["sourceStatus"] == "live"
    assert data["rows"][0]["title"] == "CPU 高"


def test_ai_big_screen_router_registers_contract_paths() -> None:
    app = FastAPI()
    app.include_router(ai_big_screen_router, prefix="/api/portal")
    paths = {route.path for route in app.routes}

    assert "/api/portal/ai-big-screens" in paths
    assert "/api/portal/ai-big-screens/draft" in paths
    assert "/api/portal/ai-big-screens/plugins" in paths
    assert "/api/portal/ai-big-screens/{screen_id}/patch" in paths
    assert "/api/portal/ai-big-screens/{screen_id}/publish" in paths


def test_portal_backend_includes_ai_big_screen_router() -> None:
    paths = {route.path for route in portal_backend_router.routes}

    assert "/api/portal/ai-big-screens" in paths
    assert "/api/portal/ai-big-screens/draft" in paths
    assert "/api/portal/ai-big-screens/plugins" in paths
