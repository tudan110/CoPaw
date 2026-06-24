#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any


def format_stats_markdown(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    return "\n".join(
        [
            "## 工单统计",
            "",
            f"- 待处理：**{data.get('todoCount', 0)}**",
            f"- 进行中：**{data.get('inProgressCount', 0)}**",
            f"- 已完成：**{data.get('finishedCount', 0)}**",
        ]
    ).strip()


def format_list_markdown(
    payload: dict[str, Any],
    *,
    title: str,
    lightweight: bool = True,
) -> str:
    rows = payload.get("rows") or []
    total = payload.get("total", len(rows))
    fetched_all = bool(payload.get("fetchedAll"))
    page_num = int(payload.get("pageNum") or 1)
    page_size = int(payload.get("pageSize") or len(rows) or 10)
    lines = [
        f"## {title}",
        "",
        f"- 总数：**{total}**",
        f"- 当前返回：**{len(rows)}**",
    ]
    if fetched_all:
        lines.append("- 查询模式：**默认全量**")
    if not rows:
        lines.extend(["", "当前没有记录。"])
        return "\n".join(lines).strip()

    lines.extend(
        [
            "",
            f"默认先预览第 {page_num} 页 {len(rows)} 条。如需继续查看，可直接说“下一页”“第 2 页”或“查看全部”。",
            "",
            _format_list_table(
                rows,
                title=title,
                start_index=1 if fetched_all else ((page_num - 1) * page_size + 1),
            ),
            "",
            "如需查看详情，可直接说“查看第 3 条”或“第 3 条详情”。",
        ]
    )
    return "\n".join(lines).strip()


def format_detail_markdown(payload: dict[str, Any], *, lightweight: bool = True) -> str:
    data = payload.get("data") or {}
    detail_payload = _build_order_workorder_detail_payload(data)
    sections = (
        ((detail_payload.get("tabs") or {}).get("form") or {}).get("sections")
    ) or []

    if lightweight:
        return _format_detail_light_markdown(detail_payload, sections)

    return _format_detail_full_markdown(detail_payload, sections)


def format_create_markdown(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    notification = payload.get("notification") or {}
    notification_status = _format_notification_status(notification)
    return "\n".join(
        [
            "## 处置工单创建结果",
            "",
            f"- `工单号`: `{data.get('workOrderId', '-')}`",
            f"- `流程`: `{data.get('processId', '-')}`",
            f"- 通知推送：**{notification_status}**",
        ]
    ).strip()


def _format_notification_status(notification: dict[str, Any]) -> str:
    status = str(notification.get("status") or "").strip().lower()
    reason = str(notification.get("reason") or "").strip()
    if status == "sent":
        return _format_notification_channels(notification, fallback="已发送")
    if status == "partial":
        return _format_notification_channels(notification, fallback="部分发送成功")
    if status == "failed":
        return f"发送失败：{reason or '未知错误'}"
    if status == "skipped":
        if reason == "webhook_not_configured":
            return "未配置"
        if reason == "missing_workorder_identifiers":
            return "已跳过（缺少工单编号）"
        return "已跳过"
    return "未配置"


def _format_notification_channels(notification: dict[str, Any], *, fallback: str) -> str:
    channels = notification.get("channels") or []
    sent_channels = [
        str(item.get("channel") or "").strip()
        for item in channels
        if str(item.get("status") or "").strip().lower() == "sent"
    ]
    if not sent_channels:
        return fallback
    label_map = {
        "app": "应用",
        "dingtalk": "钉钉",
        "feishu": "飞书",
    }
    labels = [label_map.get(name, name) for name in sent_channels if name]
    return "、".join(labels) + "已发送"


def _format_list_table(rows: list[dict[str, Any]], *, title: str, start_index: int = 1) -> str:
    is_finished = "已办" in title
    normalized = [
        _normalize_list_row(row, is_finished=is_finished, sequence=start_index + offset)
        for offset, row in enumerate(rows)
    ]
    if is_finished:
        headers = ["序号", "工单号", "流程号", "标题", "流程", "状态", "处理人", "创建时间", "更新时间"]
        table_rows = [
            [
                item["sequence"],
                item["workOrderId"],
                item["processId"],
                item["title"],
                item["processName"],
                item["state"],
                item["principals"],
                item["createTime"],
                item["updateTime"],
            ]
            for item in normalized
        ]
    else:
        headers = ["序号", "工单号", "流程号", "标题", "流程", "当前节点", "处理人", "优先级", "创建时间"]
        table_rows = [
            [
                item["sequence"],
                item["workOrderId"],
                item["processId"],
                item["title"],
                item["processName"],
                item["stateName"],
                item["principals"],
                item["priority"],
                item["createTime"],
            ]
            for item in normalized
        ]
    return _markdown_table(headers, table_rows)


def _format_detail_light_markdown(
    detail_payload: dict[str, Any],
    process_forms: list[dict[str, Any]],
) -> str:
    summary_items = detail_payload.get("summary") or []
    tabs = detail_payload.get("tabs") or {}
    form_sections = ((tabs.get("form") or {}).get("sections") or []) if isinstance(tabs, dict) else []
    record_items = ((tabs.get("records") or {}).get("records") or []) if isinstance(tabs, dict) else []
    tracking_nodes = ((tabs.get("tracking") or {}).get("nodes") or []) if isinstance(tabs, dict) else []

    lines = [
        "## 工单详情",
        "",
        f"- 流程名称：**{_safe_inline(detail_payload.get('processName') or '-')}**",
    ]
    for item in summary_items:
        label = _safe_inline(item.get("label") if isinstance(item, dict) else "-")
        value = _safe_inline(item.get("value") if isinstance(item, dict) else "-")
        if value != "-":
            lines.append(f"- {label}：**{value}**")

    preview_fields = _flatten_preview_fields(form_sections, limit=10)
    if preview_fields:
        lines.extend(
            [
                "",
                "### 表单信息预览",
                _markdown_table(
                    ["字段", "内容"],
                    [[field["label"], _trim_cell(field["value"], limit=80)] for field in preview_fields],
                ),
            ]
        )
    elif process_forms:
        lines.extend(["", "### 表单信息预览", "当前表单没有可直接预览的字段。"])

    if record_items:
        lines.extend(["", "### 流转记录"])
        for index, record in enumerate(record_items, start=1):
            lines.append(
                f"{index}. `{_safe_inline(record.get('nodeLabel') if isinstance(record, dict) else '-')}`"
                f" | 状态：{status_text_value(record.get('status') if isinstance(record, dict) else '-')}"
                f" | 办理人：{_safe_inline(record.get('assignee') if isinstance(record, dict) else '-')}"
                f" | 接收：{_safe_inline(record.get('receiveTime') if isinstance(record, dict) else '-')}"
                f" | 办理：{_safe_inline(record.get('handleTime') if isinstance(record, dict) else '-')}"
            )

    if tracking_nodes:
        lines.extend(
            [
                "",
                "### 流程跟踪",
                " -> ".join(
                    f"{_safe_inline(node.get('label') if isinstance(node, dict) else '-')}（{status_text_value(node.get('status') if isinstance(node, dict) else '-') }）"
                    for node in tracking_nodes
                ),
            ]
        )

    lines.extend(
        [
            "",
            _portal_order_detail_block(detail_payload),
            "",
            "如需继续查看，可以直接说：`查看完整表单信息`、`查看完整流转记录`、`查看完整流程跟踪`。",
        ]
    )
    return "\n".join(lines).strip()


def _format_detail_full_markdown(
    detail_payload: dict[str, Any],
    process_forms: list[dict[str, Any]],
) -> str:
    summary_items = detail_payload.get("summary") or []
    tabs = detail_payload.get("tabs") or {}
    form_sections = ((tabs.get("form") or {}).get("sections") or []) if isinstance(tabs, dict) else []
    record_items = ((tabs.get("records") or {}).get("records") or []) if isinstance(tabs, dict) else []
    tracking_nodes = ((tabs.get("tracking") or {}).get("nodes") or []) if isinstance(tabs, dict) else []

    lines = [
        "## 工单详情",
        "",
        f"- 流程名称：**{_safe_inline(detail_payload.get('processName') or '-')}**",
        f"- 表单数：**{len(process_forms)}**",
        f"- 流转节点数：**{len(record_items)}**",
    ]
    for item in summary_items:
        label = _safe_inline(item.get("label") if isinstance(item, dict) else "-")
        value = _safe_inline(item.get("value") if isinstance(item, dict) else "-")
        if value != "-":
            lines.append(f"- {label}：**{value}**")

    lines.extend(["", "### 表单信息"])
    if form_sections:
        for section in form_sections:
            section_title = _safe_inline(section.get("title") if isinstance(section, dict) else "表单信息")
            lines.extend(["", f"#### {section_title}"])
            fields = section.get("fields") if isinstance(section, dict) else []
            table_rows = []
            for field in fields or []:
                if not isinstance(field, dict):
                    continue
                value = field.get("value")
                if value in (None, "", []):
                    continue
                rendered_value = "；".join(str(item) for item in value) if isinstance(value, list) else _safe_inline(value)
                table_rows.append([_safe_inline(field.get("label")), rendered_value])
            lines.append(_markdown_table(["字段", "内容"], table_rows) if table_rows else "当前分组没有可展示字段。")
    else:
        lines.append("当前表单没有可展示字段。")

    lines.extend(["", "### 流转记录"])
    if record_items:
        for index, record in enumerate(record_items, start=1):
            if not isinstance(record, dict):
                continue
            lines.append(
                f"{index}. `{_safe_inline(record.get('nodeLabel'))}`"
                f" | 状态：{status_text_value(record.get('status'))}"
                f" | 办理人：{_safe_inline(record.get('assignee'))}"
                f" | 候选：{_safe_inline(record.get('candidate'))}"
                f" | 接收：{_safe_inline(record.get('receiveTime'))}"
                f" | 办理：{_safe_inline(record.get('handleTime'))}"
                f" | 耗时：{_safe_inline(record.get('duration'))}"
            )
            comments = record.get("comments")
            if isinstance(comments, list) and comments:
                lines.append(f"   处理意见：{'；'.join(_safe_inline(item) for item in comments)}")
    else:
        lines.append("当前没有流转记录。")

    lines.extend(["", "### 流程跟踪"])
    if tracking_nodes:
        for index, node in enumerate(tracking_nodes, start=1):
            if not isinstance(node, dict):
                continue
            lines.append(
                f"{index}. `{_safe_inline(node.get('label'))}`"
                f" | 类型：{_safe_inline(node.get('kind'))}"
                f" | 状态：{status_text_value(node.get('status'))}"
                f" | 处理人：{_safe_inline(node.get('assignee'))}"
                f" | 开始：{_safe_inline(node.get('startTime'))}"
                f" | 结束：{_safe_inline(node.get('endTime'))}"
            )
    else:
        lines.append("当前没有流程跟踪信息。")

    lines.extend(["", _portal_order_detail_block(detail_payload)])

    return "\n".join(lines).strip()


def _safe_inline(value: Any) -> str:
    text = str(value or "-").replace("\n", " ").strip()
    return text or "-"


def _priority_label(value: Any) -> str:
    """ferry 数字优先级 3/2/1 → P1/P2/P3。"""
    if value in (None, "", "-"):
        return "-"
    try:
        return {3: "P1", 2: "P2", 1: "P3"}.get(int(value), str(value))
    except (TypeError, ValueError):
        return _safe_inline(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_list_row(row: dict[str, Any], *, is_finished: bool, sequence: int) -> dict[str, Any]:
    row = row if isinstance(row, dict) else {}
    normalized = {
        "sequence": sequence,
        "workOrderId": str(row.get("id") or "-"),
        "processId": str(row.get("process") or "-"),
        "title": _safe_inline(row.get("title")),
        "processName": _safe_inline(row.get("process_name")),
        "principals": _safe_inline(row.get("principals")),
        "createTime": str(row.get("create_time") or "-"),
    }
    if is_finished:
        normalized["updateTime"] = str(row.get("update_time") or "-")
        normalized["state"] = "已结束" if _as_int(row.get("is_end")) == 1 else "进行中"
    else:
        normalized["stateName"] = _safe_inline(row.get("state_name"))
        normalized["priority"] = _priority_label(row.get("priority"))
    return normalized


def _build_order_workorder_detail_payload(data: dict[str, Any]) -> dict[str, Any]:
    """把 ferry process-structure 响应映射成门户消费的归一化详情块。"""
    process = data.get("process") if isinstance(data.get("process"), dict) else {}
    work_order = data.get("workOrder") if isinstance(data.get("workOrder"), dict) else {}
    nodes = data.get("nodes") or []
    history = data.get("circulationHistory") or []
    tpls = data.get("tpls") or []

    process_name = _safe_inline(
        process.get("name") or work_order.get("process_name") or "-"
    )
    current_state = str(work_order.get("current_state") or "")
    node_label_map = {
        str(node.get("id")): _safe_inline(node.get("label"))
        for node in nodes
        if isinstance(node, dict)
    }

    form_sections = _build_ferry_form_sections(tpls)
    form_fields = [
        field for section in form_sections for field in section.get("fields") or []
    ]

    return {
        "processName": process_name,
        "summary": _build_ferry_detail_summary(
            work_order,
            form_fields,
            node_label_map,
            current_state,
        ),
        "tabs": {
            "form": {"title": "表单信息", "sections": form_sections},
            "records": _build_ferry_record_tab(history),
            "tracking": _build_ferry_tracking_tab(nodes, history, current_state),
        },
    }


def _ferry_form_label_map(structure: dict[str, Any]) -> dict[str, str]:
    """从 ferry 表单 form_structure 里尽量挖出 字段名→中文标签 映射。

    ferry 表单 widget schema 文档未完整给出，这里做防御式深度遍历，
    兼容 vform / form-generator 常见结构，挖不到就回退原始 key。
    """
    label_map: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        config = node.get("__config__") if isinstance(node.get("__config__"), dict) else {}
        options = node.get("options") if isinstance(node.get("options"), dict) else {}
        name = (
            node.get("model")
            or node.get("__vModel__")
            or node.get("vModel")
            or node.get("name")
            or options.get("name")
            or node.get("id")
        )
        label = node.get("label") or config.get("label") or options.get("label")
        if isinstance(name, str) and name and isinstance(label, str) and label:
            label_map.setdefault(name, label)
        for key in ("list", "children", "columns", "widgetList", "tableColumns", "trItems"):
            if key in node:
                walk(node[key])

    walk(structure.get("list") if isinstance(structure, dict) else structure)
    return label_map


def _build_ferry_form_sections(tpls: list[Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for tpl in tpls:
        if not isinstance(tpl, dict):
            continue
        form_data = tpl.get("form_data") if isinstance(tpl.get("form_data"), dict) else {}
        structure = (
            tpl.get("form_structure")
            if isinstance(tpl.get("form_structure"), dict)
            else {}
        )
        label_map = _ferry_form_label_map(structure)
        fields = [
            {
                "name": str(name),
                "label": label_map.get(str(name), str(name)),
                "value": _normalize_form_value(value),
                "multiline": False,
            }
            for name, value in form_data.items()
        ]
        sections.append(
            {
                "title": _safe_inline(tpl.get("name") or "表单信息"),
                "fields": fields,
            }
        )
    return sections


def _build_ferry_detail_summary(
    work_order: dict[str, Any],
    form_fields: list[dict[str, Any]],
    node_label_map: dict[str, str],
    current_state: str,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    title = _safe_inline(work_order.get("title"))
    if title != "-":
        items.append({"label": "工单标题", "value": title})
    priority = _priority_label(work_order.get("priority"))
    if priority != "-":
        items.append({"label": "优先级", "value": priority})
    node_label = node_label_map.get(current_state) or _safe_inline(
        work_order.get("state_name")
    )
    items.append({"label": "当前节点", "value": node_label or "-"})
    principals = _safe_inline(work_order.get("principals"))
    if principals != "-":
        items.append({"label": "处理人", "value": principals})

    if len(items) < 2:
        for field in form_fields:
            value = field.get("value")
            if value in (None, "", [], "-"):
                continue
            items.append(
                {
                    "label": field.get("label") or field.get("name") or "字段",
                    "value": _compact_summary_value(value),
                }
            )
            if len(items) >= 4:
                break
    return items[:4]


def _ferry_circulation_status(value: Any) -> str:
    """ferry 流转记录 status → 前端状态键（枚举待真实响应校正）。"""
    try:
        code = int(value)
    except (TypeError, ValueError):
        return "finished"
    return {1: "active", 2: "finished", 3: "rejected"}.get(code, "finished")


def _ferry_record_comments(node: dict[str, Any]) -> list[str]:
    raw = node.get("opinion") or node.get("comment") or node.get("remark")
    text = str(raw or "").strip()
    return [text] if text else []


def _build_ferry_record_tab(history: list[Any]) -> dict[str, Any]:
    records = []
    for index, node in enumerate(history):
        if not isinstance(node, dict):
            continue
        records.append(
            {
                "id": f"record-{node.get('id', index)}",
                "status": _ferry_circulation_status(node.get("status")),
                "nodeLabel": _safe_inline(node.get("circulation")),
                "nodeType": "-",
                "assignee": _safe_inline(
                    node.get("processor") or node.get("processor_id")
                ),
                "candidate": "-",
                "receiveTime": str(node.get("create_time") or "-"),
                "handleTime": str(
                    node.get("update_time") or node.get("handle_time") or "-"
                ),
                "duration": str(node.get("duration") or "-"),
                "comments": _ferry_record_comments(node),
            }
        )
    return {"title": "流转记录", "records": records}


def _build_ferry_tracking_tab(
    nodes: list[Any],
    history: list[Any],
    current_state: str,
) -> dict[str, Any]:
    finished_ids = {
        str(item.get("node_id") or item.get("activityId") or "")
        for item in history
        if isinstance(item, dict)
    }
    ordered = sorted(
        [node for node in nodes if isinstance(node, dict)],
        key=lambda node: _as_int(node.get("sort"), 0),
    )
    track = []
    for node in ordered:
        node_id = str(node.get("id") or "")
        clazz = str(node.get("clazz") or "")
        if node_id and node_id == current_state:
            status = "active"
        elif node_id and node_id in finished_ids:
            status = "finished"
        elif clazz == "start":
            status = "finished"
        else:
            status = "pending"
        track.append(
            {
                "id": node_id,
                "label": _safe_inline(node.get("label")),
                "kind": clazz or "-",
                "status": status,
            }
        )
    return {"title": "流程跟踪", "nodes": track}


def _compact_summary_value(value: Any) -> str:
    text = _safe_inline(", ".join(str(item) for item in value) if isinstance(value, list) else value)
    return text if len(text) <= 64 else f"{text[:61]}..."


def _flatten_preview_fields(sections: list[dict[str, Any]], *, limit: int) -> list[dict[str, str]]:
    preview: list[dict[str, str]] = []
    for section in sections:
        for field in section.get("fields") or []:
            label = _safe_inline(field.get("label") if isinstance(field, dict) else "-")
            value = field.get("value") if isinstance(field, dict) else "-"
            if value in (None, "", []):
                continue
            preview.append(
                {
                    "label": label,
                    "value": ", ".join(str(item) for item in value) if isinstance(value, list) else _safe_inline(value),
                }
            )
            if len(preview) >= limit:
                return preview
    return preview


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = [
        "| " + " | ".join(_escape_markdown_cell(value) for value in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, separator, *body])


def _portal_order_detail_block(detail_payload: dict[str, Any]) -> str:
    return "```portal-order-detail\n" + json.dumps(
        detail_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n```"


def _escape_markdown_cell(value: Any) -> str:
    return _safe_inline(value).replace("|", "\\|")


def _trim_cell(value: Any, *, limit: int) -> str:
    text = _safe_inline(value)
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def _normalize_form_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                pass
        return text or "-"
    if value is None:
        return "-"
    return value


def status_text_value(status: Any) -> str:
    normalized = str(status or "")
    if normalized == "finished":
        return "已完成"
    if normalized == "active":
        return "处理中"
    if normalized == "rejected":
        return "已驳回"
    return "未到达"
