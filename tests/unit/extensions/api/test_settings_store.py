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
