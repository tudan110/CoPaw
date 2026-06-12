# -*- coding: utf-8 -*-
"""统一轻应用货架（/light-apps）聚合端点测试。"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.extensions import (
    natural_language_customization_registry as registry,
)
from qwenpaw.extensions.api import app_artifacts_service
from qwenpaw.extensions.api.app_artifacts_api import (
    router as app_artifacts_router,
)
from qwenpaw.extensions.api.light_apps_api import router as light_apps_router
from qwenpaw.extensions.api.natural_language_customization_api import (
    router as nl_customization_router,
)


class _FakeIntentModel:
    async def __call__(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "scenarioType": "inspection",
            "targetType": "Oracle",
            "targetName": "Oracle",
            "triggerType": "schedule",
            "triggerLabel": "每天 08:00",
            "scheduleCron": "0 8 * * *",
            "actions": ["analyze"],
            "displayTargets": ["assistant-entry"],
            "roles": ["运维"],
            "restrictions": [],
            "approvalMode": "none",
            "confidence": 0.95,
        }
        return json.dumps(payload, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _isolated_storages(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        registry,
        "NL_CUSTOMIZATION_REGISTRY_PATH",
        tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        registry,
        "NL_CUSTOMIZATION_BUNDLE_DIR",
        tmp_path / "bundles",
    )
    monkeypatch.setattr(
        registry,
        "NL_CUSTOMIZATION_ACTIVE_PATH",
        tmp_path / "active.json",
    )

    artifacts_dir = tmp_path / "app_artifacts"
    monkeypatch.setattr(
        app_artifacts_service,
        "APP_ARTIFACTS_DATA_DIR",
        artifacts_dir,
    )
    monkeypatch.setattr(
        app_artifacts_service,
        "APP_ARTIFACTS_DB_PATH",
        artifacts_dir / "artifacts.db",
    )
    monkeypatch.setattr(
        app_artifacts_service,
        "APP_ARTIFACTS_HTML_DIR",
        artifacts_dir / "html",
    )
    monkeypatch.setattr(app_artifacts_service, "_DB_INITIALIZED", False)

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter",
        lambda *args, **kwargs: (_FakeIntentModel(), object()),
    )


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    app.include_router(app_artifacts_router, prefix="/api/portal")
    app.include_router(light_apps_router, prefix="/api/portal")
    return TestClient(app)


def _seed_listed_task_app(client: TestClient) -> dict:
    """发布→应用→上架一个固化任务应用（registry 有 apply 前置守卫）。"""
    preview = client.post(
        "/api/portal/nl-customization/preview",
        json={"prompt": "给我一个 Oracle 巡检助手，每天 8 点执行。"},
    )
    assert preview.status_code == 200
    published = client.post(
        "/api/portal/nl-customization/publish",
        json={"preview": preview.json(), "requestedBy": "test"},
    )
    assert published.status_code == 200
    version_id = published.json()["versionId"]
    applied = client.post(
        "/api/portal/nl-customization/apply",
        json={"versionId": version_id, "requestedBy": "test"},
    )
    assert applied.status_code == 200
    listed = client.post(
        "/api/portal/nl-customization/listing",
        json={"versionId": version_id, "listed": True, "requestedBy": "test"},
    )
    assert listed.status_code == 200
    return published.json()["record"]


def _seed_page_app(client: TestClient, *, listed: bool) -> str:
    created = client.post(
        "/api/portal/app-artifacts",
        json={
            "title": "告警趋势报表",
            "description": "页面应用",
            "type": "app",
            "html_content": "<html><body>chart</body></html>",
        },
    )
    assert created.status_code == 200
    app_id = created.json()["id"]
    if listed:
        response = client.post(
            f"/api/portal/app-artifacts/{app_id}/listing",
            json={"listed": True},
        )
        assert response.status_code == 200
    return app_id


def test_light_apps_aggregates_both_sources() -> None:
    client = _make_client()
    task_record = _seed_listed_task_app(client)
    page_app_id = _seed_page_app(client, listed=True)

    response = client.get("/api/portal/light-apps")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2

    by_kind = {item["kind"]: item for item in items}
    task_item = by_kind["task"]
    assert task_item["id"] == task_record["versionId"]
    assert task_item["appId"] == task_record["appId"]
    assert task_item["launch"]["type"] == "chat-dispatch"
    assert task_item["launch"]["employeeId"] == task_record["launchEmployeeId"]
    assert task_item["launch"]["prompt"] == task_record["launchPrompt"]
    assert task_item["listedAt"] != ""

    page_item = by_kind["page"]
    assert page_item["id"] == page_app_id
    assert page_item["artifactType"] == "app"
    assert page_item["launch"]["type"] == "open-url"
    assert page_item["launch"]["url"] == (
        f"/portal-api/app-artifacts/{page_app_id}/preview"
    )
    assert page_item["listedAt"] != ""

    listed_ats = [item["listedAt"] for item in items]
    assert listed_ats == sorted(listed_ats, reverse=True)


def test_light_apps_excludes_unlisted_items() -> None:
    client = _make_client()
    _seed_page_app(client, listed=False)

    response = client.get("/api/portal/light-apps")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_light_apps_respects_limit() -> None:
    client = _make_client()
    _seed_page_app(client, listed=True)
    _seed_page_app(client, listed=True)

    response = client.get("/api/portal/light-apps?limit=1")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
