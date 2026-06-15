# -*- coding: utf-8 -*-
"""Display-field enrichment for big-screen alarm rows (skill parity).

These cover the additive rich fields added to ``_normalize_alarm_row``
and the ``format_alarm_duration`` helper, kept in a separate module so
the heavy legacy ``test_portal_real_alarms.py`` is left untouched.
"""
from datetime import datetime, timedelta, timezone

from qwenpaw.extensions.integrations import portal_real_alarms
from qwenpaw.extensions.integrations.portal_real_alarms import (
    query_portal_real_alarms,
)

_ALARM_TZ = timezone(timedelta(hours=8))

_POST_PATH = (
    "qwenpaw.extensions.integrations"
    ".portal_real_alarms._post_real_alarm_list"
)


def _rich_row() -> dict:
    return {
        "alarmuniqueid": "A-1",
        "alarmtitle": "内存使用率",
        "alarmseverity": "1",
        "alarmstatus": "1",
        "alarmclass": "threshold",
        "speciality": "操作系统",
        "alarmregion": "XA",
        "neId": "7953",
        "devId": 18,
        "eventtime": "2026-06-15 10:57:31",
        "eventlasttime": "2026-06-15 15:07:31",
        "alarmcount": "404",
        "devName": "智观部署虚机",
        "manageIp": "82.156.83.38",
    }


def test_normalize_alarm_row_enriches_display_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        _POST_PATH,
        lambda *, limit, begin_time, end_time, alarm_status=None: {
            "code": 200,
            "total": 1,
            "rows": [_rich_row()],
        },
    )
    payload = query_portal_real_alarms(
        limit=10,
        now=datetime(2026, 6, 15, 7, 7, 31, tzinfo=timezone.utc),
    )
    alarm = payload["items"][0]
    # rich display fields aligned with the real-alarm skill table
    assert alarm["levelName"] == "紧急"
    assert alarm["statusName"] == "活跃"
    assert alarm["className"] == "性能告警"
    assert alarm["speciality"] == "操作系统"
    assert alarm["region"] == "XA"
    assert alarm["ciId"] == "7953"  # neId preferred over devId
    assert alarm["count"] == 404
    assert "内存使用率" in alarm["message"]
    assert "智观部署虚机" in alarm["message"]


def test_normalize_alarm_row_keeps_dispatch_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        _POST_PATH,
        lambda *, limit, begin_time, end_time, alarm_status=None: {
            "code": 200,
            "total": 1,
            "rows": [_rich_row()],
        },
    )
    payload = query_portal_real_alarms(limit=10)
    alarm = payload["items"][0]
    # dispatch/chat flow must be untouched by the additive enrichment
    assert alarm["title"] == "内存使用率"
    assert alarm["level"] == "critical"
    assert alarm["status"] == "active"
    assert alarm["employeeId"] == "fault"
    assert alarm["visibleContent"] == "内存使用率（智观部署虚机 82.156.83.38）"


def test_format_alarm_duration() -> None:
    now = datetime(2026, 6, 15, 15, 7, 31, tzinfo=_ALARM_TZ)
    assert (
        portal_real_alarms.format_alarm_duration(
            "2026-06-15 10:57:31",
            now=now,
        )
        == "4h10m"
    )
    assert portal_real_alarms.format_alarm_duration("", now=now) == ""
    assert portal_real_alarms.format_alarm_duration("bad", now=now) == ""
    # future event time → no misleading duration
    assert (
        portal_real_alarms.format_alarm_duration(
            "2026-06-15 18:00:00",
            now=now,
        )
        == ""
    )
