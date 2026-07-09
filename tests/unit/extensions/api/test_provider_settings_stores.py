# -*- coding: utf-8 -*-
"""Unit tests for the Qiming/Xingchen model-provider settings stores.

Covers the shared :mod:`provider_settings_base` engine through both thin
stores: resolution priority (DB override > env(QWENPAW_/COPAW_) > default),
the string resolution used by the adapters' ``_read_env``, masked-secret
payloads, ``apply_settings_update`` semantics (empty no-op / CLEAR /
unknown-key), and reset.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.extensions.api import qiming_settings_store as q
from qwenpaw.extensions.api import xingchen_settings_store as x

_QIMING_ENVS = (
    "QWENPAW_QIMING_BASE_URL",
    "COPAW_QIMING_BASE_URL",
    "QWENPAW_QIMING_APP_KEY",
    "COPAW_QIMING_APP_KEY",
    "QWENPAW_QIMING_MODELS",
    "COPAW_QIMING_MODELS",
)
_XINGCHEN_ENVS = (
    "QWENPAW_XINGCHEN_BASE_URL",
    "COPAW_XINGCHEN_BASE_URL",
    "QWENPAW_XINGCHEN_AUTHORIZATION",
    "COPAW_XINGCHEN_AUTHORIZATION",
)


def _db(tmp_path: Path) -> Path:
    return tmp_path / "settings.db"


def _clear(monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_default_then_env_then_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, _QIMING_ENVS)

    # No override, no env -> spec default ("" for base_url, models default).
    assert q.resolve_text("QWENPAW_QIMING_BASE_URL", db_path=db) == ""
    assert (
        q.resolve_text("QWENPAW_QIMING_MODELS", db_path=db)
        == "qiming25_72b_fc"
    )

    # Env set -> env wins over default.
    monkeypatch.setenv("QWENPAW_QIMING_BASE_URL", "http://env:1")
    assert q.resolve_text("QWENPAW_QIMING_BASE_URL", db_path=db) == (
        "http://env:1"
    )

    # Settings-page override wins over env.
    q.apply_settings_update({"qiming_base_url": "http://page:2"}, db_path=db)
    assert q.resolve_text("QWENPAW_QIMING_BASE_URL", db_path=db) == (
        "http://page:2"
    )


def test_copaw_legacy_env_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, _QIMING_ENVS)
    # Only the legacy COPAW_ name is set -> still resolved.
    monkeypatch.setenv("COPAW_QIMING_BASE_URL", "http://legacy:9")
    assert q.resolve_text("QWENPAW_QIMING_BASE_URL", db_path=db) == (
        "http://legacy:9"
    )


def test_sensitive_field_masked_in_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, _QIMING_ENVS)
    q.apply_settings_update(
        {"qiming_app_key": "SECRET_wxyz", "qiming_app_id": "ID7"},
        db_path=db,
    )
    payload = q.build_settings_payload(db_path=db)
    # Sensitive -> masked dict; non-sensitive id -> plain string.
    assert payload["effective"]["qiming_app_key"] == {
        "is_set": True,
        "masked": "****wxyz",
    }
    assert payload["effective"]["qiming_app_id"] == "ID7"
    assert payload["overrides"]["qiming_app_key"] is True


def test_empty_sensitive_is_noop_and_clear_removes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, _QIMING_ENVS)
    q.apply_settings_update({"qiming_app_key": "keep_me"}, db_path=db)

    # Empty string leaves the stored secret untouched.
    q.apply_settings_update({"qiming_app_key": ""}, db_path=db)
    assert q.has_override("qiming_app_key", db_path=db) is True

    # CLEAR sentinel deletes the override.
    q.apply_settings_update({"qiming_app_key": q.CLEAR_SENTINEL}, db_path=db)
    assert q.has_override("qiming_app_key", db_path=db) is False


def test_unknown_key_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        q.apply_settings_update({"not_a_field": "x"}, db_path=db)


def test_reset_drops_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, _QIMING_ENVS)
    q.apply_settings_update({"qiming_base_url": "http://page:2"}, db_path=db)
    assert q.has_override("qiming_base_url", db_path=db) is True
    q.reset_setting("qiming_base_url", db_path=db)
    assert q.has_override("qiming_base_url", db_path=db) is False


def test_xingchen_store_basics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, _XINGCHEN_ENVS)
    # Default path is the adapter's hard-coded one.
    assert x.resolve_text("QWENPAW_XINGCHEN_CHAT_PATH", db_path=db) == (
        "/aipaas/lm/v1/telechat/chat115b"
    )
    # Override + masked authorization.
    x.apply_settings_update(
        {
            "xingchen_base_url": "http://xc:8088",
            "xingchen_authorization": "AUTHvalue",
        },
        db_path=db,
    )
    assert x.resolve_text("QWENPAW_XINGCHEN_BASE_URL", db_path=db) == (
        "http://xc:8088"
    )
    payload = x.build_settings_payload(db_path=db)
    assert payload["effective"]["xingchen_authorization"]["masked"] == (
        "****alue"
    )


def test_unmodelled_env_returns_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A name the store doesn't model -> "" so the adapter's own os.getenv
    # legacy fallback handles it.
    db = _db(tmp_path)
    assert q.resolve_text("QWENPAW_QIMING_TIMEOUT_SECONDS", db_path=db) == ""


_ORDER_ENVS = (
    "ORDER_API_BASE_URL",
    "ORDER_AUTHORIZATION",
    "ORDER_TIMEOUT_SECONDS",
    "ORDER_VERIFY_SSL",
    "ORDER_ENABLE_CURL_FALLBACK",
)


def test_order_store_basics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import order_settings_store as ordr

    db = _db(tmp_path)
    _clear(monkeypatch, _ORDER_ENVS)
    # ferry connection defaults empty so the client falls back to INOE
    assert ordr.resolve_text("ORDER_API_BASE_URL", db_path=db) == ""
    assert ordr.resolve_text("ORDER_AUTHORIZATION", db_path=db) == ""
    # override + masked authorization
    ordr.apply_settings_update(
        {
            "order_api_base_url": "http://ferry:30080/ferry",
            "order_authorization": "Bearer secrettoken",
        },
        db_path=db,
    )
    assert ordr.resolve_text("ORDER_API_BASE_URL", db_path=db) == (
        "http://ferry:30080/ferry"
    )
    payload = ordr.build_settings_payload(db_path=db)
    assert payload["effective"]["order_authorization"]["masked"] == (
        "****oken"
    )
    # unknown key rejected
    with pytest.raises(ValueError):
        ordr.apply_settings_update({"nope": "x"}, db_path=db)


_KUNLUN_ENVS = (
    "QWENPAW_KUNLUN_BASE_URL",
    "COPAW_KUNLUN_BASE_URL",
    "QWENPAW_KUNLUN_APP_CODE",
    "QWENPAW_KUNLUN_APP_SECRET",
    "COPAW_KUNLUN_APP_SECRET",
    "QWENPAW_KUNLUN_MODELS",
    "QWENPAW_KUNLUN_VERIFY_SSL",
)


def test_kunlun_store_basics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import kunlun_settings_store as k

    db = _db(tmp_path)
    _clear(monkeypatch, _KUNLUN_ENVS)
    # Defaults encode the subscription's gateway root + example model.
    assert k.resolve_text("QWENPAW_KUNLUN_BASE_URL", db_path=db) == (
        "https://ogw.klnaas.189.cn:21000"
    )
    assert k.resolve_text("QWENPAW_KUNLUN_MODELS", db_path=db) == "app_001"
    # Bool field resolves through the same text channel the adapter uses.
    assert k.resolve_text("QWENPAW_KUNLUN_VERIFY_SSL", db_path=db) == ("False")
    # override + masked app secret
    k.apply_settings_update(
        {
            "kunlun_base_url": "https://gw.test:21000",
            "kunlun_app_secret": "SECRETvalu",
        },
        db_path=db,
    )
    assert k.resolve_text("QWENPAW_KUNLUN_BASE_URL", db_path=db) == (
        "https://gw.test:21000"
    )
    payload = k.build_settings_payload(db_path=db)
    assert payload["effective"]["kunlun_app_secret"]["masked"] == ("****valu")
    # unknown key rejected
    with pytest.raises(ValueError):
        k.apply_settings_update({"nope": "x"}, db_path=db)
