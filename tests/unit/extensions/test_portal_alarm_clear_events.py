# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from qwenpaw.extensions import portal_alarm_clear_events as store


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "alarm-clear-events.db"


def test_record_clear_notification_creates_pending_event(
    tmp_path: Path,
) -> None:
    event = store.record_clear_notification(
        alarm_id="alarm-1",
        res_id="3094",
        clear_time="2026-06-10 12:00:00",
        clear_type="auto",
        raw_payload='{"alarmId": "alarm-1"}',
        path=_db_path(tmp_path),
    )

    assert event["alarmId"] == "alarm-1"
    assert event["resId"] == "3094"
    assert event["verifyStatus"] == "pending"
    assert event["verifyAttempts"] == 0
    assert event["nextVerifyAt"]
    assert event["deduped"] is False


def test_record_clear_notification_ignored_status_not_due(
    tmp_path: Path,
) -> None:
    """An ignored event keeps an empty schedule and is never returned by
    fetch_due_clear_events, so the verification loop skips it."""
    db_path = _db_path(tmp_path)
    event = store.record_clear_notification(
        alarm_id="alarm-untracked",
        initial_status="ignored",
        path=db_path,
    )

    assert event["verifyStatus"] == "ignored"
    assert event["nextVerifyAt"] == ""
    assert event["deduped"] is False
    assert store.fetch_due_clear_events(limit=10, path=db_path) == []
    # Still visible for audit.
    assert len(store.list_clear_events(path=db_path)) == 1


def test_record_clear_notification_requires_alarm_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        store.record_clear_notification(
            alarm_id="   ",
            path=_db_path(tmp_path),
        )


def test_record_clear_notification_dedupes_active_event(
    tmp_path: Path,
) -> None:
    db_path = _db_path(tmp_path)
    first = store.record_clear_notification(
        alarm_id="alarm-1",
        clear_time="2026-06-10 12:00:00",
        path=db_path,
    )
    second = store.record_clear_notification(
        alarm_id="alarm-1",
        res_id="3094",
        clear_time="2026-06-10 12:05:00",
        path=db_path,
    )

    assert second["deduped"] is True
    assert second["id"] == first["id"]
    # Refreshed fields win; the original scheduling stays untouched.
    assert second["resId"] == "3094"
    assert second["clearTime"] == "2026-06-10 12:05:00"
    assert second["nextVerifyAt"] == first["nextVerifyAt"]
    assert len(store.list_clear_events(path=db_path)) == 1


def test_record_clear_notification_creates_new_event_after_terminal(
    tmp_path: Path,
) -> None:
    db_path = _db_path(tmp_path)
    first = store.record_clear_notification(
        alarm_id="alarm-1",
        path=db_path,
    )
    store.update_clear_event(
        first["id"],
        verify_status="recovered",
        path=db_path,
    )

    second = store.record_clear_notification(
        alarm_id="alarm-1",
        path=db_path,
    )

    assert second["deduped"] is False
    assert second["id"] != first["id"]


def test_fetch_due_clear_events_returns_only_due_events(
    tmp_path: Path,
) -> None:
    db_path = _db_path(tmp_path)
    now = store.local_now()
    due = store.record_clear_notification(
        alarm_id="alarm-due",
        next_verify_at=(now - timedelta(seconds=5)).isoformat(),
        path=db_path,
    )
    store.record_clear_notification(
        alarm_id="alarm-future",
        next_verify_at=(now + timedelta(hours=1)).isoformat(),
        path=db_path,
    )
    observing = store.record_clear_notification(
        alarm_id="alarm-observing",
        next_verify_at=(now - timedelta(seconds=5)).isoformat(),
        path=db_path,
    )
    store.update_clear_event(
        observing["id"],
        verify_status="observing",
        path=db_path,
    )
    terminal = store.record_clear_notification(
        alarm_id="alarm-done",
        next_verify_at=(now - timedelta(seconds=5)).isoformat(),
        path=db_path,
    )
    store.update_clear_event(
        terminal["id"],
        verify_status="recovered",
        path=db_path,
    )

    due_events = store.fetch_due_clear_events(limit=10, path=db_path)

    due_ids = {event["id"] for event in due_events}
    assert due["id"] in due_ids
    assert observing["id"] in due_ids
    assert len(due_events) == 2


def test_update_clear_event_rejects_unknown_column(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    event = store.record_clear_notification(alarm_id="alarm-1", path=db_path)

    with pytest.raises(ValueError):
        store.update_clear_event(
            event["id"],
            alarm_id="not-allowed",
            path=db_path,
        )


def test_reset_zombie_verifying_events(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    event = store.record_clear_notification(alarm_id="alarm-1", path=db_path)
    store.update_clear_event(
        event["id"],
        verify_status="verifying",
        next_verify_at="",
        path=db_path,
    )

    count = store.reset_zombie_verifying_events(path=db_path)

    assert count == 1
    refreshed = store.get_clear_event(event["id"], path=db_path)
    assert refreshed is not None
    assert refreshed["verifyStatus"] == "pending"
    assert refreshed["nextVerifyAt"]
