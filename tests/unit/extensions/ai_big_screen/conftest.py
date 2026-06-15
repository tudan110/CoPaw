# -*- coding: utf-8 -*-
"""Shared isolation for the ai_big_screen test package.

The pipeline records telemetry into the store's SQLite database as a
side effect (M2); without redirection every pipeline/eval test would
write events into the developer's real runtime database. Individual
tests may still monkeypatch these paths again — test-level patches
win over this autouse fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from qwenpaw.extensions.ai_big_screen import store

    monkeypatch.setattr(
        store,
        "DEFAULT_DB_PATH",
        tmp_path / "ai_big_screen" / "ai_big_screen.sqlite3",
    )
    monkeypatch.setattr(
        store,
        "DEFAULT_REGISTRY_PATH",
        tmp_path / "ai_big_screen" / "registry.json",
    )
    monkeypatch.setattr(store, "_DEFAULT_MIGRATION_DONE", True)

    # Hermetic dynamic-capability discovery (M3-B/C): point WORKING_DIR
    # at an empty temp tree so skill discovery finds nothing, and stub
    # the proxy connector list to empty. Tests that exercise these
    # (test_proxy_capabilities / test_skill_capabilities) override with
    # their own monkeypatch, which runs after this autouse fixture.
    from qwenpaw import constant

    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path / "qwenpaw_home")
    from qwenpaw.extensions.api import proxy_datasource_service

    monkeypatch.setattr(
        proxy_datasource_service,
        "list_bigscreen_datasources",
        list,
    )
    monkeypatch.setattr(
        proxy_datasource_service,
        "get_datasource",
        lambda _datasource_id: None,
    )
