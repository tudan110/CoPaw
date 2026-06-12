# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import pytest

from qwenpaw.extensions.api import recovery_verification_service as svc


# ---------------------------------------------------------------------------
# is_alarm_in_active_payload
# ---------------------------------------------------------------------------


def test_is_alarm_in_active_payload_matches_alarm_id() -> None:
    payload = {
        "items": [
            {"alarmId": "alarm-1"},
            {"id": "alarm-2"},
        ],
    }
    assert svc.is_alarm_in_active_payload("alarm-1", payload) is True
    assert svc.is_alarm_in_active_payload("alarm-2", payload) is True
    assert svc.is_alarm_in_active_payload("alarm-3", payload) is False
    assert svc.is_alarm_in_active_payload("", payload) is False
    assert svc.is_alarm_in_active_payload("alarm-1", None) is False


# ---------------------------------------------------------------------------
# decide_verification_outcome
# ---------------------------------------------------------------------------


def _metric(status: str, summary: str = "") -> dict[str, Any]:
    return {"status": status, "summary": summary, "abnormalMetrics": []}


def test_still_active_alarm_is_judged_recurred() -> None:
    outcome = svc.decide_verification_outcome(
        inoe_recheck="still_active",
        metric_verification=None,
        attempt_number=1,
        retry_count=3,
        observation_minutes=30,
    )
    assert outcome["eventStatus"] == "recurred"
    assert outcome["registryStatus"] == "recurred"
    assert outcome["retry"] is False
    assert outcome["notify"] is True


def test_recovered_metrics_enter_observation_window() -> None:
    outcome = svc.decide_verification_outcome(
        inoe_recheck="cleared",
        metric_verification=_metric("recovered", "指标正常"),
        attempt_number=1,
        retry_count=3,
        observation_minutes=30,
    )
    assert outcome["eventStatus"] == "observing"
    assert outcome["registryStatus"] == "resolved"
    assert outcome["verificationStatus"] == "recovered"
    assert outcome["notify"] is True


def test_recovered_metrics_without_observation_finish_immediately() -> None:
    outcome = svc.decide_verification_outcome(
        inoe_recheck="cleared",
        metric_verification=_metric("recovered"),
        attempt_number=1,
        retry_count=3,
        observation_minutes=0,
    )
    assert outcome["eventStatus"] == "recovered"
    assert outcome["registryStatus"] == "resolved"


def test_unrecovered_metrics_retry_while_budget_remains() -> None:
    outcome = svc.decide_verification_outcome(
        inoe_recheck="cleared",
        metric_verification=_metric("unrecovered", "锁等待仍异常"),
        attempt_number=2,
        retry_count=3,
        observation_minutes=30,
    )
    assert outcome["eventStatus"] == "pending"
    assert outcome["registryStatus"] == ""
    assert outcome["retry"] is True
    assert outcome["notify"] is False


def test_unrecovered_metrics_exhausted_become_recovery_failed() -> None:
    outcome = svc.decide_verification_outcome(
        inoe_recheck="cleared",
        metric_verification=_metric("unrecovered", "锁等待仍异常"),
        attempt_number=4,
        retry_count=3,
        observation_minutes=30,
    )
    assert outcome["eventStatus"] == "unrecovered"
    assert outcome["registryStatus"] == "recovery_failed"
    assert outcome["retry"] is False
    assert outcome["notify"] is True


def test_unknown_metrics_exhausted_become_recovery_unknown() -> None:
    outcome = svc.decide_verification_outcome(
        inoe_recheck="unavailable",
        metric_verification=None,
        attempt_number=4,
        retry_count=3,
        observation_minutes=30,
    )
    assert outcome["eventStatus"] == "unknown"
    assert outcome["registryStatus"] == "recovery_unknown"
    assert outcome["notify"] is True


def test_zero_retry_count_finalizes_on_first_attempt() -> None:
    outcome = svc.decide_verification_outcome(
        inoe_recheck="cleared",
        metric_verification=_metric("unrecovered"),
        attempt_number=1,
        retry_count=0,
        observation_minutes=0,
    )
    assert outcome["eventStatus"] == "unrecovered"
    assert outcome["retry"] is False


# ---------------------------------------------------------------------------
# decide_observation_outcome
# ---------------------------------------------------------------------------


def test_observation_recurrence_is_judged_recurred() -> None:
    outcome = svc.decide_observation_outcome(inoe_recheck="still_active")
    assert outcome["eventStatus"] == "recurred"
    assert outcome["registryStatus"] == "recurred"
    assert outcome["notify"] is True


def test_observation_quiet_window_confirms_recovery() -> None:
    outcome = svc.decide_observation_outcome(inoe_recheck="cleared")
    assert outcome["eventStatus"] == "recovered"
    assert outcome["registryStatus"] == ""
    assert outcome["notify"] is False


# ---------------------------------------------------------------------------
# History / notification builders
# ---------------------------------------------------------------------------


def test_build_recovery_history_message_includes_verdict() -> None:
    message = svc.build_recovery_history_message(
        event={"alarmId": "alarm-1", "clearTime": "2026-06-10 12:00:00"},
        outcome={"eventStatus": "unrecovered", "summary": "指标仍异常"},
        verification={
            "abnormalMetrics": [
                {"metricCode": "lock_wait", "latestValue": "3"},
            ],
        },
        alarm_record={"title": "数据库锁异常", "deviceName": "db-01"},
    )
    assert message["type"] == "agent"
    assert "alarm-1" in message["content"]
    assert "指标仍异常" in message["content"]
    assert "lock_wait=3" in message["content"]


def test_build_recovery_notification_text_titles() -> None:
    cases = {
        "recovered": "告警恢复验证通过",
        "observing": "告警恢复验证通过",
        "recurred": "告警复发提醒",
        "unrecovered": "告警清除但未恢复",
        "unknown": "告警恢复验证待确认",
    }
    for status, expected_title in cases.items():
        title, text = svc.build_recovery_notification_text(
            event={"alarmId": "alarm-1"},
            outcome={"eventStatus": status, "summary": "结论"},
            alarm_record=None,
        )
        assert title == expected_title
        assert "alarm-1" in text


# ---------------------------------------------------------------------------
# send_recovery_notification
# ---------------------------------------------------------------------------


def test_send_recovery_notification_skips_without_config() -> None:
    result = svc.send_recovery_notification(
        event={"alarmId": "alarm-1"},
        outcome={"eventStatus": "recovered", "summary": "ok"},
        alarm_record=None,
        config={},
    )
    assert result["status"] == "skipped"


def test_send_recovery_notification_posts_to_configured_channels() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(url: str, payload: dict, timeout: float) -> dict:
        calls.append((url, payload))
        return {"errcode": "0", "code": "0"}

    result = svc.send_recovery_notification(
        event={"alarmId": "alarm-1"},
        outcome={"eventStatus": "unrecovered", "summary": "未恢复"},
        alarm_record={"title": "数据库锁异常"},
        config={
            "push_url": "http://push.example/api",
            "dingtalk_webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=x",
            "dingtalk_secret": "SECabc",
            "feishu_webhook_url": "https://open.feishu.cn/hook/x",
            "timeout_seconds": 3,
        },
        post_json=fake_post,
    )

    assert result["status"] == "sent"
    assert len(calls) == 3
    dingtalk_url = calls[1][0]
    assert "timestamp=" in dingtalk_url and "sign=" in dingtalk_url
    assert calls[1][1]["msgtype"] == "markdown"
    assert calls[2][1]["msg_type"] == "text"


def test_send_recovery_notification_reports_channel_failure() -> None:
    def failing_post(url: str, payload: dict, timeout: float) -> dict:
        raise RuntimeError("connection refused")

    result = svc.send_recovery_notification(
        event={"alarmId": "alarm-1"},
        outcome={"eventStatus": "recovered", "summary": "ok"},
        alarm_record=None,
        config={"push_url": "http://push.example/api"},
        post_json=failing_post,
    )

    assert result["status"] == "failed"
    assert result["channels"][0]["status"] == "failed"


def test_load_recovery_notification_config_prefers_recovery_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        svc.settings_store,
        "get_namespace",
        lambda namespace: {
            "alarm_analyst": {"dingtalk_webhook_url": "https://analyst"},
            "recovery_verification": {
                "dingtalk_webhook_url": "https://recovery",
            },
        },
    )
    config = svc.load_recovery_notification_config()
    assert config["dingtalk_webhook_url"] == "https://recovery"


def test_load_recovery_notification_config_falls_back_to_alarm_analyst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        svc.settings_store,
        "get_namespace",
        lambda namespace: {
            "alarm_analyst": {"feishu_webhook_url": "https://analyst"},
            "recovery_verification": {"push_url": ""},
        },
    )
    config = svc.load_recovery_notification_config()
    assert config["feishu_webhook_url"] == "https://analyst"
