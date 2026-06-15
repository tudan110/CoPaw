#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 渲染模块：把分析结果渲染成适合聊天窗口展示的 Markdown"""

from typing import Any, Dict, List

DEFAULT_MARKDOWN_ALARM_LIMIT = 20


def _format_percent(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0%"
    return f"{int(numeric)}%" if float(numeric).is_integer() else f"{numeric:.2f}%"


def _build_markdown_table(rows: List[Dict[str, Any]], columns: List[tuple]) -> str:
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
    if not groups:
        return f"## {title}\n\n暂无数据。"
    lines = [f"## {title}", ""]
    for i, group in enumerate(groups, start=1):
        lines.append(f"{i}. {group['name']}：{group['count']} 条（{_format_percent(group['ratio'])}）")
    return "\n".join(lines)


def _render_alarm_section(title: str, rows: List[Dict[str, Any]]) -> str:
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
    """把分析结果渲染成适合聊天窗口展示的 Markdown。"""
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
