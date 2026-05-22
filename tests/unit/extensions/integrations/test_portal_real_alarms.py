import json
from datetime import datetime, timezone

import httpx

from qwenpaw.extensions.integrations import portal_real_alarms
from qwenpaw.extensions.integrations.portal_real_alarms import query_portal_real_alarms


def test_query_portal_real_alarms_normalizes_live_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {
            "code": 200,
            "total": 1,
            "rows": [
                {
                    "alarmuniqueid": "COMMON__1776338881568_2044739586778116096",
                    "alarmtitle": "数据库锁异常",
                    "devId": 3094,
                    "alarmseverity": "1",
                    "alarmstatus": "1",
                    "eventtime": "2026-04-15 19:20:00",
                    "devName": "MySQL",
                    "manageIp": "10.43.150.186",
                }
            ],
        },
    )
    payload = query_portal_real_alarms(
        limit=10,
        now=datetime(2026, 4, 17, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert payload["source"] == "live"
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "COMMON__1776338881568_2044739586778116096"
    assert payload["items"][0]["alarmId"] == "COMMON__1776338881568_2044739586778116096"
    assert payload["items"][0]["resId"] == "3094"
    assert payload["items"][0]["level"] == "critical"
    assert payload["items"][0]["employeeId"] == "fault"
    assert payload["items"][0]["dispatchContent"] == "mysql/死锁 + cmdb/新增/插入"


def test_query_portal_real_alarms_uses_fallback_dispatch_for_camel_case_subtype(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {
            "code": 200,
            "total": 1,
            "rows": [
                {
                    "alarmuniqueid": "COMMON__other_alarm_1",
                    "alarmtitle": "CPU利用率过高",
                    "alarmSubType": "性能",
                    "alarmseverity": "2",
                    "alarmstatus": "1",
                    "eventtime": "2026-04-15 19:25:00",
                    "devName": "k8s-node-01",
                    "manageIp": "10.0.0.8",
                }
            ],
        },
    )
    payload = query_portal_real_alarms(limit=10)

    assert payload["source"] == "live"
    assert payload["items"][0]["dispatchContent"] == "CPU利用率过高 / k8s-node-01 / 性能"


def test_query_portal_real_alarms_omits_missing_device_sentinel_from_fallback_dispatch(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {
            "code": 200,
            "total": 1,
            "rows": [
                {
                    "alarmuniqueid": "COMMON__other_alarm_2",
                    "alarmtitle": "CPU利用率过高",
                    "alarmSubType": "性能",
                    "alarmseverity": "2",
                    "alarmstatus": "1",
                    "eventtime": "2026-04-15 19:25:00",
                    "manageIp": "10.0.0.8",
                }
            ],
        },
    )
    payload = query_portal_real_alarms(limit=10)

    assert payload["source"] == "live"
    assert payload["items"][0]["deviceName"] == "--"
    assert payload["items"][0]["dispatchContent"] == "CPU利用率过高 / 性能"


def test_query_portal_real_alarms_preserves_deadlock_dispatch_for_english_mysql_alarm(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {
            "code": 200,
            "total": 1,
            "rows": [
                {
                    "alarmuniqueid": "COMMON__mysql_deadlock_english_1",
                    "alarmtitle": "DEADLOCK detected",
                    "alarmsubtype": "database-lock",
                    "alarmseverity": "1",
                    "alarmstatus": "1",
                    "eventtime": "2026-04-15 19:26:00",
                    "devName": "MySQL",
                    "manageIp": "10.0.0.9",
                }
            ],
        },
    )
    payload = query_portal_real_alarms(limit=10)

    assert payload["source"] == "live"
    assert payload["items"][0]["dispatchContent"] == "mysql/死锁 + cmdb/新增/插入"


def test_query_portal_real_alarms_returns_empty_live_payload_when_live_rows_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {"code": 200, "total": 0, "rows": []},
    )

    payload = query_portal_real_alarms(limit=10)

    assert payload == {"total": 0, "items": [], "source": "live"}


def test_query_portal_real_alarms_returns_empty_live_payload_on_request_failure(monkeypatch) -> None:
    def _raise_request_error(*, limit, begin_time, end_time):
        raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _raise_request_error,
    )

    payload = query_portal_real_alarms(limit=10)

    assert payload == {"total": 0, "items": [], "source": "live"}


def test_query_portal_real_alarms_returns_empty_live_payload_when_request_failure_has_no_fallback(
    monkeypatch,
) -> None:
    def _raise_request_error(*, limit, begin_time, end_time):
        raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _raise_request_error,
    )
    payload = query_portal_real_alarms(limit=10)

    assert payload == {"total": 0, "items": [], "source": "live"}


def test_query_portal_real_alarms_sends_last_24_hours_active_alarm_request(monkeypatch) -> None:
    captured = {}

    def _fake_post(*, limit, begin_time, end_time):
        captured["limit"] = limit
        captured["begin_time"] = begin_time
        captured["end_time"] = end_time
        return {"code": 200, "total": 0, "rows": []}

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _fake_post,
    )
    monkeypatch.delenv("QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS", raising=False)
    query_portal_real_alarms(
        limit=5,
        now=datetime(2026, 4, 17, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert captured["limit"] == 5
    assert captured["begin_time"] == "2026-04-16 01:00:00"
    assert captured["end_time"] == "2026-04-17 01:00:00"


def test_query_portal_real_alarms_posts_gateway_json_payload(monkeypatch) -> None:
    captured = {}
    monkeypatch.delenv("INOE_API_BASE_URL", raising=False)
    monkeypatch.delenv("INOE_API_TOKEN", raising=False)

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers["content-type"]
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "rows": [
                    {
                        "alarmuniqueid": "live-row-1",
                        "alarmtitle": "数据库锁异常",
                        "alarmseverity": "1",
                        "eventtime": "2026-04-15 19:20:00",
                        "devName": "MySQL",
                        "manageIp": "10.43.150.186",
                    }
                ],
                "total": 1,
            },
        )

    transport = httpx.MockTransport(_handler)
    original_client = httpx.Client

    def _client_factory(*args, **kwargs) -> httpx.Client:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("qwenpaw.extensions.integrations.portal_real_alarms.httpx.Client", _client_factory)
    payload = query_portal_real_alarms(
        limit=5,
        now=datetime(2026, 4, 17, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert payload["source"] == "live"
    assert payload["total"] == 1
    assert captured["method"] == "POST"
    assert captured["url"] == (
        f"{portal_real_alarms.DEFAULT_INOE_API_BASE_URL}{portal_real_alarms.REAL_ALARM_LIST_ENDPOINT}"
    )
    assert captured["content_type"].startswith("application/json")
    assert captured["json"]["alarmstatus"] == "1"
    assert captured["json"]["params"] == {
        "beginEventtime": "2026-04-16 01:00:00",
        "endEventtime": "2026-04-17 01:00:00",
    }


def test_query_portal_real_alarms_posts_bearer_header_from_config(monkeypatch) -> None:
    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"code": 200, "rows": [], "total": 0})

    transport = httpx.MockTransport(_handler)
    original_client = httpx.Client

    def _client_factory(*args, **kwargs) -> httpx.Client:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setenv("INOE_API_BASE_URL", "http://example.test")
    monkeypatch.setenv("INOE_API_TOKEN", "demo-token")
    monkeypatch.setattr("qwenpaw.extensions.integrations.portal_real_alarms.httpx.Client", _client_factory)
    payload = query_portal_real_alarms(limit=3)

    assert payload == {"total": 0, "items": [], "source": "live"}
    assert captured["url"] == "http://example.test/resource/realalarm/list"
    assert captured["authorization"] == "Bearer demo-token"
