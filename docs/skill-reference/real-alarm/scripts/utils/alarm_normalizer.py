#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警数据规范化模块：枚举值 → 可读中文名称"""

from typing import Any, Dict, Iterable, List, Optional

# 告警级别：接口返回数字，展示时转为中文
ALARM_SEVERITY_MAP = {
    "1": "紧急",
    "2": "严重",
    "3": "普通",
    "4": "预警",
}

# 告警状态：接口返回数字，展示时转为中文
ALARM_STATUS_MAP = {
    "0": "自动清除",
    "1": "活跃",
    "2": "同步清除",
    "3": "手工清除",
}

# 告警类别：接口返回英文 key，展示时转为中文
ALARM_CLASS_MAP = {
    "sys_log": "设备告警",
    "threshold": "性能告警",
    "derivative": "衍生告警",
}

# 对外展示字段的中文标签（供渲染层参考）
FIELD_LABELS = {
    "alarmuniqueid": "告警ID",
    "alarmtitle": "告警标题",
    "alarmseverity": "告警级别",
    "devName": "设备名称",
    "devId": "资源ID",
    "manageIp": "管理IP",
    "neId": "CI ID",
    "eventtime": "告警发生时间",
    "speciality": "专业",
    "alarmregion": "区域",
    "alarmstatus": "告警状态",
    "alarmclass": "告警类别",
}


def map_alarm_severity(value: Optional[str]) -> str:
    return ALARM_SEVERITY_MAP.get(str(value), str(value) or "未知")


def map_alarm_status(value: Optional[str]) -> str:
    return ALARM_STATUS_MAP.get(str(value), str(value) or "未知")


def map_alarm_class(value: Optional[str]) -> str:
    return ALARM_CLASS_MAP.get(str(value), str(value) or "未知")


def normalize_alarm(alarm: Dict[str, Any]) -> Dict[str, Any]:
    """为单条告警补充规范化字段（不修改原始字段）。"""
    normalized = dict(alarm)
    normalized["alarmSeverityName"] = map_alarm_severity(alarm.get("alarmseverity"))
    normalized["alarmStatusName"] = map_alarm_status(alarm.get("alarmstatus"))
    normalized["alarmClassName"] = map_alarm_class(alarm.get("alarmclass"))
    return normalized


def normalize_alarms(alarms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [normalize_alarm(alarm) for alarm in alarms]


def build_alarm_rows(alarms: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """提取告警关键字段，适合表格展示。"""
    rows: List[Dict[str, Any]] = []
    for alarm in alarms:
        rows.append({
            "alarmuniqueid": alarm.get("alarmuniqueid") or "-",
            "alarmtitle": alarm.get("alarmtitle") or "-",
            "alarmSeverityName": alarm.get("alarmSeverityName") or "-",
            "devName": alarm.get("devName") or "-",
            "manageIp": alarm.get("manageIp") or "-",
            "neId": alarm.get("neId") or alarm.get("ciId") or alarm.get("devId") or "-",
            "eventtime": alarm.get("eventtime") or "-",
            "speciality": alarm.get("speciality") or "-",
            "alarmregion": alarm.get("alarmregion") or "-",
            "alarmStatusName": alarm.get("alarmStatusName") or "-",
        })
    return rows
