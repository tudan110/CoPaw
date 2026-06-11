# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen import store


def _screen(screen_id: str = "screen-a", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "id": screen_id,
        "name": "测试大屏",
        "status": "draft",
        "layout": {"type": "grid"},
        "theme": {"mode": "dark"},
        "components": [{"id": "c1", "type": "table", "data": {}}],
        "dataBindings": [],
        "versions": [
            {
                "versionId": "v1",
                "screenId": screen_id,
                "changeSummary": "初始生成",
                "createdAt": "2026-06-11T10:00:00",
                "configSnapshot": {"id": screen_id},
            },
        ],
        "publishTargets": [],
    }
    payload.update(overrides)
    return payload


@pytest.fixture(name="db_path")
def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "ai_big_screen" / "ai_big_screen.sqlite3"


class TestScreensCrud:
    def test_save_get_roundtrip(self, db_path: Path) -> None:
        saved = store.save_screen(screen=_screen(), path=db_path)
        assert saved["updatedAt"]
        assert saved["updatedBy"] == "portal"
        fetched = store.get_screen(screen_id="screen-a", path=db_path)
        assert fetched["name"] == "测试大屏"
        assert fetched["components"][0]["id"] == "c1"

    def test_save_replaces_by_id(self, db_path: Path) -> None:
        store.save_screen(screen=_screen(), path=db_path)
        store.save_screen(
            screen=_screen(name="改名后"),
            requested_by="tester",
            path=db_path,
        )
        fetched = store.get_screen(screen_id="screen-a", path=db_path)
        assert fetched["name"] == "改名后"
        assert fetched["updatedBy"] == "tester"
        assert len(store.list_screens(path=db_path)) == 1

    def test_list_orders_by_updated_desc_and_limits(
        self,
        db_path: Path,
    ) -> None:
        for index in range(3):
            store.save_screen(
                screen=_screen(screen_id=f"screen-{index}"),
                path=db_path,
            )
        items = store.list_screens(limit=2, path=db_path)
        assert len(items) == 2
        assert items[0]["id"] == "screen-2"  # most recent first

    def test_get_missing_raises(self, db_path: Path) -> None:
        with pytest.raises(ValueError):
            store.get_screen(screen_id="nope", path=db_path)

    def test_delete_returns_and_removes(self, db_path: Path) -> None:
        store.save_screen(screen=_screen(), path=db_path)
        deleted = store.delete_screen(screen_id="screen-a", path=db_path)
        assert deleted["id"] == "screen-a"
        with pytest.raises(ValueError):
            store.get_screen(screen_id="screen-a", path=db_path)
        with pytest.raises(ValueError):
            store.delete_screen(screen_id="screen-a", path=db_path)


class TestVersionsMirror:
    def test_versions_mirrored_to_table(self, db_path: Path) -> None:
        screen = _screen()
        screen["versions"].append(
            {
                "versionId": "v2",
                "screenId": "screen-a",
                "changeSummary": "patch",
                "createdAt": "2026-06-11T11:00:00",
                "configSnapshot": {"id": "screen-a"},
            },
        )
        store.save_screen(screen=screen, path=db_path)
        versions = store.list_screen_versions(
            screen_id="screen-a",
            path=db_path,
        )
        assert [v["versionId"] for v in versions] == ["v1", "v2"]

    def test_delete_cascades_versions(self, db_path: Path) -> None:
        store.save_screen(screen=_screen(), path=db_path)
        store.delete_screen(screen_id="screen-a", path=db_path)
        assert (
            store.list_screen_versions(screen_id="screen-a", path=db_path)
            == []
        )


class TestDraftTasks:
    def test_task_lifecycle(self, db_path: Path) -> None:
        task = {
            "taskId": "task-1",
            "status": "queued",
            "stage": "queued",
            "message": "已创建生成任务",
            "createdAt": "2026-06-11T10:00:00",
            "updatedAt": "2026-06-11T10:00:00",
            "screen": None,
            "error": "",
        }
        store.create_task(task=task, path=db_path)
        fetched = store.get_task(task_id="task-1", path=db_path)
        assert fetched["status"] == "queued"

        store.update_task(
            task_id="task-1",
            updates={"status": "running", "stage": "取数"},
            path=db_path,
        )
        fetched = store.get_task(task_id="task-1", path=db_path)
        assert fetched["status"] == "running"
        assert fetched["stage"] == "取数"
        assert fetched["updatedAt"] >= task["updatedAt"]

        store.update_task(
            task_id="task-1",
            updates={
                "status": "succeeded",
                "stage": "completed",
                "screen": {"id": "screen-a", "components": []},
            },
            path=db_path,
        )
        fetched = store.get_task(task_id="task-1", path=db_path)
        assert fetched["screen"]["id"] == "screen-a"

    def test_get_missing_task_raises(self, db_path: Path) -> None:
        with pytest.raises(ValueError):
            store.get_task(task_id="task-miss", path=db_path)

    def test_update_missing_task_is_noop(self, db_path: Path) -> None:
        store.update_task(
            task_id="task-miss",
            updates={"status": "running"},
            path=db_path,
        )  # must not raise

    def test_purge_old_finished_tasks(self, db_path: Path) -> None:
        old = {
            "taskId": "task-old",
            "status": "succeeded",
            "stage": "completed",
            "createdAt": "2020-01-01T00:00:00",
            "updatedAt": "2020-01-01T00:00:00",
        }
        fresh = {
            "taskId": "task-fresh",
            "status": "running",
            "stage": "取数",
            "createdAt": "2020-01-01T00:00:00",
            "updatedAt": "2020-01-01T00:00:00",
        }
        store.create_task(task=old, path=db_path)
        store.create_task(task=fresh, path=db_path)
        purged = store.purge_tasks(ttl_seconds=3600, path=db_path)
        assert purged == 1  # finished+stale removed; running kept
        with pytest.raises(ValueError):
            store.get_task(task_id="task-old", path=db_path)
        assert store.get_task(task_id="task-fresh", path=db_path)


class TestMigration:
    def test_migrates_registry_json_once(
        self,
        tmp_path: Path,
        db_path: Path,
    ) -> None:
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "updatedAt": "2026-06-10T00:00:00",
                    "items": [
                        _screen(screen_id="legacy-1"),
                        _screen(screen_id="legacy-2", name="旧屏二"),
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        migrated = store.migrate_from_registry(
            registry_path=registry_path,
            path=db_path,
        )
        assert migrated == 2
        assert (
            store.get_screen(screen_id="legacy-2", path=db_path)["name"]
            == "旧屏二"
        )
        # idempotent: second run migrates nothing (db not empty)
        assert (
            store.migrate_from_registry(
                registry_path=registry_path,
                path=db_path,
            )
            == 0
        )

    def test_migrate_without_registry_is_zero(self, db_path: Path) -> None:
        assert (
            store.migrate_from_registry(
                registry_path=Path("Z:/no/such/registry.json"),
                path=db_path,
            )
            == 0
        )
