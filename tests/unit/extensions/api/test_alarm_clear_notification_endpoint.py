# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from qwenpaw.extensions.api import portal_backend


@pytest.fixture()
def client() -> TestClient:
    return TestClient(portal_backend.app)


@pytest.fixture()
def recorded_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stub out the SQLite store and registry so tests stay hermetic."""
    events: list[dict[str, Any]] = []

    def fake_record(**kwargs: Any) -> dict[str, Any]:
        events.append(kwargs)
        return {
            "id": len(events),
            "alarmId": kwargs.get("alarm_id"),
            "nextVerifyAt": kwargs.get("next_verify_at"),
            "deduped": False,
        }

    monkeypatch.setattr(
        portal_backend,
        "record_clear_notification",
        fake_record,
    )
    monkeypatch.setattr(
        portal_backend,
        "get_alarm_record",
        lambda alarm_id: None,
    )
    monkeypatch.setattr(
        portal_backend,
        "_update_portal_real_alarm_registry_safe",
        lambda **kwargs: None,
    )
    return events


def test_clear_notification_accepts_minimal_payload(
    client: TestClient,
    recorded_events: list[dict[str, Any]],
) -> None:
    response = client.post(
        "/api/portal/real-alarms/clear-notifications",
        json={"alarmId": "alarm-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["alarmId"] == "alarm-1"
    assert body["tracked"] is False
    assert body["eventId"] == 1
    assert recorded_events[0]["alarm_id"] == "alarm-1"
    assert recorded_events[0]["next_verify_at"]


def test_clear_notification_accepts_inoe_field_names(
    client: TestClient,
    recorded_events: list[dict[str, Any]],
) -> None:
    response = client.post(
        "/api/portal/real-alarms/clear-notifications",
        json={
            "alarmuniqueid": "alarm-9",
            "cleartime": "2026-06-10 12:00:00",
            "clearType": "manual",
            "operator": "张三",
        },
    )

    assert response.status_code == 200
    assert response.json()["alarmId"] == "alarm-9"
    stored = recorded_events[0]
    assert stored["clear_time"] == "2026-06-10 12:00:00"
    assert stored["clear_type"] == "manual"
    assert stored["operator"] == "张三"


def test_clear_notification_rejects_missing_alarm_id(
    client: TestClient,
    recorded_events: list[dict[str, Any]],
) -> None:
    response = client.post(
        "/api/portal/real-alarms/clear-notifications",
        json={"reason": "no id"},
    )

    assert response.status_code == 422
    assert recorded_events == []


def test_clear_notification_supplements_res_id_from_registry(
    client: TestClient,
    recorded_events: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_updates: list[dict[str, Any]] = []
    monkeypatch.setattr(
        portal_backend,
        "get_alarm_record",
        lambda alarm_id: {"alarmId": alarm_id, "resId": "3094"},
    )
    monkeypatch.setattr(
        portal_backend,
        "_update_portal_real_alarm_registry_safe",
        lambda **kwargs: registry_updates.append(kwargs),
    )

    response = client.post(
        "/api/portal/real-alarms/clear-notifications",
        json={"alarmId": "alarm-1"},
    )

    assert response.status_code == 200
    assert response.json()["tracked"] is True
    assert recorded_events[0]["res_id"] == "3094"
    assert registry_updates[0]["verification_status"] == "clear_reported"


def test_list_clear_events_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portal_backend,
        "list_clear_events",
        lambda *, alarm_id, limit: [
            {"id": 1, "alarmId": "alarm-1", "verifyStatus": "pending"},
        ],
    )

    response = client.get("/api/portal/real-alarms/clear-events")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["alarmId"] == "alarm-1"
