#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 渲染模块：把分析结果渲染成适合聊天窗口展示的 Markdown

这是整条链路的最后一步：analyze_by_mode() 产出的是结构化字典（给
程序用的），这个模块负责把它转成人能直接读的 Markdown 文字+表格+
图表（给聊天窗口用的）。三种分析模式（summary / 分组统计 / search）
分别对应下面 render_markdown() 里的三段逻辑，互相独立，不共用具体
排版代码。
"""

from typing import Any, Dict, List

# 表格里默认最多展示多少条告警明细，避免几百条告警塞满整个聊天窗口。
DEFAULT_MARKDOWN_ALARM_LIMIT = 20


def _format_percent(value: Any) -> str:
    """把数字格式化成百分比文本：整数就不带小数（"12%"），否则保留两位
    小数（"12.34%"）。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0%"
    return f"{int(numeric)}%" if float(numeric).is_integer() else f"{numeric:.2f}%"


def _build_markdown_table(rows: List[Dict[str, Any]], columns: List[tuple]) -> str:
    """按标准 Markdown 表格语法拼字符串：表头行、分隔行（|---|---|)、
    数据行。columns 是 (字段名, 中文表头) 的元组列表，决定了取哪些
    字段、按什么顺序、显示什么表头。字段里如果有换行符会被替换成
    空格，避免破坏表格的一行一条记录格式。
    """
    if not rows:
        return "暂无数据。"
    header = "| " + " | ".join(label for _, label in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(key, "-")).replace("\n", " ") for key, _ in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def _build_truncation_note(total: int, shown: int) -> str:
    """如果表格做了截断（总数超过展示数），补一句提示文字告诉用户
    "只看到了一部分"，避免用户误以为总共只有这么几条告警。
    """
    if total <= shown:
        return ""
    return f"\n\n仅展示前 **{shown}** 条，实际共 **{total}** 条。"


def _build_summary_conclusions(summary: Dict[str, Any]) -> List[str]:
    """从概览数据中提炼自然语言结论。"""
    conclusions: List[str] = []
    title_distribution = summary.get("title_distribution", []) or []
    device_distribution = summary.get("device_distribution", []) or []
    critical_count = int(summary.get("critical_count", 0) or 0)
    total_alarms = int(summary.get("total_alarms", 0) or 0)

    if title_distribution:
        top = title_distribution[0]
        conclusions.append(f"出现最多的告警是 **{top['name']}**，共 **{top['count']}** 次。")
    if device_distribution:
        top = device_distribution[0]
        conclusions.append(f"告警最多的设备是 **{top['name']}**，共 **{top['count']}** 次告警。")
    if total_alarms:
        if critical_count == 0:
            conclusions.append("当前无严重级别告警，系统运行状态良好。")
        else:
            conclusions.append(f"当前存在 **{critical_count}** 条严重告警，建议优先处理。")

    return conclusions


def _build_group_conclusion(mode: str, groups: List[Dict[str, Any]]) -> str:
    """单维度分组模式（severity/title/device/...）下，从排名第一的分组
    提炼一句自然语言结论，和 summary 模式的 _build_summary_conclusions
    是类似的思路，只是这里只有一个维度、只需要说一句话。
    """
    if not groups:
        return ""
    top = groups[0]
    label_map = {
        "severity": "告警级别", "title": "告警标题", "device": "设备",
        "speciality": "专业", "region": "区域",
    }
    prefix = label_map.get(mode, "分组")
    return f"{prefix}中占比最高的是 **{top['name']}**，共 **{top['count']}** 条，占比 **{_format_percent(top['ratio'])}**。"


def _render_group_section(title: str, groups: List[Dict[str, Any]]) -> str:
    """把一组分组统计渲染成有序列表（"1. xxx：n 条（p%）"），是图表
    之外的文字版数据展示，即使聊天前端不支持渲染 ECharts 代码块，
    用户也能直接从这段文字看懂分布情况。
    """
    if not groups:
        return f"## {title}\n\n暂无数据。"
    lines = [f"## {title}", ""]
    for i, group in enumerate(groups, start=1):
        lines.append(f"{i}. {group['name']}：{group['count']} 条（{_format_percent(group['ratio'])}）")
    return "\n".join(lines)


def _render_alarm_section(title: str, rows: List[Dict[str, Any]]) -> str:
    """把一批告警渲染成一个带标题的表格区块，固定只展示前
    DEFAULT_MARKDOWN_ALARM_LIMIT 条，超出部分用 _build_truncation_note
    提示总数。
    """
    columns = [
        ("alarmtitle", "告警标题"),
        ("alarmSeverityName", "告警级别"),
        ("devName", "设备名称"),
        ("manageIp", "管理IP"),
        ("neId", "CI ID"),
        ("eventtime", "告警发生时间"),
        ("speciality", "专业"),
        ("alarmStatusName", "告警状态"),
    ]
    preview_rows = rows[:DEFAULT_MARKDOWN_ALARM_LIMIT]
    table = _build_markdown_table(preview_rows, columns)
    note = _build_truncation_note(len(rows), len(preview_rows))
    return f"## {title}\n\n{table}{note}"


def render_markdown(output: Dict[str, Any]) -> str:
    """把分析结果渲染成适合聊天窗口展示的 Markdown。

    按 output["mode"] 分三条完全独立的渲染路径：
    - summary：先给几句自动结论，再给各维度分组列表+图表，最后附上
      严重/活跃告警的预览表格
    - severity/title/device/speciality/region（单维度分组）：给一句
      结论 + 该维度的分组列表 + 图表
    - search：不做分组统计，直接把匹配到的告警列表渲染成表格
    """
    mode = output.get("mode", "summary")
    matched_total = int(output.get("matched_total", 0))
    fetched_total = int(output.get("fetched_total", 0))
    summary = output.get("summary", {}) or {}
    rows = output.get("rows", []) or []

    from utils.chart_generator import _render_chart_section

    lines = ["# 告警查询结果", ""]

    if mode == "summary":
        conclusions = _build_summary_conclusions(summary)
        conclusion_lines = [f"- {item}" for item in conclusions] or ["- 暂无明显结论。"]
        lines.extend([
            f"共获取 **{fetched_total}** 条告警，本次纳入分析 **{matched_total}** 条。",
            "",
            "## 自动结论", "",
            *conclusion_lines, "",
            "## 概览", "",
            f"- 告警总数：{summary.get('total_alarms', 0)} 条",
            f"- 严重告警：{summary.get('critical_count', 0)} 条（{_format_percent(summary.get('critical_ratio', 0))}）",
            f"- 活跃告警：{summary.get('active_count', 0)} 条（{_format_percent(summary.get('active_ratio', 0))}）",
            "",
            _render_group_section("告警级别分布", summary.get("severity_distribution", [])),
            "",
            _render_chart_section("告警级别分布", summary.get("severity_distribution", []), "pie"),
            "",
            _render_group_section("告警标题 Top", summary.get("title_distribution", [])),
            "",
            _render_chart_section("告警标题 Top", summary.get("title_distribution", []), "bar"),
            "",
            _render_group_section("设备告警 Top", summary.get("device_distribution", [])),
            "",
            _render_chart_section("设备告警 Top", summary.get("device_distribution", []), "bar"),
            "",
            _render_group_section("专业分布", summary.get("speciality_distribution", [])),
        ])
        if summary.get("critical_alarms_preview"):
            lines.extend(["", _render_alarm_section("严重告警预览", summary.get("critical_alarms_preview", []))])
        if summary.get("active_alarms_preview"):
            lines.extend(["", _render_alarm_section("活跃告警预览", summary.get("active_alarms_preview", []))])
        if rows:
            lines.extend(["", _render_alarm_section("告警示例", rows)])
        return "\n".join(lines).strip()

    if mode in {"severity", "title", "device", "speciality", "region"}:
        group_conclusion = _build_group_conclusion(mode, summary.get("groups", []))
        title_map = {
            "severity": "告警级别分布", "title": "告警标题分布",
            "device": "设备告警分布", "speciality": "专业分布", "region": "区域分布",
        }
        lines.extend([
            f"本次共匹配 **{matched_total}** 条告警。",
            "",
            group_conclusion if group_conclusion else "暂无可用结论。",
            "",
            _render_group_section(title_map[mode], summary.get("groups", [])),
            "",
            _render_chart_section(
                title_map[mode],
                summary.get("groups", []),
                "bar" if mode in {"title", "device"} else "pie",
            ),
        ])
        if rows:
            lines.extend(["", _render_alarm_section("告警预览", rows)])
        return "\n".join(lines).strip()

    if mode == "search":
        lines.extend([
            f"本次共匹配 **{summary.get('matched_count', matched_total)}** 条告警。",
            "",
            "以下为匹配到的告警列表。" if rows else "未找到匹配告警。",
            "",
            _render_alarm_section("匹配告警", rows),
        ])
        return "\n".join(lines).strip()

    return "\n".join(lines).strip()


def render_error_markdown(result: Dict[str, Any]) -> str:
    return "\n".join([
        "# 告警查询失败",
        "",
        f"- 错误码：{result.get('code', '-')}",
        f"- 错误信息：{result.get('msg', '未知错误')}",
    ])
