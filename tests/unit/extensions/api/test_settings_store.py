# -*- coding: utf-8 -*-
"""Unit tests for the shared namespaced settings store."""
from __future__ import annotations

from pathlib import Path

from qwenpaw.extensions.api import settings_store as store


def _db(tmp_path: Path) -> Path:
    return tmp_path / "settings.db"


def test_set_and_get_namespace(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_values("alpha", {"a": 1, "b": "x"}, db_path=db)
    assert store.get_namespace("alpha", db_path=db) == {"a": 1, "b": "x"}


def test_namespaces_are_isolated(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_values("alpha", {"shared": 1}, db_path=db)
    store.set_values("beta", {"shared": 2}, db_path=db)
    assert store.get_namespace("alpha", db_path=db) == {"shared": 1}
    assert store.get_namespace("beta", db_path=db) == {"shared": 2}


def test_delete_value(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_values("alpha", {"a": 1, "b": 2}, db_path=db)
    store.delete_value("alpha", "a", db_path=db)
    assert store.get_namespace("alpha", db_path=db) == {"b": 2}


def test_replace_namespace_drops_missing_keys(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_values("alpha", {"a": 1, "b": 2}, db_path=db)
    store.replace_namespace("alpha", {"c": 3}, db_path=db)
    assert store.get_namespace("alpha", db_path=db) == {"c": 3}


def test_replace_namespace_empty_clears(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_values("alpha", {"a": 1}, db_path=db)
    store.replace_namespace("alpha", {}, db_path=db)
    assert not store.get_namespace("alpha", db_path=db)


def test_set_values_empty_is_noop(tmp_path: Path) -> None:
    db = _db(tmp_path)
    store.set_values("alpha", {}, db_path=db)
    assert not store.get_namespace("alpha", db_path=db)


def test_object_values_roundtrip(tmp_path: Path) -> None:
    db = _db(tmp_path)
    nested = {"push_url": "http://x", "timeout_seconds": 8}
    store.set_values("notification", {"scope1": nested}, db_path=db)
    assert store.get_namespace("notification", db_path=db)["scope1"] == nested


def test_migration_flag(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert store.is_migrated("flag-x", db_path=db) is False
    store.mark_migrated("flag-x", db_path=db)
    assert store.is_migrated("flag-x", db_path=db) is True


def test_cache_expires_so_cross_process_writes_become_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import json
    import sqlite3

    db = _db(tmp_path)
    store.set_values("alpha", {"a": 1}, db_path=db)
    assert store.get_namespace("alpha", db_path=db) == {"a": 1}

    # Simulate another worker process writing the same DB directly —
    # this never touches our in-process cache.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE settings SET value = ? WHERE namespace = ? AND key = ?",
        (json.dumps(2), "alpha", "a"),
    )
    conn.commit()
    conn.close()

    # Within the TTL the cached snapshot is still served...
    assert store.get_namespace("alpha", db_path=db) == {"a": 1}
    # ...but once it expires the fresh value is read from the DB.
    monkeypatch.setattr(store, "_CACHE_TTL_SECONDS", 0.0)
    assert store.get_namespace("alpha", db_path=db) == {"a": 2}
