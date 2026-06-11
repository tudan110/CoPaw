# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.api.notification_settings_api import router

app = FastAPI()
app.include_router(router, prefix="/api/portal")


async def _request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        return await client.request(method, path, **kwargs)


def _default_scope() -> dict[str, object]:
    return {
        "push_url": "",
        "dingtalk_webhook_url": "",
        "dingtalk_secret": "",
        "feishu_webhook_url": "",
        "feishu_secret": "",
        "timeout_seconds": 8,
        "mention_all": False,
    }


@pytest.fixture(autouse=True)
def _use_tmp_settings(tmp_path: Path):
    settings_file = tmp_path / "extensions" / "notifications" / "settings.json"
    legacy_settings_file = tmp_path / "settings.json"
    settings_db = tmp_path / "extensions" / "settings" / "settings.db"
    with (
        patch(
            "qwenpaw.extensions.api.notification_settings_api._SETTINGS_FILE",
            settings_file,
        ),
        patch(
            "qwenpaw.extensions.api.notification_settings_api._LEGACY_SETTINGS_FILE",
            legacy_settings_file,
        ),
        patch(
            "qwenpaw.extensions.api.notification_settings_api._SETTINGS_DB",
            settings_db,
        ),
    ):
        yield {
            "current": settings_file,
            "legacy": legacy_settings_file,
            "db": settings_db,
        }


async def test_get_notification_channels_defaults():
    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert resp.json() == {
        "inspection": _default_scope(),
        "alarm_analyst": _default_scope(),
        "order_workflow": _default_scope(),
    }


async def test_put_notification_channels_roundtrip(
    _use_tmp_settings: dict[str, Path]
):
    payload = {
        "alarm_analyst": {
            "push_url": "http://notify.example.com/push",
            "dingtalk_webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=test",
            "dingtalk_secret": "SEC-test",
            "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "feishu_secret": "feishu-secret",
            "timeout_seconds": 12,
            "mention_all": True,
        },
    }

    put_resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json=payload,
    )
    get_resp = await _request(
        "GET", "/api/portal/settings/notification-channels"
    )

    assert put_resp.status_code == 200
    assert get_resp.status_code == 200
    assert get_resp.json()["alarm_analyst"] == payload["alarm_analyst"]
    assert get_resp.json()["order_workflow"]["timeout_seconds"] == 8

    stored = settings_store.get_namespace(
        "notification_channels",
        db_path=_use_tmp_settings["db"],
    )
    assert stored["alarm_analyst"] == payload["alarm_analyst"]


async def test_put_notification_channels_accepts_custom_scope(
    _use_tmp_settings: dict[str, Path],
):
    payload = {
        "web_monitor": {
            "push_url": " http://notify.example.com/web ",
            "timeout_seconds": "10",
            "mention_all": "true",
        },
    }

    put_resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json=payload,
    )
    get_resp = await _request(
        "GET", "/api/portal/settings/notification-channels"
    )

    assert put_resp.status_code == 200
    assert get_resp.status_code == 200
    assert get_resp.json()["web_monitor"] == {
        **_default_scope(),
        "push_url": "http://notify.example.com/web",
        "timeout_seconds": 10,
        "mention_all": True,
    }

    stored = settings_store.get_namespace(
        "notification_channels",
        db_path=_use_tmp_settings["db"],
    )
    assert stored["web_monitor"]["push_url"] == (
        "http://notify.example.com/web"
    )


async def test_delete_notification_channels_removes_custom_scope():
    put_resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={"web_monitor": {"push_url": "http://notify.example.com/web"}},
    )
    delete_resp = await _request(
        "DELETE",
        "/api/portal/settings/notification-channels/web_monitor",
    )

    assert put_resp.status_code == 200
    assert delete_resp.status_code == 200
    assert "web_monitor" not in delete_resp.json()


async def test_delete_notification_channels_rejects_builtin_scope():
    resp = await _request(
        "DELETE",
        "/api/portal/settings/notification-channels/order_workflow",
    )

    assert resp.status_code == 400
    assert (
        "Built-in notification scope cannot be deleted"
        in resp.json()["detail"]
    )


async def test_put_notification_channels_preserves_other_settings(
    _use_tmp_settings: dict[str, Path],
):
    # Seed an existing scope via the legacy JSON, which is migrated into the
    # shared settings DB on first access.
    _use_tmp_settings["current"].parent.mkdir(parents=True, exist_ok=True)
    _use_tmp_settings["current"].write_text(
        json.dumps(
            {
                "notification_channels": {
                    "order_workflow": {
                        "push_url": "http://order.example.com/push",
                        "dingtalk_webhook_url": "",
                        "dingtalk_secret": "",
                        "feishu_webhook_url": "",
                        "feishu_secret": "",
                        "timeout_seconds": 9,
                        "mention_all": True,
                    },
                },
            },
        ),
        "utf-8",
    )

    resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={
            "alarm_analyst": {
                "push_url": "http://inspection.example.com/push",
                "timeout_seconds": 15,
                "mention_all": False,
            },
        },
    )

    assert resp.status_code == 200
    # Updating one scope must not drop the other; verify through the API.
    payload = resp.json()
    assert payload["order_workflow"]["push_url"] == (
        "http://order.example.com/push"
    )
    assert payload["alarm_analyst"]["push_url"] == (
        "http://inspection.example.com/push"
    )

    get_resp = await _request(
        "GET",
        "/api/portal/settings/notification-channels",
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["order_workflow"]["push_url"] == (
        "http://order.example.com/push"
    )


async def test_put_notification_channels_rejects_invalid_timeout():
    resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={"inspection": {"timeout_seconds": 0}},
    )

    assert resp.status_code == 400
    assert "greater than 0" in resp.json()["detail"]


async def test_put_notification_channels_rejects_invalid_scope_payload():
    resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={"web_monitor": ["not", "a", "dict"]},
    )

    assert resp.status_code == 400
    assert "Invalid notification scope" in resp.json()["detail"]


async def test_get_notification_channels_ignores_deprecated_keyword(
    _use_tmp_settings: dict[str, Path],
):
    _use_tmp_settings["current"].parent.mkdir(parents=True, exist_ok=True)
    _use_tmp_settings["current"].write_text(
        json.dumps(
            {
                "notification_channels": {
                    "inspection": {
                        "push_url": "http://notify.example.com/push",
                        "dingtalk_webhook_url": "",
                        "dingtalk_secret": "",
                        "dingtalk_keyword": "inspection",
                        "feishu_webhook_url": "",
                        "feishu_secret": "",
                        "timeout_seconds": 10,
                        "mention_all": True,
                    },
                },
            },
        ),
        "utf-8",
    )

    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert "dingtalk_keyword" not in resp.json()["inspection"]
    assert (
        resp.json()["inspection"]["push_url"]
        == "http://notify.example.com/push"
    )


async def test_get_notification_channels_maps_legacy_order_create_scope(
    _use_tmp_settings: dict[str, Path],
):
    _use_tmp_settings["legacy"].write_text(
        json.dumps(
            {
                "notification_channels": {
                    "order_create": {
                        "push_url": "http://legacy.example.com/push",
                        "dingtalk_webhook_url": (
                            "https://oapi.dingtalk.com/robot/send?access_token=legacy"
                        ),
                        "dingtalk_secret": "SEC-legacy",
                        "feishu_webhook_url": "",
                        "feishu_secret": "",
                        "timeout_seconds": 11,
                        "mention_all": True,
                    },
                },
            },
        ),
        "utf-8",
    )

    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert (
        resp.json()["alarm_analyst"]["push_url"]
        == "http://legacy.example.com/push"
    )
    assert (
        resp.json()["order_workflow"]["push_url"]
        == "http://legacy.example.com/push"
    )
