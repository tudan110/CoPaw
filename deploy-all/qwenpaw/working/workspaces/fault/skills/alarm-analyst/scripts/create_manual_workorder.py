#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建人工处置工单。

使用方式:
    python scripts/create_manual_workorder.py \
      --chat-id 82bd7e8c-6940-414b-a59e-aede36f713ad \
      --res-id 3094 \
      --metric-type mysql \
      --alarm-id alarm-001 \
      --alarm-title "数据库锁异常" \
      --visible-content "数据库锁异常（db_mysql_001 10.43.150.186）" \
      --device-name db_mysql_001 \
      --manage-ip 10.43.150.186 \
      --asset-id db_mysql_001 \
      --level critical \
      --status active \
      --event-time "2026-04-20 15:00:00" \
      --analysis-summary "AI 已完成根因分析，自动创建人工处置工单" \
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
import random
import re
import subprocess
import sys
import tempfile
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


DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_NOTIFY_TIMEOUT_SECONDS = 8
DEFAULT_TICKET_PRIORITY = "P1"
DEFAULT_TICKET_CATEGORY = "database-lock"
DEFAULT_TICKET_SOURCE = "portal-fault-disposal-ai"
DEFAULT_EXTERNAL_SYSTEM = "manual-workorder"
ALLOWED_OUTPUTS = {"json", "markdown"}


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return

    skill_dir = Path(__file__).resolve().parents[1]
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=True)


_load_skill_env()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_base_url(api_base_url: str | None) -> str:
    base_url = (api_base_url or os.getenv("INOE_API_BASE_URL") or "").strip()
    if not base_url:
        raise ValueError("未设置 INOE_API_BASE_URL，请检查 skills/alarm-analyst/.env")
    return base_url.rstrip("/")


def _get_token(token: str | None) -> str:
    normalized_token = _safe_str(token or os.getenv("INOE_API_TOKEN"))
    if not normalized_token:
        raise ValueError("未设置 INOE_API_TOKEN，请检查 skills/alarm-analyst/.env")
    return normalized_token


def _get_timeout(timeout_seconds: int | None) -> int:
    if timeout_seconds is not None:
        return timeout_seconds
    raw = _safe_str(os.getenv("ALARM_ANALYST_METRIC_TIMEOUT_SECONDS"))
    return int(raw) if raw else DEFAULT_TIMEOUT_SECONDS


def _get_notify_env(name: str) -> str:
    return _safe_str(
        os.getenv(f"ORDER_CREATE_NOTIFY_{name}")
        or os.getenv(f"ALARM_ANALYST_CREATE_NOTIFY_{name}")
    )


def _get_notify_timeout() -> int:
    raw = _get_notify_env("TIMEOUT_SECONDS")
    return int(raw) if raw else DEFAULT_NOTIFY_TIMEOUT_SECONDS


def _get_notify_mention_all() -> bool:
    return (_get_notify_env("MENTION_ALL") or "false").lower() in {"1", "true", "yes"}


def _build_serial_no() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
    suffix = f"{random.randint(0, 99999):05d}"
    return f"{timestamp}{suffix}"


def _join_suggestions(value: Any) -> str:
    if isinstance(value, list):
        normalized = [_safe_str(item) for item in value if _safe_str(item)]
        return "；".join(normalized)
    return _safe_str(value)


def _build_notification_summary(*, visible_content: str, analysis_summary: str, root_cause: str) -> str:
    parts: list[str] = []
    for text in [visible_content, analysis_summary, root_cause]:
        compact = re.sub(r"\s+", " ", _safe_str(text)).strip("，,；;。 ")
        if compact and compact not in parts:
            parts.append(compact)
    return "；".join(parts) or "-"


def _build_notification_context(
    payload: dict[str, Any],
    response_payload: dict[str, Any],
) -> dict[str, str]:
    ticket = payload.get("ticket") or {}
    analysis = payload.get("analysis") or {}
    alarm = payload.get("alarm") or {}
    response_data = response_payload.get("data") or {}

    title = _safe_str(ticket.get("title") or alarm.get("title")) or "AI创建处置工单"
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
        "res_id": _safe_str(payload.get("resId")) or "-",
        "level": _safe_str(alarm.get("level")) or "-",
        "root_cause": root_cause,
        "suggestions": suggestions,
        "task_id": _safe_str(response_data.get("taskId")) or "-",
        "proc_ins_id": _safe_str(response_data.get("procInsId")) or "-",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_notification_markdown_lines(context: dict[str, str]) -> list[str]:
    return [
        "**AI创建处置工单**",
        "",
        f"- **标题**：{context['title']}",
        f"- **摘要**：{context['summary']}",
        (
            "- **资源**："
            f"{context['device_name']} / {context['manage_ip']} / CI ID: "
            f"{context['res_id']}"
        ),
        f"- **等级**：{context['level']}",
        f"- **根因方向**：{context['root_cause']}",
        f"- **处置建议**：{context['suggestions']}",
        f"- **taskId**：{context['task_id']}",
        f"- **procInsId**：{context['proc_ins_id']}",
        f"- **创建时间**：{context['created_at']}",
        "",
        "> 此工单为 AI 自动创建，请尽快跟进处置。",
    ]


def _build_notification_markdown_text(context: dict[str, str]) -> str:
    return "\n".join(_build_notification_markdown_lines(context))


def _build_notification_plain_text_lines(context: dict[str, str]) -> list[str]:
    return [
        "AI创建处置工单",
        f"标题：{context['title']}",
        f"摘要：{context['summary']}",
        f"资源：{context['device_name']} / {context['manage_ip']} / CI ID: {context['res_id']}",
        f"等级：{context['level']}",
        f"根因方向：{context['root_cause']}",
        f"处置建议：{context['suggestions']}",
        f"taskId：{context['task_id']}",
        f"procInsId：{context['proc_ins_id']}",
        f"创建时间：{context['created_at']}",
        "此工单为 AI 自动创建，请尽快跟进处置。",
    ]


def _build_app_notify_payload(context: dict[str, str]) -> dict[str, Any]:
    return {
        "title": "AI创建处置工单",
        "content": "\n".join(_build_notification_plain_text_lines(context)),
        "type": "text",
    }


def _build_dingtalk_notify_payload(context: dict[str, str]) -> dict[str, Any]:
    markdown_lines: list[str] = []
    keyword = _get_notify_env("DINGTALK_KEYWORD")
    if keyword:
        markdown_lines.extend([keyword, ""])
    markdown_lines.extend(_build_notification_markdown_lines(context))
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {
            "title": _safe_str(context.get("title")) or "AI创建处置工单",
            "text": "\n".join(markdown_lines),
        },
    }
    if _get_notify_mention_all():
        payload["at"] = {"isAtAll": True}
    return payload


def _build_feishu_notify_payload(context: dict[str, str]) -> dict[str, Any]:
    suggestion_lines = [
        f"- {item.strip()}"
        for item in context["suggestions"].split("；")
        if item.strip()
    ] or ["- 暂无处置建议"]
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
                            "content": f"**管理 IP / CI ID**\n{context['manage_ip']} / {context['res_id']}",
                        },
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**摘要**\n"
                        f"{context['summary']}\n\n"
                        f"**根因方向**\n{context['root_cause']}"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**处置建议**\n" + "\n".join(suggestion_lines),
                },
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"taskId：{context['task_id']}",
                    },
                    {
                        "tag": "plain_text",
                        "content": f"procInsId：{context['proc_ins_id']}",
                    },
                    {
                        "tag": "plain_text",
                        "content": f"创建时间：{context['created_at']}",
                    },
                ],
            },
        ]
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
                    "content": f"AI创建处置工单 — {context['device_name']}",
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


def _notify_workorder_created(
    payload: dict[str, Any],
    response_payload: dict[str, Any],
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

    response_data = response_payload.get("data") or {}
    task_id = _safe_str(response_data.get("taskId"))
    proc_ins_id = _safe_str(response_data.get("procInsId"))
    if not task_id and not proc_ins_id:
        return {
            "enabled": True,
            "status": "skipped",
            "reason": "missing_workorder_identifiers",
            "channels": [],
        }

    context = _build_notification_context(payload, response_payload)
    channels: list[dict[str, Any]] = []
    if app_push_url:
        channels.append(
            _send_app_push(
                channel_name="app",
                push_url=app_push_url,
                payload=_build_app_notify_payload(context),
            )
        )
    if dingtalk_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="dingtalk",
                webhook_url=_build_dingtalk_signed_webhook_url(dingtalk_webhook_url),
                payload=_build_dingtalk_notify_payload(context),
                success_predicate=lambda data: str(data.get("errcode", "")) == "0",
            )
        )
    if feishu_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="feishu",
                webhook_url=feishu_webhook_url,
                payload=_build_feishu_notify_payload(context),
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
        if reason == "missing_workorder_identifiers":
            return "— 已跳过（缺少工单编号）"
        return "— 已跳过"
    return "— 未配置"


def _normalize_suggestions(
    suggestions: list[str] | None = None,
    suggestions_json: str | None = None,
) -> list[str]:
    normalized = [_safe_str(item) for item in suggestions or [] if _safe_str(item)]
    if suggestions_json:
        try:
            parsed = json.loads(suggestions_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--suggestions-json 不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("--suggestions-json 必须是字符串数组")
        normalized.extend(_safe_str(item) for item in parsed if _safe_str(item))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in normalized:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    if not deduped:
        raise ValueError("至少提供一条处置建议，请使用 --suggestion 或 --suggestions-json")
    return deduped


def _default_ticket_title(alarm_title: str) -> str:
    title = _safe_str(alarm_title) or "故障"
    return f"AI创建 · {title}人工处置"


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


def build_workorder_payload(args: argparse.Namespace) -> dict[str, Any]:
    suggestions = _normalize_suggestions(args.suggestion, args.suggestions_json)
    alarm_id = _require_alarm_id(args.alarm_id)
    alarm_title = _normalize_ai_alarm_title(_safe_str(args.alarm_title))
    analysis_summary = _safe_str(args.analysis_summary) or "AI 已完成根因分析，自动创建人工处置工单"

    return {
        "chatId": _safe_str(args.chat_id),
        "resId": _safe_str(args.res_id),
        "metricType": _safe_str(args.metric_type) or "mysql",
        "alarm": {
            "alarmId": alarm_id,
            "title": alarm_title,
            "visibleContent": _safe_str(args.visible_content),
            "deviceName": _safe_str(args.device_name),
            "manageIp": _safe_str(args.manage_ip),
            "assetId": _safe_str(args.asset_id),
            "level": _safe_str(args.level),
            "status": _safe_str(args.status),
            "eventTime": _safe_str(args.event_time),
        },
        "analysis": {
            "summary": analysis_summary,
            "rootCause": _safe_str(args.root_cause),
            "suggestions": suggestions,
        },
        "ticket": {
            "title": _safe_str(args.ticket_title) or _default_ticket_title(alarm_title),
            "priority": _safe_str(args.ticket_priority) or DEFAULT_TICKET_PRIORITY,
            "category": _safe_str(args.ticket_category) or DEFAULT_TICKET_CATEGORY,
            "source": _safe_str(args.ticket_source) or DEFAULT_TICKET_SOURCE,
            "externalSystem": _safe_str(args.ticket_external_system) or DEFAULT_EXTERNAL_SYSTEM,
        },
    }


def _should_fallback_to_curl(error: Exception) -> bool:
    return isinstance(error, (requests.RequestException, OSError))


def _curl_post_json(
    *,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as body_file:
        body_file.write(json.dumps(json_payload, ensure_ascii=False).encode("utf-8"))
        body_path = body_file.name

    try:
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(timeout_seconds),
            url,
            "--header",
            f"Content-Type: {headers['Content-Type']}",
            "--header",
            f"SerialNo: {headers['SerialNo']}",
            "--header",
            f"Authorization: {headers['Authorization']}",
            "--data",
            f"@{body_path}",
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass

    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"工单接口返回了非 JSON 内容: {completed.stdout}") from exc


def create_manual_workorder(
    payload: dict[str, Any],
    *,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    base_url = _normalize_base_url(api_base_url)
    auth_token = _get_token(token)
    timeout = _get_timeout(timeout_seconds)
    url = f"{base_url}/flowable/workflow/workOrder/faultManualWorkorders"
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "SerialNo": _build_serial_no(),
        "Authorization": auth_token,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        if not _should_fallback_to_curl(exc):
            raise
        data = _curl_post_json(
            url=url,
            headers=headers,
            json_payload=payload,
            timeout_seconds=timeout,
        )

    if not isinstance(data, dict):
        raise RuntimeError(f"工单接口返回格式异常: {data!r}")
    code = data.get("code")
    if code != 200:
        raise RuntimeError(
            f"工单创建失败: code={code}, msg={data.get('msg') or 'unknown'}"
        )
    data["notification"] = _notify_workorder_created(payload, data)
    return data


def format_markdown_result(payload: dict[str, Any], response: dict[str, Any]) -> str:
    ticket = payload.get("ticket") or {}
    analysis = payload.get("analysis") or {}
    alarm = payload.get("alarm") or {}
    data = response.get("data") or {}
    notification = response.get("notification") or {}
    suggestions = analysis.get("suggestions") or []

    lines = [
        "## AI 创建处置工单结果",
        f"- 工单标题：{ticket.get('title') or '-'}",
        f"- 工单来源：{ticket.get('source') or '-'}",
        f"- 告警流水号：`{alarm.get('alarmId') or ''}`",
        f"- 告警标题：{alarm.get('title') or '-'}",
        f"- 资源 ID（CI ID）：`{payload.get('resId') or ''}`",
        f"- 分析摘要：{analysis.get('summary') or '-'}",
        f"- 根因方向：{analysis.get('rootCause') or '-'}",
        f"- 处置建议：{'；'.join(str(item) for item in suggestions) if suggestions else '-'}",
        f"- procInsId：`{data.get('procInsId') or ''}`",
        f"- taskId：`{data.get('taskId') or ''}`",
        f"- 通知状态：**{_format_notification_status(notification)}**",
        "- 当前状态：已自动调用 4.2 接口创建工单（AI 创建）",
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="创建人工处置工单")
    parser.add_argument("--chat-id", required=True, help="当前故障会话 ID")
    parser.add_argument("--res-id", required=True, help="CMDB CI ID")
    parser.add_argument("--metric-type", default="mysql", help="资源类型，例如 mysql")
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
        "--suggestion",
        action="append",
        default=[],
        help="处置建议，可重复传入多次",
    )
    parser.add_argument(
        "--suggestions-json",
        default="",
        help='JSON 数组格式的处置建议，例如 ["排查长事务","检查阻塞链"]',
    )
    parser.add_argument("--ticket-title", default="", help="工单标题")
    parser.add_argument("--ticket-priority", default=DEFAULT_TICKET_PRIORITY, help="工单优先级")
    parser.add_argument("--ticket-category", default=DEFAULT_TICKET_CATEGORY, help="工单分类")
    parser.add_argument("--ticket-source", default=DEFAULT_TICKET_SOURCE, help="工单来源")
    parser.add_argument(
        "--ticket-external-system",
        default=DEFAULT_EXTERNAL_SYSTEM,
        help="外部工单系统标识",
    )
    parser.add_argument("--api-base-url", default="", help="工单接口基础地址")
    parser.add_argument("--token", default="", help="工单接口 Authorization")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="请求超时秒数")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = build_workorder_payload(args)
        response = create_manual_workorder(
            payload,
            api_base_url=args.api_base_url,
            token=args.token,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(
            json.dumps(
                {
                    "request": payload,
                    "response": response,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_markdown_result(payload, response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
