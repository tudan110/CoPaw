# -*- coding: utf-8 -*-
"""Capability field catalogs and field-name normalization helpers.

Ported from the legacy monolith (``ai_big_screen_service.py``) so both
the L2 fetchers and the L3 orchestrator can resolve user/LLM supplied
field names (labels, aliases) onto canonical row keys.
"""
from __future__ import annotations

import re
from typing import Any

CAPABILITY_FIELD_DEFINITIONS: dict[str, list[dict[str, Any]]] = {
    "system-logs": [
        {"key": "time", "label": "时间", "aliases": ["日志时间", "发生时间"]},
        {"key": "level", "label": "级别", "aliases": ["日志级别"]},
        {"key": "host", "label": "主机", "aliases": ["机器", "节点"]},
        {"key": "service", "label": "服务", "aliases": ["应用", "系统"]},
        {"key": "message", "label": "日志内容", "aliases": ["内容", "消息"]},
    ],
    "real-alarms": [
        {
            "key": "eventTime",
            "label": "时间",
            "aliases": ["告警时间", "发生时间"],
        },
        {
            "key": "level",
            "label": "级别",
            "aliases": ["告警级别", "严重级别"],
        },
        {"key": "title", "label": "告警", "aliases": ["告警标题", "标题"]},
        {
            "key": "deviceName",
            "label": "资源",
            "aliases": ["设备", "对象"],
        },
        {"key": "manageIp", "label": "IP", "aliases": ["管理IP", "资源IP"]},
    ],
    "cmdb-resources": [
        {"key": "name", "label": "指标", "aliases": ["名称", "资源指标"]},
        {"key": "value", "label": "值", "aliases": ["数量", "指标值"]},
    ],
    "workorders": [
        {
            "key": "workorderNo",
            "label": "工单号",
            "aliases": ["工单编号", "编号"],
        },
        {"key": "title", "label": "标题", "aliases": ["工单标题", "名称"]},
        {
            "key": "status",
            "label": "状态",
            "aliases": ["工单状态", "处理状态"],
        },
        {
            "key": "severity",
            "label": "级别",
            "aliases": ["优先级", "严重级别"],
        },
        {
            "key": "eventTime",
            "label": "时间",
            "aliases": ["创建时间", "接收时间"],
        },
        {
            "key": "starter",
            "label": "流程发起人",
            "aliases": ["发起人", "startUserName"],
        },
        {
            "key": "taskName",
            "label": "任务节点",
            "aliases": ["当前节点", "流程节点"],
        },
        {
            "key": "processName",
            "label": "流程名称",
            "aliases": ["工单流程名称"],
        },
        {"key": "taskId", "label": "任务编号", "aliases": ["任务ID"]},
        {
            "key": "procInsId",
            "label": "流程实例",
            "aliases": ["流程实例ID"],
        },
    ],
}

DEFAULT_CAPABILITY_FIELDS: dict[str, list[str]] = {
    "system-logs": ["time", "level", "host", "service", "message"],
    "real-alarms": ["eventTime", "level", "title", "deviceName", "manageIp"],
    "cmdb-resources": ["name", "value"],
    "workorders": ["workorderNo", "title", "status", "severity", "eventTime"],
}


def coerce_field_values(raw_fields: Any) -> list[str]:
    """Split a fields payload (list or delimited string) into tokens."""
    if isinstance(raw_fields, str):
        values = re.split(r"[,，、\s]+", raw_fields)
    elif isinstance(raw_fields, list):
        values = [str(item) for item in raw_fields]
    else:
        values = []
    normalized: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def resolve_capability_field_key(capability_id: str, value: str) -> str:
    """Map a key/label/alias spelling onto the canonical field key."""
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    lowered = candidate.lower()
    for field in CAPABILITY_FIELD_DEFINITIONS.get(capability_id, []):
        key = str(field.get("key") or "")
        label = str(field.get("label") or "")
        aliases = [
            str(item) for item in field.get("aliases", []) if str(item).strip()
        ]
        if lowered == key.lower() or candidate == label:
            return key
        if any(
            lowered == alias.lower() or candidate == alias for alias in aliases
        ):
            return key
    return ""


def normalize_capability_fields(
    capability_id: str,
    raw_fields: Any,
    *,
    fallback: list[str] | None = None,
) -> list[str]:
    """Resolve requested fields to canonical keys, with safe fallback."""
    normalized: list[str] = []
    for value in coerce_field_values(raw_fields):
        key = resolve_capability_field_key(capability_id, value)
        if key and key not in normalized:
            normalized.append(key)
    if normalized:
        return normalized
    allowed_keys = {
        str(field.get("key") or "")
        for field in CAPABILITY_FIELD_DEFINITIONS.get(capability_id, [])
    }
    return [field for field in list(fallback or []) if field in allowed_keys]


def default_capability_fields(capability_id: str) -> list[str]:
    return list(DEFAULT_CAPABILITY_FIELDS.get(capability_id, []))


def columns_for_capability_fields(
    capability_id: str,
    raw_fields: Any,
) -> list[dict[str, str]]:
    """Build ``[{key, label}]`` columns for the requested fields."""
    field_keys = normalize_capability_fields(
        capability_id,
        raw_fields,
        fallback=default_capability_fields(capability_id),
    )
    columns: list[dict[str, str]] = []
    for key in field_keys:
        for field in CAPABILITY_FIELD_DEFINITIONS.get(capability_id, []):
            if str(field.get("key") or "") == key:
                columns.append(
                    {"key": key, "label": str(field.get("label") or key)},
                )
                break
    return columns


def safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
