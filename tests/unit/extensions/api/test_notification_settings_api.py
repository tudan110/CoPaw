# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.extensions.api.notification_settings_api import router

app = FastAPI()
app.include_router(router, prefix="/api/portal")


async def _request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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
            "qwenpaw.extensions.api.notification_settings_api.NOTIFICATIONS_DATA_DIR",
            settings_file.parent,
        ),
    ):
        yield {
            "current": settings_file,
            "legacy": legacy_settings_file,
        }


async def test_get_notification_channels_defaults():
    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert resp.json() == {
        "inspection": _default_scope(),
        "alarm_analyst": _default_scope(),
        "order_workflow": _default_scope(),
    }


async def test_put_notification_channels_roundtrip(_use_tmp_settings: dict[str, Path]):
    payload = {
        "alarm_analyst": {
            "push_url": "http://notify.example.com/push",
            "dingtalk_webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=test",
            "dingtalk_secret": "SEC-test",
            "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "feishu_secret": "feishu-secret",
            "timeout_seconds": 12,
            "mention_all": True,
        }
    }

    put_resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json=payload,
    )
    get_resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert put_resp.status_code == 200
    assert get_resp.status_code == 200
    assert get_resp.json()["alarm_analyst"] == payload["alarm_analyst"]
    assert get_resp.json()["order_workflow"]["timeout_seconds"] == 8

    data = json.loads(_use_tmp_settings["current"].read_text("utf-8"))
    assert data["notification_channels"]["alarm_analyst"] == payload["alarm_analyst"]


async def test_put_notification_channels_preserves_other_settings(
    _use_tmp_settings: dict[str, Path],
):
    _use_tmp_settings["current"].parent.mkdir(parents=True, exist_ok=True)
    _use_tmp_settings["current"].write_text(
        json.dumps(
            {
                "theme": "dark",
                "notification_channels": {
                    "order_workflow": {
                        "push_url": "http://order.example.com/push",
                        "dingtalk_webhook_url": "",
                        "dingtalk_secret": "",
                        "feishu_webhook_url": "",
                        "feishu_secret": "",
                        "timeout_seconds": 9,
                        "mention_all": True,
                    }
                },
            }
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
            }
        },
    )

    assert resp.status_code == 200
    data = json.loads(_use_tmp_settings["current"].read_text("utf-8"))
    assert data["theme"] == "dark"
    assert data["notification_channels"]["order_workflow"]["push_url"] == (
        "http://order.example.com/push"
    )
    assert data["notification_channels"]["alarm_analyst"]["push_url"] == (
        "http://inspection.example.com/push"
    )


async def test_put_notification_channels_rejects_invalid_timeout():
    resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={"inspection": {"timeout_seconds": 0}},
    )

    assert resp.status_code == 400
    assert "greater than 0" in resp.json()["detail"]


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
                    }
                }
            }
        ),
        "utf-8",
    )

    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert "dingtalk_keyword" not in resp.json()["inspection"]
    assert resp.json()["inspection"]["push_url"] == "http://notify.example.com/push"


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
                    }
                }
            }
        ),
        "utf-8",
    )

    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert resp.json()["alarm_analyst"]["push_url"] == "http://legacy.example.com/push"
    assert resp.json()["order_workflow"]["push_url"] == "http://legacy.example.com/push"
