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

from qwenpaw.extensions.ai_big_screen import store
from qwenpaw.extensions.api.ai_big_screen_api import (
    create_ai_big_screen_draft_task,
    delete_ai_big_screen,
    duplicate_ai_big_screen,
    generate_ai_big_screen_draft,
    get_ai_big_screen,
    get_ai_big_screen_capability_config,
    get_ai_big_screen_draft_task,
    get_ai_big_screen_metrics,
    list_ai_big_screen_plugins,
    list_ai_big_screens,
    patch_ai_big_screen,
    publish_ai_big_screen,
    refresh_ai_big_screen,
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
def _tmp_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(
        store,
        "DEFAULT_DB_PATH",
        tmp_path / "ai_big_screen" / "ai_big_screen.sqlite3",
    )
    # keep the one-time default migration away from the real registry
    monkeypatch.setattr(
        store,
        "DEFAULT_REGISTRY_PATH",
        tmp_path / "ai_big_screen" / "registry.json",
    )
    monkeypatch.setattr(store, "_DEFAULT_MIGRATION_DONE", False)


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


class TestRefreshEndpoint:
    async def test_refresh_rehydrates_and_persists(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.integrations import order_workflow

        saved = await _draft_and_save()
        assert saved["components"][0]["data"]["rows"][0]["id"] == "wo-1"

        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: {
                "source": "live",
                "total": 2,
                "items": [
                    {"id": "wo-9", "title": "新工单", "status": "todo"},
                ],
                "stats": {"todo": 1},
            },
        )
        refreshed = (await refresh_ai_big_screen(saved["id"])).screen
        assert refreshed["components"][0]["data"]["rows"][0]["id"] == "wo-9"
        assert len(refreshed["versions"]) == len(saved["versions"])

        persisted = get_ai_big_screen(saved["id"]).screen
        assert persisted["components"][0]["data"]["rows"][0]["id"] == "wo-9"

    async def test_refresh_missing_screen_is_404(self) -> None:
        with pytest.raises(HTTPException) as excinfo:
            await refresh_ai_big_screen("screen-missing")
        assert excinfo.value.status_code == 404


class TestMetricsEndpoint:
    def test_metrics_aggregates_recent_window(self) -> None:
        from qwenpaw.extensions.ai_big_screen import telemetry

        telemetry.record_generation(
            {"kind": "draft", "success": True, "durationMs": 1000},
        )
        telemetry.record_generation(
            {
                "kind": "patch",
                "success": False,
                "durationMs": 200,
                "capabilityStatuses": {"real-alarms": "failed"},
            },
        )
        response = get_ai_big_screen_metrics(limit=100)
        assert response.total == 2
        assert response.successRate == pytest.approx(0.5)
        assert response.kinds == {"draft": 1, "patch": 1}
        assert response.capabilityFailureRates["real-alarms"] == 1.0

    async def test_draft_and_refresh_record_events(self) -> None:
        saved = await _draft_and_save()
        await refresh_ai_big_screen(saved["id"])
        response = get_ai_big_screen_metrics(limit=100)
        assert response.kinds.get("draft", 0) >= 1
        assert response.kinds.get("refresh", 0) == 1
        assert response.successRate == 1.0


class TestCapabilityConfigEndpoint:
    def test_lists_capabilities_with_domain_and_health(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # INOE configured, n9e not → mixed health
        for var in (
            "N9E_API_BASE_URL",
            "N9E_USER_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("INOE_API_BASE_URL", "http://82.156.83.38:30080")
        monkeypatch.setenv("INOE_API_TOKEN", "tok")

        response = get_ai_big_screen_capability_config()
        by_id = {item.id: item for item in response.items}

        # the planning-only gap capability is not a data source
        assert "capability-gap" not in by_id
        # functional-domain + connection are surfaced per capability
        assert by_id["real-alarms"].category == "alarm"
        assert by_id["real-alarms"].connection == "inoe"
        assert by_id["real-alarms"].configured is True
        # n9e-backed logs report unconfigured + the tab to fix it
        assert by_id["system-logs"].configured is False
        assert by_id["system-logs"].settingsTab == "n9e"
        assert by_id["system-logs"].reason
        # web capability never needs a connection
        assert by_id["web-live-data"].configured is True


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

    async def test_patch_preview_returns_diff_without_persisting(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        saved = await _draft_and_save()
        component_id = saved["components"][0]["id"]
        original_title = saved["components"][0]["title"]
        from qwenpaw.extensions.ai_big_screen import patch as patch_module

        monkeypatch.setattr(
            patch_module,
            "create_pipeline_model",
            lambda: FakeModel(
                [
                    json.dumps(
                        {
                            "summary": "预览标题变更",
                            "operations": [
                                {
                                    "op": "setComponentTitle",
                                    "componentId": component_id,
                                    "value": "预览后的标题",
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
                instruction="把标题改成预览后的标题",
                selectedComponentId=component_id,
                requestedBy="tester",
                preview=True,
            ),
        )
        assert response.preview is True
        assert response.version is None
        assert response.diff == [
            {
                "componentId": component_id,
                "field": "title",
                "before": original_title,
                "after": "预览后的标题",
            },
        ]
        preview_component = next(
            c for c in response.screen["components"] if c["id"] == component_id
        )
        assert preview_component["title"] == "预览后的标题"
        # nothing persisted: same title, same single version
        persisted = get_ai_big_screen(saved["id"]).screen
        component = next(
            c for c in persisted["components"] if c["id"] == component_id
        )
        assert component["title"] == original_title
        assert [v["versionId"] for v in persisted["versions"]] == ["v1"]
