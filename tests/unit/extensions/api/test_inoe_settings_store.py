# -*- coding: utf-8 -*-
"""Unit tests for the standalone INOE gateway settings store.

Covers the resolution priority (inoe override > legacy diagnosis override >
env > default), the one-time legacy migration, the masked-token payload,
``apply_settings_update`` semantics, reset, and the shared HTTP helpers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.extensions.api import inoe_settings_store as store
from qwenpaw.extensions.api import settings_store


def _db(tmp_path: Path) -> Path:
    return tmp_path / "inoe_settings.db"


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INOE_API_BASE_URL", False)
    monkeypatch.delenv("INOE_API_TOKEN", False)
    monkeypatch.delenv("INOE_API_TIMEOUT", False)


def test_defaults_then_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    # No override, no env -> hard-coded defaults.
    assert store.get_base_url(db_path=db) == "http://gateway:30080"
    assert store.get_timeout_seconds(db_path=db) == 30.0
    assert store.get_token(db_path=db) == ""
    # Env set, still no override -> env wins over default (and is normalized).
    monkeypatch.setenv("INOE_API_BASE_URL", "http://env-host:8080/")
    monkeypatch.setenv("INOE_API_TIMEOUT", "12")
    monkeypatch.setenv("INOE_API_TOKEN", "env-token")
    assert store.get_base_url(db_path=db) == "http://env-host:8080"
    assert store.get_timeout_seconds(db_path=db) == 12.0
    assert store.get_token(db_path=db) == "env-token"


def test_inoe_override_wins_over_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("INOE_API_BASE_URL", "http://env-host:8080")
    store.apply_settings_update(
        {"inoe_api_base_url": "http://page-host:9090"},
        db_path=db,
    )
    assert store.get_base_url(db_path=db) == "http://page-host:9090"


def test_legacy_diagnosis_override_is_migrated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    # Simulate the old layout: value stored under the diagnosis namespace.
    settings_store.set_values(
        "diagnosis",
        {"inoe_api_base_url": "http://legacy:1234"},
        db_path=db,
    )
    # Resolution still finds it ...
    assert store.get_base_url(db_path=db) == "http://legacy:1234"
    # ... and the one-time migration moved it into the inoe namespace
    # while clearing the legacy copy.
    assert (
        settings_store.get_namespace("inoe", db_path=db).get(
            "inoe_api_base_url"
        )
        == "http://legacy:1234"
    )
    assert "inoe_api_base_url" not in settings_store.get_namespace(
        "diagnosis",
        db_path=db,
    )


def test_build_payload_masks_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    store.apply_settings_update(
        {"inoe_api_token": "super-secret-9876"},
        db_path=db,
    )
    payload = store.build_settings_payload(db_path=db)
    token = payload["effective"]["inoe_api_token"]
    assert token == {"is_set": True, "masked": "****9876"}
    # Raw secret must never appear anywhere in the payload.
    assert "super-secret-9876" not in str(payload)
    assert payload["overrides"]["inoe_api_token"] is True
    assert payload["groups"]["inoe_api_base_url"] == "inoe"


def test_apply_update_empty_token_keeps_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    store.apply_settings_update({"inoe_api_token": "keep-me-1234"}, db_path=db)
    # Empty string = no change.
    store.apply_settings_update({"inoe_api_token": ""}, db_path=db)
    assert store.get_token(db_path=db) == "keep-me-1234"
    # Sentinel clears it.
    store.apply_settings_update(
        {"inoe_api_token": store.CLEAR_SENTINEL},
        db_path=db,
    )
    assert store.has_override("inoe_api_token", db_path=db) is False
    assert store.get_token(db_path=db) == ""


def test_apply_update_rejects_unknown_key(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        store.apply_settings_update({"nope": 1}, db_path=db)


def test_apply_update_validates_timeout_bounds(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        store.apply_settings_update(
            {"inoe_api_timeout_seconds": 0},
            db_path=db,
        )


def test_reset_restores_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("INOE_API_BASE_URL", "http://env-host:8080")
    store.apply_settings_update(
        {"inoe_api_base_url": "http://page:9090"},
        db_path=db,
    )
    store.reset_setting("inoe_api_base_url", db_path=db)
    assert store.get_base_url(db_path=db) == "http://env-host:8080"
    with pytest.raises(ValueError):
        store.reset_setting("nope", db_path=db)


def test_build_headers_and_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("INOE_API_BASE_URL", "http://gw:30080")
    monkeypatch.setenv("INOE_API_TOKEN", "abc")
    headers = store.build_headers(db_path=db)
    assert headers["Authorization"] == "Bearer abc"
    assert headers["Content-Type"].startswith("application/json")
    # An already-prefixed token must not be double-prefixed.
    monkeypatch.setenv("INOE_API_TOKEN", "Bearer xyz")
    assert store.build_headers(db_path=db)["Authorization"] == "Bearer xyz"
    assert (
        store.build_url("/resource/x", {"a": 1}, db_path=db)
        == "http://gw:30080/resource/x?a=1"
    )


def test_no_token_omits_authorization_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    assert "Authorization" not in store.build_headers(db_path=db)
