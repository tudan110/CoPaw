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


def test_portal_backend_registers_nl_customization_routes() -> None:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    paths = {route.path for route in app.routes}

    assert "/api/portal/nl-customization/preview" in paths
    assert "/api/portal/nl-customization/publish" in paths
    assert "/api/portal/nl-customization/versions" in paths
