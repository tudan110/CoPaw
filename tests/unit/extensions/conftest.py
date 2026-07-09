# -*- coding: utf-8 -*-
"""Shared fixtures for extension tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings_db(tmp_path, monkeypatch):
    """Redirect the shared settings DB to a per-test temp file.

    Config resolution is settings-page DB > env > default, so on a
    developer machine the real ``~/.qwenpaw/extensions/settings/
    settings.db`` would silently shadow whatever env vars a test
    monkeypatches. Every namespaced read/write funnels through
    ``settings_store._open_db``, so redirecting connections aimed at
    the real DB path (module defaults are baked in at import time)
    is enough to isolate all stores at once.
    """
    from qwenpaw.extensions.api import settings_store

    real_open = settings_store._open_db
    real_db = str(settings_store.DEFAULT_DB_PATH)
    tmp_db = tmp_path / "settings.db"

    def _redirected_open(db_path):
        if str(db_path) == real_db:
            db_path = tmp_db
        return real_open(db_path)

    settings_store._CACHE.clear()
    monkeypatch.setattr(settings_store, "_open_db", _redirected_open)
    yield
    settings_store._CACHE.clear()


@pytest.fixture(autouse=True)
def _clear_big_screen_ttl_cache():
    """The cross-request capability TTL cache is process-global; clear
    it around every test so mocked integrations never leak cached
    results into each other."""
    from qwenpaw.extensions.ai_big_screen.capabilities import TTL_CACHE

    TTL_CACHE.clear()
    yield
    TTL_CACHE.clear()
