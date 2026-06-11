# -*- coding: utf-8 -*-
"""Recovery verification for INOE alarm-clear notifications.

When INOE reports an alarm as cleared we do not take their word for it.
Each clear event goes through up to three checks, driven by the
background loop in ``portal_backend``:

1. INOE-side recheck — the alarm must no longer appear in the active
   alarm list. If it is still (or again) active, the clear is moot and
   the event is judged ``recurred``.
2. Metric verification — the latest key metrics for the alarm's
   resource must look healthy (reuses ``evaluate_metric_recovery``).
3. Recurrence observation — after metrics pass, the alarm is watched
   for a configurable window; reappearing in the active list flips the
   verdict to ``recurred``.

This module holds the pure decision logic, message builders, and the
webhook notification senders. The loop itself (asyncio, INOE/metric
queries) stays in ``portal_backend`` to avoid circular imports; it
injects query results into the functions here, which keeps everything
in this file unit-testable without network or DB access.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import traceback
from typing import Any, Callable, Mapping
from urllib.parse import quote_plus

import requests

from qwenpaw.extensions.api import settings_store

# Verification outcome -> alarm registry status. An empty registry
# status means "leave the alarm record untouched".
_OUTCOME_REGISTRY_STATUS = {
    "recovered": "resolved",
    "unrecovered": "recovery_failed",
    "unknown": "recovery_unknown",
    "recurred": "recurred",
}

# Notification channel config is shared with the alarm-analyst scope so
# operators configure webhooks once; a dedicated recovery scope (if ever
# saved from the settings page) wins.
_NOTIFICATION_NAMESPACE = "notification_channels"
_NOTIFICATION_SCOPE_CANDIDATES = ("recovery_verification", "alarm_analyst")


# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------


def is_alarm_in_active_payload(
    alarm_id: str,
    alarms_payload: Mapping[str, Any] | None,
) -> bool:
    """Whether ``alarm_id`` appears in an INOE active-alarm payload."""
    normalized = str(alarm_id or "").strip()
    if not normalized or not isinstance(alarms_payload, Mapping):
        return False
    items = alarms_payload.get("items")
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, Mapping):
            continue
        candidate = str(
            item.get("alarmId") or item.get("id") or "",
        ).strip()
        if candidate and candidate == normalized:
            return True
    return False


def decide_verification_outcome(
    *,
    inoe_recheck: str,
    metric_verification: Mapping[str, Any] | None,
    attempt_number: int,
    retry_count: int,
    observation_minutes: float,
) -> dict[str, Any]:
    """Judge one verification attempt of a clear event.

    ``inoe_recheck`` is ``"cleared"`` (alarm absent from the active
    list), ``"still_active"`` (alarm present) or ``"unavailable"``
    (INOE could not be queried live). ``metric_verification`` is the
    output of ``evaluate_metric_recovery`` or ``None`` when no resource
    id was available to query. ``attempt_number`` is 1-based and counts
    the attempt being judged.

    Returns a dict with:
    - ``eventStatus``: next ``alarm_clear_events.verify_status``
    - ``registryStatus``: alarm registry status to set ("" = keep)
    - ``verificationStatus``: registry ``verification_status`` value
    - ``retry``: whether to reschedule another verification attempt
    - ``notify``: whether to push a webhook notification
    - ``summary``: human-readable conclusion (Chinese, used in messages)
    """
    if inoe_recheck == "still_active":
        return {
            "eventStatus": "recurred",
            "registryStatus": _OUTCOME_REGISTRY_STATUS["recurred"],
            "verificationStatus": "recurred",
            "retry": False,
            "notify": True,
            "summary": (
                "收到清除通知后复核 INOE 活动告警列表，该告警仍处于活动状态，" "判定为未清除/已复发，告警将重新进入分析流程"
            ),
        }

    metric_status = (
        str(
            (metric_verification or {}).get("status") or "unknown",
        )
        .strip()
        .lower()
    )
    metric_summary = str(
        (metric_verification or {}).get("summary") or "",
    ).strip()

    if metric_status == "recovered":
        inoe_note = (
            "INOE 活动列表已确认清除"
            if inoe_recheck == "cleared"
            else "INOE 活动列表暂不可达，以指标结论为准"
        )
        if observation_minutes > 0:
            return {
                "eventStatus": "observing",
                "registryStatus": _OUTCOME_REGISTRY_STATUS["recovered"],
                "verificationStatus": "recovered",
                "retry": False,
                "notify": True,
                "summary": (
                    f"{inoe_note}；{metric_summary or '关键指标未见异常'}。"
                    f"已判定恢复，进入 {observation_minutes:g} 分钟复发观察期"
                ),
            }
        return {
            "eventStatus": "recovered",
            "registryStatus": _OUTCOME_REGISTRY_STATUS["recovered"],
            "verificationStatus": "recovered",
            "retry": False,
            "notify": True,
            "summary": (
                f"{inoe_note}；{metric_summary or '关键指标未见异常'}。" "已确认恢复"
            ),
        }

    # unrecovered / unknown: retry while budget remains.
    if attempt_number <= max(0, int(retry_count)):
        return {
            "eventStatus": "pending",
            "registryStatus": "",
            "verificationStatus": "verifying",
            "retry": True,
            "notify": False,
            "summary": (
                f"第 {attempt_number} 次验证未通过"
                f"（{metric_summary or '指标状态无法判定'}），稍后重试"
            ),
        }

    if metric_status == "unrecovered":
        return {
            "eventStatus": "unrecovered",
            "registryStatus": _OUTCOME_REGISTRY_STATUS["unrecovered"],
            "verificationStatus": "unrecovered",
            "retry": False,
            "notify": True,
            "summary": (
                "INOE 报告告警已清除，但重试后关键指标仍异常"
                f"（{metric_summary or '指标持续异常'}），"
                "判定为未真正恢复，请人工介入"
            ),
        }
    return {
        "eventStatus": "unknown",
        "registryStatus": _OUTCOME_REGISTRY_STATUS["unknown"],
        "verificationStatus": "unknown",
        "retry": False,
        "notify": True,
        "summary": (
            "收到 INOE 清除通知，但多次验证均无法判定是否恢复"
            f"（{metric_summary or '缺少可用指标'}），请人工确认"
        ),
    }


def decide_observation_outcome(
    *,
    inoe_recheck: str,
) -> dict[str, Any]:
    """Judge the end-of-observation-window check."""
    if inoe_recheck == "still_active":
        return {
            "eventStatus": "recurred",
            "registryStatus": _OUTCOME_REGISTRY_STATUS["recurred"],
            "verificationStatus": "recurred",
            "retry": False,
            "notify": True,
            "summary": ("复发观察期内该告警再次出现在 INOE 活动列表，判定为复发，" "告警将重新进入分析流程"),
        }
    note = (
        "复发观察期结束，告警未再出现"
        if inoe_recheck == "cleared"
        else "复发观察期结束（INOE 暂不可达，未发现复发迹象）"
    )
    return {
        "eventStatus": "recovered",
        "registryStatus": "",
        "verificationStatus": "recovered",
        "retry": False,
        "notify": False,
        "summary": f"{note}，恢复结论维持不变",
    }


# ---------------------------------------------------------------------------
# History message builder (fault-disposal chat)
# ---------------------------------------------------------------------------


def build_recovery_history_message(
    *,
    event: Mapping[str, Any],
    outcome: Mapping[str, Any],
    verification: Mapping[str, Any] | None,
    alarm_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    alarm_id = str(event.get("alarmId") or "").strip()
    title = str((alarm_record or {}).get("title") or "").strip()
    device_name = str((alarm_record or {}).get("deviceName") or "").strip()
    content_lines = ["## 告警清除通知 — 恢复验证结果"]
    content_lines.append(f"- 告警编号：`{alarm_id}`")
    if title:
        content_lines.append(f"- 告警标题：{title}")
    if device_name:
        content_lines.append(f"- 设备：{device_name}")
    clear_time = str(event.get("clearTime") or "").strip()
    if clear_time:
        content_lines.append(f"- INOE 清除时间：{clear_time}")
    content_lines.append(
        f"- 验证结论：{outcome.get('summary') or '未知'}",
    )
    abnormal_metrics = (verification or {}).get("abnormalMetrics") or []
    if abnormal_metrics:
        metric_descriptions = "；".join(
            f"{item.get('metricCode')}="
            f"{item.get('latestValue') or item.get('avgValue') or '-'}"
            for item in abnormal_metrics
            if isinstance(item, Mapping)
        )
        content_lines.append(f"- 当前仍异常指标：{metric_descriptions}")
    return {
        "type": "agent",
        "content": "\n".join(content_lines),
        "recoveryVerification": dict(verification or {}),
        "clearEvent": dict(event),
    }


# ---------------------------------------------------------------------------
# Webhook notification (app push / DingTalk / Feishu)
# ---------------------------------------------------------------------------


def load_recovery_notification_config() -> dict[str, Any]:
    """Read webhook config, preferring a dedicated recovery scope."""
    channels = settings_store.get_namespace(_NOTIFICATION_NAMESPACE)
    for scope in _NOTIFICATION_SCOPE_CANDIDATES:
        config = channels.get(scope)
        if isinstance(config, dict) and any(
            str(config.get(key) or "").strip()
            for key in (
                "push_url",
                "dingtalk_webhook_url",
                "feishu_webhook_url",
            )
        ):
            return dict(config)
    return {}


def _notification_title(outcome: Mapping[str, Any]) -> str:
    status = str(outcome.get("eventStatus") or "").strip()
    if status in ("recovered", "observing"):
        return "告警恢复验证通过"
    if status == "recurred":
        return "告警复发提醒"
    if status == "unrecovered":
        return "告警清除但未恢复"
    return "告警恢复验证待确认"


def build_recovery_notification_text(
    *,
    event: Mapping[str, Any],
    outcome: Mapping[str, Any],
    alarm_record: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """Return ``(title, markdown_text)`` for webhook pushes."""
    title = _notification_title(outcome)
    lines = [f"### {title}"]
    alarm_id = str(event.get("alarmId") or "").strip()
    lines.append(f"- 告警编号：{alarm_id}")
    alarm_title = str((alarm_record or {}).get("title") or "").strip()
    if alarm_title:
        lines.append(f"- 告警标题：{alarm_title}")
    device_name = str((alarm_record or {}).get("deviceName") or "").strip()
    if device_name:
        lines.append(f"- 设备：{device_name}")
    clear_time = str(event.get("clearTime") or "").strip()
    if clear_time:
        lines.append(f"- INOE 清除时间：{clear_time}")
    lines.append(f"- 验证结论：{outcome.get('summary') or '未知'}")
    return title, "\n".join(lines)


def _build_dingtalk_signed_url(webhook_url: str, secret: str) -> str:
    secret = (secret or "").strip()
    if not secret:
        return webhook_url
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    encoded_sign = quote_plus(base64.b64encode(sign))
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}timestamp={timestamp}&sign={encoded_sign}"


def _feishu_sign_fields(secret: str) -> dict[str, str]:
    secret = (secret or "").strip()
    if not secret:
        return {}
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = base64.b64encode(
        hmac.new(
            string_to_sign.encode("utf-8"),
            b"",
            digestmod=hashlib.sha256,
        ).digest(),
    ).decode("utf-8")
    return {"timestamp": timestamp, "sign": sign}


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        return {}


def send_recovery_notification(
    *,
    event: Mapping[str, Any],
    outcome: Mapping[str, Any],
    alarm_record: Mapping[str, Any] | None,
    config: Mapping[str, Any] | None = None,
    post_json: Callable[..., dict[str, Any]] = _post_json,
) -> dict[str, Any]:
    """Push the verification verdict to configured webhook channels.

    Failures are reported in the result, never raised — notification is
    best-effort and must not break the verification loop.
    """
    effective_config = (
        dict(config)
        if config is not None
        else load_recovery_notification_config()
    )
    push_url = str(effective_config.get("push_url") or "").strip()
    dingtalk_url = str(
        effective_config.get("dingtalk_webhook_url") or "",
    ).strip()
    feishu_url = str(
        effective_config.get("feishu_webhook_url") or "",
    ).strip()
    if not push_url and not dingtalk_url and not feishu_url:
        return {"status": "skipped", "reason": "webhook_not_configured"}

    try:
        timeout_seconds = float(effective_config.get("timeout_seconds") or 8)
    except (TypeError, ValueError):
        timeout_seconds = 8.0
    title, text = build_recovery_notification_text(
        event=event,
        outcome=outcome,
        alarm_record=alarm_record,
    )

    channels: list[dict[str, Any]] = []
    if push_url:
        channels.append(
            _send_channel(
                "app",
                lambda: post_json(
                    push_url,
                    {"title": title, "content": text},
                    timeout_seconds,
                ),
            ),
        )
    if dingtalk_url:
        signed_url = _build_dingtalk_signed_url(
            dingtalk_url,
            str(effective_config.get("dingtalk_secret") or ""),
        )
        channels.append(
            _send_channel(
                "dingtalk",
                lambda: post_json(
                    signed_url,
                    {
                        "msgtype": "markdown",
                        "markdown": {"title": title, "text": text},
                    },
                    timeout_seconds,
                ),
            ),
        )
    if feishu_url:
        feishu_payload: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": f"{title}\n{text}"},
        }
        feishu_payload.update(
            _feishu_sign_fields(
                str(effective_config.get("feishu_secret") or ""),
            ),
        )
        channels.append(
            _send_channel(
                "feishu",
                lambda: post_json(feishu_url, feishu_payload, timeout_seconds),
            ),
        )

    sent = sum(1 for item in channels if item.get("status") == "sent")
    if sent == len(channels):
        status = "sent"
    elif sent > 0:
        status = "partial"
    else:
        status = "failed"
    return {"status": status, "channels": channels}


def _send_channel(
    channel_name: str,
    sender: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        response_json = sender()
    except Exception as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
        }
    errcode = str(response_json.get("errcode", "0"))
    code = str(response_json.get("code", "0"))
    if errcode not in ("0", "") or code not in ("0", "", "200"):
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": response_json.get("errmsg")
            or response_json.get("msg")
            or "webhook_rejected",
        }
    return {"channel": channel_name, "status": "sent", "reason": ""}


def send_recovery_notification_safe(**kwargs: Any) -> dict[str, Any]:
    """Wrapper that guarantees no exception escapes."""
    try:
        return send_recovery_notification(**kwargs)
    except Exception as exc:
        print(
            "[WARN] recovery verification notification failed: "
            f"{type(exc).__name__}: {exc}",
        )
        traceback.print_exc()
        return {"status": "failed", "reason": str(exc)}
