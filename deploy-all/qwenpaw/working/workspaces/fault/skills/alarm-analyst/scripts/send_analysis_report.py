#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推送 AI 告警分析报告通知。

使用方式:
    python scripts/send_analysis_report.py \
      --alarm-id alarm-001 \
      --alarm-title "数据库锁异常" \
      --visible-content "数据库锁异常（db_mysql_001 10.43.150.186）" \
      --device-name db_mysql_001 \
      --manage-ip 10.43.150.186 \
      --asset-id db_mysql_001 \
      --level critical \
      --status active \
      --event-time "2026-04-20 15:00:00" \
      --analysis-summary "AI 已完成根因分析" \
      --root-cause "疑似 MySQL 锁等待 / 长事务 / 死锁" \
      --suggestion "排查长事务" \
      --suggestion "检查阻塞链" \
      --suggestion "确认是否存在热点更新" \
      --output markdown
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


DEFAULT_NOTIFY_TIMEOUT_SECONDS = 8
ALLOWED_OUTPUTS = {"json", "markdown"}

_SEVERITY_MAP = {
    "1": "紧急",
    "2": "严重",
    "3": "普通",
    "4": "预警",
    "critical": "紧急",
    "urgent": "严重",
    "warning": "普通",
    "info": "预警",
}


def _normalize_severity(raw: str) -> str:
    """将告警级别数字转为中文名称，已是中文则原样返回。"""
    s = str(raw).strip()
    return _SEVERITY_MAP.get(s, s) if s else "-"


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return



_load_skill_env()


def _load_notification_setting_helpers():
    current_path = Path(__file__).resolve()
    for parent in current_path.parents:
        helper_dir = parent / "extensions" / "notifications"
        if helper_dir.is_dir() and (parent / "workspaces").is_dir():
            if str(helper_dir) not in sys.path:
                sys.path.insert(0, str(helper_dir))
            from notification_settings import (
                resolve_notification_bool,
                resolve_notification_int,
                resolve_notification_text,
            )

            return (
                resolve_notification_bool,
                resolve_notification_int,
                resolve_notification_text,
            )
    raise RuntimeError("无法定位 working/extensions/notifications/notification_settings.py")


(
    _RESOLVE_NOTIFICATION_BOOL,
    _RESOLVE_NOTIFICATION_INT,
    _RESOLVE_NOTIFICATION_TEXT,
) = _load_notification_setting_helpers()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _get_notify_env(name: str) -> str:
    setting_key_map = {
        "PUSH_URL": (
            "push_url",
            ["ORDER_CREATE_NOTIFY_PUSH_URL", "ALARM_ANALYST_CREATE_NOTIFY_PUSH_URL"],
        ),
        "DINGTALK_WEBHOOK_URL": (
            "dingtalk_webhook_url",
            [
                "ORDER_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL",
                "ALARM_ANALYST_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL",
            ],
        ),
        "DINGTALK_SECRET": (
            "dingtalk_secret",
            [
                "ORDER_CREATE_NOTIFY_DINGTALK_SECRET",
                "ALARM_ANALYST_CREATE_NOTIFY_DINGTALK_SECRET",
            ],
        ),
        "FEISHU_WEBHOOK_URL": (
            "feishu_webhook_url",
            [
                "ORDER_CREATE_NOTIFY_FEISHU_WEBHOOK_URL",
                "ALARM_ANALYST_CREATE_NOTIFY_FEISHU_WEBHOOK_URL",
            ],
        ),
        "FEISHU_SECRET": (
            "feishu_secret",
            [
                "ORDER_CREATE_NOTIFY_FEISHU_SECRET",
                "ALARM_ANALYST_CREATE_NOTIFY_FEISHU_SECRET",
            ],
        ),
    }
    if name not in setting_key_map:
        return ""
    setting_key, env_keys = setting_key_map[name]
    return _safe_str(
        _RESOLVE_NOTIFICATION_TEXT(
            "alarm_analyst",
            setting_key,
            env_keys=env_keys,
            start_path=Path(__file__).resolve(),
        )
    )


def _get_notify_timeout() -> int:
    return _RESOLVE_NOTIFICATION_INT(
        "alarm_analyst",
        "timeout_seconds",
        env_keys=[
            "ORDER_CREATE_NOTIFY_TIMEOUT_SECONDS",
            "ALARM_ANALYST_CREATE_NOTIFY_TIMEOUT_SECONDS",
        ],
        start_path=Path(__file__).resolve(),
        default=DEFAULT_NOTIFY_TIMEOUT_SECONDS,
    )


def _get_notify_mention_all() -> bool:
    return _RESOLVE_NOTIFICATION_BOOL(
        "alarm_analyst",
        "mention_all",
        env_keys=[
            "ORDER_CREATE_NOTIFY_MENTION_ALL",
            "ALARM_ANALYST_CREATE_NOTIFY_MENTION_ALL",
        ],
        start_path=Path(__file__).resolve(),
        default=False,
    )


def _join_suggestions(value: Any) -> str:
    if isinstance(value, list):
        normalized = [_safe_str(item) for item in value if _safe_str(item)]
        return "；".join(normalized)
    return _safe_str(value)


def _build_grouped_suggestion_lines(suggestions_str: str) -> list[str]:
    """Build suggestion lines with optional 3-tier group headers.

    When detail mode is on, the suggestions list contains group-header
    sentinels (e.g. ``🚨 紧急止血（立即执行）``) interleaved with the actual
    item texts.  This function detects those sentinels and emits them as
    bold group titles, then emits the subsequent items as numbered lines
    (resetting the counter per group).  When no group headers are present
    (flat mode), it just numbers all items.
    """
    GROUP_PREFIXES = ("🚨", "🔧", "🛡️")
    raw_items = [item.strip() for item in suggestions_str.split("；") if item.strip()]
    if not raw_items:
        return ["暂无处置建议"]
    has_groups = any(
        item.startswith(prefix) for item in raw_items for prefix in GROUP_PREFIXES
    )
    if not has_groups:
        return [
            f"{idx}. {item}"
            for idx, item in enumerate(raw_items, start=1)
        ]
    lines: list[str] = []
    counter = 0
    for item in raw_items:
        if item.startswith(GROUP_PREFIXES):
            if counter > 0:
                lines.append("")
            lines.append(f"**{item}**")
            counter = 0
        else:
            counter += 1
            lines.append(f"{counter}. {item}")
    return lines


def _build_notification_summary(*, visible_content: str, analysis_summary: str, root_cause: str) -> str:
    parts: list[str] = []
    for text in [visible_content, analysis_summary, root_cause]:
        compact = re.sub(r"\s+", " ", _safe_str(text)).strip("，,；;。 ")
        if compact and compact not in parts:
            parts.append(compact)
    return "；".join(parts) or "-"


def _build_notification_context(
    payload: dict[str, Any],
) -> dict[str, str]:
    analysis = payload.get("analysis") or {}
    alarm = payload.get("alarm") or {}

    title = _safe_str(alarm.get("title")) or "AI告警分析报告"
    visible_content = _safe_str(alarm.get("visibleContent"))
    analysis_summary = _safe_str(analysis.get("summary"))
    root_cause = _safe_str(analysis.get("rootCause")) or "-"
    suggestions = _join_suggestions(analysis.get("suggestions")) or "-"

    return {
        "title": title,
        "summary": _build_notification_summary(
            visible_content=visible_content,
            analysis_summary=analysis_summary,
            root_cause=root_cause,
        ),
        "device_name": _safe_str(alarm.get("deviceName")) or "-",
        "manage_ip": _safe_str(alarm.get("manageIp")) or "-",
        "alarm_id": _safe_str(alarm.get("alarmId")) or "-",
        "level": _normalize_severity(alarm.get("level", "")),
        "root_cause": root_cause,
        "suggestions": suggestions,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_notification_markdown_lines(context: dict[str, str], abnormal_metrics: list[dict[str, str]] | None = None) -> list[str]:
    lines = [
        "**AI告警分析报告**",
        "",
        f"- **标题**：{context['title']}",
        f"- **摘要**：{context['summary']}",
        (
            "- **资源**："
            f"{context['device_name']} / {context['manage_ip']} / 告警编号: "
            f"{context['alarm_id']}"
        ),
        f"- **等级**：{context['level']}",
    ]
    if abnormal_metrics:
        lines.append("")
        lines.append("- **异常指标**：")
        for idx, m in enumerate(abnormal_metrics, start=1):
            unit = f" {m['unit']}" if m.get("unit") else ""
            reason = f"（{m['reason']}）" if m.get("reason") else ""
            lines.append(f"  {idx}. {m['name']}：{m['value']}{unit}{reason}")
        lines.append("")
    suggestion_text = "\n".join(_build_grouped_suggestion_lines(context["suggestions"]))
    lines.append(f"- **根因方向**：{context['root_cause']}")
    lines.extend([
        f"- **处置建议**：\n{suggestion_text}",
        f"- **分析时间**：{context['created_at']}",
        "",
        "> 此报告为 AI 自动生成，请尽快跟进处置。",
    ])
    return lines


def _build_notification_markdown_text(context: dict[str, str]) -> str:
    return "\n".join(_build_notification_markdown_lines(context))


def _build_notification_plain_text_lines(context: dict[str, str], abnormal_metrics: list[dict[str, str]] | None = None) -> list[str]:
    lines = [
        "AI告警分析报告",
        f"标题：{context['title']}",
        f"摘要：{context['summary']}",
        f"资源：{context['device_name']} / {context['manage_ip']} / 告警编号: {context['alarm_id']}",
        f"等级：{context['level']}",
    ]
    if abnormal_metrics:
        lines.append("异常指标：")
        for idx, m in enumerate(abnormal_metrics, start=1):
            unit = f" {m['unit']}" if m.get("unit") else ""
            reason = f"（{m['reason']}）" if m.get("reason") else ""
            lines.append(f"  {idx}. {m['name']}：{m['value']}{unit}{reason}")
    lines.append(f"根因方向：{context['root_cause']}")
    lines.append("处置建议：")
    lines.extend(_build_grouped_suggestion_lines(context["suggestions"]))
    lines.extend([
        f"分析时间：{context['created_at']}",
        "此报告为 AI 自动生成，请尽快跟进处置。",
    ])
    return lines


def _build_app_notify_payload(context: dict[str, str], abnormal_metrics: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "title": "AI告警分析报告",
        "content": "\n".join(_build_notification_plain_text_lines(context, abnormal_metrics)),
        "type": "text",
    }


def _build_dingtalk_notify_payload(context: dict[str, str], abnormal_metrics: list[dict[str, str]] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {
            "title": _safe_str(context.get("title")) or "AI告警分析报告",
            "text": "\n".join(_build_notification_markdown_lines(context, abnormal_metrics)),
        },
    }
    if _get_notify_mention_all():
        payload["at"] = {"isAtAll": True}
    return payload


def _build_feishu_notify_payload(context: dict[str, str], abnormal_metrics: list[dict[str, str]] | None = None) -> dict[str, Any]:
    suggestion_lines = _build_grouped_suggestion_lines(context["suggestions"])
    elements: list[dict[str, Any]] = []
    if _get_notify_mention_all():
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "<at id=all></at>",
                },
            }
        )
    elements.extend(
        [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**告警标题**\n{context['title']}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**告警等级**\n{context['level']}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**设备名称**\n{context['device_name']}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**管理 IP / 告警编号**\n{context['manage_ip']} / {context['alarm_id']}",
                        },
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**摘要**\n{context['summary']}",
                },
            },
        ]
    )
    if abnormal_metrics:
        metric_lines = []
        for idx, m in enumerate(abnormal_metrics, start=1):
            unit = f" {m['unit']}" if m.get("unit") else ""
            reason = f"（{m['reason']}）" if m.get("reason") else ""
            metric_lines.append(f"{idx}. {m['name']}：{m['value']}{unit}{reason}")
        elements.extend([
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**异常指标**\n" + "\n".join(metric_lines),
                },
            },
        ])
    elements.extend([
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**根因方向**\n{context['root_cause']}",
            },
        },
    ])
    elements.extend([
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**处置建议**\n" + "\n".join(suggestion_lines),
            },
        },
    ])
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"告警编号：{context['alarm_id']}",
                },
                {
                    "tag": "plain_text",
                    "content": f"分析时间：{context['created_at']}",
                },
            ],
        }
    )
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": "red",
                "title": {
                    "tag": "plain_text",
                    "content": f"AI告警分析报告 — {context['device_name']}",
                },
            },
            "elements": elements,
        },
    }
    secret = _get_notify_env("FEISHU_SECRET")
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        sign = base64.b64encode(
            hmac.new(
                string_to_sign.encode("utf-8"),
                b"",
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return payload


def _build_dingtalk_signed_webhook_url(webhook_url: str) -> str:
    secret = _get_notify_env("DINGTALK_SECRET")
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


def _is_successful_push_response(response_json: Any) -> bool:
    if not isinstance(response_json, dict) or not response_json:
        return True
    if "success" in response_json:
        return bool(response_json.get("success"))
    if "ok" in response_json:
        return bool(response_json.get("ok"))
    if "code" in response_json:
        return str(response_json.get("code") or "") in {"0", "200"}
    if "status" in response_json:
        return str(response_json.get("status") or "").lower() in {"ok", "success", "sent"}
    if "errcode" in response_json:
        return str(response_json.get("errcode") or "") == "0"
    return True


def _send_app_push(*, channel_name: str, push_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(
            push_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_get_notify_timeout(),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": str(exc),
        }

    try:
        response_json = response.json()
    except (AttributeError, ValueError):
        response_json = {}

    if _is_successful_push_response(response_json):
        return {
            "channel": channel_name,
            "status": "sent",
            "reason": "",
        }

    return {
        "channel": channel_name,
        "status": "failed",
        "reason": response_json.get("errmsg")
        or response_json.get("message")
        or response_json.get("reason")
        or "push_rejected",
    }


def _send_json_webhook(
    *,
    channel_name: str,
    webhook_url: str,
    payload: dict[str, Any],
    success_predicate: Any,
) -> dict[str, Any]:
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_get_notify_timeout(),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": str(exc),
        }

    try:
        response_json = response.json()
    except ValueError as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": f"invalid_json_response: {exc}",
        }

    if success_predicate(response_json):
        return {
            "channel": channel_name,
            "status": "sent",
            "reason": "",
        }
    return {
        "channel": channel_name,
        "status": "failed",
        "reason": response_json.get("errmsg")
        or response_json.get("message")
        or "webhook_rejected",
    }


def _notify_analysis_report(
    payload: dict[str, Any],
) -> dict[str, Any]:
    app_push_url = _get_notify_env("PUSH_URL") or _get_notify_env("WEBHOOK_URL")
    dingtalk_webhook_url = _get_notify_env("DINGTALK_WEBHOOK_URL")
    feishu_webhook_url = _get_notify_env("FEISHU_WEBHOOK_URL")
    if not app_push_url and not dingtalk_webhook_url and not feishu_webhook_url:
        return {
            "enabled": False,
            "status": "skipped",
            "reason": "webhook_not_configured",
            "channels": [],
        }

    context = _build_notification_context(payload)
    abnormal_metrics = (payload.get("analysis") or {}).get("abnormalMetrics") or []
    channels: list[dict[str, Any]] = []
    if app_push_url:
        channels.append(
            _send_app_push(
                channel_name="app",
                push_url=app_push_url,
                payload=_build_app_notify_payload(context, abnormal_metrics),
            )
        )
    if dingtalk_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="dingtalk",
                webhook_url=_build_dingtalk_signed_webhook_url(dingtalk_webhook_url),
                payload=_build_dingtalk_notify_payload(context, abnormal_metrics),
                success_predicate=lambda data: str(data.get("errcode", "")) == "0",
            )
        )
    if feishu_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="feishu",
                webhook_url=feishu_webhook_url,
                payload=_build_feishu_notify_payload(context, abnormal_metrics),
                success_predicate=lambda data: str(data.get("StatusCode", "")) == "0"
                or str(data.get("code", "")) == "0",
            )
        )

    sent_count = sum(1 for item in channels if item.get("status") == "sent")
    if sent_count == len(channels) and channels:
        status = "sent"
        reason = ""
    elif sent_count > 0:
        status = "partial"
        reason = "partial_failure"
    else:
        status = "failed"
        reason = "; ".join(
            f"{item.get('channel')}:{item.get('reason') or 'unknown'}"
            for item in channels
        )
    return {
        "enabled": True,
        "status": status,
        "reason": reason,
        "channels": channels,
    }


def _format_notification_channels(notification: dict[str, Any], *, fallback: str) -> str:
    sent_channels = [
        _safe_str(item.get("channel"))
        for item in notification.get("channels") or []
        if _safe_str(item.get("status")).lower() == "sent"
    ]
    if not sent_channels:
        return fallback
    label_map = {
        "app": "应用",
        "dingtalk": "钉钉",
        "feishu": "飞书",
    }
    labels = [label_map.get(name, name) for name in sent_channels if name]
    return "、".join(labels) + "已发送"


def _format_notification_status(notification: dict[str, Any]) -> str:
    status = _safe_str(notification.get("status")).lower()
    reason = _safe_str(notification.get("reason"))
    if status == "sent":
        return "✅ 已成功推送"
    if status == "partial":
        return "⚠️ 部分推送成功"
    if status == "failed":
        return f"❌ 推送失败：{reason or '未知错误'}"
    if status == "skipped":
        if reason == "webhook_not_configured":
            return "— 未配置"
        return "— 已跳过"
    return "— 未配置"


def _normalize_suggestion_items(
    suggestions: list[str] | None = None,
    suggestions_json: str | None = None,
) -> list[dict[str, str]]:
    """Parse --suggestion / --suggestions-json into {"text", "stage"} items.

    --suggestions-json accepts either a flat string array (legacy) or an
    array of ``{"text": "...", "stage": "emergency"|"repair"}`` objects.
    Items tagged ``stage="emergency"`` are the single source of truth for
    which suggestion(s) get sorted first and prefixed with 🚑 in the
    unified 处置建议 list, so callers no longer need to separately
    duplicate that text into ``--emergency-plan``.
    """
    items: list[dict[str, str]] = [
        {"text": _safe_str(item), "stage": ""}
        for item in suggestions or []
        if _safe_str(item)
    ]

    if suggestions_json:
        try:
            parsed = json.loads(suggestions_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--suggestions-json 不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("--suggestions-json 必须是数组")
        for entry in parsed:
            if isinstance(entry, str):
                text = _safe_str(entry)
                if text:
                    items.append({"text": text, "stage": ""})
            elif isinstance(entry, dict):
                text = _safe_str(entry.get("text") or entry.get("description"))
                if not text:
                    continue
                stage = _safe_str(entry.get("stage")).lower()
                if stage not in {"emergency", "repair", "prevention"}:
                    stage = ""
                items.append({"text": text, "stage": stage})

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        key = f"{item['stage']}\0{item['text']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    if not deduped:
        raise ValueError("至少提供一条处置建议，请使用 --suggestion 或 --suggestions-json")
    return deduped


def _default_report_title(alarm_title: str) -> str:
    title = _safe_str(alarm_title) or "故障"
    return f"AI分析 · {title}"


def _parse_abnormal_metrics(raw: str) -> list[dict[str, str]]:
    """Parse --abnormal-metrics-json into a list of metric dicts."""
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = _safe_str(item.get("name") or item.get("metricName") or "")
        if not name:
            continue
        result.append({
            "name": name,
            "code": _safe_str(item.get("code") or item.get("metricCode") or ""),
            "value": _safe_str(item.get("value") or item.get("latestValue") or ""),
            "unit": _safe_str(item.get("unit") or ""),
            "reason": _safe_str(item.get("reason") or item.get("异常说明") or ""),
        })
    return result


def _normalize_ai_alarm_title(alarm_title: str) -> str:
    title = _safe_str(alarm_title) or "故障告警"
    title = re.sub(r"^\s*AI\s*创建\s*[·:：-]?\s*", "", title)
    title = re.sub(r"\s*[\(（]\s*AI\s*创建\s*[\)）]\s*$", "", title)
    title = title.strip() or "故障告警"
    return f"{title}（AI创建）"


def _require_alarm_id(alarm_id: str) -> str:
    normalized = _safe_str(alarm_id)
    if not normalized:
        raise ValueError("必须提供告警流水号，请通过 --alarm-id 传入并映射到 alarm.alarmId")
    return normalized


def build_report_payload(args: argparse.Namespace) -> dict[str, Any]:
    suggestion_items = _normalize_suggestion_items(args.suggestion, args.suggestions_json)
    detail_mode = os.getenv("ALARM_ANALYST_DISPOSAL_DETAIL_MODE", "false").strip().lower() == "true"

    legacy_emergency_plan = _safe_str(getattr(args, "emergency_plan", ""))
    emergency_texts = [
        item["text"] for item in suggestion_items if item["stage"] == "emergency"
    ]
    if legacy_emergency_plan and legacy_emergency_plan not in emergency_texts:
        emergency_texts.insert(0, legacy_emergency_plan)
    repair_texts = [
        item["text"] for item in suggestion_items if item["stage"] == "repair"
    ]
    prevention_texts = [
        item["text"] for item in suggestion_items if item["stage"] == "prevention"
    ]
    other_texts = [
        item["text"] for item in suggestion_items
        if item["stage"] not in {"emergency", "repair", "prevention"}
    ]

    if detail_mode:
        suggestions: list[str] = []
        if emergency_texts:
            suggestions.append("🚨 紧急止血（立即执行）")
            for text in emergency_texts:
                suggestions.append(f"🚑 {text}")
        if repair_texts or other_texts:
            suggestions.append("🔧 根因修复（计划内操作 / 短期）")
            for text in repair_texts + other_texts:
                suggestions.append(text)
        if prevention_texts:
            suggestions.append("🛡️ 预防措施（中长期）")
            suggestions.extend(prevention_texts)
    else:
        suggestions = [f"🚑 {text}" for text in emergency_texts] + repair_texts + other_texts + prevention_texts
    alarm_id = _require_alarm_id(args.alarm_id)
    alarm_title = _normalize_ai_alarm_title(_safe_str(args.alarm_title))
    analysis_summary = _safe_str(args.analysis_summary) or "AI 已完成根因分析"
    abnormal_metrics = _parse_abnormal_metrics(getattr(args, "abnormal_metrics_json", ""))

    return {
        "alarmId": alarm_id,
        "chatId": _safe_str(getattr(args, "chat_id", "")),
        "resId": _safe_str(getattr(args, "res_id", "")),
        "metricType": _safe_str(args.metric_type) or "mysql",
        "alarm": {
            "alarmId": alarm_id,
            "title": alarm_title,
            "visibleContent": _safe_str(args.visible_content),
            "deviceName": _safe_str(args.device_name),
            "manageIp": _safe_str(args.manage_ip),
            "assetId": _safe_str(args.asset_id),
            "level": _normalize_severity(args.level),
            "status": _safe_str(args.status),
            "eventTime": _safe_str(args.event_time),
        },
        "analysis": {
            "summary": analysis_summary,
            "rootCause": _safe_str(args.root_cause),
            "suggestions": suggestions,
            "abnormalMetrics": abnormal_metrics,
        },
    }


def send_analysis_report(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send notification for the analysis report. No workorder creation."""
    notification = _notify_analysis_report(payload)
    return {
        "status": "sent" if notification.get("status") == "sent" else notification.get("status", "unknown"),
        "notification": notification,
    }


def format_markdown_result(payload: dict[str, Any], result: dict[str, Any]) -> str:
    analysis = payload.get("analysis") or {}
    alarm = payload.get("alarm") or {}
    notification = result.get("notification") or {}
    suggestions = analysis.get("suggestions") or []

    lines = [
        "## AI 告警分析报告推送结果",
        f"- 告警编号：`{alarm.get('alarmId') or payload.get('alarmId') or ''}`",
        f"- 告警标题：{alarm.get('title') or '-'}",
        f"- 分析摘要：{analysis.get('summary') or '-'}",
        f"- 根因方向：{analysis.get('rootCause') or '-'}",
        f"- 处置建议：{'；'.join(str(item) for item in suggestions) if suggestions else '-'}",
        f"- 通知状态：**{_format_notification_status(notification)}**",
        f"- 通知渠道：{_format_notification_channels(notification, fallback='无')}",
        "- 当前状态：已推送分析报告，等待处置完成回调",
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="推送 AI 告警分析报告")
    parser.add_argument("--alarm-id", required=True, help="告警流水号，对应 alarm.alarmId")
    parser.add_argument("--alarm-title", required=True, help="告警标题")
    parser.add_argument("--visible-content", default="", help="告警可见摘要")
    parser.add_argument("--device-name", default="", help="设备名 / 资源名")
    parser.add_argument("--manage-ip", default="", help="管理 IP")
    parser.add_argument("--asset-id", default="", help="资产编号")
    parser.add_argument("--level", default="", help="告警级别")
    parser.add_argument("--status", default="active", help="告警状态")
    parser.add_argument("--event-time", default="", help="告警时间")
    parser.add_argument("--analysis-summary", default="", help="AI 分析摘要")
    parser.add_argument("--root-cause", default="", help="根因方向")
    parser.add_argument(
        "--emergency-plan",
        default="",
        help=(
            "紧急预案（止血动作）的手工兜底写法，仅在未使用 --suggestions-json 的 "
            "stage 标记时才需要传；会以 🚑 前缀追加到处置建议列表最前，不再单独成段"
        ),
    )
    parser.add_argument(
        "--suggestion",
        action="append",
        default=[],
        help="处置建议，可重复传入多次",
    )
    parser.add_argument(
        "--suggestions-json",
        default="",
        help=(
            "JSON 数组格式的处置建议，支持两种写法：纯字符串数组（例如 "
            '["排查长事务","检查阻塞链"]，全部归入处置建议）；或带 stage '
            '的对象数组（例如 [{"text":"执行 memory purge 止血",'
            '"stage":"emergency"},{"text":"扩容宿主机内存","stage":"repair"}]，'
            "stage=emergency 的条目会自动排到处置建议列表最前并加 🚑 前缀，"
            "与 repair/无 stage 条目合并为同一个列表，不再单独成段"
        ),
    )
    parser.add_argument(
        "--abnormal-metrics-json",
        default="",
        help='JSON 数组格式的异常指标，例如 [{"name":"CPU IO等待","code":"cpu_iowait","value":"85.3","unit":"%","reason":"远超正常水平"}]',
    )
    parser.add_argument("--metric-type", default="mysql", help="资源类型，例如 mysql")
    parser.add_argument("--chat-id", default="", help="当前故障会话 ID（可选）")
    parser.add_argument("--res-id", default="", help="CMDB CI ID（可选）")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = build_report_payload(args)
        result = send_analysis_report(payload)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(
            json.dumps(
                {
                    "request": payload,
                    "result": result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_markdown_result(payload, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
