#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警数据分析模块"""

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from get_alarms import execute


SEARCHABLE_FIELDS = {"alarmtitle", "devName", "manageIp", "speciality", "alarmregion"}
DEFAULT_FETCH_PAGE_SIZE = 100
DEFAULT_TOP_N = 10


def make_error(code: int, message: str) -> Dict[str, Any]:
    """构造统一错误响应。"""
    return {
        "code": code,
        "msg": message,
        "total": 0,
        "rows": [],
    }


def fetch_all_alarms(
    token: str,
    api_base_url: Optional[str],
    page_size: int = DEFAULT_FETCH_PAGE_SIZE,
    begin_time: Optional[str] = None,
    end_time: Optional[str] = None,
    alarm_severitys: Optional[List[str]] = None,
    alarm_status: Optional[str] = None,
    cities: Optional[List[str]] = None,
    ci_id: Optional[str] = None,
    ne_alias: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> Dict[str, Any]:
    """分页获取全部告警。"""
    first_page = execute(
        page_num=1,
        page_size=1,
        token=token,
        api_base_url=api_base_url,
        begin_time=begin_time,
        end_time=end_time,
        alarm_severitys=alarm_severitys,
        alarm_status=alarm_status,
        cities=cities,
        ci_id=ci_id,
        ne_alias=ne_alias,
        resource_type=resource_type,
    )
    if first_page.get("code") != 200:
        return first_page

    total = int(first_page.get("total") or 0)
    if total == 0:
        return {
            "code": 200,
            "msg": "查询成功",
            "total": 0,
            "rows": [],
            "pages": 0,
            "page_size": page_size,
        }

    total_pages = math.ceil(total / page_size)
    rows: List[Dict[str, Any]] = []

    for page_num in range(1, total_pages + 1):
        page_result = execute(
            page_num=page_num,
            page_size=page_size,
            token=token,
            api_base_url=api_base_url,
            begin_time=begin_time,
            end_time=end_time,
            alarm_severitys=alarm_severitys,
            alarm_status=alarm_status,
            cities=cities,
            ci_id=ci_id,
            ne_alias=ne_alias,
            resource_type=resource_type,
        )
        if page_result.get("code") != 200:
            page_result["partial_rows"] = rows
            page_result["partial_count"] = len(rows)
            page_result["failed_page"] = page_num
            page_result["total_pages"] = total_pages
            return page_result

        page_rows = page_result.get("rows") or []
        if not isinstance(page_rows, list):
            return make_error(500, "接口返回格式异常：rows 不是数组")
        rows.extend(page_rows)

    return {
        "code": 200,
        "msg": "查询成功",
        "total": total,
        "rows": rows,
        "pages": total_pages,
        "page_size": page_size,
    }


def apply_filters(
    alarms: Iterable[Dict[str, Any]],
    keyword: str = "",
    keyword_field: str = "all",
    severity: str = "",
    device_name: str = "",
    manage_ip: str = "",
    speciality: str = "",
    region: str = "",
    ci_id: str = "",
) -> List[Dict[str, Any]]:
    """按条件过滤告警。"""
    normalized_keyword = keyword.strip().lower()
    normalized_severity = severity.strip().lower()
    normalized_device_name = device_name.strip().lower()
    normalized_manage_ip = manage_ip.strip().lower()
    normalized_speciality = speciality.strip().lower()
    normalized_region = region.strip().lower()
    normalized_ci_id = ci_id.strip().lower()

    result: List[Dict[str, Any]] = []
    for alarm in alarms:
        if normalized_severity and normalized_severity not in str(alarm.get("alarmseverity", "")).lower() and normalized_severity not in str(alarm.get("alarmSeverityName", "")).lower():
            continue
        if normalized_device_name and normalized_device_name not in str(alarm.get("devName", "")).lower():
            continue
        if normalized_manage_ip and normalized_manage_ip not in str(alarm.get("manageIp", "")).lower():
            continue
        if normalized_speciality and normalized_speciality not in str(alarm.get("speciality", "")).lower():
            continue
        if normalized_region and normalized_region not in str(alarm.get("alarmregion", "")).lower():
            continue
        if normalized_ci_id and not matches_ci_id(alarm, normalized_ci_id):
            continue
        if normalized_keyword and not matches_keyword(alarm, normalized_keyword, keyword_field):
            continue
        result.append(alarm)
    return result


def matches_ci_id(alarm: Dict[str, Any], ci_id: str) -> bool:
    """匹配 CI/网元 ID。"""
    candidates = (
        alarm.get("neId"),
        alarm.get("ciId"),
        alarm.get("devId"),
        alarm.get("ciid"),
        alarm.get("neid"),
    )
    return any(ci_id == str(value).strip().lower() for value in candidates if value is not None)


def matches_keyword(alarm: Dict[str, Any], keyword: str, keyword_field: str) -> bool:
    """匹配关键字。"""
    if not keyword:
        return True

    if keyword_field == "all":
        search_fields = SEARCHABLE_FIELDS
    else:
        search_fields = {keyword_field}

    return any(keyword in str(alarm.get(field, "")).lower() for field in search_fields)


def summarize_groups(counter: Counter[str], total: int, top_n: int = DEFAULT_TOP_N) -> List[Dict[str, Any]]:
    """把计数器转换成统一分组输出。"""
    groups: List[Dict[str, Any]] = []
    for name, count in counter.most_common(top_n):
        ratio = round((count / total) * 100, 2) if total else 0
        groups.append(
            {
                "name": name,
                "count": count,
                "ratio": ratio,
            }
        )
    return groups


def build_overview(alarms: List[Dict[str, Any]], top_n: int = DEFAULT_TOP_N) -> Dict[str, Any]:
    """生成综合概览。"""
    total = len(alarms)
    severity_counter = Counter(alarm["alarmSeverityName"] for alarm in alarms)
    status_counter = Counter(alarm["alarmStatusName"] for alarm in alarms)
    title_counter = Counter(str(alarm.get("alarmtitle") or "未标注") for alarm in alarms)
    device_counter = Counter(str(alarm.get("devName") or "未标注") for alarm in alarms)
    speciality_counter = Counter(str(alarm.get("speciality") or "未标注") for alarm in alarms)
    region_counter = Counter(str(alarm.get("alarmregion") or "未标注") for alarm in alarms)
    critical_alarms = [alarm for alarm in alarms if str(alarm.get("alarmseverity")) == "1"]
    active_alarms = [alarm for alarm in alarms if str(alarm.get("alarmstatus")) == "1"]

    critical_count = len(critical_alarms)
    active_count = len(active_alarms)

    return {
        "total_alarms": total,
        "critical_count": critical_count,
        "critical_ratio": round((critical_count / total) * 100, 2) if total else 0,
        "active_count": active_count,
        "active_ratio": round((active_count / total) * 100, 2) if total else 0,
        "severity_distribution": summarize_groups(severity_counter, total, top_n),
        "status_distribution": summarize_groups(status_counter, total, top_n),
        "title_distribution": summarize_groups(title_counter, total, top_n),
        "device_distribution": summarize_groups(device_counter, total, top_n),
        "speciality_distribution": summarize_groups(speciality_counter, total, top_n),
        "region_distribution": summarize_groups(region_counter, total, top_n),
        "critical_alarms_preview": _build_alarm_rows(critical_alarms[:top_n]),
        "active_alarms_preview": _build_alarm_rows(active_alarms[:top_n]),
    }


def _build_alarm_rows(alarms: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def analyze_by_mode(
    mode: str,
    alarms: List[Dict[str, Any]],
    top_n: int = DEFAULT_TOP_N,
    include_alarms: bool = False,
) -> Dict[str, Any]:
    """根据模式分析告警"""
    total = len(alarms)

    if mode == "summary":
        return {
            "mode": mode,
            "summary": build_overview(alarms, top_n),
            "rows": [],  # summary 模式不需要返回所有告警
        }

    field_getter_map = {
        "severity": lambda alarm: alarm["alarmSeverityName"],
        "title": lambda alarm: str(alarm.get("alarmtitle") or "未标注"),
        "device": lambda alarm: str(alarm.get("devName") or "未标注"),
        "speciality": lambda alarm: str(alarm.get("speciality") or "未标注"),
        "region": lambda alarm: str(alarm.get("alarmregion") or "未标注"),
        "status": lambda alarm: alarm["alarmStatusName"],
    }

    if mode in field_getter_map:
        counter = Counter(field_getter_map[mode](alarm) for alarm in alarms)
        return {
            "mode": mode,
            "summary": {
                "total_alarms": total,
                "groups": summarize_groups(counter, total, top_n),
            },
            "rows": _build_alarm_rows(alarms[:top_n]) if include_alarms else [],
        }

    if mode == "search":
        return {
            "mode": mode,
            "summary": {
                "matched_count": total,
            },
            "rows": _build_alarm_rows(alarms if include_alarms else alarms[:top_n]),
        }

    return make_error(400, f"不支持的 mode: {mode}")
