#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ECharts 图表生成模块"""

import json
from typing import Any, Dict, List


def _build_pie_chart_option(title: str, groups: List[Dict[str, Any]], donut: bool = False) -> Dict[str, Any]:
    """生成饼图配置。"""
    return {
        "title": {
            "text": title,
            "left": "center",
        },
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}: {c}条 ({d}%)",
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
            "name": "数量（条）",
        },
        "series": [
            {
                "name": "告警数量",
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
                    _render_chart_section("告警级别分布", summary.get("severity_distribution", []), "pie"),
                    _render_chart_section("告警标题 Top", summary.get("title_distribution", []), "bar"),
                    _render_chart_section("设备告警 Top", summary.get("device_distribution", []), "bar"),
                    _render_chart_section("专业分布", summary.get("speciality_distribution", []), "pie"),
                    _render_chart_section("区域分布", summary.get("region_distribution", []), "pie"),
                ],
            )
        )
    elif mode in {"severity", "title", "device", "speciality", "region"}:
        title_map = {
            "severity": ("告警级别分布", "pie"),
            "title": ("告警标题分布", "bar"),
            "device": ("设备告警分布", "bar"),
            "speciality": ("专业分布", "pie"),
            "region": ("区域分布", "pie"),
        }
        title, chart_type = title_map.get(mode, ("分布", "pie"))
        sections.append(_render_chart_section(title, summary.get("groups", []), chart_type))
    elif mode == "search":
        # 搜索模式不生成图表
        pass

    sections = [section for section in sections if section]
    if sections:
        return "\n\n".join(sections)
    return "暂无可渲染图表。"