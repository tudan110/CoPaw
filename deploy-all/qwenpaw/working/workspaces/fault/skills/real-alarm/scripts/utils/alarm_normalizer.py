#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警数据规范化模块"""

from typing import Any, Dict, Iterable, List, Optional

ALARM_SEVERITY_MAP = {
    "1": "严重",
    "2": "重要",
    "3": "一般",
    "4": "提示",
}

ALARM_STATUS_MAP = {
    "0": "自动清除",
    "1": "活跃",
    "2": "同步清除",
    "3": "手工清除",
}

ALARM_CLASS_MAP = {
    "sys_log": "设备告警",
    "threshold": "性能告警",
    "derivative": "衍生告警",
}

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
    """映射告警级别"""
    return ALARM_SEVERITY_MAP.get(str(value), str(value) or "未知")


def map_alarm_status(value: Optional[str]) -> str:
    """映射告警状态"""
    return ALARM_STATUS_MAP.get(str(value), str(value) or "未知")


def map_alarm_class(value: Optional[str]) -> str:
    """映射告警类别"""
    return ALARM_CLASS_MAP.get(str(value), str(value) or "未知")


def normalize_alarm(alarm: Dict[str, Any]) -> Dict[str, Any]:
    """规范化单个告警"""
    normalized = dict(alarm)
    normalized["alarmSeverityName"] = map_alarm_severity(alarm.get("alarmseverity"))
    normalized["alarmStatusName"] = map_alarm_status(alarm.get("alarmstatus"))
    normalized["alarmClassName"] = map_alarm_class(alarm.get("alarmclass"))
    return normalized


def normalize_alarms(alarms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量规范化告警"""
    return [normalize_alarm(alarm) for alarm in alarms]


def build_alarm_rows(alarms: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """提取常用输出字段。"""
    rows: List[Dict[str, Any]] = []
    for alarm in alarms:
        rows.append(
            {
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
            }
        )
    return rows
