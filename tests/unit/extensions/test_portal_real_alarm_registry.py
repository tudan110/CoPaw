# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

from qwenpaw.extensions import portal_real_alarm_registry


def _registry_path(tmp_path: Path) -> Path:
    return tmp_path / "portal-real-alarm-registry.json"


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
    payload = json.loads(registry_path.read_text(encoding="utf-8"))

    assert record["createdAt"].endswith("+08:00")
    assert record["updatedAt"].endswith("+08:00")
    assert payload["updatedAt"].endswith("+08:00")


def test_default_registry_path_migrates_legacy_file_into_extension_subdir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "portal_real_alarm_registry.json"
    new_path = tmp_path / "extensions" / "portal_real_alarm" / "portal_real_alarm_registry.json"
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-05-12T10:00:00+08:00",
                "alarms": {
                    "alarm-1": {
                        "alarmId": "alarm-1",
                        "status": "analyzing",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        portal_real_alarm_registry,
        "LEGACY_PORTAL_REAL_ALARM_REGISTRY_PATH",
        legacy_path,
    )
    monkeypatch.setattr(
        portal_real_alarm_registry,
        "PORTAL_REAL_ALARM_REGISTRY_PATH",
        new_path,
    )
    monkeypatch.setattr(
        portal_real_alarm_registry,
        "DEFAULT_PORTAL_REAL_ALARM_REGISTRY_PATH",
        new_path,
    )

    records = portal_real_alarm_registry.load_alarm_records()

    assert records["alarm-1"]["alarmId"] == "alarm-1"
    assert new_path.exists()
    assert not legacy_path.exists()
