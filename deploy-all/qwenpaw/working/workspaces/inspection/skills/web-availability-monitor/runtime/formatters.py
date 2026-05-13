#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from urllib.parse import urljoin


STATUS_LABELS = {
    "enabled": "启用",
    "disabled": "停用",
    "success": "成功",
    "passed": "已通过",
    "failed": "失败",
    "running": "运行中",
    "warning": "告警",
    "skipped": "已跳过",
    "schedule": "定时调度",
    "manual": "手工执行",
    "abort": "失败终止",
    "continue-warning": "失败继续并标记 Warning",
}


def format_health_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Web 可用性监测系统状态",
            "",
            f"- 健康检查：**{_status_text(payload.get('status') or payload.get('ok') or 'ok')}**",
            f"- 原始返回：`{_safe_inline(str(payload)[:200])}`",
        ]
    ).strip()


def format_dashboard_markdown(payload: dict[str, Any]) -> str:
    trend = payload.get("recentTrend") or []
    failures = payload.get("recentFailures") or []
    lines = [
        "## Web 可用性监测看板",
        "",
        f"- 监测任务数：**{payload.get('totalMonitors', 0)}**",
        f"- 总执行次数：**{payload.get('totalRuns', 0)}**",
        f"- 成功次数：**{payload.get('successRuns', 0)}**",
        f"- 失败次数：**{payload.get('failedRuns', 0)}**",
        f"- Warning 次数：**{payload.get('warningRuns', 0)}**",
        f"- 跳过次数：**{payload.get('skippedRuns', 0)}**",
    ]
    total_runs = int(payload.get("totalRuns") or 0)
    success_runs = int(payload.get("successRuns") or 0)
    if total_runs > 0:
        lines.append(f"- 成功率：**{success_runs / total_runs:.0%}**")

    if trend:
        lines.extend(
            [
                "",
                "### 最近趋势",
                _markdown_table(
                    ["日期", "总执行", "成功", "失败"],
                    [
                        [
                            item.get("day", "-"),
                            item.get("total", 0),
                            item.get("success", 0),
                            item.get("failed", 0),
                        ]
                        for item in trend
                    ],
                ),
            ]
        )

    if failures:
        lines.extend(
            [
                "",
                "### 近期失败",
                _markdown_table(
                    ["任务名称", "目标 URL", "触发方式", "摘要", "时间", "Run ID"],
                    [
                        [
                            item.get("monitorName", "-"),
                            _trim_cell(item.get("targetUrl", "-"), 60),
                            _status_text(item.get("triggerType", "-")),
                            _trim_cell(item.get("summary", "-"), 40),
                            _format_time(item.get("createdAt")),
                            item.get("id", "-"),
                        ]
                        for item in failures
                    ],
                ),
            ]
        )
    else:
        lines.extend(["", "### 近期失败", "当前没有失败记录。"])
    return "\n".join(lines).strip()


def format_monitor_list_markdown(payload: dict[str, Any], *, limit: int | None = None) -> str:
    monitors = payload.get("monitors") or []
    if limit and limit > 0:
        monitors = monitors[:limit]

    lines = [
        "## Web 监测任务列表",
        "",
        f"- 返回任务数：**{len(monitors)}**",
    ]
    if not monitors:
        lines.extend(["", "当前没有匹配的监测任务。"])
        return "\n".join(lines).strip()

    lines.extend(
        [
            "",
            _markdown_table(
                ["序号", "任务名称", "状态", "目标 URL", "调度", "最近状态", "Monitor ID"],
                [
                    [
                        index,
                        item.get("name", "-"),
                        _status_text(item.get("status", "-")),
                        _trim_cell(item.get("targetUrl", "-"), 60),
                        _schedule_summary(item),
                        _status_text(item.get("lastRunStatus", "-")),
                        item.get("id", "-"),
                    ]
                    for index, item in enumerate(monitors, start=1)
                ],
            ),
            "",
            "如需进一步查看，可直接说“查看第 2 条详情”“查看某个任务最近执行”或“手工执行某个任务”。",
        ]
    )
    return "\n".join(lines).strip()


def format_monitor_detail_markdown(payload: dict[str, Any]) -> str:
    monitor = payload.get("monitor") if isinstance(payload.get("monitor"), dict) else payload
    steps = _monitor_steps(monitor)
    lines = [
        "## Web 监测任务详情",
        "",
        f"- 任务名称：**{_safe_inline(monitor.get('name') or '-')}**",
        f"- Monitor ID：`{_safe_inline(monitor.get('id') or '-')}`",
        f"- 任务状态：**{_status_text(monitor.get('status') or '-')}**",
        f"- 目标 URL：`{_safe_inline(monitor.get('targetUrl') or '-')}`",
        f"- 任务描述：{_safe_inline(monitor.get('description') or '-')}",
        f"- 调度状态：**{'启用' if monitor.get('scheduleEnabled') else '停用'}**",
        f"- Cron：`{_safe_inline(monitor.get('scheduleCron') or '-')}`",
        f"- 时区：`{_safe_inline(monitor.get('scheduleTimezone') or '-')}`",
        f"- 最近状态：**{_status_text(monitor.get('lastRunStatus') or '-')}**",
        f"- 最近开始时间：{_format_time(monitor.get('lastRunStartedAt'))}",
        f"- 最近结束时间：{_format_time(monitor.get('lastRunFinishedAt'))}",
    ]
    if steps:
        lines.extend(
            [
                "",
                "### 步骤定义",
                _markdown_table(
                    ["序号", "步骤名称", "动作", "失败策略", "启用", "关键配置"],
                    [
                        [
                            index,
                            step.get("name", "-"),
                            step.get("actionType", "-"),
                            _status_text(step.get("onFailure", "-")),
                            "是" if step.get("enabled") else "否",
                            _trim_cell(_step_config_summary(step), 70),
                        ]
                        for index, step in enumerate(steps, start=1)
                    ],
                ),
            ]
        )
    return "\n".join(lines).strip()


def format_run_list_markdown(payload: dict[str, Any], *, limit: int | None = None) -> str:
    runs = payload.get("runs") or []
    if limit and limit > 0:
        runs = runs[:limit]

    lines = [
        "## 监测任务最近执行",
        "",
        f"- 返回记录数：**{len(runs)}**",
    ]
    if not runs:
        lines.extend(["", "当前没有执行记录。"])
        return "\n".join(lines).strip()
    lines.extend(
        [
            "",
            _markdown_table(
                ["序号", "Run ID", "状态", "触发方式", "耗时", "开始时间", "摘要"],
                [
                    [
                        index,
                        item.get("id", "-"),
                        _status_text(item.get("status", "-")),
                        _status_text(item.get("triggerType", "-")),
                        _duration_text(item.get("durationMs")),
                        _format_time(item.get("startedAt")),
                        _trim_cell(item.get("summary", "-"), 40),
                    ]
                    for index, item in enumerate(runs, start=1)
                ],
            ),
        ]
    )
    return "\n".join(lines).strip()


def format_run_detail_markdown(payload: dict[str, Any], *, base_url: str = "") -> str:
    run = payload.get("run") or {}
    steps = payload.get("steps") or []
    lines = [
        "## Web 监测执行详情",
        "",
        f"- Run ID：`{_safe_inline(run.get('id') or '-')}`",
        f"- Monitor ID：`{_safe_inline(run.get('monitorId') or '-')}`",
        f"- 状态：**{_status_text(run.get('status') or '-')}**",
        f"- 触发方式：**{_status_text(run.get('triggerType') or '-')}**",
        f"- 耗时：**{_duration_text(run.get('durationMs'))}**",
        f"- 开始时间：{_format_time(run.get('startedAt'))}",
        f"- 结束时间：{_format_time(run.get('finishedAt'))}",
        f"- 摘要：{_safe_inline(run.get('summary') or '-')}",
    ]

    if steps:
        lines.extend(["", "### 步骤结果"])
        for step in steps:
            output_snapshot = step.get("outputSnapshot") or {}
            action_desc = output_snapshot.get("actionDescription") if isinstance(output_snapshot, dict) else ""
            screenshot_url = _absolute_url(base_url, step.get("screenshotUrl"))
            lines.extend(
                [
                    "",
                    f"#### {int(step.get('stepIndex', 0)) + 1}. {_safe_inline(step.get('stepName') or '-')}",
                    f"- 动作：`{_safe_inline(step.get('actionType') or '-')}`",
                    f"- 状态：**{_status_text(step.get('status') or '-')}**",
                    f"- 失败策略：**{_status_text(step.get('onFailure') or '-')}**",
                    f"- 耗时：**{_duration_text(step.get('durationMs'))}**",
                    f"- 执行动作：{_safe_inline(action_desc or '-')}",
                ]
            )
            if step.get("errorMessage"):
                lines.append(f"- 错误：**{_safe_inline(step.get('errorMessage'))}**")
            if screenshot_url:
                lines.append(f"- 截图：{screenshot_url}")
            input_snapshot = step.get("inputSnapshot")
            if input_snapshot:
                lines.append(f"- 输入：`{_trim_cell(_safe_inline(_json_text(input_snapshot)), 120)}`")
            output_snapshot_value = step.get("outputSnapshot")
            if output_snapshot_value:
                lines.append(f"- 输出：`{_trim_cell(_safe_inline(_json_text(output_snapshot_value)), 120)}`")

    return "\n".join(lines).strip()


def format_selector_helper_markdown(payload: dict[str, Any]) -> str:
    suggestions = payload.get("suggestions") or []
    lines = [
        "## 页面元素定位建议",
        "",
        f"- 页面标题：**{_safe_inline(payload.get('pageTitle') or '-')}**",
        f"- 最终 URL：`{_safe_inline(payload.get('finalUrl') or '-')}`",
        f"- 建议数量：**{len(suggestions)}**",
    ]
    if not suggestions:
        lines.extend(["", "当前没有生成可用定位建议。"])
        return "\n".join(lines).strip()
    lines.extend(
        [
            "",
            _markdown_table(
                ["序号", "标签", "文本", "role", "locator", "坐标"],
                [
                    [
                        index,
                        item.get("label", "-"),
                        _trim_cell(item.get("text", "-"), 30),
                        item.get("role", "-"),
                        _trim_cell(_json_text(item.get("locator") or {}), 70),
                        _bounds_summary(item.get("bounds") or {}),
                    ]
                    for index, item in enumerate(suggestions, start=1)
                ],
            ),
        ]
    )
    return "\n".join(lines).strip()


def format_monitor_mutation_markdown(action: str, payload: dict[str, Any], *, base_url: str = "") -> str:
    monitor = payload.get("monitor") if isinstance(payload.get("monitor"), dict) else None
    run = payload.get("run") if isinstance(payload.get("run"), dict) else None
    action_title = {
        "create": "创建监测任务结果",
        "update": "更新监测任务结果",
        "publish": "发布监测任务结果",
        "trigger": "手工执行结果",
        "delete-monitor": "删除监测任务结果",
        "delete-run": "删除运行记录结果",
        "delete-runs": "批量删除运行记录结果",
    }.get(action, "操作结果")

    lines = [f"## {action_title}", ""]
    if monitor:
        lines.extend(
            [
                f"- Monitor ID：`{_safe_inline(monitor.get('id') or '-')}`",
                f"- 任务名称：**{_safe_inline(monitor.get('name') or '-')}**",
                f"- 目标 URL：`{_safe_inline(monitor.get('targetUrl') or '-')}`",
                f"- 状态：**{_status_text(monitor.get('status') or '-')}**",
                f"- 调度：{_schedule_summary(monitor)}",
            ]
        )
    if run:
        lines.extend(
            [
                f"- Run ID：`{_safe_inline(run.get('id') or '-')}`",
                f"- 状态：**{_status_text(run.get('status') or '-')}**",
                f"- 触发方式：**{_status_text(run.get('triggerType') or '-')}**",
                f"- 摘要：{_safe_inline(run.get('summary') or '-')}",
            ]
        )
        if run.get("id"):
            run_id = str(run.get("id") or "").strip()
            detail_target = urljoin(base_url.rstrip("/") + "/", f"runs/{run_id}") if base_url else run_id
            lines.append(f"- 详情：{detail_target}")
    if not monitor and not run:
        lines.append(f"- 原始返回：`{_safe_inline(_json_text(payload))}`")
    return "\n".join(lines).strip()


def _monitor_steps(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(monitor, dict):
        return []
    for key in ("publishedDefinition", "draftDefinition", "definition"):
        definition = monitor.get(key)
        if isinstance(definition, dict):
            steps = definition.get("steps")
            if isinstance(steps, list):
                return [step for step in steps if isinstance(step, dict)]
    return []


def _schedule_summary(item: dict[str, Any]) -> str:
    if not item.get("scheduleEnabled"):
        return "未启用"
    cron = _safe_inline(item.get("scheduleCron") or "-")
    timezone = _safe_inline(item.get("scheduleTimezone") or "-")
    return f"`{cron}` / `{timezone}`"


def _step_config_summary(step: dict[str, Any]) -> str:
    config = step.get("config") or {}
    if not isinstance(config, dict):
        return "-"
    if step.get("actionType") == "goto":
        return f"url={config.get('url', '-')}, waitUntil={config.get('waitUntil', '-')}"
    if step.get("actionType") in {"assertText", "assertElement", "click", "input", "scroll", "wait"}:
        return _json_text(config)
    return _json_text(config)


def _absolute_url(base_url: str, value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if not base_url:
        return raw
    return urljoin(base_url.rstrip("/") + "/", raw.lstrip("/"))


def _status_text(value: Any) -> str:
    normalized = str(value or "-").strip()
    return STATUS_LABELS.get(normalized, normalized or "-")


def _duration_text(value: Any) -> str:
    if value in (None, "", "-"):
        return "-"
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.2f}s"
    return f"{milliseconds}ms"


def _format_time(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(raw)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _bounds_summary(bounds: dict[str, Any]) -> str:
    if not isinstance(bounds, dict):
        return "-"
    return ",".join(
        [
            f"x={_num(bounds.get('x'))}",
            f"y={_num(bounds.get('y'))}",
            f"w={_num(bounds.get('width'))}",
            f"h={_num(bounds.get('height'))}",
        ]
    )


def _num(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.1f}"


def _json_text(value: Any) -> str:
    try:
        return _safe_inline(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except TypeError:
        return _safe_inline(str(value))


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "暂无数据"
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        output.append(
            "| " + " | ".join(_trim_cell(_safe_inline(item), 120) for item in row) + " |"
        )
    return "\n".join(output)


def _safe_inline(value: Any) -> str:
    return str(value if value not in (None, "") else "-").replace("\n", " ").replace("|", "\\|").strip()


def _trim_cell(value: Any, limit: int) -> str:
    text = _safe_inline(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
