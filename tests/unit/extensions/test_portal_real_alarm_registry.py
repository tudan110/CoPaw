# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

from qwenpaw.extensions import portal_real_alarm_registry


def _registry_path(tmp_path: Path) -> Path:
    return tmp_path / "portal-real-alarm-registry.db"


def test_filter_visible_alarms_hides_handled_alarm_entries(tmp_path: Path) -> None:
    registry_path = _registry_path(tmp_path)
    portal_real_alarm_registry.update_alarm_record(
        alarm={
            "alarmId": "alarm-1",
            "resId": "3094",
            "title": "数据库锁异常",
        },
        status="manual_pending",
        path=registry_path,
    )

    payload = portal_real_alarm_registry.filter_visible_alarms(
        {
            "total": 2,
            "items": [
                {"alarmId": "alarm-1", "title": "数据库锁异常"},
                {"alarmId": "alarm-2", "title": "链路抖动"},
            ],
            "source": "live",
        },
        path=registry_path,
    )

    assert payload["total"] == 1
    assert payload["items"] == [{"alarmId": "alarm-2", "title": "链路抖动"}]


def test_update_alarm_record_can_resolve_existing_entry_by_chat_id(tmp_path: Path) -> None:
    registry_path = _registry_path(tmp_path)
    created = portal_real_alarm_registry.update_alarm_record(
        alarm={
            "alarmId": "alarm-1",
            "resId": "3094",
            "title": "数据库锁异常",
        },
        status="analyzing",
        session_id="portal-fault-alarm-alarm-1",
        chat_id="chat-1",
        source="auto-poll",
        path=registry_path,
    )

    updated = portal_real_alarm_registry.update_alarm_record(
        chat_id="chat-1",
        res_id="3094",
        status="manual_recovered",
        verification_status="recovered",
        source="manual-close",
        path=registry_path,
    )

    records = portal_real_alarm_registry.load_alarm_records(path=registry_path)

    assert created["alarmId"] == "alarm-1"
    assert updated["alarmId"] == "alarm-1"
    assert updated["status"] == "manual_recovered"
    assert updated["verificationStatus"] == "recovered"
    assert records["alarm-1"]["chatId"] == "chat-1"


def test_registry_timestamps_fall_back_to_east_eight_timezone(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_path = _registry_path(tmp_path)

    monkeypatch.setattr(
        portal_real_alarm_registry,
        "_default_registry_timezone",
        lambda: timezone(timedelta(hours=8)),
    )

    record = portal_real_alarm_registry.update_alarm_record(
        alarm={
            "alarmId": "alarm-1",
            "resId": "3094",
            "title": "数据库锁异常",
        },
        status="analyzing",
        path=registry_path,
    )

    assert record["createdAt"].endswith("+08:00")
    assert record["updatedAt"].endswith("+08:00")


def test_json_migration_imports_legacy_file_into_sqlite(tmp_path: Path) -> None:
    """When a JSON file exists alongside the DB path, records are migrated."""
    json_path = tmp_path / "portal-real-alarm-registry.json"
    db_path = tmp_path / "portal-real-alarm-registry.db"

    json_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-05-12T10:00:00+08:00",
                "alarms": {
                    "alarm-1": {
                        "alarmId": "alarm-1",
                        "status": "analyzing",
                        "sessionId": "sess-1",
                        "resId": "3094",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Clear migration cache so it triggers
    portal_real_alarm_registry._MIGRATED_DBS.discard(str(db_path.resolve()))

    records = portal_real_alarm_registry.load_alarm_records(path=db_path)

    assert "alarm-1" in records
    assert records["alarm-1"]["alarmId"] == "alarm-1"
    assert records["alarm-1"]["status"] == "analyzing"
    assert records["alarm-1"]["sessionId"] == "sess-1"
    # JSON file should be renamed to .bak
    assert not json_path.exists()
    assert json_path.with_suffix(".json.bak").exists()


def test_json_path_argument_is_transparently_converted_to_db(tmp_path: Path) -> None:
    """Passing a .json path resolves to a sibling .db file."""
    json_path = tmp_path / "test-registry.json"

    portal_real_alarm_registry.update_alarm_record(
        alarm={"alarmId": "alarm-x", "title": "test"},
        status="new",
        path=json_path,  # .json path passed
    )

    db_path = tmp_path / "test-registry.db"
    assert db_path.exists()
    assert not json_path.exists()

    records = portal_real_alarm_registry.load_alarm_records(path=json_path)
    assert "alarm-x" in records


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Running migration twice doesn't duplicate records."""
    json_path = tmp_path / "registry.json"
    db_path = tmp_path / "registry.db"

    json_path.write_text(
        json.dumps({
            "version": 1,
            "updatedAt": "",
            "alarms": {
                "a1": {"alarmId": "a1", "status": "new"},
            },
        }),
        encoding="utf-8",
    )

    portal_real_alarm_registry._MIGRATED_DBS.discard(str(db_path.resolve()))
    portal_real_alarm_registry.load_alarm_records(path=db_path)

    # Write another JSON (simulate leftover) and force re-migration
    bak_path = json_path.with_suffix(".json.bak")
    if bak_path.exists():
        bak_path.rename(json_path)
    portal_real_alarm_registry._MIGRATED_DBS.discard(str(db_path.resolve()))
    records = portal_real_alarm_registry.load_alarm_records(path=db_path)

    assert len(records) == 1
    assert records["a1"]["alarmId"] == "a1"
