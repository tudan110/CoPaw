# -*- coding: utf-8 -*-
"""应用成果上架/下架（listed_at）相关的 API 测试。"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.extensions.api import app_artifacts_service as service
from qwenpaw.extensions.api.app_artifacts_api import (
    router as app_artifacts_router,
)


@pytest.fixture(autouse=True)
def _isolated_artifacts_storage(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "app_artifacts"
    monkeypatch.setattr(service, "APP_ARTIFACTS_DATA_DIR", data_dir)
    monkeypatch.setattr(
        service,
        "APP_ARTIFACTS_DB_PATH",
        data_dir / "artifacts.db",
    )
    monkeypatch.setattr(
        service,
        "APP_ARTIFACTS_HTML_DIR",
        data_dir / "html",
    )
    monkeypatch.setattr(service, "_DB_INITIALIZED", False)


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(app_artifacts_router, prefix="/api/portal")
    return TestClient(app)


def _create_app(client: TestClient, title: str = "测试应用") -> str:
    response = client.post(
        "/api/portal/app-artifacts",
        json={
            "title": title,
            "description": "desc",
            "type": "app",
            "html_content": "<html><body>hi</body></html>",
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_legacy_db_without_listed_at_is_migrated() -> None:
    """旧 schema（无 listed_at 列）的存量库可被迁移并正常读取。"""
    db_path = service.APP_ARTIFACTS_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE apps (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'app',
            status TEXT NOT NULL DEFAULT 'published',
            author TEXT NOT NULL DEFAULT '',
            session_id TEXT,
            html_path TEXT,
            config TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO apps (
            id, title, description, type, status, author,
            session_id, html_path, config, tags, version,
            created_at, updated_at
        ) VALUES (
            'legacy01', '旧应用', '', 'app', 'published', '',
            NULL, NULL, NULL, '[]', 1,
            '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
        """,
    )
    conn.commit()
    conn.close()

    client = _make_client()
    response = client.get("/api/portal/app-artifacts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "legacy01"
    assert items[0]["listed_at"] == ""


def test_listing_round_trip_and_listed_filter() -> None:
    client = _make_client()
    app_id = _create_app(client)

    listed = client.post(
        f"/api/portal/app-artifacts/{app_id}/listing",
        json={"listed": True},
    )
    assert listed.status_code == 200
    assert listed.json()["listed_at"] != ""

    only_listed = client.get("/api/portal/app-artifacts?listed=true")
    assert only_listed.status_code == 200
    assert [i["id"] for i in only_listed.json()["items"]] == [app_id]

    unlisted = client.post(
        f"/api/portal/app-artifacts/{app_id}/listing",
        json={"listed": False},
    )
    assert unlisted.status_code == 200
    assert unlisted.json()["listed_at"] == ""

    only_listed_again = client.get(
        "/api/portal/app-artifacts?listed=true",
    )
    assert only_listed_again.json()["items"] == []
    not_listed = client.get("/api/portal/app-artifacts?listed=false")
    assert [i["id"] for i in not_listed.json()["items"]] == [app_id]


def test_listing_requires_published_status() -> None:
    client = _make_client()
    app_id = _create_app(client)

    offline = client.put(
        f"/api/portal/app-artifacts/{app_id}",
        json={"status": "offline"},
    )
    assert offline.status_code == 200

    response = client.post(
        f"/api/portal/app-artifacts/{app_id}/listing",
        json={"listed": True},
    )
    assert response.status_code == 400
    assert "仅已发布的应用可以上架" in response.json()["detail"]


def test_listing_unknown_app_returns_404() -> None:
    client = _make_client()
    response = client.post(
        "/api/portal/app-artifacts/nonexistent/listing",
        json={"listed": True},
    )
    assert response.status_code == 404
