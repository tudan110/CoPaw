# -*- coding: utf-8 -*-
"""Unit tests for the alarm-diagnosis settings override store.

Covers the resolution priority (DB override > env > default), the
override write/delete lifecycle, the masked-token payload, and the
PUT-style ``apply_settings_update`` semantics for sensitive fields.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.extensions.api import diagnosis_settings_store as store


def _db(tmp_path: Path) -> Path:
    return tmp_path / "diagnosis_settings.db"


def test_resolve_falls_back_to_default_then_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    # No override, no env -> hard-coded default.
    monkeypatch.delenv("QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT", False)
    assert (
        store.resolve_int(
            "auto_takeover_limit",
            "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT",
            100,
            min_value=1,
            db_path=db,
        )
        == 100
    )
    # Env set, still no override -> env wins over default.
    monkeypatch.setenv(
        "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT",
        "33",
    )
    assert (
        store.resolve_int(
            "auto_takeover_limit",
            "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT",
            100,
            min_value=1,
            db_path=db,
        )
        == 33
    )


def test_db_override_wins_over_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    monkeypatch.setenv(
        "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED",
        "true",
    )
    store.set_overrides({"auto_takeover_enabled": False}, db_path=db)
    assert (
        store.resolve_bool(
            "auto_takeover_enabled",
            "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED",
            True,
            db_path=db,
        )
        is False
    )


def test_delete_override_restores_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    monkeypatch.setenv(
        "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED",
        "true",
    )
    store.set_overrides({"auto_takeover_enabled": False}, db_path=db)
    store.delete_override("auto_takeover_enabled", db_path=db)
    assert (
        store.resolve_bool(
            "auto_takeover_enabled",
            "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED",
            True,
            db_path=db,
        )
        is True
    )


def test_resolve_int_clamps_override_to_min(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_overrides({"max_active_analyses": 0}, db_path=db)
    assert (
        store.resolve_int(
            "max_active_analyses",
            "QWENPAW_PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES",
            1,
            min_value=1,
            db_path=db,
        )
        == 1
    )


def test_build_payload_masks_token(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_overrides({"inoe_api_token": "super-secret-9876"}, db_path=db)
    payload = store.build_settings_payload(db_path=db)
    token = payload["effective"]["inoe_api_token"]
    assert token == {"is_set": True, "masked": "****9876"}
    # Raw secret must never appear anywhere in the payload.
    assert "super-secret-9876" not in str(payload)
    assert payload["overrides"]["inoe_api_token"] is True


def test_apply_update_empty_token_keeps_secret(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_overrides({"inoe_api_token": "keep-me-1234"}, db_path=db)
    # Empty string = no change.
    store.apply_settings_update({"inoe_api_token": ""}, db_path=db)
    assert (
        store.resolve_str(
            "inoe_api_token",
            "INOE_API_TOKEN",
            "",
            db_path=db,
        )
        == "keep-me-1234"
    )
    # Sentinel clears it.
    store.apply_settings_update(
        {"inoe_api_token": store.CLEAR_SENTINEL},
        db_path=db,
    )
    assert store.has_override("inoe_api_token", db_path=db) is False


def test_apply_update_rejects_unknown_key(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        store.apply_settings_update({"nope": 1}, db_path=db)


def test_apply_update_validates_numeric_bounds(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        store.apply_settings_update(
            {"auto_takeover_interval_seconds": 5},
            db_path=db,
        )


def test_apply_update_coerces_and_stores_number(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.apply_settings_update(
        {"auto_takeover_interval_seconds": "120"},
        db_path=db,
    )
    assert (
        store.get_overrides(db_path=db)["auto_takeover_interval_seconds"]
        == 120
    )
