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
        {"key": "title", "label": "告警标题", "aliases": ["告警", "标题"]},
        {
            "key": "levelName",
            "label": "级别",
            "aliases": ["告警级别", "严重级别", "level"],
        },
        {
            "key": "deviceName",
            "label": "设备名称",
            "aliases": ["设备", "资源", "对象"],
        },
        {"key": "manageIp", "label": "管理IP", "aliases": ["IP", "资源IP"]},
        {
            "key": "ciId",
            "label": "CI ID",
            "aliases": ["CIID", "neId", "资源ID", "配置项"],
        },
        {
            "key": "eventTime",
            "label": "告警发生时间",
            "aliases": ["告警时间", "发生时间", "时间"],
        },
        {
            "key": "statusName",
            "label": "告警状态",
            "aliases": ["状态", "告警状态名"],
        },
        {
            "key": "className",
            "label": "告警类别",
            "aliases": ["类别", "告警类型"],
        },
        {
            "key": "speciality",
            "label": "专业",
            "aliases": ["专业分类", "专业领域"],
        },
        {"key": "region", "label": "区域", "aliases": ["告警区域", "地域"]},
        {
            "key": "eventLastTime",
            "label": "最近发生",
            "aliases": ["最后发生时间", "持续至"],
        },
        {"key": "count", "label": "触发次数", "aliases": ["次数", "告警次数"]},
    ],
    "cmdb-resources": [
        # "name"/"value" kept as aliases so screens saved before the
        # typed-column upgrade still resolve onto real columns.
        {
            "key": "type",
            "label": "资源类型",
            "aliases": ["name", "名称", "类型", "资源指标", "指标"],
        },
        {
            "key": "total",
            "label": "总数",
            "aliases": ["value", "数量", "值", "指标值"],
        },
        {"key": "normal", "label": "正常", "aliases": ["正常数", "健康"]},
        {"key": "alarm", "label": "告警", "aliases": ["告警数", "异常"]},
    ],
    "cmdb-applications": [
        {
            "key": "name",
            "label": "应用名称",
            "aliases": ["应用", "名称", "应用系统", "系统名称"],
        },
        {
            "key": "ciId",
            "label": "CI ID",
            "aliases": ["CIID", "配置项ID", "资源ID", "id"],
        },
        {"key": "appType", "label": "应用类型", "aliases": ["类型"]},
        {
            "key": "status",
            "label": "应用状态",
            "aliases": ["状态", "在线状态", "运行状态"],
        },
        {"key": "alarmStatus", "label": "告警状态", "aliases": ["告警"]},
        {"key": "level", "label": "等级", "aliases": ["级别", "重要等级"]},
        {
            "key": "opDuty",
            "label": "运维负责人",
            "aliases": ["负责人", "运维人员", "责任人"],
        },
        {
            "key": "installDate",
            "label": "纳管时间",
            "aliases": ["接入时间", "安装时间", "创建时间"],
        },
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
    "real-alarms": [
        "title",
        "levelName",
        "deviceName",
        "manageIp",
        "ciId",
        "eventTime",
        "statusName",
    ],
    "cmdb-resources": ["type", "total", "normal", "alarm"],
    "cmdb-applications": [
        "name",
        "ciId",
        "appType",
        "status",
        "alarmStatus",
        "level",
        "opDuty",
        "installDate",
    ],
    "workorders": ["workorderNo", "title", "status", "severity", "eventTime"],
    "self-monitor-overview": ["layer", "status", "detail"],
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
        aliases = [str(item) for item in field.get("aliases", []) if str(item).strip()]
        if lowered == key.lower() or candidate == label:
            return key
        if any(lowered == alias.lower() or candidate == alias for alias in aliases):
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
    """Coerce ``value`` to ``int``, returning ``fallback`` when it can't."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
