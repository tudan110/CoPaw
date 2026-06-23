# -*- coding: utf-8 -*-
"""Unit tests for INOE materialisation in ``working_secrets``.

These cover the bridge that pushes the resolved INOE gateway connection
from :mod:`inoe_settings_store` (the DB-backed, settings-page source of
truth) into ``os.environ``, which skill subprocesses inherit. The point is
that the image no longer ships a per-skill ``.env`` with a baked-in gateway
address: the value is resolved at runtime and chosen per-environment via
the settings page.

Precedence under test:

* a settings-page override is forced into ``os.environ`` (even over env);
* with no override, an existing env value is preserved (``setdefault``);
* an empty resolved value never clobbers a live credential;
* ``force=True`` rewrites unconditionally (the post-save refresh path).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.extensions.api import inoe_settings_store as store
from qwenpaw.extensions.integrations import working_secrets


def _db(tmp_path: Path) -> Path:
    return tmp_path / "inoe_settings.db"


def _track_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make monkeypatch own the INOE keys so teardown cleans materialised
    writes too (we delenv to seed an absent baseline it can restore)."""
    for name in (
        "INOE_API_BASE_URL",
        "INOE_API_TOKEN",
        "INOE_API_TIMEOUT",
        "INOE_ENABLE_CURL_FALLBACK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_override_forced_over_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_env(monkeypatch)
    # An env value exists (e.g. docker -e / static secrets file)...
    monkeypatch.setenv("INOE_API_BASE_URL", "http://env-host:8080")
    # ...but the settings page set an override.
    store.apply_settings_update(
        {"inoe_api_base_url": "http://page-host:9090"},
        db_path=db,
    )

    working_secrets.materialize_inoe_to_environ(db_path=db)

    # DB override wins, even though the env var was already set.
    assert os.environ["INOE_API_BASE_URL"] == "http://page-host:9090"


def test_no_override_preserves_existing_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_env(monkeypatch)
    # No override; an env value (secrets file / docker -e) is present.
    monkeypatch.setenv("INOE_API_BASE_URL", "http://env-host:8080")

    working_secrets.materialize_inoe_to_environ(db_path=db)

    # setdefault must not clobber the real export.
    assert os.environ["INOE_API_BASE_URL"] == "http://env-host:8080"


def test_no_override_no_env_falls_back_to_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_env(monkeypatch)

    working_secrets.materialize_inoe_to_environ(db_path=db)

    # Nothing set anywhere -> the store default is materialised so a skill
    # still has a usable (if generic) value.
    assert os.environ["INOE_API_BASE_URL"] == store.DEFAULT_INOE_API_BASE_URL


def test_empty_token_never_clobbers_live_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_env(monkeypatch)
    # A live token is already present (from the static secrets file).
    monkeypatch.setenv("INOE_API_TOKEN", "live-secret")
    # No override and no env token in the store's eyes other than this one;
    # force=True must still not overwrite it with a blank.
    working_secrets.materialize_inoe_to_environ(force=True, db_path=db)

    assert os.environ["INOE_API_TOKEN"] == "live-secret"


def test_force_refresh_applies_new_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_env(monkeypatch)
    monkeypatch.setenv("INOE_API_TOKEN", "old-token")

    # Simulate a settings-page save, then the refresh hook.
    store.apply_settings_update({"inoe_api_token": "new-token"}, db_path=db)
    working_secrets.refresh_inoe_environ(db_path=db)

    assert os.environ["INOE_API_TOKEN"] == "new-token"


def test_bool_default_materialises_lowercase_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_env(monkeypatch)
    # No override, no env -> default is on.
    assert store.get_enable_curl_fallback(db_path=db) is True

    working_secrets.materialize_inoe_to_environ(db_path=db)

    # Skills read it via os.getenv(...).lower() in {"1","true",...}.
    assert os.environ["INOE_ENABLE_CURL_FALLBACK"] == "true"


def test_bool_override_off_materialises_lowercase_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_env(monkeypatch)
    # Turn the fallback off from the settings page.
    store.apply_settings_update(
        {"inoe_enable_curl_fallback": False}, db_path=db)
    working_secrets.refresh_inoe_environ(db_path=db)

    got = os.environ["INOE_ENABLE_CURL_FALLBACK"]
    assert got == "false"
    # And a skill's own parse of it lands on False.
    parsed = got.strip().lower() in {"1", "true", "yes", "on"}
    assert parsed is False


# --- alarm-analyst metric settings (diagnosis namespace -> os.environ) ---


def _track_alarm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ALARM_ANALYST_METRIC_TIMEOUT_SECONDS",
        "ALARM_ANALYST_METRIC_PAGE_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_alarm_analyst_default_materialises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    _track_alarm_env(monkeypatch)
    # No override, no env -> code defaults reach os.environ for the skill.
    working_secrets.materialize_alarm_analyst_to_environ(db_path=db)
    assert os.environ["ALARM_ANALYST_METRIC_TIMEOUT_SECONDS"] == "120"
    assert os.environ["ALARM_ANALYST_METRIC_PAGE_SIZE"] == "20"


def test_alarm_analyst_override_materialises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import diagnosis_settings_store as diag

    db = _db(tmp_path)
    _track_alarm_env(monkeypatch)
    diag.apply_settings_update(
        {
            "alarm_analyst_metric_timeout_seconds": 200,
            "alarm_analyst_metric_page_size": 50,
        },
        db_path=db,
    )
    working_secrets.refresh_alarm_analyst_environ(db_path=db)
    assert os.environ["ALARM_ANALYST_METRIC_TIMEOUT_SECONDS"] == "200"
    assert os.environ["ALARM_ANALYST_METRIC_PAGE_SIZE"] == "50"


def test_inspection_metric_materialises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import diagnosis_settings_store as diag

    db = _db(tmp_path)
    for name in (
        "INSPECTION_METRIC_TIMEOUT_SECONDS",
        "INSPECTION_METRIC_PAGE_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)
    # No override -> code defaults (120 / 100) reach the skill.
    working_secrets.materialize_alarm_analyst_to_environ(db_path=db)
    assert os.environ["INSPECTION_METRIC_TIMEOUT_SECONDS"] == "120"
    assert os.environ["INSPECTION_METRIC_PAGE_SIZE"] == "100"
    # Override wins after a settings-page save.
    diag.apply_settings_update(
        {"inspection_metric_page_size": 20}, db_path=db)
    working_secrets.refresh_alarm_analyst_environ(db_path=db)
    assert os.environ["INSPECTION_METRIC_PAGE_SIZE"] == "20"
