from datetime import datetime, timedelta, timezone

from qwenpaw.extensions.integrations import portal_real_alarms
from qwenpaw.extensions.integrations.portal_real_alarms import query_portal_real_alarms


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_query_portal_real_alarms_normalizes_live_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time, alarm_status=None: {
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
        lambda *, limit, begin_time, end_time, alarm_status=None: {
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
        lambda *, limit, begin_time, end_time, alarm_status=None: {
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
        lambda *, limit, begin_time, end_time, alarm_status=None: {
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
        lambda *, limit, begin_time, end_time, alarm_status=None: {"code": 200, "total": 0, "rows": []},
    )

    payload = query_portal_real_alarms(limit=10)

    assert payload == {"total": 0, "items": [], "source": "live"}


def test_query_portal_real_alarms_returns_empty_live_payload_on_request_failure(monkeypatch) -> None:
    def _raise_request_error(*, limit, begin_time, end_time, alarm_status=None):
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
    def _raise_request_error(*, limit, begin_time, end_time, alarm_status=None):
        raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _raise_request_error,
    )
    payload = query_portal_real_alarms(limit=10)

    assert payload == {"total": 0, "items": [], "source": "live"}


def test_query_portal_real_alarms_defaults_to_current_active_without_time_filter(monkeypatch) -> None:
    captured = {}

    def _fake_post(*, limit, begin_time=None, end_time=None, alarm_status=None):
        captured["limit"] = limit
        captured["begin_time"] = begin_time
        captured["end_time"] = end_time
        captured["alarm_status"] = alarm_status
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
    assert captured["begin_time"] is None
    assert captured["end_time"] is None
    assert captured["alarm_status"] is None


def test_query_portal_real_alarms_preserves_backend_total_beyond_page_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time=None, end_time=None, alarm_status=None: {
            "code": 200,
            "total": 5948,
            "rows": [
                {
                    "alarmuniqueid": "COMMON__active_alarm_1",
                    "alarmtitle": "CPU利用率过高",
                    "alarmseverity": "1",
                    "eventtime": "2026-06-03 10:00:00",
                    "devName": "node-1",
                    "manageIp": "10.0.0.1",
                },
            ],
        },
    )

    payload = query_portal_real_alarms(limit=5)

    assert payload["total"] == 5948
    assert len(payload["items"]) == 1


def test_query_portal_real_alarms_sends_explicit_minute_window(monkeypatch) -> None:
    captured = {}

    def _fake_post(*, limit, begin_time=None, end_time=None, alarm_status=None):
        captured["limit"] = limit
        captured["begin_time"] = begin_time
        captured["end_time"] = end_time
        captured["alarm_status"] = alarm_status
        return {"code": 200, "total": 0, "rows": []}

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _fake_post,
    )
    query_portal_real_alarms(
        limit=5,
        now=datetime(2026, 4, 17, 1, 0, 0, tzinfo=timezone.utc),
        lookback_minutes=15,
    )

    assert captured["limit"] == 5
    assert captured["begin_time"] == "2026-04-17 08:45:00"
    assert captured["end_time"] == "2026-04-17 09:00:00"
    assert captured["alarm_status"] is None


def test_query_portal_real_alarms_sends_explicit_alarm_status(monkeypatch) -> None:
    captured = {}

    def _fake_post(*, limit, begin_time=None, end_time=None, alarm_status=None):
        captured["limit"] = limit
        captured["begin_time"] = begin_time
        captured["end_time"] = end_time
        captured["alarm_status"] = alarm_status
        return {"code": 200, "total": 0, "rows": []}

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _fake_post,
    )
    query_portal_real_alarms(limit=5, alarm_status="1")

    assert captured == {
        "limit": 5,
        "begin_time": None,
        "end_time": None,
        "alarm_status": "1",
    }


def test_query_portal_real_alarms_posts_gateway_json_payload(monkeypatch) -> None:
    captured = {}
    monkeypatch.delenv("INOE_API_BASE_URL", raising=False)
    monkeypatch.delenv("INOE_API_TOKEN", raising=False)

    def _fake_post(url, *, json, headers, timeout):
        captured["method"] = "POST"
        captured["url"] = url
        captured["content_type"] = headers["Content-Type"]
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse(
            {
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

    monkeypatch.setattr(portal_real_alarms.requests, "post", _fake_post)
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
    assert captured["json"]["alarmstatus"] is None
    assert captured["json"]["params"] == {"beginEventtime": None, "endEventtime": None}
    assert captured["timeout"] == 30.0


def test_query_portal_real_alarms_falls_back_to_curl_on_connection_error(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {}
    monkeypatch.setenv("INOE_API_BASE_URL", "http://example.test")
    monkeypatch.setenv("INOE_API_TOKEN", "demo-token")

    def _raise_connection_error(*args, **kwargs):
        raise portal_real_alarms.requests.exceptions.ConnectionError("requests path blocked")

    class _FakeCompleted:
        returncode = 0
        stdout = "200"
        stderr = ""

    def _fake_run(args, *, capture_output, text, encoding, timeout, check):
        output_path = args[args.index("-o") + 1]
        body = {
            "code": 200,
            "total": 5995,
            "rows": [
                {
                    "alarmuniqueid": "live-row-1",
                    "alarmtitle": "CPU等待IO时间过长",
                    "alarmseverity": "2",
                    "eventtime": "2026-06-03 10:00:00",
                    "devName": "node-1",
                    "manageIp": "10.0.0.1",
                }
            ],
        }
        tmp_path.joinpath("unused").write_text("", encoding="utf-8")
        with open(output_path, "w", encoding="utf-8") as handle:
            import json

            json.dump(body, handle, ensure_ascii=False)
        captured["args"] = args
        captured["timeout"] = timeout
        captured["payload"] = json.loads(args[args.index("--data-binary") + 1])
        return _FakeCompleted()

    monkeypatch.setattr(portal_real_alarms.requests, "post", _raise_connection_error)
    monkeypatch.setattr(portal_real_alarms.subprocess, "run", _fake_run)

    payload = query_portal_real_alarms(limit=3)

    assert payload["source"] == "live"
    assert payload["total"] == 5995
    assert payload["items"][0]["title"] == "CPU等待IO时间过长"
    assert "--max-time" in captured["args"]
    assert captured["args"][captured["args"].index("--max-time") + 1] == "30"
    assert captured["timeout"] == 35
    assert captured["payload"]["alarmstatus"] is None
    assert captured["payload"]["params"] == {"beginEventtime": None, "endEventtime": None}


def test_query_portal_real_alarms_posts_bearer_header_from_config(monkeypatch) -> None:
    captured = {}

    def _fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["authorization"] = headers.get("Authorization")
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse({"code": 200, "rows": [], "total": 0})

    monkeypatch.setenv("INOE_API_BASE_URL", "http://example.test")
    monkeypatch.setenv("INOE_API_TOKEN", "demo-token")
    monkeypatch.setattr(portal_real_alarms.requests, "post", _fake_post)
    payload = query_portal_real_alarms(limit=3)

    assert payload == {"total": 0, "items": [], "source": "live"}
    assert captured["url"] == "http://example.test/resource/realalarm/list"
    assert captured["authorization"] == "Bearer demo-token"


def test_parse_alarm_event_time_uses_alarm_timezone(monkeypatch) -> None:
    monkeypatch.setattr(
        portal_real_alarms,
        "_get_alarm_timezone",
        lambda: timezone(timedelta(hours=8)),
    )

    parsed = portal_real_alarms.parse_alarm_event_time("2026-06-11 10:00:00")

    assert parsed is not None
    assert parsed.astimezone(timezone.utc) == datetime(
        2026, 6, 11, 2, 0, 0, tzinfo=timezone.utc
    )
    assert portal_real_alarms.parse_alarm_event_time("not-a-time") is None
    assert portal_real_alarms.parse_alarm_event_time("") is None


def test_filter_alarms_started_after_keeps_new_and_unparsable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        portal_real_alarms,
        "_get_alarm_timezone",
        lambda: timezone(timedelta(hours=8)),
    )
    # Cutoff = 2026-06-11 10:00 in the alarm platform's +08 timezone.
    cutoff = datetime(2026, 6, 11, 2, 0, 0, tzinfo=timezone.utc)
    payload = {
        "total": 3,
        "items": [
            {"alarmId": "old", "eventTime": "2026-06-11 09:59:59"},
            {"alarmId": "new", "eventTime": "2026-06-11 10:00:00"},
            {"alarmId": "weird", "eventTime": "no-time"},
        ],
        "source": "live",
    }

    filtered = portal_real_alarms.filter_alarms_started_after(
        payload, cutoff
    )

    # Older alarms drop; on-or-after stays; unparsable times fail open.
    assert [item["alarmId"] for item in filtered["items"]] == [
        "new",
        "weird",
    ]
    assert filtered["total"] == 2
    assert filtered["source"] == "live"
