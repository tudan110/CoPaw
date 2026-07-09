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
    return {"code": code, "msg": message, "total": 0, "rows": []}


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
    """分页拉取全部告警，自动处理分页逻辑。

    get_alarms.py 里的 execute() 一次只查一页（接口本身就是分页返回
    的，一次最多给几十/几百条），如果告警有几千条，Agent 不可能一页一
    页手动去拼。这个函数就是把"翻页"这件重复劳动封装掉：先用
    page_size=1 探一下总数有多少，算出总共要翻多少页，再循环把每一页
    都拉回来拼成一份完整列表，调用方只需要一次调用就能拿到全量数据。
    """
    # 第一次请求只要 1 条（page_size=1），目的不是要数据，而是要接口
    # 返回的 total 字段，用来算总共有多少页需要翻。
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
        return {"code": 200, "msg": "查询成功", "total": 0, "rows": [], "pages": 0, "page_size": page_size}

    # math.ceil 向上取整：比如总共 101 条、每页 100 条，算出来是 2 页
    # （最后一页只有 1 条也要单独算一页，不能直接整除舍掉）。
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
            # 翻到某一页时失败了（比如网络抖动、接口超时），不能让
            # 前面已经拉到的数据白白丢掉，所以把已经拿到的部分数据也
            # 一并带在错误结果里（partial_rows），方便调用方决定是要
            # 直接放弃，还是"能用多少算多少"地继续处理。
            page_result["partial_rows"] = rows
            page_result["partial_count"] = len(rows)
            page_result["failed_page"] = page_num
            page_result["total_pages"] = total_pages
            return page_result

        page_rows = page_result.get("rows") or []
        if not isinstance(page_rows, list):
            return make_error(500, "接口返回格式异常：rows 不是数组")
        rows.extend(page_rows)

    return {"code": 200, "msg": "查询成功", "total": total, "rows": rows, "pages": total_pages, "page_size": page_size}


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
    """按条件过滤告警列表（本地过滤，接口侧过滤用 ne_alias/alarm_status 等参数）。"""
    normalized_keyword = keyword.strip().lower()
    normalized_severity = severity.strip().lower()
    normalized_device_name = device_name.strip().lower()
    normalized_manage_ip = manage_ip.strip().lower()
    normalized_speciality = speciality.strip().lower()
    normalized_region = region.strip().lower()
    normalized_ci_id = ci_id.strip().lower()

    result: List[Dict[str, Any]] = []
    for alarm in alarms:
        if normalized_severity and normalized_severity not in str(alarm.get("alarmseverity", "")).lower() \
                and normalized_severity not in str(alarm.get("alarmSeverityName", "")).lower():
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
    """匹配 CI/网元 ID（兼容 neId / ciId / devId 多个字段）。

    不同批次的数据里，"资源 ID"这个含义可能落在不同字段名下（大小写
    也不统一），所以把常见的几种候选字段都列出来，任意一个匹配上就算
    命中，不要求调用方提前知道具体是哪个字段。
    """
    candidates = (
        alarm.get("neId"),
        alarm.get("ciId"),
        alarm.get("devId"),
        alarm.get("ciid"),
        alarm.get("neid"),
    )
    return any(ci_id == str(value).strip().lower() for value in candidates if value is not None)


def matches_keyword(alarm: Dict[str, Any], keyword: str, keyword_field: str) -> bool:
    """判断一条告警是否命中关键字搜索。

    keyword_field="all" 时会在标题/设备名/管理IP/专业/区域这几个常见
    字段里挨个找（SEARCHABLE_FIELDS），只要有一个字段包含关键字就算
    命中；也可以指定只搜某一个具体字段。
    """
    if not keyword:
        return True
    search_fields = SEARCHABLE_FIELDS if keyword_field == "all" else {keyword_field}
    return any(keyword in str(alarm.get(field, "")).lower() for field in search_fields)


def summarize_groups(counter: Counter, total: int, top_n: int = DEFAULT_TOP_N) -> List[Dict[str, Any]]:
    """把计数器转换成统一分组输出（name / count / ratio）。

    counter.most_common(top_n) 会按数量从高到低排序，只取前 top_n 个，
    避免比如设备有几百种、返回一个巨长的列表。ratio 是这个分组数量
    占总数的百分比，四舍五入保留两位小数。
    """
    groups: List[Dict[str, Any]] = []
    for name, count in counter.most_common(top_n):
        ratio = round((count / total) * 100, 2) if total else 0
        groups.append({"name": name, "count": count, "ratio": ratio})
    return groups


def build_overview(alarms: List[Dict[str, Any]], top_n: int = DEFAULT_TOP_N) -> Dict[str, Any]:
    """生成综合概览（summary 模式使用）。

    一次性算出好几种维度的统计：按级别/状态/标题/设备/专业/区域分组
    的 Top N，加上"严重告警"和"活跃告警"各自的数量、占比和预览列表。
    这样 Agent 一次调用就能拿到全部维度，不需要为了看不同维度反复调用
    脚本。
    """
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
    """从原始告警字典里只挑出适合展示给用户的字段，组成表格行。

    接口原始返回的字段远不止这些（还有很多内部字段、调试字段），直接
    全部展示会让聊天窗口的表格又长又难读，所以这里做了一次"精简"，
    只保留标题、级别、设备、IP、发生时间等对用户有意义的信息。
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


def analyze_by_mode(
    mode: str,
    alarms: List[Dict[str, Any]],
    top_n: int = DEFAULT_TOP_N,
    include_alarms: bool = False,
) -> Dict[str, Any]:
    """根据 --mode 参数分析告警，返回结构化结果供 Markdown 渲染器使用。

    这是整个分析脚本的调度中心：summary 走综合概览；severity/title/
    device/speciality/region 走"按某个字段分组统计"的统一逻辑；search
    是纯列表匹配，不做分组。不同 mode 返回的字典结构不完全一样（比如
    summary 模式的 summary 字段是个大字典，其他分组模式的 summary 字段
    只有 total_alarms + groups），调用方（markdown_renderer.py）需要
    按 mode 分别处理。
    """
    total = len(alarms)

    if mode == "summary":
        return {"mode": mode, "summary": build_overview(alarms, top_n), "rows": []}

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
            "summary": {"total_alarms": total, "groups": summarize_groups(counter, total, top_n)},
            "rows": _build_alarm_rows(alarms[:top_n]) if include_alarms else [],
        }

    if mode == "search":
        return {
            "mode": mode,
            "summary": {"matched_count": total},
            "rows": _build_alarm_rows(alarms if include_alarms else alarms[:top_n]),
        }

    return make_error(400, f"不支持的 mode: {mode}")
