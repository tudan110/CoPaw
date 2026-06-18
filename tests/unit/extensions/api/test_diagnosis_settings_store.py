# -*- coding: utf-8 -*-
"""Unit tests for the alarm-diagnosis settings override store.

Covers the resolution priority (DB override > env > default), the
override write/delete lifecycle, the masked-token payload, and the
PUT-style ``apply_settings_update`` semantics for sensitive fields.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


# NOTE: INOE gateway fields (base URL / token / timeout) moved out of the
# diagnosis namespace into their own store — see test_inoe_settings_store.py.


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


def test_analysis_anchor_set_get_clear(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert store.get_analysis_anchor(db_path=db) is None
    now = datetime(2026, 6, 11, 2, 30, tzinfo=timezone.utc)
    store.set_analysis_anchor(now, db_path=db)
    assert store.get_analysis_anchor(db_path=db) == now
    store.clear_analysis_anchor(db_path=db)
    assert store.get_analysis_anchor(db_path=db) is None


def test_sync_analysis_anchor_on_toggle(tmp_path: Path) -> None:
    db = _db(tmp_path)
    now = datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc)
    # off -> on: anchor recorded.
    store.sync_analysis_anchor_on_toggle(False, True, now=now, db_path=db)
    assert store.get_analysis_anchor(db_path=db) == now
    # unchanged: anchor preserved.
    store.sync_analysis_anchor_on_toggle(
        True,
        True,
        now=now + timedelta(hours=1),
        db_path=db,
    )
    assert store.get_analysis_anchor(db_path=db) == now
    # on -> off: anchor cleared.
    store.sync_analysis_anchor_on_toggle(True, False, db_path=db)
    assert store.get_analysis_anchor(db_path=db) is None


def test_analysis_lookback_hours_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    monkeypatch.delenv("QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS", False)
    assert (
        store.resolve_float(
            "analysis_lookback_hours",
            "QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS",
            0,
            min_value=0,
            max_value=720,
            db_path=db,
        )
        == 0
    )
    # Env layer (the revived legacy variable) applies without override.
    monkeypatch.setenv("QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS", "2")
    assert (
        store.resolve_float(
            "analysis_lookback_hours",
            "QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS",
            0,
            min_value=0,
            max_value=720,
            db_path=db,
        )
        == 2
    )
    # Page override wins over env.
    store.apply_settings_update({"analysis_lookback_hours": 1}, db_path=db)
    assert (
        store.resolve_float(
            "analysis_lookback_hours",
            "QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS",
            0,
            min_value=0,
            max_value=720,
            db_path=db,
        )
        == 1
    )
    # Negative values rejected by validation.
    with pytest.raises(ValueError):
        store.apply_settings_update(
            {"analysis_lookback_hours": -1},
            db_path=db,
        )


def test_alarm_list_limit_resolution_and_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    monkeypatch.delenv("QWENPAW_PORTAL_REAL_ALARM_LIST_LIMIT", False)
    assert (
        store.resolve_int(
            "alarm_list_limit",
            "QWENPAW_PORTAL_REAL_ALARM_LIST_LIMIT",
            20,
            min_value=1,
            max_value=200,
            db_path=db,
        )
        == 20
    )
    store.apply_settings_update({"alarm_list_limit": 50}, db_path=db)
    assert (
        store.resolve_int(
            "alarm_list_limit",
            "QWENPAW_PORTAL_REAL_ALARM_LIST_LIMIT",
            20,
            min_value=1,
            max_value=200,
            db_path=db,
        )
        == 50
    )
    with pytest.raises(ValueError):
        store.apply_settings_update({"alarm_list_limit": 0}, db_path=db)
    with pytest.raises(ValueError):
        store.apply_settings_update({"alarm_list_limit": 500}, db_path=db)


def test_alarm_query_window_hours_resolution_and_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    monkeypatch.delenv(
        "QWENPAW_PORTAL_REAL_ALARM_QUERY_WINDOW_HOURS", False
    )
    assert (
        store.resolve_float(
            "alarm_query_window_hours",
            "QWENPAW_PORTAL_REAL_ALARM_QUERY_WINDOW_HOURS",
            24,
            min_value=1,
            max_value=8760,
            db_path=db,
        )
        == 24
    )
    store.apply_settings_update(
        {"alarm_query_window_hours": 72}, db_path=db
    )
    assert (
        store.resolve_float(
            "alarm_query_window_hours",
            "QWENPAW_PORTAL_REAL_ALARM_QUERY_WINDOW_HOURS",
            24,
            min_value=1,
            max_value=8760,
            db_path=db,
        )
        == 72
    )
    with pytest.raises(ValueError):
        store.apply_settings_update(
            {"alarm_query_window_hours": 0}, db_path=db
        )


def test_anchor_not_exposed_as_override_nor_settable(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_analysis_anchor(
        datetime(2026, 6, 11, 4, 0, tzinfo=timezone.utc),
        db_path=db,
    )
    payload = store.build_settings_payload(db_path=db)
    assert "analysis_started_at" not in payload["overrides"]
    assert payload["state"]["analysis_started_at"].startswith("2026-06-11")
    with pytest.raises(ValueError):
        store.apply_settings_update(
            {"analysis_started_at": "2026-01-01T00:00:00+00:00"},
            db_path=db,
        )
