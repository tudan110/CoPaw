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
    settings_db = tmp_path / "extensions" / "settings" / "settings.db"
    with patch(
        "qwenpaw.extensions.api.notification_settings_api._SETTINGS_DB",
        settings_db,
    ):
        yield {"db": settings_db, "root": tmp_path}


async def test_get_notification_channels_defaults():
    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert resp.json() == {
        "inspection": _default_scope(),
        "alarm_analyst": _default_scope(),
        "order_workflow": _default_scope(),
    }


async def test_put_notification_channels_roundtrip(
    _use_tmp_settings: dict[str, Path],
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
        "PUT", "/api/portal/settings/notification-channels", json=payload
    )
    get_resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert put_resp.status_code == 200
    assert get_resp.status_code == 200
    assert get_resp.json()["alarm_analyst"] == payload["alarm_analyst"]
    assert get_resp.json()["order_workflow"]["timeout_seconds"] == 8
    assert settings_store.get_namespace(
        "notification_channels", db_path=_use_tmp_settings["db"]
    )["alarm_analyst"] == payload["alarm_analyst"]


async def test_put_notification_channels_accepts_custom_scope(
    _use_tmp_settings: dict[str, Path],
):
    put_resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={
            "web_monitor": {
                "push_url": " http://notify.example.com/web ",
                "timeout_seconds": "10",
                "mention_all": "true",
            },
        },
    )

    assert put_resp.status_code == 200
    assert put_resp.json()["web_monitor"] == {
        **_default_scope(),
        "push_url": "http://notify.example.com/web",
        "timeout_seconds": 10,
        "mention_all": True,
    }
    assert settings_store.get_namespace(
        "notification_channels", db_path=_use_tmp_settings["db"]
    )["web_monitor"]["push_url"] == "http://notify.example.com/web"


async def test_put_notification_channels_preserves_other_scopes(
    _use_tmp_settings: dict[str, Path],
):
    settings_store.replace_namespace(
        "notification_channels",
        {
            "order_workflow": {
                **_default_scope(),
                "push_url": "http://order.example.com/push",
                "timeout_seconds": 9,
                "mention_all": True,
            },
        },
        db_path=_use_tmp_settings["db"],
    )

    resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={
            "alarm_analyst": {
                "push_url": "http://alarm.example.com/push",
                "timeout_seconds": 15,
                "mention_all": False,
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json()["order_workflow"]["push_url"] == "http://order.example.com/push"
    assert resp.json()["alarm_analyst"]["push_url"] == "http://alarm.example.com/push"


async def test_get_notification_channels_uses_legacy_scope_alias(
    _use_tmp_settings: dict[str, Path],
):
    settings_store.replace_namespace(
        "notification_channels",
        {
            "order_create": {
                **_default_scope(),
                "push_url": "http://legacy.example.com/push",
                "timeout_seconds": 11,
                "mention_all": True,
            },
        },
        db_path=_use_tmp_settings["db"],
    )

    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert resp.json()["alarm_analyst"]["push_url"] == "http://legacy.example.com/push"
    assert resp.json()["order_workflow"]["push_url"] == "http://legacy.example.com/push"


async def test_get_notification_channels_ignores_legacy_json(
    _use_tmp_settings: dict[str, Path],
):
    legacy_file = (
        _use_tmp_settings["root"]
        / "extensions"
        / "notifications"
        / "settings.json"
    )
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(
        json.dumps(
            {"notification_channels": {"inspection": {"push_url": "ignored"}}}
        ),
        "utf-8",
    )

    resp = await _request("GET", "/api/portal/settings/notification-channels")

    assert resp.status_code == 200
    assert resp.json()["inspection"] == _default_scope()


async def test_delete_notification_channels_removes_custom_scope():
    await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={"web_monitor": {"push_url": "http://notify.example.com/web"}},
    )
    delete_resp = await _request(
        "DELETE", "/api/portal/settings/notification-channels/web_monitor"
    )

    assert delete_resp.status_code == 200
    assert "web_monitor" not in delete_resp.json()


async def test_delete_notification_channels_rejects_builtin_scope():
    resp = await _request(
        "DELETE", "/api/portal/settings/notification-channels/order_workflow"
    )

    assert resp.status_code == 400
    assert "Built-in notification scope cannot be deleted" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"inspection": {"timeout_seconds": 0}}, "greater than 0"),
        ({"web_monitor": ["not", "a", "dict"]}, "Invalid notification scope"),
    ],
)
async def test_put_notification_channels_rejects_invalid_payload(
    payload: dict, detail: str
):
    resp = await _request(
        "PUT", "/api/portal/settings/notification-channels", json=payload
    )

    assert resp.status_code == 400
    assert detail in resp.json()["detail"]


async def test_put_notification_channels_ignores_deprecated_keyword():
    resp = await _request(
        "PUT",
        "/api/portal/settings/notification-channels",
        json={
            "inspection": {
                "push_url": "http://notify.example.com/push",
                "dingtalk_keyword": "inspection",
            },
        },
    )

    assert resp.status_code == 200
    assert "dingtalk_keyword" not in resp.json()["inspection"]
