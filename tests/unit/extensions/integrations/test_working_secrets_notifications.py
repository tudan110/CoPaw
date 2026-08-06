# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.integrations import working_secrets


def _db(tmp_path: Path) -> Path:
    return tmp_path / "extensions" / "settings" / "settings.db"


def _clear_notification_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("QWENPAW_NOTIFICATION_") or name.startswith(
            ("INSPECTION_NOTIFY_", "ALARM_ANALYST_CREATE_NOTIFY_", "ORDER_CREATE_NOTIFY_")
        ):
            monkeypatch.delenv(name, raising=False)


def test_materializes_builtin_notification_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_notification_env(monkeypatch)
    settings_store.replace_namespace(
        "notification_channels",
        {
            "inspection": {
                "push_url": "http://inspection.example.com",
                "timeout_seconds": 12,
                "mention_all": False,
            },
            "alarm_analyst": {
                "push_url": "http://alarm.example.com",
                "dingtalk_secret": "alarm-secret",
                "mention_all": True,
            },
            "order_workflow": {
                "push_url": "http://order.example.com",
                "timeout_seconds": 9,
            },
        },
        db_path=db,
    )

    working_secrets.refresh_notification_channels_environ(db_path=db)

    assert os.environ["QWENPAW_NOTIFICATION_INSPECTION_PUSH_URL"] == (
        "http://inspection.example.com"
    )
    assert os.environ["INSPECTION_NOTIFY_TIMEOUT_SECONDS"] == "12"
    assert os.environ["QWENPAW_NOTIFICATION_INSPECTION_MENTION_ALL"] == "false"
    assert os.environ["QWENPAW_NOTIFICATION_ALARM_ANALYST_DINGTALK_SECRET"] == (
        "alarm-secret"
    )
    assert os.environ["ALARM_ANALYST_CREATE_NOTIFY_MENTION_ALL"] == "true"
    assert os.environ["QWENPAW_NOTIFICATION_ORDER_WORKFLOW_PUSH_URL"] == (
        "http://order.example.com"
    )
    assert os.environ["ORDER_CREATE_NOTIFY_WEBHOOK_URL"] == "http://order.example.com"


def test_notification_legacy_scope_fallback_and_stale_value_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_notification_env(monkeypatch)
    settings_store.replace_namespace(
        "notification_channels",
        {"order_create": {"push_url": "http://legacy.example.com"}},
        db_path=db,
    )

    working_secrets.refresh_notification_channels_environ(db_path=db)

    assert os.environ["QWENPAW_NOTIFICATION_ALARM_ANALYST_PUSH_URL"] == (
        "http://legacy.example.com"
    )
    assert os.environ["QWENPAW_NOTIFICATION_ORDER_WORKFLOW_PUSH_URL"] == (
        "http://legacy.example.com"
    )
    assert "QWENPAW_NOTIFICATION_INSPECTION_PUSH_URL" not in os.environ

    settings_store.replace_namespace(
        "notification_channels",
        {"alarm_analyst": {"push_url": ""}},
        db_path=db,
    )
    working_secrets.refresh_notification_channels_environ(db_path=db)

    assert "QWENPAW_NOTIFICATION_ALARM_ANALYST_PUSH_URL" not in os.environ
    assert "QWENPAW_NOTIFICATION_ORDER_WORKFLOW_PUSH_URL" not in os.environ
    assert "ORDER_CREATE_NOTIFY_PUSH_URL" not in os.environ


def test_notification_materialization_does_not_disturb_env_without_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_notification_env(monkeypatch)
    monkeypatch.setenv("ORDER_CREATE_NOTIFY_PUSH_URL", "http://external.example.com")

    working_secrets.materialize_notification_channels_to_environ(db_path=db)

    assert os.environ["ORDER_CREATE_NOTIFY_PUSH_URL"] == "http://external.example.com"
