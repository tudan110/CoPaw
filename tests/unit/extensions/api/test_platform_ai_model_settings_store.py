# -*- coding: utf-8 -*-
"""Tests for the model selection shared by standalone platform AI APIs."""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.config.config import ModelSlotConfig


class _Provider:
    def __init__(self, models: set[str]) -> None:
        self._models = models

    def has_model(self, model_id: str) -> bool:
        return model_id in self._models


class _Manager:
    def __init__(self) -> None:
        self.provider = _Provider({"glm-5.1", "deepseek-v3"})

    def get_provider(self, provider_id: str):
        return self.provider if provider_id == "ctyun" else None


def test_selection_is_persisted_as_a_model_reference_only(tmp_path: Path) -> None:
    from qwenpaw.extensions.api import platform_ai_model_settings_store as store

    db_path = tmp_path / "settings.db"
    store.apply_settings_update(
        {"providerId": "ctyun", "modelId": "glm-5.1"},
        manager=_Manager(),
        db_path=db_path,
    )

    assert store.get_model_slot(db_path=db_path) == ModelSlotConfig(
        provider_id="ctyun",
        model="glm-5.1",
    )
    assert store.build_settings_payload(db_path=db_path) == {
        "providerId": "ctyun",
        "modelId": "glm-5.1",
        "usesGlobalDefault": False,
    }


def test_empty_selection_reverts_to_global_default(tmp_path: Path) -> None:
    from qwenpaw.extensions.api import platform_ai_model_settings_store as store

    db_path = tmp_path / "settings.db"
    store.apply_settings_update(
        {"providerId": "ctyun", "modelId": "glm-5.1"},
        manager=_Manager(),
        db_path=db_path,
    )
    store.apply_settings_update(
        {"providerId": "", "modelId": ""},
        manager=_Manager(),
        db_path=db_path,
    )

    assert store.get_model_slot(db_path=db_path) is None
    assert store.build_settings_payload(db_path=db_path)["usesGlobalDefault"] is True


def test_selection_rejects_unknown_or_half_configured_models(tmp_path: Path) -> None:
    from qwenpaw.extensions.api import platform_ai_model_settings_store as store

    db_path = tmp_path / "settings.db"
    with pytest.raises(ValueError, match="必须同时选择"):
        store.apply_settings_update(
            {"providerId": "ctyun", "modelId": ""},
            manager=_Manager(),
            db_path=db_path,
        )
    with pytest.raises(ValueError, match="不存在"):
        store.apply_settings_update(
            {"providerId": "ctyun", "modelId": "missing"},
            manager=_Manager(),
            db_path=db_path,
        )
