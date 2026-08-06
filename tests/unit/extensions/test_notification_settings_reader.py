# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "extensions"
    / "notifications"
    / "notification_settings.py"
)
_SPEC = importlib.util.spec_from_file_location("notification_settings", MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
notification_settings = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notification_settings)


def _create_db(tmp_path: Path, channels: dict[str, dict]) -> Path:
    db_path = tmp_path / "extensions" / "settings" / "settings.db"
    db_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE settings (namespace TEXT, key TEXT, value TEXT)"
        )
        connection.executemany(
            "INSERT INTO settings VALUES (?, ?, ?)",
            [
                ("notification_channels", scope, json.dumps(payload))
                for scope, payload in channels.items()
            ],
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def test_resolves_exact_scope_from_shared_settings_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _create_db(
        tmp_path,
        {
            "inspection": {
                "push_url": "http://sqlite.example.com/push",
                "timeout_seconds": 12,
                "mention_all": True,
            },
        },
    )
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTION_NOTIFY_PUSH_URL", "http://env.example.com")

    assert notification_settings.resolve_notification_text(
        "inspection",
        "push_url",
        env_keys=["INSPECTION_NOTIFY_PUSH_URL"],
        start_path=tmp_path,
    ) == "http://sqlite.example.com/push"
    assert notification_settings.resolve_notification_int(
        "inspection",
        "timeout_seconds",
        env_keys=[],
        start_path=tmp_path,
        default=8,
    ) == 12
    assert notification_settings.resolve_notification_bool(
        "inspection",
        "mention_all",
        env_keys=[],
        start_path=tmp_path,
        default=False,
    )


def test_resolves_legacy_scope_then_environment_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _create_db(tmp_path, {"order_create": {"push_url": "http://legacy.example.com"}})
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("NOTIFY_TIMEOUT", "15")

    assert notification_settings.resolve_notification_text(
        "alarm_analyst",
        "push_url",
        env_keys=[],
        start_path=tmp_path,
    ) == "http://legacy.example.com"
    assert notification_settings.resolve_notification_int(
        "alarm_analyst",
        "timeout_seconds",
        env_keys=["NOTIFY_TIMEOUT"],
        start_path=tmp_path,
        default=8,
    ) == 15


def test_missing_or_invalid_db_uses_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))

    assert notification_settings.resolve_notification_text(
        "inspection", "push_url", env_keys=[], start_path=tmp_path, default="fallback"
    ) == "fallback"
    assert notification_settings.resolve_notification_bool(
        "inspection", "mention_all", env_keys=[], start_path=tmp_path, default=True
    )

    db_path = tmp_path / "extensions" / "settings" / "settings.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("not a sqlite database", "utf-8")
    assert notification_settings.resolve_notification_int(
        "inspection", "timeout_seconds", env_keys=[], start_path=tmp_path, default=8
    ) == 8
