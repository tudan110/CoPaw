# -*- coding: utf-8 -*-
"""Unit tests for the N9E log settings store + materialisation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.extensions.api import n9e_settings_store as n9e
from qwenpaw.extensions.integrations import working_secrets as ws

_ENVS = (
    "N9E_API_BASE_URL",
    "N9E_USER_TOKEN",
    "N9E_LOG_DATASOURCE_ID",
    "N9E_LOG_INDEX",
    "N9E_LOG_TIMESTAMP_FIELD",
)


def _db(tmp_path: Path) -> Path:
    return tmp_path / "settings.db"


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)


def test_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch)
    assert n9e.resolve_text("N9E_LOG_TIMESTAMP_FIELD", db_path=db) == (
        "@timestamp"
    )
    assert n9e.resolve_text("N9E_LOG_DATASOURCE_ID", db_path=db) == "1"
    assert n9e.resolve_text("N9E_API_BASE_URL", db_path=db) == ""


def test_override_and_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch)
    n9e.apply_settings_update(
        {
            "n9e_api_base_url": "http://n9e:17001",
            "n9e_user_token": "secret_wxyz",
            "n9e_log_index": "casaos-syslog-*",
        },
        db_path=db,
    )
    pl = n9e.build_settings_payload(db_path=db)
    assert pl["effective"]["n9e_api_base_url"] == "http://n9e:17001"
    assert pl["effective"]["n9e_user_token"]["masked"].endswith("wxyz")
    assert pl["effective"]["n9e_log_index"] == "casaos-syslog-*"


def test_materialise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch)
    n9e.apply_settings_update(
        {"n9e_api_base_url": "http://n9e:17001"}, db_path=db
    )
    ws.materialize_n9e_to_environ(force=True, db_path=db)
    assert os.environ["N9E_API_BASE_URL"] == "http://n9e:17001"
    # default fields materialise too
    assert os.environ["N9E_LOG_TIMESTAMP_FIELD"] == "@timestamp"


def test_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch)
    n9e.apply_settings_update(
        {"n9e_api_base_url": "http://n9e:17001"}, db_path=db
    )
    assert n9e.has_override("n9e_api_base_url", db_path=db) is True
    n9e.reset_setting("n9e_api_base_url", db_path=db)
    assert n9e.has_override("n9e_api_base_url", db_path=db) is False
