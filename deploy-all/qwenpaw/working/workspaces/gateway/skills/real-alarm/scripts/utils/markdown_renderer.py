#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 渲染模块"""

from typing import Any, Dict, List

DEFAULT_MARKDOWN_ALARM_LIMIT = 20


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


def _build_preview_rows(rows: List[Dict[str, Any]], limit: int = DEFAULT_MARKDOWN_ALARM_LIMIT) -> List[Dict[str, Any]]:
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

    title_distribution = summary.get("title_distribution", []) or []
    device_distribution = summary.get("device_distribution", []) or []
    critical_count = int(summary.get("critical_count", 0) or 0)
    total_alarms = int(summary.get("total_alarms", 0) or 0)

    if title_distribution:
        top_title = title_distribution[0]
        conclusions.append(
            f"出现最多的告警是 **{top_title['name']}**，共 **{top_title['count']}** 次。"
        )

    if device_distribution:
        top_device = device_distribution[0]
        conclusions.append(
            f"告警最多的设备是 **{top_device['name']}**，共 **{top_device['count']}** 次告警。"
        )

    if total_alarms:
        if critical_count == 0:
            conclusions.append("当前无严重级别告警，系统运行状态良好。")
        else:
            conclusions.append(f"当前存在 **{critical_count}** 条严重告警，建议优先处理。")

    return conclusions


def _build_group_conclusion(mode: str, groups: List[Dict[str, Any]]) -> str:
    """生成分布类模式的结论。"""
    if not groups:
        return ""

    top_group = groups[0]
    label_map = {
        "severity": "告警级别",
        "title": "告警标题",
        "device": "设备",
        "speciality": "专业",
        "region": "区域",
    }
    prefix = label_map.get(mode, "分组")
    return f"{prefix}中占比最高的是 **{top_group['name']}**，共 **{top_group['count']}** 条，占比 **{_format_percent(top_group['ratio'])}**。"


def _render_group_section(title: str, groups: List[Dict[str, Any]]) -> str:
    """渲染分布统计段落。"""
    if not groups:
        return f"## {title}\n\n暂无数据。"

    lines = [f"## {title}", ""]
    for index, group in enumerate(groups, start=1):
        lines.append(f"{index}. {group['name']}：{group['count']} 条（{_format_percent(group['ratio'])}）")
    return "\n".join(lines)


def _render_alarm_section(title: str, rows: List[Dict[str, Any]]) -> str:
    """渲染告警明细段落。"""
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
    preview_rows = _build_preview_rows(rows)
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
        conclusion_lines = [f"- {item}" for item in conclusions] if conclusions else ["- 暂无明显结论。"]
        lines.extend(
            [
                f"共获取 **{fetched_total}** 条告警，本次纳入分析 **{matched_total}** 条。",
                "",
                "## 自动结论",
                "",
                *conclusion_lines,
                "",
                "## 概览",
                "",
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
            ]
        )
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
            "severity": "告警级别分布",
            "title": "告警标题分布",
            "device": "设备告警分布",
            "speciality": "专业分布",
            "region": "区域分布",
        }
        lines.extend(
            [
                f"本次共匹配 **{matched_total}** 条告警。",
                "",
                f"{group_conclusion}" if group_conclusion else "暂无可用结论。",
                "",
                _render_group_section(title_map[mode], summary.get("groups", [])),
                "",
                _render_chart_section(
                    title_map[mode],
                    summary.get("groups", []),
                    "bar" if mode in {"title", "device"} else "pie",
                ),
            ]
        )
        if rows:
            lines.extend(["", _render_alarm_section("告警预览", rows)])
        return "\n".join(lines).strip()

    if mode == "search":
        lines.extend(
            [
                f"本次共匹配 **{summary.get('matched_count', matched_total)}** 条告警。",
                "",
                "以下为匹配到的告警列表。" if rows else "未找到匹配告警。",
                "",
                _render_alarm_section("匹配告警", rows),
            ]
        )
        return "\n".join(lines).strip()

    return "\n".join(lines).strip()


def render_error_markdown(result: Dict[str, Any]) -> str:
    """把错误结果渲染成 Markdown。"""
    return "\n".join([
        "# 告警查询失败",
        "",
        f"- 错误码：{result.get('code', '-')}",
        f"- 错误信息：{result.get('msg', '未知错误')}",
    ])
