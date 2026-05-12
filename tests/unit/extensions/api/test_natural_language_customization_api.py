# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.exceptions import ProviderError
from qwenpaw.extensions.api.natural_language_customization_api import (
    router as nl_customization_router,
)
from qwenpaw.extensions import natural_language_customization_registry as registry


class _FakePreviewModel:
    async def __call__(self, messages: list[dict[str, str]]) -> str:
        user_content = messages[-1]["content"]
        if "首页" in user_content or "卡片" in user_content:
            payload = {
                "scenarioType": "portal-dashboard",
                "targetType": "首页",
                "targetName": "待处理工单",
                "triggerType": "manual",
                "triggerLabel": "手动触发",
                "scheduleCron": "",
                "actions": ["render"],
                "displayTargets": ["portal-home", "portal-card"],
                "roles": ["领导", "运维"],
                "restrictions": [],
                "approvalMode": "none",
                "confidence": 0.91,
            }
        else:
            payload = {
                "scenarioType": "inspection",
                "targetType": "Oracle",
                "targetName": "Oracle",
                "triggerType": "schedule",
                "triggerLabel": "每天 08:00",
                "scheduleCron": "0 8 * * *",
                "actions": ["analyze", "ticket"],
                "displayTargets": ["assistant-entry"],
                "roles": ["运维"],
                "restrictions": ["禁止自动变更"],
                "approvalMode": "manual",
                "confidence": 0.96,
            }
        return json.dumps(payload, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _mock_preview_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter",
        lambda *args, **kwargs: (_FakePreviewModel(), object()),
    )


def test_nl_customization_preview_route_builds_structured_bundle() -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    client = TestClient(app)

    response = client.post(
        "/api/portal/nl-customization/preview",
        json={
            "prompt": "给我一个 Oracle 巡检助手，每天 8 点执行，异常自动建单，但不能自动变更。",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"]["scenarioType"] == "inspection"
    assert payload["intent"]["targetType"] == "Oracle"
    assert payload["matchedTemplate"]["skillId"] == "inspection-analyst"
    assert payload["bundle"]["scheduler"]["cron"] == "0 8 * * *"
    assert payload["bundle"]["policies"]["allowProductionChange"] is False
    assert "建议补充通知渠道" not in payload["missingInputs"]


def test_nl_customization_preview_route_requires_default_llm(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    client = TestClient(app)

    def _raise_missing_model(*args: Any, **kwargs: Any) -> tuple[object, object]:
        raise ProviderError("No active model configured.")

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter",
        _raise_missing_model,
    )

    response = client.post(
        "/api/portal/nl-customization/preview",
        json={"prompt": "给我一个 Oracle 巡检助手"},
    )

    assert response.status_code == 400
    assert "未配置默认大模型" in response.json()["detail"]


def test_nl_customization_publish_route_persists_version_listing(
    monkeypatch,
    tmp_path,
) -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    client = TestClient(app)
    registry_path = tmp_path / "nl_customization_registry.json"
    bundle_dir = tmp_path / "nl_customization_bundles"

    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_BUNDLE_DIR", bundle_dir)

    preview_response = client.post(
        "/api/portal/nl-customization/preview",
        json={
            "prompt": "首页加一个待处理工单卡片，领导只能看汇总，运维能看明细。",
        },
    )
    assert preview_response.status_code == 200

    publish_response = client.post(
        "/api/portal/nl-customization/publish",
        json={
            "preview": preview_response.json(),
            "requestedBy": "portal-test",
        },
    )

    assert publish_response.status_code == 200
    published = publish_response.json()
    assert published["record"]["requestedBy"] == "portal-test"
    assert registry_path.exists()

    versions_response = client.get("/api/portal/nl-customization/versions")
    assert versions_response.status_code == 200
    versions_payload = versions_response.json()
    assert len(versions_payload["items"]) == 1
    assert versions_payload["items"][0]["versionId"] == published["versionId"]

    bundle_payload = json.loads(bundle_dir.joinpath(f"{published['versionId']}.json").read_text(encoding="utf-8"))
    assert bundle_payload["record"]["title"] == preview_response.json()["title"]

    version_detail_response = client.get(
        f"/api/portal/nl-customization/versions/{published['versionId']}",
    )
    assert version_detail_response.status_code == 200
    detail_payload = version_detail_response.json()
    assert detail_payload["versionId"] == published["versionId"]
    assert detail_payload["preview"]["title"] == preview_response.json()["title"]


def test_nl_customization_apply_route_marks_active_version(
    monkeypatch,
    tmp_path,
) -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    client = TestClient(app)
    registry_path = tmp_path / "nl_customization_registry.json"
    bundle_dir = tmp_path / "nl_customization_bundles"
    active_path = tmp_path / "nl_customization_active.json"

    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_BUNDLE_DIR", bundle_dir)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_ACTIVE_PATH", active_path)

    preview_response = client.post(
        "/api/portal/nl-customization/preview",
        json={
            "prompt": "首页加一个待处理工单卡片，领导只能看汇总，运维能看明细。",
        },
    )
    assert preview_response.status_code == 200

    publish_response = client.post(
        "/api/portal/nl-customization/publish",
        json={
            "preview": preview_response.json(),
            "requestedBy": "portal-test",
        },
    )
    assert publish_response.status_code == 200
    published = publish_response.json()

    apply_response = client.post(
        "/api/portal/nl-customization/apply",
        json={
            "versionId": published["versionId"],
            "requestedBy": "portal-test",
        },
    )
    assert apply_response.status_code == 200
    applied = apply_response.json()
    assert applied["versionId"] == published["versionId"]
    assert active_path.exists()

    active_payload = json.loads(active_path.read_text(encoding="utf-8"))
    assert active_payload["versionId"] == published["versionId"]
    assert active_payload["effectiveBundle"]["portal"]["displayTargets"] == [
        "portal-home",
        "portal-card",
    ]

    versions_response = client.get("/api/portal/nl-customization/versions")
    assert versions_response.status_code == 200
    versions_payload = versions_response.json()
    assert versions_payload["items"][0]["isActive"] is True
    assert versions_payload["items"][0]["isListed"] is False
    assert versions_payload["items"][0]["versionId"] == published["versionId"]

    active_response = client.get("/api/portal/nl-customization/active")
    assert active_response.status_code == 200
    active_view = active_response.json()
    assert active_view["activeVersionId"] == published["versionId"]
    assert active_view["record"]["versionId"] == published["versionId"]
    assert active_view["effectiveBundle"]["portal"]["displayTargets"] == [
        "portal-home",
        "portal-card",
    ]

    apps_response = client.get("/api/portal/nl-customization/apps")
    assert apps_response.status_code == 200
    apps_payload = apps_response.json()
    assert apps_payload["items"] == []

    listing_response = client.post(
        "/api/portal/nl-customization/listing",
        json={
            "versionId": published["versionId"],
            "listed": True,
            "requestedBy": "portal-test",
        },
    )
    assert listing_response.status_code == 200
    listed_payload = listing_response.json()
    assert listed_payload["listed"] is True
    assert listed_payload["record"]["isActive"] is True
    assert listed_payload["record"]["isListed"] is True

    versions_response = client.get("/api/portal/nl-customization/versions")
    assert versions_response.status_code == 200
    versions_payload = versions_response.json()
    assert versions_payload["items"][0]["isListed"] is True

    apps_response = client.get("/api/portal/nl-customization/apps")
    assert apps_response.status_code == 200
    apps_payload = apps_response.json()
    assert len(apps_payload["items"]) == 1
    assert apps_payload["items"][0]["versionId"] == published["versionId"]
    assert apps_payload["items"][0]["launchEmployeeId"] == "query"
    assert apps_payload["items"][0]["displayTargets"] == ["portal-home", "portal-card"]

    unlisting_response = client.post(
        "/api/portal/nl-customization/listing",
        json={
            "versionId": published["versionId"],
            "listed": False,
            "requestedBy": "portal-test",
        },
    )
    assert unlisting_response.status_code == 200
    assert unlisting_response.json()["listed"] is False

    apps_response = client.get("/api/portal/nl-customization/apps")
    assert apps_response.status_code == 200
    assert apps_response.json()["items"] == []


def test_nl_customization_delete_route_removes_non_active_version(
    monkeypatch,
    tmp_path,
) -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    client = TestClient(app)
    registry_path = tmp_path / "nl_customization_registry.json"
    bundle_dir = tmp_path / "nl_customization_bundles"
    active_path = tmp_path / "nl_customization_active.json"

    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_BUNDLE_DIR", bundle_dir)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_ACTIVE_PATH", active_path)

    first_preview = client.post(
        "/api/portal/nl-customization/preview",
        json={"prompt": "首页加一个待处理工单卡片，领导只能看汇总，运维能看明细。"},
    )
    second_preview = client.post(
        "/api/portal/nl-customization/preview",
        json={"prompt": "给我一个 Oracle 巡检助手，每天 8 点执行，异常自动建单，但不能自动变更。"},
    )
    first_publish = client.post(
        "/api/portal/nl-customization/publish",
        json={"preview": first_preview.json(), "requestedBy": "portal-test"},
    )
    second_publish = client.post(
        "/api/portal/nl-customization/publish",
        json={"preview": second_preview.json(), "requestedBy": "portal-test"},
    )
    assert first_publish.status_code == 200
    assert second_publish.status_code == 200

    active_version_id = first_publish.json()["versionId"]
    delete_version_id = second_publish.json()["versionId"]
    apply_response = client.post(
        "/api/portal/nl-customization/apply",
        json={"versionId": active_version_id, "requestedBy": "portal-test"},
    )
    assert apply_response.status_code == 200

    delete_response = client.delete(
        f"/api/portal/nl-customization/versions/{delete_version_id}",
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["versionId"] == delete_version_id
    assert not bundle_dir.joinpath(f"{delete_version_id}.json").exists()

    versions_response = client.get("/api/portal/nl-customization/versions")
    assert versions_response.status_code == 200
    remaining_versions = versions_response.json()["items"]
    assert len(remaining_versions) == 1
    assert remaining_versions[0]["versionId"] == active_version_id

    active_delete_response = client.delete(
        f"/api/portal/nl-customization/versions/{active_version_id}",
    )
    assert active_delete_response.status_code == 400
    assert "当前生效版本不允许删除" in active_delete_response.json()["detail"]


def test_nl_customization_supports_multiple_listed_apps(
    monkeypatch,
    tmp_path,
) -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    client = TestClient(app)
    registry_path = tmp_path / "nl_customization_registry.json"
    bundle_dir = tmp_path / "nl_customization_bundles"
    active_path = tmp_path / "nl_customization_active.json"

    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_BUNDLE_DIR", bundle_dir)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_ACTIVE_PATH", active_path)

    dashboard_preview = client.post(
        "/api/portal/nl-customization/preview",
        json={"prompt": "首页加一个待处理工单卡片，领导只能看汇总，运维能看明细。"},
    )
    inspection_preview = client.post(
        "/api/portal/nl-customization/preview",
        json={"prompt": "给我一个 Oracle 巡检助手，每天 8 点执行，异常自动建单，但不能自动变更。"},
    )
    dashboard_publish = client.post(
        "/api/portal/nl-customization/publish",
        json={"preview": dashboard_preview.json(), "requestedBy": "portal-test"},
    )
    inspection_publish = client.post(
        "/api/portal/nl-customization/publish",
        json={"preview": inspection_preview.json(), "requestedBy": "portal-test"},
    )
    dashboard_version_id = dashboard_publish.json()["versionId"]
    inspection_version_id = inspection_publish.json()["versionId"]

    apply_dashboard = client.post(
        "/api/portal/nl-customization/apply",
        json={"versionId": dashboard_version_id, "requestedBy": "portal-test"},
    )
    apply_inspection = client.post(
        "/api/portal/nl-customization/apply",
        json={"versionId": inspection_version_id, "requestedBy": "portal-test"},
    )
    assert apply_dashboard.status_code == 200
    assert apply_inspection.status_code == 200

    list_dashboard = client.post(
        "/api/portal/nl-customization/listing",
        json={"versionId": dashboard_version_id, "listed": True, "requestedBy": "portal-test"},
    )
    list_inspection = client.post(
        "/api/portal/nl-customization/listing",
        json={"versionId": inspection_version_id, "listed": True, "requestedBy": "portal-test"},
    )
    assert list_dashboard.status_code == 200
    assert list_inspection.status_code == 200

    apps_response = client.get("/api/portal/nl-customization/apps")
    assert apps_response.status_code == 200
    apps_items = apps_response.json()["items"]
    assert len(apps_items) == 2
    assert {item["versionId"] for item in apps_items} == {
        dashboard_version_id,
        inspection_version_id,
    }

    versions_response = client.get("/api/portal/nl-customization/versions")
    assert versions_response.status_code == 200
    versions_items = versions_response.json()["items"]
    active_versions = {
        item["versionId"]
        for item in versions_items
        if item.get("isActive")
    }
    listed_versions = {
        item["versionId"]
        for item in versions_items
        if item.get("isListed")
    }
    assert active_versions == {dashboard_version_id, inspection_version_id}
    assert listed_versions == {dashboard_version_id, inspection_version_id}


def test_nl_customization_registry_migrates_legacy_files(
    monkeypatch,
    tmp_path,
) -> None:
    legacy_registry_path = tmp_path / "nl_customization_registry.json"
    legacy_bundle_dir = tmp_path / "nl_customization_bundles"
    legacy_active_path = tmp_path / "nl_customization_active.json"
    new_registry_path = tmp_path / "extensions" / "nl_customization" / "registry.json"
    new_bundle_dir = tmp_path / "extensions" / "nl_customization" / "bundles"
    new_active_path = tmp_path / "extensions" / "nl_customization" / "active.json"

    legacy_bundle_dir.mkdir(parents=True, exist_ok=True)
    legacy_registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-05-12T10:00:00+08:00",
                "activeVersionId": "nlc-1",
                "appliedAt": "2026-05-12T10:00:00+08:00",
                "activePath": str(legacy_active_path),
                "items": [{"versionId": "nlc-1", "title": "测试应用"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    legacy_active_path.write_text(
        json.dumps(
            {
                "versionId": "nlc-1",
                "record": {"versionId": "nlc-1", "title": "测试应用"},
                "preview": {"bundle": {}},
                "effectiveBundle": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    legacy_bundle_dir.joinpath("nlc-1.json").write_text(
        json.dumps({"versionId": "nlc-1", "preview": {"bundle": {}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(registry, "LEGACY_NL_CUSTOMIZATION_REGISTRY_PATH", legacy_registry_path)
    monkeypatch.setattr(registry, "LEGACY_NL_CUSTOMIZATION_BUNDLE_DIR", legacy_bundle_dir)
    monkeypatch.setattr(registry, "LEGACY_NL_CUSTOMIZATION_ACTIVE_PATH", legacy_active_path)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_REGISTRY_PATH", new_registry_path)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_BUNDLE_DIR", new_bundle_dir)
    monkeypatch.setattr(registry, "NL_CUSTOMIZATION_ACTIVE_PATH", new_active_path)
    monkeypatch.setattr(registry, "DEFAULT_NL_CUSTOMIZATION_REGISTRY_PATH", new_registry_path)
    monkeypatch.setattr(registry, "DEFAULT_NL_CUSTOMIZATION_BUNDLE_DIR", new_bundle_dir)
    monkeypatch.setattr(registry, "DEFAULT_NL_CUSTOMIZATION_ACTIVE_PATH", new_active_path)

    items = registry.list_published_customizations(limit=10)

    assert items[0]["versionId"] == "nlc-1"
    assert new_registry_path.exists()
    assert new_active_path.exists()
    assert new_bundle_dir.joinpath("nlc-1.json").exists()
    assert not legacy_registry_path.exists()
    assert not legacy_active_path.exists()


def test_portal_backend_registers_nl_customization_routes() -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    paths = {route.path for route in app.routes}

    assert "/api/portal/nl-customization/preview" in paths
    assert "/api/portal/nl-customization/publish" in paths
    assert "/api/portal/nl-customization/apply" in paths
    assert "/api/portal/nl-customization/listing" in paths
    assert "/api/portal/nl-customization/active" in paths
    assert "/api/portal/nl-customization/apps" in paths
    assert "/api/portal/nl-customization/versions" in paths
    assert "/api/portal/nl-customization/versions/{version_id}" in paths
