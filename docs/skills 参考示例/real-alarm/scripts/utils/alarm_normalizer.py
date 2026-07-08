#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警数据规范化模块：枚举值 → 可读中文名称

接口返回的原始数据里，很多字段是给机器看的枚举代号（数字或英文
key），比如 alarmseverity="1"、alarmclass="sys_log"，直接展示给用户
会看不懂。这个模块的职责就是给每条告警"翻译"出人类可读的中文字段，
不改动、不删除原始字段（方便调用方仍能拿到原始值做精确匹配）。
"""

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
    """数字级别 → 中文（查不到映射就原样返回，兜底显示"未知"）。"""
    return ALARM_SEVERITY_MAP.get(str(value), str(value) or "未知")


def map_alarm_status(value: Optional[str]) -> str:
    """数字状态 → 中文。"""
    return ALARM_STATUS_MAP.get(str(value), str(value) or "未知")


def map_alarm_class(value: Optional[str]) -> str:
    """英文类别代号 → 中文。"""
    return ALARM_CLASS_MAP.get(str(value), str(value) or "未知")


def normalize_alarm(alarm: Dict[str, Any]) -> Dict[str, Any]:
    """为单条告警补充规范化字段（不修改原始字段）。

    先复制一份原始字典（dict(alarm)），再往新字典里加 *Name 结尾的
    可读字段，这样调用方既能拿到原始的 alarmseverity="1" 用于精确
    匹配/过滤，也能拿到 alarmSeverityName="紧急" 直接展示给用户。
    """
    normalized = dict(alarm)
    normalized["alarmSeverityName"] = map_alarm_severity(alarm.get("alarmseverity"))
    normalized["alarmStatusName"] = map_alarm_status(alarm.get("alarmstatus"))
    normalized["alarmClassName"] = map_alarm_class(alarm.get("alarmclass"))
    return normalized


def normalize_alarms(alarms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """对一批告警批量做 normalize_alarm。"""
    return [normalize_alarm(alarm) for alarm in alarms]


def build_alarm_rows(alarms: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """提取告警关键字段，适合表格展示。

    和 alarm_analyzer.py 里的 _build_alarm_rows() 是同一个思路的重复
    实现（历史遗留，两处都需要"精简字段"这个能力）：只保留标题、级别、
    设备、IP、发生时间等对用户有意义的字段，屏蔽掉内部/调试字段。
    """
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
