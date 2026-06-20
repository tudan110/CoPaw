#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备统一汇总脚本

使用方式:
    python3 analyze_devices.py --mode summary
    python3 analyze_devices.py --mode vendor
    python3 analyze_devices.py --mode search --keyword core

说明:
    - 统一拉取全部设备后做本地过滤、分组和汇总
    - 优先环境变量/共享 secrets，回退 skill 目录下的 .env 文件
    - 配置项：INOE_API_BASE_URL（API 基础地址）、INOE_API_TOKEN（认证令牌）
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from get_devices import execute, get_token

DEFAULT_FETCH_PAGE_SIZE = 100
DEFAULT_TOP_N = 10
DEFAULT_MARKDOWN_DEVICE_LIMIT = 20

VENDOR_MAP = {
    "HW": "华为",
    "ZX": "中兴",
    "H3": "H3C",
}

DEVICE_TYPE_MAP = {
    "route": "路由器",
    "switch": "交换机",
}

DEVICE_STATUS_MAP = {
    "online": "在线",
    "offline": "离线",
}

RESOURCE_STATUS_MAP = {
    "normal": "正常",
    "abnormal": "异常",
}

FIELD_LABELS = {
    "devName": "设备名称",
    "manageIp": "管理IP",
    "vendorId": "厂商",
    "modelId": "型号",
    "devClass": "类型",
    "delStatus": "设备状态",
    "resStatus": "资源状态",
    "accessTime": "最后访问时间",
}

SEARCHABLE_FIELDS = {"devName", "manageIp", "vendorId", "modelId", "devClass", "delStatus", "resStatus"}
ALLOWED_MODES = {
    "summary",
    "status",
    "resource-status",
    "vendor",
    "model",
    "type",
    "abnormal",
    "search",
}
ALLOWED_OUTPUTS = {"json", "markdown", "markdown-echarts-only"}


def make_error(code: int, message: str) -> Dict[str, Any]:
    """构造统一错误响应。"""
    return {
        "code": code,
        "msg": message,
        "total": 0,
        "rows": [],
    }


def map_vendor(value: Optional[str]) -> str:
    return VENDOR_MAP.get((value or "").strip(), (value or "其他").strip() or "其他")


def map_device_type(value: Optional[str]) -> str:
    return DEVICE_TYPE_MAP.get((value or "").strip(), (value or "其他类型").strip() or "其他类型")


def map_device_status(value: Optional[str]) -> str:
    return DEVICE_STATUS_MAP.get((value or "").strip(), (value or "未知").strip() or "未知")


def map_resource_status(value: Optional[str]) -> str:
    return RESOURCE_STATUS_MAP.get((value or "").strip(), (value or "未知").strip() or "未知")


def normalize_device(device: Dict[str, Any]) -> Dict[str, Any]:
    """补充常用可读字段，便于统一分析。"""
    normalized = dict(device)
    normalized["vendorName"] = map_vendor(device.get("vendorId"))
    normalized["deviceTypeName"] = map_device_type(device.get("devClass"))
    normalized["deviceStatusName"] = map_device_status(device.get("delStatus"))
    normalized["resourceStatusName"] = map_resource_status(device.get("resStatus"))
    return normalized


def fetch_all_devices(token: str, api_base_url: Optional[str], page_size: int) -> Dict[str, Any]:
    """分页获取全部设备。"""
    first_page = execute(page_num=1, page_size=1, token=token, api_base_url=api_base_url)
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
    devices: Iterable[Dict[str, Any]],
    keyword: str,
    keyword_field: str,
    vendor: str,
    model: str,
    device_type: str,
    status: str,
    resource_status: str,
) -> List[Dict[str, Any]]:
    """按条件过滤设备。"""
    normalized_keyword = keyword.strip().lower()
    normalized_vendor = vendor.strip().lower()
    normalized_model = model.strip().lower()
    normalized_type = device_type.strip().lower()
    normalized_status = status.strip().lower()
    normalized_resource_status = resource_status.strip().lower()

    result: List[Dict[str, Any]] = []
    for device in devices:
        if normalized_vendor and normalized_vendor not in str(device.get("vendorId", "")).lower() and normalized_vendor not in str(device.get("vendorName", "")).lower():
            continue
        if normalized_model and normalized_model not in str(device.get("modelId", "")).lower():
            continue
        if normalized_type and normalized_type not in str(device.get("devClass", "")).lower() and normalized_type not in str(device.get("deviceTypeName", "")).lower():
            continue
        if normalized_status and normalized_status not in str(device.get("delStatus", "")).lower() and normalized_status not in str(device.get("deviceStatusName", "")).lower():
            continue
        if normalized_resource_status and normalized_resource_status not in str(device.get("resStatus", "")).lower() and normalized_resource_status not in str(device.get("resourceStatusName", "")).lower():
            continue
        if normalized_keyword and not matches_keyword(device, normalized_keyword, keyword_field):
            continue
        result.append(device)
    return result


def matches_keyword(device: Dict[str, Any], keyword: str, keyword_field: str) -> bool:
    """匹配关键字。"""
    if not keyword:
        return True

    if keyword_field == "all":
        search_fields = SEARCHABLE_FIELDS
    else:
        search_fields = {keyword_field}

    return any(keyword in str(device.get(field, "")).lower() for field in search_fields)


def summarize_groups(counter: Counter[str], total: int, top_n: int) -> List[Dict[str, Any]]:
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


def build_overview(devices: List[Dict[str, Any]], top_n: int) -> Dict[str, Any]:
    """生成综合概览。"""
    total = len(devices)
    status_counter = Counter(device["deviceStatusName"] for device in devices)
    resource_status_counter = Counter(device["resourceStatusName"] for device in devices)
    vendor_counter = Counter(device["vendorName"] for device in devices)
    model_counter = Counter(str(device.get("modelId") or "未标注") for device in devices)
    type_counter = Counter(device["deviceTypeName"] for device in devices)
    abnormal_devices = [device for device in devices if str(device.get("resStatus", "")).lower() == "abnormal"]
    offline_devices = [device for device in devices if str(device.get("delStatus", "")).lower() == "offline"]

    online_count = status_counter.get("在线", 0)
    abnormal_count = len(abnormal_devices)

    return {
        "total_devices": total,
        "online_count": online_count,
        "offline_count": len(offline_devices),
        "online_ratio": round((online_count / total) * 100, 2) if total else 0,
        "abnormal_count": abnormal_count,
        "abnormal_ratio": round((abnormal_count / total) * 100, 2) if total else 0,
        "status_distribution": summarize_groups(status_counter, total, top_n),
        "resource_status_distribution": summarize_groups(resource_status_counter, total, top_n),
        "vendor_distribution": summarize_groups(vendor_counter, total, top_n),
        "model_distribution": summarize_groups(model_counter, total, top_n),
        "type_distribution": summarize_groups(type_counter, total, top_n),
        "abnormal_devices_preview": build_device_rows(abnormal_devices[:top_n]),
        "offline_devices_preview": build_device_rows(offline_devices[:top_n]),
    }


def build_device_rows(devices: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """提取常用输出字段。"""
    rows: List[Dict[str, Any]] = []
    for device in devices:
        rows.append(
            {
                "devName": device.get("devName") or "-",
                "manageIp": device.get("manageIp") or "-",
                "vendorName": device.get("vendorName") or "-",
                "modelId": device.get("modelId") or "-",
                "deviceTypeName": device.get("deviceTypeName") or "-",
                "deviceStatusName": device.get("deviceStatusName") or "-",
                "resourceStatusName": device.get("resourceStatusName") or "-",
                "accessTime": device.get("accessTime") or "-",
            }
        )
    return rows


def _format_percent(value: Any) -> str:
    """格式化百分比。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0%"

    if numeric.is_integer():
        return f"{int(numeric)}%"
    return f"{numeric:.2f}%"


def _build_markdown_table(rows: List[Dict[str, Any]], columns: List[tuple[str, str]]) -> str:
    """把字典列表渲染成 Markdown 表格。"""
    if not rows:
        return "暂无数据。"

    header = "| " + " | ".join(label for _, label in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append(
            "| " + " | ".join(str(row.get(key, "-")).replace("\n", " ") for key, _ in columns) + " |"
        )
    return "\n".join([header, separator, *body])


def _build_preview_rows(rows: List[Dict[str, Any]], limit: int = DEFAULT_MARKDOWN_DEVICE_LIMIT) -> List[Dict[str, Any]]:
    """限制 Markdown 展示条数。"""
    return rows[:limit]


def _build_truncation_note(total: int, shown: int) -> str:
    """生成截断提示。"""
    if total <= shown:
        return ""
    return f"\n\n仅展示前 **{shown}** 条，实际共 **{total}** 条。"


def _build_summary_conclusions(summary: Dict[str, Any]) -> List[str]:
    """生成综合概览结论。"""
    conclusions: List[str] = []

    vendor_distribution = summary.get("vendor_distribution", []) or []
    model_distribution = summary.get("model_distribution", []) or []
    online_ratio = float(summary.get("online_ratio", 0) or 0)
    abnormal_count = int(summary.get("abnormal_count", 0) or 0)
    total_devices = int(summary.get("total_devices", 0) or 0)

    if vendor_distribution:
        top_vendor = vendor_distribution[0]
        conclusions.append(
            f"设备主要集中在 **{top_vendor['name']}**，共 **{top_vendor['count']}** 台，占比 **{_format_percent(top_vendor['ratio'])}**。"
        )

    if model_distribution:
        top_model = model_distribution[0]
        conclusions.append(
            f"出现最多的型号是 **{top_model['name']}**，共 **{top_model['count']}** 台。"
        )

    if total_devices:
        if online_ratio >= 99:
            conclusions.append("当前设备整体在线情况较好，几乎全部在线。")
        elif online_ratio >= 90:
            conclusions.append(f"当前在线率为 **{_format_percent(online_ratio)}**，整体状态较稳定。")
        else:
            conclusions.append(f"当前在线率为 **{_format_percent(online_ratio)}**，建议优先关注离线设备。")

        if abnormal_count == 0:
            conclusions.append("当前未发现资源状态异常设备。")
        else:
            conclusions.append(f"当前存在 **{abnormal_count}** 台资源异常设备，建议优先排查。")

    return conclusions


def _build_group_conclusion(mode: str, groups: List[Dict[str, Any]]) -> Optional[str]:
    """生成分布类模式的结论。"""
    if not groups:
        return None

    top_group = groups[0]
    label_map = {
        "status": "设备状态",
        "resource-status": "资源状态",
        "vendor": "厂商",
        "model": "型号",
        "type": "设备类型",
    }
    prefix = label_map.get(mode, "分组")
    return f"{prefix}中占比最高的是 **{top_group['name']}**，共 **{top_group['count']}** 台，占比 **{_format_percent(top_group['ratio'])}**。"


def _render_group_section(title: str, groups: List[Dict[str, Any]]) -> str:
    """渲染分布统计段落。"""
    if not groups:
        return f"## {title}\n\n暂无数据。"

    lines = [f"## {title}", ""]
    for index, group in enumerate(groups, start=1):
        lines.append(f"{index}. {group['name']}：{group['count']} 台（{_format_percent(group['ratio'])}）")
    return "\n".join(lines)


def _render_device_section(title: str, rows: List[Dict[str, Any]]) -> str:
    """渲染设备明细段落。"""
    columns = [
        ("devName", "设备名称"),
        ("manageIp", "管理IP"),
        ("deviceStatusName", "设备状态"),
        ("resourceStatusName", "资源状态"),
        ("modelId", "型号"),
        ("vendorName", "厂商"),
    ]
    preview_rows = _build_preview_rows(rows)
    table = _build_markdown_table(preview_rows, columns)
    note = _build_truncation_note(len(rows), len(preview_rows))
    return f"## {title}\n\n{table}{note}"


def _build_pie_chart_option(title: str, groups: List[Dict[str, Any]], donut: bool = False) -> Dict[str, Any]:
    """生成饼图配置。"""
    return {
        "title": {
            "text": title,
            "left": "center",
        },
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}: {c}台 ({d}%)",
        },
        "legend": {
            "right": "5%",
            "top": "center",
            "orient": "vertical",
        },
        "series": [
            {
                "name": title,
                "type": "pie",
                "radius": ["40%", "68%"] if donut else "56%",
                "data": [
                    {"name": group["name"], "value": group["count"]}
                    for group in groups
                ],
            }
        ],
    }


def _build_bar_chart_option(title: str, groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成柱状图配置。"""
    return {
        "title": {
            "text": title,
            "left": "center",
        },
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "shadow"},
        },
        "grid": {
            "left": 48,
            "right": 24,
            "bottom": 72,
            "top": 56,
        },
        "xAxis": {
            "type": "category",
            "data": [group["name"] for group in groups],
            "axisLabel": {"rotate": 30},
        },
        "yAxis": {
            "type": "value",
            "name": "数量（台）",
        },
        "series": [
            {
                "name": "设备数量",
                "type": "bar",
                "barMaxWidth": 40,
                "data": [group["count"] for group in groups],
            }
        ],
    }


def _render_chart_section(title: str, groups: List[Dict[str, Any]], chart_type: str = "pie") -> str:
    """渲染 ECharts 代码块。"""
    if not groups:
        return ""

    if chart_type == "bar":
        option = _build_bar_chart_option(title, groups)
    else:
        option = _build_pie_chart_option(title, groups, donut=chart_type == "donut")
    option_text = json.dumps(option, ensure_ascii=False, indent=2)
    return "\n".join([
        f"## {title}图表",
        "",
        "```echarts",
        option_text,
        "```",
    ])


def render_chart_only_markdown(output: Dict[str, Any]) -> str:
    """仅输出图表代码块，适合前端直接渲染。"""
    mode = output.get("mode", "summary")
    summary = output.get("summary", {}) or {}
    sections: List[str] = []

    if mode == "summary":
        sections.extend(
            filter(
                None,
                [
                    _render_chart_section("厂商分布", summary.get("vendor_distribution", []), "pie"),
                    _render_chart_section("型号 Top", summary.get("model_distribution", []), "bar"),
                    _render_chart_section("类型分布", summary.get("type_distribution", []), "pie"),
                    _render_chart_section("设备状态分布", summary.get("status_distribution", []), "pie"),
                    _render_chart_section("资源状态分布", summary.get("resource_status_distribution", []), "pie"),
                ],
            )
        )
    elif mode in {"status", "resource-status", "vendor", "model", "type"}:
        title_map = {
            "status": ("设备状态分布", "pie"),
            "resource-status": ("资源状态分布", "pie"),
            "vendor": ("厂商分布", "pie"),
            "model": ("型号分布", "bar"),
            "type": ("类型分布", "pie"),
        }
        title, chart_type = title_map[mode]
        sections.append(_render_chart_section(title, summary.get("groups", []), chart_type))
    elif mode == "abnormal":
        sections.append(
            _render_chart_section(
                "资源异常占比",
                [
                    {"name": "异常", "count": summary.get("abnormal_count", 0), "ratio": summary.get("abnormal_ratio", 0)},
                    {"name": "正常", "count": max(int(output.get("matched_total", 0)) - int(summary.get("abnormal_count", 0)), 0), "ratio": max(100 - float(summary.get("abnormal_ratio", 0)), 0)},
                ],
                "pie",
            )
        )

    sections = [section for section in sections if section]
    if sections:
        return "\n\n".join(sections)
    return "暂无可渲染图表。"


def render_markdown(output: Dict[str, Any]) -> str:
    """把分析结果渲染成适合聊天窗口展示的 Markdown。"""
    mode = output.get("mode", "summary")
    matched_total = int(output.get("matched_total", 0))
    fetched_total = int(output.get("fetched_total", 0))
    summary = output.get("summary", {}) or {}
    rows = output.get("rows", []) or []

    lines = ["# 设备查询结果", ""]

    if mode == "summary":
        conclusions = _build_summary_conclusions(summary)
        conclusion_lines = [f"- {item}" for item in conclusions] if conclusions else ["- 暂无明显结论。"]
        lines.extend(
            [
                f"共获取 **{fetched_total}** 台设备，本次纳入分析 **{matched_total}** 台。",
                "",
                "## 自动结论",
                "",
                *conclusion_lines,
                "",
                "## 概览",
                "",
                f"- 设备总数：{summary.get('total_devices', 0)} 台",
                f"- 在线设备：{summary.get('online_count', 0)} 台（{_format_percent(summary.get('online_ratio', 0))}）",
                f"- 离线设备：{summary.get('offline_count', 0)} 台",
                f"- 资源异常：{summary.get('abnormal_count', 0)} 台（{_format_percent(summary.get('abnormal_ratio', 0))}）",
                "",
                _render_group_section("设备状态分布", summary.get("status_distribution", [])),
                "",
                _render_group_section("资源状态分布", summary.get("resource_status_distribution", [])),
                "",
                _render_group_section("厂商分布", summary.get("vendor_distribution", [])),
                "",
                _render_chart_section("厂商分布", summary.get("vendor_distribution", []), "pie"),
                "",
                _render_group_section("型号 Top", summary.get("model_distribution", [])),
                "",
                _render_chart_section("型号 Top", summary.get("model_distribution", []), "bar"),
                "",
                _render_group_section("类型分布", summary.get("type_distribution", [])),
            ]
        )
        if summary.get("abnormal_devices_preview"):
            lines.extend(["", _render_device_section("异常设备预览", summary.get("abnormal_devices_preview", []))])
        if summary.get("offline_devices_preview"):
            lines.extend(["", _render_device_section("离线设备预览", summary.get("offline_devices_preview", []))])
        if rows:
            lines.extend(["", _render_device_section("设备样例", rows)])
        return "\n".join(lines).strip()

    if mode in {"status", "resource-status", "vendor", "model", "type"}:
        group_conclusion = _build_group_conclusion(mode, summary.get("groups", []))
        title_map = {
            "status": "设备状态分布",
            "resource-status": "资源状态分布",
            "vendor": "厂商分布",
            "model": "型号分布",
            "type": "类型分布",
        }
        lines.extend(
            [
                f"本次共匹配 **{matched_total}** 台设备。",
                "",
                f"{group_conclusion}" if group_conclusion else "暂无可用结论。",
                "",
                _render_group_section(title_map[mode], summary.get("groups", [])),
                "",
                _render_chart_section(
                    title_map[mode],
                    summary.get("groups", []),
                    "bar" if mode == "model" else "pie",
                ),
            ]
        )
        if rows:
            lines.extend(["", _render_device_section("设备预览", rows)])
        return "\n".join(lines).strip()

    if mode == "abnormal":
        lines.extend(
            [
                f"本次共检查 **{matched_total}** 台设备，其中资源异常 **{summary.get('abnormal_count', 0)}** 台（{_format_percent(summary.get('abnormal_ratio', 0))}）。",
                "",
                "存在资源异常设备，建议优先关注以下清单。" if summary.get("abnormal_count", 0) else "当前未发现资源异常设备。",
                "",
                _render_chart_section(
                    "资源异常占比",
                    [
                        {"name": "异常", "count": summary.get("abnormal_count", 0), "ratio": summary.get("abnormal_ratio", 0)},
                        {"name": "正常", "count": max(matched_total - summary.get("abnormal_count", 0), 0), "ratio": max(100 - float(summary.get("abnormal_ratio", 0)), 0)},
                    ],
                    "pie",
                ),
                "",
                _render_device_section("异常设备", rows),
            ]
        )
        return "\n".join(lines).strip()

    if mode == "search":
        lines.extend(
            [
                f"本次共匹配 **{summary.get('matched_count', matched_total)}** 台设备。",
                "",
                "以下为匹配到的设备列表。" if rows else "未找到匹配设备。",
                "",
                _render_device_section("匹配设备", rows),
            ]
        )
        return "\n".join(lines).strip()

    return "\n".join(lines).strip()


def render_error_markdown(result: Dict[str, Any]) -> str:
    """把错误结果渲染成 Markdown。"""
    return "\n".join([
        "# 设备查询失败",
        "",
        f"- 错误码：{result.get('code', '-')}",
        f"- 错误信息：{result.get('msg', '未知错误')}",
    ])


def print_result(result: Dict[str, Any], output_format: str) -> None:
    """按输出格式打印结果。"""
    if output_format == "markdown-echarts-only":
        if result.get("code") == 200:
            print(render_chart_only_markdown(result))
        else:
            print(render_error_markdown(result))
        return
    if output_format == "markdown":
        if result.get("code") == 200:
            print(render_markdown(result))
        else:
            print(render_error_markdown(result))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def analyze_devices(mode: str, devices: List[Dict[str, Any]], top_n: int, include_devices: bool) -> Dict[str, Any]:
    """根据 mode 生成汇总结果。"""
    total = len(devices)
    if mode == "summary":
        analysis = build_overview(devices, top_n)
        return {
            "mode": mode,
            "summary": analysis,
            "rows": build_device_rows(devices[:top_n]) if include_devices else [],
        }

    field_getter_map = {
        "status": lambda device: device["deviceStatusName"],
        "resource-status": lambda device: device["resourceStatusName"],
        "vendor": lambda device: device["vendorName"],
        "model": lambda device: str(device.get("modelId") or "未标注"),
        "type": lambda device: device["deviceTypeName"],
    }

    if mode in field_getter_map:
        counter = Counter(field_getter_map[mode](device) for device in devices)
        return {
            "mode": mode,
            "summary": {
                "total_devices": total,
                "groups": summarize_groups(counter, total, top_n),
            },
            "rows": build_device_rows(devices[:top_n]) if include_devices else [],
        }

    if mode == "abnormal":
        abnormal_devices = [device for device in devices if str(device.get("resStatus", "")).lower() == "abnormal"]
        return {
            "mode": mode,
            "summary": {
                "total_devices": total,
                "abnormal_count": len(abnormal_devices),
                "abnormal_ratio": round((len(abnormal_devices) / total) * 100, 2) if total else 0,
            },
            "rows": build_device_rows(abnormal_devices[:top_n] if not include_devices else abnormal_devices),
        }

    if mode == "search":
        return {
            "mode": mode,
            "summary": {
                "matched_count": total,
            },
            "rows": build_device_rows(devices if include_devices else devices[:top_n]),
        }

    return make_error(400, f"不支持的 mode: {mode}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统一汇总设备信息，支持总览、分布统计、异常设备和关键字搜索",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 综合概览
  python3 analyze_devices.py --mode summary

  # 按厂商统计
  python3 analyze_devices.py --mode vendor

  # 查看异常设备
  python3 analyze_devices.py --mode abnormal --include-devices

  # 搜索名称或 IP 包含 core 的设备
  python3 analyze_devices.py --mode search --keyword core

  # 查询华为离线设备
  python3 analyze_devices.py --mode search --vendor HW --status offline --include-devices
        """,
    )
    parser.add_argument("--mode", choices=sorted(ALLOWED_MODES), default="summary", help="分析模式")
    parser.add_argument("--token", type=str, required=False, help="JWT 认证令牌（可选，默认从环境变量 INOE_API_TOKEN 读取）")
    parser.add_argument("--api_base_url", type=str, required=False, help="API 基础地址（可选，默认从环境变量 INOE_API_BASE_URL 读取）")
    parser.add_argument("--keyword", type=str, default="", help="搜索关键字")
    parser.add_argument(
        "--keyword_field",
        choices=["all", *sorted(SEARCHABLE_FIELDS)],
        default="all",
        help="关键字搜索字段，默认 all",
    )
    parser.add_argument("--vendor", type=str, default="", help="按厂商过滤，例如 HW / 华为")
    parser.add_argument("--model", type=str, default="", help="按型号过滤")
    parser.add_argument("--device_type", type=str, default="", help="按设备类型过滤，例如 route / 路由器")
    parser.add_argument("--status", type=str, default="", help="按设备状态过滤，例如 online / offline")
    parser.add_argument("--resource_status", type=str, default="", help="按资源状态过滤，例如 normal / abnormal")
    parser.add_argument("--fetch_page_size", type=int, default=DEFAULT_FETCH_PAGE_SIZE, help="抓取全量设备时的分页大小，默认 100")
    parser.add_argument("--top_n", type=int, default=DEFAULT_TOP_N, help="分组结果或预览设备数量，默认 10")
    parser.add_argument("--include-devices", action="store_true", help="输出完整设备预览列表")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="json", help="输出格式，默认 json")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.fetch_page_size < 1:
        return make_error(400, "fetch_page_size 必须大于等于 1")
    if args.top_n < 1:
        return make_error(400, "top_n 必须大于等于 1")
    if args.output not in ALLOWED_OUTPUTS:
        return make_error(400, f"不支持的 output: {args.output}")
    if args.mode == "search" and not any(
        [args.keyword.strip(), args.vendor.strip(), args.model.strip(), args.device_type.strip(), args.status.strip(), args.resource_status.strip()]
    ):
        return make_error(400, "search 模式至少需要一个过滤条件或关键字")
    return None


def main() -> None:
    args = parse_args()
    validation_error = validate_args(args)
    if validation_error:
        print_result(validation_error, args.output)
        sys.exit(1)

    token = args.token or get_token()
    if not token:
        print("错误: 未设置 API Token", file=sys.stderr)
        print("请设置技能目录下的 .env、环境变量 INOE_API_TOKEN，或使用 --token 参数", file=sys.stderr)
        sys.exit(1)

    fetch_result = fetch_all_devices(token=token, api_base_url=args.api_base_url, page_size=args.fetch_page_size)
    if fetch_result.get("code") != 200:
        print_result(fetch_result, args.output)
        sys.exit(1)

    devices = [normalize_device(device) for device in fetch_result.get("rows", []) if isinstance(device, dict)]
    filtered_devices = apply_filters(
        devices,
        keyword=args.keyword,
        keyword_field=args.keyword_field,
        vendor=args.vendor,
        model=args.model,
        device_type=args.device_type,
        status=args.status,
        resource_status=args.resource_status,
    )

    analysis_result = analyze_devices(
        mode=args.mode,
        devices=filtered_devices,
        top_n=args.top_n,
        include_devices=args.include_devices,
    )
    if analysis_result.get("code") and analysis_result.get("code") != 200:
        print_result(analysis_result, args.output)
        sys.exit(1)

    output = {
        "code": 200,
        "msg": "查询成功",
        "mode": args.mode,
        "filters": {
            "keyword": args.keyword,
            "keyword_field": args.keyword_field,
            "vendor": args.vendor,
            "model": args.model,
            "device_type": args.device_type,
            "status": args.status,
            "resource_status": args.resource_status,
        },
        "fetched_total": fetch_result.get("total", 0),
        "matched_total": len(filtered_devices),
        "pages": fetch_result.get("pages", 0),
        **analysis_result,
    }
    print_result(output, args.output)


if __name__ == "__main__":
    main()
