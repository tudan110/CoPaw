# -*- coding: utf-8 -*-
"""Shared fixtures for extension tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_big_screen_ttl_cache():
    """The cross-request capability TTL cache is process-global; clear
    it around every test so mocked integrations never leak cached
    results into each other."""
    from qwenpaw.extensions.ai_big_screen.capabilities import TTL_CACHE

    TTL_CACHE.clear()
    yield
    TTL_CACHE.clear()
