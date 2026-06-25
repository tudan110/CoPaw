# -*- coding: utf-8 -*-
"""Unit tests for zgops-cmdb settings: ZGOPS connection store + the
resource-import LLM pool (dynamic) + their materialisation into os.environ.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.extensions.api import zgops_settings_store as zg
from qwenpaw.extensions.api import resource_import_llm_settings_api as llm
from qwenpaw.extensions.integrations import working_secrets as ws


def _db(tmp_path: Path) -> Path:
    return tmp_path / "settings.db"


def _clear(monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


# --- ZGOPS connection store ---------------------------------------------


def test_zgops_default_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, ("ZGOPS_BASE_URL",))
    # No override, no env -> cluster-internal code default.
    assert zg.resolve_text("ZGOPS_BASE_URL", db_path=db) == (
        "http://cnos-iomp-inoe-ui-cmdb:80"
    )
    monkeypatch.setenv("ZGOPS_BASE_URL", "http://env:1")
    assert zg.resolve_text("ZGOPS_BASE_URL", db_path=db) == "http://env:1"
    zg.apply_settings_update({"zgops_base_url": "http://page:2"}, db_path=db)
    assert zg.resolve_text("ZGOPS_BASE_URL", db_path=db) == "http://page:2"


def test_zgops_password_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    zg.apply_settings_update(
        {"zgops_password": "Cnos@2026", "zgops_username": "admin"},
        db_path=db,
    )
    pl = zg.build_settings_payload(db_path=db)
    assert pl["effective"]["zgops_password"]["is_set"] is True
    assert pl["effective"]["zgops_password"]["masked"].endswith("2026")
    assert pl["effective"]["zgops_username"] == "admin"


def test_zgops_materialise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear(monkeypatch, ("ZGOPS_BASE_URL", "ZGOPS_PASSWORD"))
    zg.apply_settings_update(
        {"zgops_base_url": "http://zg:31089", "zgops_password": "p"},
        db_path=db,
    )
    ws.materialize_zgops_to_environ(force=True, db_path=db)
    assert os.environ["ZGOPS_BASE_URL"] == "http://zg:31089"
    assert os.environ["ZGOPS_PASSWORD"] == "p"


# --- resource-import LLM pool -------------------------------------------


def test_llm_pool_store_and_mask(tmp_path: Path) -> None:
    db = _db(tmp_path)
    llm.apply_settings_update(
        {
            "scalars": {"sheet_parallelism": 2, "step_timeout": 90},
            "models": [
                {
                    "base_url": "https://a/v1",
                    "api_key": "KEYaaaa",
                    "model": "m1",
                },
            ],
        },
        db_path=db,
    )
    pl = llm.build_settings_payload(db_path=db)
    assert pl["scalars"] == {"sheet_parallelism": 2, "step_timeout": 90}
    assert pl["models"][0]["base_url"] == "https://a/v1"
    assert pl["models"][0]["api_key"]["is_set"] is True
    assert pl["models"][0]["api_key"]["masked"].endswith("aaaa")


def test_llm_pool_blank_key_keeps_existing(tmp_path: Path) -> None:
    db = _db(tmp_path)
    llm.apply_settings_update(
        {"models": [{"base_url": "https://a", "api_key": "K1", "model": "m"}]},
        db_path=db,
    )
    # Re-save the same row with blank api_key -> keep stored key.
    llm.apply_settings_update(
        {"models": [{"base_url": "https://a", "api_key": "", "model": "m"}]},
        db_path=db,
    )
    assert llm.get_resolved_models(db_path=db)[0]["api_key"] == "K1"


def test_llm_pool_materialise_expand_and_shrink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear(
        monkeypatch,
        (
            "RESOURCE_IMPORT_LLM_BASE_URL",
            "RESOURCE_IMPORT_LLM_2_BASE_URL",
            "RESOURCE_IMPORT_LLM_SHEET_PARALLELISM",
        ),
    )
    llm.apply_settings_update(
        {
            "scalars": {"sheet_parallelism": 3, "step_timeout": 60},
            "models": [
                {"base_url": "https://a/v1", "api_key": "k1", "model": "m1"},
                {"base_url": "https://b/v1", "api_key": "k2", "model": "m2"},
            ],
        },
        db_path=db,
    )
    ws.materialize_resource_import_llm_to_environ(force=True, db_path=db)
    assert os.environ["RESOURCE_IMPORT_LLM_BASE_URL"] == "https://a/v1"
    assert os.environ["RESOURCE_IMPORT_LLM_2_BASE_URL"] == "https://b/v1"
    assert os.environ["RESOURCE_IMPORT_LLM_SHEET_PARALLELISM"] == "3"

    # Shrink to one model -> _2_* must be cleared.
    llm.apply_settings_update(
        {"models": [{"base_url": "https://a", "api_key": "", "model": "m"}]},
        db_path=db,
    )
    ws.materialize_resource_import_llm_to_environ(force=True, db_path=db)
    assert os.environ.get("RESOURCE_IMPORT_LLM_2_BASE_URL") is None
    assert os.environ["RESOURCE_IMPORT_LLM_BASE_URL"] == "https://a"
