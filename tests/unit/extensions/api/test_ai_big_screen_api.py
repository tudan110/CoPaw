# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI

from qwenpaw.extensions import ai_big_screen_registry as registry
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


def test_ai_big_screen_generate_persist_publish_and_get(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)

    draft_response = generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="领导驾驶舱，关注告警、工单、资源和重点系统健康度",
            requestedBy="portal-test",
        ),
    )

    draft_screen = draft_response.screen
    assert draft_screen["status"] == "draft"
    assert draft_screen["name"] == "AI 运维驾驶舱"
    assert draft_screen["versions"][0]["versionId"] == "v1"
    assert len(draft_screen["components"]) >= 3
    plugin_ids = {item["pluginId"] for item in draft_screen["dataBindings"]}
    assert {"alarm-overview", "workorder-risk", "resource-utilization"}.issubset(
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
    assert {"external-link", "iframe"}.issubset(target_types)

    detail_response = get_ai_big_screen(screen_id)
    detail = detail_response.screen
    assert detail["id"] == screen_id
    assert detail["status"] == "published"
    assert len(detail["publishTargets"]) >= 2


def test_ai_big_screen_patch_component_visual_config(monkeypatch, tmp_path) -> None:
    _patch_registry_path(monkeypatch, tmp_path)

    draft_screen = generate_ai_big_screen_draft(
        AiBigScreenDraftRequest(
            prompt="领导驾驶舱，关注告警、工单、资源",
            requestedBy="portal-test",
        ),
    ).screen
    saved_screen = save_ai_big_screen(
        AiBigScreenSaveRequest(screen=draft_screen, requestedBy="portal-test"),
    ).screen

    screen_id = saved_screen["id"]
    selected_component_id = saved_screen["components"][0]["id"]
    patch_response = patch_ai_big_screen(
        screen_id,
        AiBigScreenPatchRequest(
            baseVersionId="v1",
            selectedComponentId=selected_component_id,
            instruction="颜色暖一点，标题改成今日重点风险",
            requestedBy="portal-test",
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


def test_ai_big_screen_plugins_route_returns_builtin_catalog() -> None:
    response = list_ai_big_screen_plugins()

    plugins = response.items
    domains = {item["domain"] for item in plugins}
    assert {"alarm", "workorder", "resource"}.issubset(domains)
    plugin_ids = {item["id"] for item in plugins}
    assert "alarm-overview" in plugin_ids
    assert "resource-utilization" in plugin_ids


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
