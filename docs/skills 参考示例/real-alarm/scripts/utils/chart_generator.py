#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ECharts 图表生成模块

这个模块不画图，只生成 ECharts 需要的配置（一份 JSON），包在
```echarts ... ``` 代码块里输出。如果聊天前端认识这种代码块，就会把它
渲染成一张真正的图表；不认识的话，用户至少还能看到一段可读的 JSON。
分组统计数据（[{"name": ..., "count": ...}, ...]）到 ECharts 配置的转换
逻辑集中在这一个文件里，其他模块不需要关心 ECharts 的具体配置格式。
"""

import json
from typing import Any, Dict, List


def _build_pie_chart_option(title: str, groups: List[Dict[str, Any]], donut: bool = False) -> Dict[str, Any]:
    """生成饼图（donut=True 时是环形图）的 ECharts option。

    适合"占比"类数据，比如告警级别分布、专业分布——这类数据关心的是
    "谁占多少比例"，饼图比柱状图更直观。
    """
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c}条 ({d}%)"},
        "legend": {"right": "5%", "top": "center", "orient": "vertical"},
        "series": [{
            "name": title,
            "type": "pie",
            "radius": ["40%", "68%"] if donut else "56%",
            "data": [{"name": group["name"], "value": group["count"]} for group in groups],
        }],
    }


def _build_bar_chart_option(title: str, groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成柱状图的 ECharts option。

    适合"排行/对比"类数据，比如告警标题 Top、设备告警 Top——这类数据
    关心的是"谁的数量最多"，柱状图的高低对比比饼图更直观。
    """
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 48, "right": 24, "bottom": 72, "top": 56},
        "xAxis": {
            "type": "category",
            "data": [group["name"] for group in groups],
            "axisLabel": {"rotate": 30},
        },
        "yAxis": {"type": "value", "name": "数量（条）"},
        "series": [{
            "name": "告警数量",
            "type": "bar",
            "barMaxWidth": 40,
            "data": [group["count"] for group in groups],
        }],
    }


def _render_chart_section(title: str, groups: List[Dict[str, Any]], chart_type: str = "pie") -> str:
    """渲染单个 ECharts 代码块。chart_type: pie / donut / bar"""
    if not groups:
        return ""
    if chart_type == "bar":
        option = _build_bar_chart_option(title, groups)
    else:
        option = _build_pie_chart_option(title, groups, donut=chart_type == "donut")
    option_text = json.dumps(option, ensure_ascii=False, indent=2)
    return "\n".join([f"## {title}图表", "", "```echarts", option_text, "```"])


def render_chart_only_markdown(output: Dict[str, Any]) -> str:
    """仅输出图表代码块，适合前端直接渲染（markdown-echarts-only 模式）。

    根据 analyze_by_mode() 产出的 mode 字段，决定要渲染哪几张图；
    summary 模式会一口气渲染 5 张图（级别/标题/设备/专业/区域），单
    维度模式（severity/title/...）只渲染对应的那一张。
    """
    mode = output.get("mode", "summary")
    summary = output.get("summary", {}) or {}
    sections: List[str] = []

    if mode == "summary":
        sections.extend(filter(None, [
            _render_chart_section("告警级别分布", summary.get("severity_distribution", []), "pie"),
            _render_chart_section("告警标题 Top", summary.get("title_distribution", []), "bar"),
            _render_chart_section("设备告警 Top", summary.get("device_distribution", []), "bar"),
            _render_chart_section("专业分布", summary.get("speciality_distribution", []), "pie"),
            _render_chart_section("区域分布", summary.get("region_distribution", []), "pie"),
        ]))
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

    sections = [s for s in sections if s]
    return "\n\n".join(sections) if sections else "暂无可渲染图表。"
