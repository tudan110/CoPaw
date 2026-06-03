from qwenpaw.extensions.integrations import portal_monitoring_overview


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
