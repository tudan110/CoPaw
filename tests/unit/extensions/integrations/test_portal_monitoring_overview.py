from datetime import datetime, timedelta, timezone

from qwenpaw.extensions.integrations import portal_monitoring_overview


def test_query_business_cockpit_uses_dashboard_contract(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        portal_monitoring_overview,
        "_get_envelope",
        lambda path, params: captured.update(path=path, params=params)
        or {"code": 200},
    )

    result = portal_monitoring_overview.query_business_cockpit()

    assert result == {"code": 200}
    assert captured == {
        "path": "/resource/monitor/overview/business/cockpit",
        "params": {"status": -1, "name": "", "sort": "error"},
    }


def test_query_active_alarm_total_uses_current_list_without_status_filter(monkeypatch) -> None:
    captured = {}

    def _fake_query_portal_real_alarms(*, limit):
        captured["limit"] = limit
        return {"source": "live", "total": 5954, "items": []}

    monkeypatch.setattr(
        portal_monitoring_overview,
        "query_portal_real_alarms",
        _fake_query_portal_real_alarms,
    )
    total = portal_monitoring_overview.query_active_alarm_total()

    assert total == 5954
    assert captured == {"limit": 1}


def test_dashboard_alarm_history_uses_current_day_without_live_alarm_filter(
    monkeypatch,
) -> None:
    captured = {}
    tz = timezone(timedelta(hours=8))

    monkeypatch.setattr(portal_monitoring_overview, "_alarm_timezone", lambda: tz)
    monkeypatch.setattr(
        portal_monitoring_overview,
        "_get_envelope",
        lambda path, params: captured.update(path=path, params=params) or {"code": 200},
    )

    portal_monitoring_overview.query_dashboard_alarm_history(
        now=datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc),
        limit=2000,
    )

    assert captured["path"] == "/resource/alarm/statistics/hisAlarmList"
    assert captured["params"] == {
        "beginTime": "2026-07-21 00:00:00",
        "endTime": "2026-07-21 23:59:59",
        "sortType": 1,
        "pageNum": 1,
        "pageSize": 1000,
    }


def test_active_alarm_history_uses_rolling_24_hours_and_uncleared_filter(
    monkeypatch,
) -> None:
    captured = {}
    tz = timezone(timedelta(hours=8))

    monkeypatch.setattr(portal_monitoring_overview, "_alarm_timezone", lambda: tz)
    monkeypatch.setattr(
        portal_monitoring_overview,
        "_get_envelope",
        lambda path, params: captured.update(path=path, params=params) or {"code": 200},
    )

    portal_monitoring_overview.query_dashboard_active_alarm_history(
        now=datetime(2026, 7, 22, 2, 6, 25, tzinfo=timezone.utc),
        limit=2000,
    )

    assert captured["path"] == "/resource/alarm/statistics/hisAlarmList"
    assert captured["params"] == {
        "beginTime": "2026-07-21 10:06:25",
        "endTime": "2026-07-22 10:06:25",
        "sortType": 1,
        "isClear": 0,
        "pageNum": 1,
        "pageSize": 1000,
    }
