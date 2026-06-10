# -*- coding: utf-8 -*-
"""API-contract tests for the AI big-screen routes (P2 pipeline).

Deep pipeline behaviour (status adjudication, guardrails, patch
semantics, degradation) is covered by tests/unit/extensions/
ai_big_screen/. These tests pin the HTTP-facing contract: route
wiring, the legacy AiBigScreenApp wire shape, the draft-task polling
protocol, and asset CRUD over the registry.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import HTTPException

from qwenpaw.extensions import ai_big_screen_registry as registry
from qwenpaw.extensions.api.ai_big_screen_api import (
    create_ai_big_screen_draft_task,
    delete_ai_big_screen,
    duplicate_ai_big_screen,
    generate_ai_big_screen_draft,
    get_ai_big_screen,
    get_ai_big_screen_draft_task,
    list_ai_big_screen_plugins,
    list_ai_big_screens,
    patch_ai_big_screen,
    publish_ai_big_screen,
    rename_ai_big_screen,
    save_ai_big_screen,
)
from qwenpaw.extensions.api.ai_big_screen_models import (
    AiBigScreenDraftRequest,
    AiBigScreenDuplicateRequest,
    AiBigScreenPatchRequest,
    AiBigScreenPublishRequest,
    AiBigScreenRenameRequest,
    AiBigScreenSaveRequest,
)


@pytest.fixture(autouse=True)
def _tmp_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(
        registry,
        "AI_BIG_SCREEN_REGISTRY_PATH",
        tmp_path / "ai_big_screen" / "registry.json",
    )


@pytest.fixture(autouse=True)
def _live_workorders(monkeypatch: pytest.MonkeyPatch) -> None:
    from qwenpaw.extensions.integrations import order_workflow

    monkeypatch.setattr(
        order_workflow,
        "query_order_workorders",
        lambda **_kw: {
            "source": "live",
            "total": 1,
            "items": [{"id": "wo-1", "title": "磁盘工单", "status": "todo"}],
            "stats": {"todo": 1},
        },
    )


class FakeModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    async def __call__(self, _messages: list[dict[str, str]]) -> Any:
        return {"text": self.responses.pop(0)}


def test_plugins_endpoint_lists_capability_catalog() -> None:
    response = list_ai_big_screen_plugins()
    ids = {item["id"] for item in response.items}
    assert "real-alarms" in ids
    assert "capability-gap" in ids


class TestDraftEndpoints:
    async def test_draft_returns_legacy_screen_shape(self) -> None:
        response = await generate_ai_big_screen_draft(
            AiBigScreenDraftRequest(prompt="查询今日工单", title="工单屏"),
        )
        screen = response.screen
        assert screen["name"] == "工单屏"
        assert screen["components"][0]["capabilityId"] == "workorders"
        assert screen["components"][0]["data"]["sourceStatus"] == "live"
        assert screen["versions"][0]["versionId"] == "v1"
        assert screen["dataBindings"]

    async def test_empty_prompt_is_400(self) -> None:
        with pytest.raises(HTTPException) as excinfo:
            await generate_ai_big_screen_draft(
                AiBigScreenDraftRequest(prompt="  "),
            )
        assert excinfo.value.status_code == 400

    async def test_draft_task_lifecycle_with_real_stages(self) -> None:
        created = await create_ai_big_screen_draft_task(
            AiBigScreenDraftRequest(prompt="查询今日工单"),
        )
        task_id = created.task["taskId"]
        assert created.task["status"] == "queued"

        current = created.task
        for _ in range(100):
            await asyncio.sleep(0.05)
            current = get_ai_big_screen_draft_task(task_id).task
            if current["status"] in {"succeeded", "failed"}:
                break
        assert current["status"] == "succeeded"
        assert current["stage"] == "completed"
        assert current["screen"]["components"]

    async def test_unknown_task_is_404(self) -> None:
        with pytest.raises(HTTPException) as excinfo:
            get_ai_big_screen_draft_task("task-missing")
        assert excinfo.value.status_code == 404


async def _draft_and_save(name: str = "工单屏") -> dict[str, Any]:
    draft = (
        await generate_ai_big_screen_draft(
            AiBigScreenDraftRequest(prompt="查询今日工单", title=name),
        )
    ).screen
    return save_ai_big_screen(
        AiBigScreenSaveRequest(screen=draft, requestedBy="tester"),
    ).screen


class TestCrudEndpoints:
    async def test_save_get_list_roundtrip(self) -> None:
        saved = await _draft_and_save()
        fetched = get_ai_big_screen(saved["id"]).screen
        assert fetched["name"] == "工单屏"
        items = list_ai_big_screens(limit=50).items
        assert any(item["id"] == saved["id"] for item in items)

    async def test_rename_and_duplicate(self) -> None:
        saved = await _draft_and_save()
        renamed = rename_ai_big_screen(
            saved["id"],
            AiBigScreenRenameRequest(name="改名屏", requestedBy="tester"),
        ).screen
        assert renamed["name"] == "改名屏"
        duplicated = duplicate_ai_big_screen(
            saved["id"],
            AiBigScreenDuplicateRequest(requestedBy="tester"),
        ).screen
        assert duplicated["id"] != saved["id"]
        assert duplicated["status"] == "draft"
        assert duplicated["versions"][0]["versionId"] == "v1"

    async def test_delete(self) -> None:
        saved = await _draft_and_save()
        deleted = delete_ai_big_screen(saved["id"])
        assert deleted.screenId == saved["id"]
        assert deleted.deleted is True
        with pytest.raises(HTTPException) as excinfo:
            get_ai_big_screen(saved["id"])
        assert excinfo.value.status_code == 404

    async def test_publish_creates_external_link(self) -> None:
        saved = await _draft_and_save()
        published = publish_ai_big_screen(
            saved["id"],
            AiBigScreenPublishRequest(requestedBy="tester"),
        )
        assert published.screen["status"] == "published"
        types = {t["type"] for t in published.publishTargets}
        assert {"portal-center", "external-link", "iframe"} <= types
        external = next(
            t for t in published.publishTargets if t["type"] == "external-link"
        )
        assert external["url"] == f"/big-screen/{saved['id']}"


class TestPatchEndpoint:
    async def test_patch_applies_and_persists_version(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        saved = await _draft_and_save()
        component_id = saved["components"][0]["id"]
        from qwenpaw.extensions.ai_big_screen import patch as patch_module

        monkeypatch.setattr(
            patch_module,
            "create_pipeline_model",
            lambda: FakeModel(
                [
                    json.dumps(
                        {
                            "summary": "改了标题",
                            "operations": [
                                {
                                    "op": "setComponentTitle",
                                    "componentId": component_id,
                                    "value": "重点工单",
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ],
            ),
        )
        response = await patch_ai_big_screen(
            saved["id"],
            AiBigScreenPatchRequest(
                instruction="把标题改成重点工单",
                selectedComponentId=component_id,
                requestedBy="tester",
            ),
        )
        assert response.summary == "改了标题"
        assert response.version["versionId"] == "v2"
        persisted = get_ai_big_screen(saved["id"]).screen
        component = next(
            c for c in persisted["components"] if c["id"] == component_id
        )
        assert component["title"] == "重点工单"
        assert [v["versionId"] for v in persisted["versions"]] == [
            "v1",
            "v2",
        ]

    async def test_patch_empty_instruction_is_400(self) -> None:
        saved = await _draft_and_save()
        with pytest.raises(HTTPException) as excinfo:
            await patch_ai_big_screen(
                saved["id"],
                AiBigScreenPatchRequest(instruction="  "),
            )
        assert excinfo.value.status_code == 400
