#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any


def format_stats_markdown(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    return "\n".join(
        [
            "## 今日工单统计",
            "",
            f"- 待处理：**{data.get('inProgressCount', 0)}**",
            f"- 已完成：**{data.get('finishedCount', 0)}**",
            f"- 进行中：**{data.get('todoCount', 0)}**",
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
    process_forms = data.get("processFormList") or []
    detail_payload = _build_order_workorder_detail_payload(data)

    if lightweight:
        return _format_detail_light_markdown(detail_payload, process_forms)

    return _format_detail_full_markdown(detail_payload, process_forms)


def format_create_markdown(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    notification = payload.get("notification") or {}
    notification_status = _format_notification_status(notification)
    return "\n".join(
        [
            "## 处置工单创建结果",
            "",
            f"- `procInsId`: `{data.get('procInsId', '-')}`",
            f"- `taskId`: `{data.get('taskId', '-')}`",
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
        headers = ["序号", "任务编号", "流程名称", "任务节点", "流程发起人", "接收时间", "审批时间", "耗时"]
        table_rows = [
            [
                item["sequence"],
                item["taskId"],
                item["processName"],
                item["taskName"],
                item["starter"],
                item["receiveTime"],
                item["finishTime"],
                item["duration"],
            ]
            for item in normalized
        ]
    else:
        headers = ["序号", "任务编号", "流程名称", "任务节点", "流程版本", "流程发起人", "接收时间"]
        table_rows = [
            [
                item["sequence"],
                item["taskId"],
                item["processName"],
                item["taskName"],
                item["version"],
                item["starter"],
                item["receiveTime"],
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


def _resolve_process_name(row: dict[str, Any]) -> str:
    proc_vars = row.get("procVars") or {}
    return (
        row.get("procDefName")
        or proc_vars.get("title")
        or proc_vars.get("alarmTitle")
        or "-"
    )


def _resolve_task_name(row: dict[str, Any]) -> str:
    return row.get("taskName") or "-"


def _resolve_version(row: dict[str, Any]) -> str:
    version = row.get("procDefVersion")
    if version in (None, ""):
        return "-"
    return f"v{version}"


def _normalize_list_row(row: dict[str, Any], *, is_finished: bool, sequence: int) -> dict[str, Any]:
    normalized = {
        "sequence": sequence,
        "taskId": str(row.get("taskId") or "-"),
        "procInsId": str(row.get("procInsId") or "-"),
        "processName": _resolve_process_name(row),
        "taskName": _resolve_task_name(row),
        "starter": str(row.get("startUserName") or "-"),
        "receiveTime": str(row.get("createTime") or "-"),
    }
    if is_finished:
        normalized["finishTime"] = str(row.get("finishTime") or "-")
        normalized["duration"] = str(row.get("duration") or "-")
    else:
        normalized["version"] = _resolve_version(row)
    return normalized


def _build_order_workorder_detail_payload(data: dict[str, Any]) -> dict[str, Any]:
    process_forms = data.get("processFormList") or []
    history_nodes = data.get("historyProcNodeList") or []
    bpmn_xml = str(data.get("bpmnXml") or "")
    process_name = _extract_process_name_from_bpmn(bpmn_xml) or _first_form_title(process_forms)
    form_fields = _collect_form_fields(process_forms)

    return {
        "processName": process_name or "-",
        "summary": _build_detail_summary(form_fields, history_nodes),
        "tabs": {
            "form": _build_form_tab(process_forms),
            "records": _build_record_tab(history_nodes),
            "tracking": _build_tracking_tab(
                bpmn_xml,
                data.get("flowViewer") or {},
                history_nodes,
            ),
        },
    }


def _build_detail_summary(
    form_fields: list[dict[str, Any]],
    history_nodes: list[dict[str, Any]],
) -> list[dict[str, str]]:
    active_node = _pick_active_or_latest_node(history_nodes)
    summary_items: list[dict[str, str]] = []
    consumed_names: set[str] = set()

    for item in (
        _build_summary_item(
            form_fields,
            consumed_names,
            label="告警标题",
            names=("title", "alarmTitle"),
            labels=("告警标题",),
        ),
        _build_summary_item(
            form_fields,
            consumed_names,
            label="设备名称",
            names=("deviceName", "devName", "ciName", "instanceName"),
            labels=("设备名称", "设备别名", "资源", "实例名称"),
        ),
        _build_summary_item(
            form_fields,
            consumed_names,
            label="管理 IP",
            names=("manageIp", "deviceIp", "ip", "hostIp"),
            labels=("管理IP", "设备IP", "设备 ip", "IP地址"),
        ),
    ):
        if item:
            summary_items.append(item)

    for field in form_fields:
        name = str(field.get("name") or "").strip()
        label = str(field.get("label") or name or "字段")
        value = field.get("value")
        if name in consumed_names or value in (None, "", []):
            continue
        summary_items.append(
            {
                "label": label,
                "value": _compact_summary_value(value),
            }
        )
        consumed_names.add(name)
        if len(summary_items) >= 3:
            break

    summary_items.append(
        {
            "label": "当前节点",
            "value": _safe_inline(_resolve_node_label(active_node) if active_node else "-"),
        }
    )
    return summary_items[:4]


def _build_form_tab(process_forms: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for form in process_forms:
        fields = _extract_form_fields(
            form.get("formModel") or {},
            form.get("formData") or {},
        )
        sections.append(
            {
                "title": str(form.get("title") or "表单信息"),
                "fields": fields,
            }
        )
    return {
        "title": "表单信息",
        "sections": sections,
    }


def _build_record_tab(history_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    records = []
    for index, node in enumerate(sorted(history_nodes, key=_history_sort_key)):
        comments = node.get("commentList") or []
        is_active = not node.get("endTime") and str(node.get("activityType") or "") == "userTask"
        records.append(
            {
                "id": f"record-{index}",
                "status": "active" if is_active else "finished",
                "nodeLabel": _resolve_node_label(node),
                "nodeType": str(node.get("activityType") or "-"),
                "assignee": str(node.get("assigneeName") or node.get("assigneeId") or "-"),
                "candidate": str(node.get("candidate") or "-"),
                "receiveTime": str(node.get("createTime") or "-"),
                "handleTime": str(node.get("endTime") or "-"),
                "duration": str(node.get("duration") or "-"),
                "comments": [
                    str(comment.get("fullMessage") or comment.get("message") or "").strip()
                    for comment in comments
                    if str(comment.get("fullMessage") or comment.get("message") or "").strip()
                ],
            }
        )
    return {
        "title": "流转记录",
        "records": records,
    }


def _build_tracking_tab(
    bpmn_xml: str,
    flow_viewer: dict[str, Any],
    history_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed = _parse_bpmn_flow(bpmn_xml)
    history_map = {str(node.get("activityId") or ""): node for node in history_nodes}
    finished = {str(item) for item in flow_viewer.get("finishedTaskSet") or []}
    unfinished = {str(item) for item in flow_viewer.get("unfinishedTaskSet") or []}
    rejected = {str(item) for item in flow_viewer.get("rejectedTaskSet") or []}
    nodes = []
    for item in parsed["nodes"]:
        node_id = item["id"]
        status = "pending"
        if node_id in finished:
            status = "finished"
        elif node_id in unfinished:
            status = "active"
        elif node_id in rejected:
            status = "rejected"
        history = history_map.get(node_id) or {}
        nodes.append(
            {
                "id": node_id,
                "label": _resolve_node_label(history) if history else item["label"],
                "kind": item["kind"],
                "status": status,
                "assignee": str(history.get("assigneeName") or history.get("assigneeId") or "-"),
                "startTime": str(history.get("createTime") or "-"),
                "endTime": str(history.get("endTime") or "-"),
            }
        )
    return {
        "title": "流程跟踪",
        "nodes": nodes,
    }


def _collect_form_fields(process_forms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_fields: list[dict[str, Any]] = []
    for form in process_forms:
        all_fields.extend(
            _extract_form_fields(
                form.get("formModel") or {},
                form.get("formData") or {},
            )
        )
    return all_fields


def _lookup_field_value(
    fields: list[dict[str, Any]],
    *,
    names: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
) -> Any:
    normalized_names = {item.strip().lower() for item in names if item.strip()}
    normalized_labels = {item.strip().lower() for item in labels if item.strip()}
    for field in fields:
        name = str(field.get("name") or "").strip().lower()
        label = str(field.get("label") or "").strip().lower()
        if name in normalized_names or label in normalized_labels:
            value = field.get("value")
            if value not in (None, "", []):
                return value
    for field in fields:
        label = str(field.get("label") or "").strip().lower()
        if any(token in label for token in normalized_labels):
            value = field.get("value")
            if value not in (None, "", []):
                return value
    return "-"


def _build_summary_item(
    fields: list[dict[str, Any]],
    consumed_names: set[str],
    *,
    label: str,
    names: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
) -> dict[str, str] | None:
    normalized_names = {item.strip().lower() for item in names if item.strip()}
    normalized_labels = {item.strip().lower() for item in labels if item.strip()}
    for field in fields:
        name = str(field.get("name") or "").strip()
        normalized_name = name.lower()
        normalized_label = str(field.get("label") or "").strip().lower()
        value = field.get("value")
        if normalized_name in normalized_names or normalized_label in normalized_labels:
            if value in (None, "", []):
                return None
            consumed_names.add(name)
            return {
                "label": label,
                "value": _compact_summary_value(value),
            }
    return None


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


def _extract_form_fields(form_model: dict[str, Any], form_data: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    def walk_widgets(widgets: list[dict[str, Any]]) -> None:
        for widget in widgets:
            options = widget.get("options") or {}
            name = str(options.get("name") or "").strip()
            if widget.get("formItemFlag") and name:
                fields.append(
                    {
                        "name": name,
                        "label": str(options.get("label") or name),
                        "value": _normalize_form_value(form_data.get(name)),
                        "multiline": widget.get("type") == "textarea",
                    }
                )
            for child in widget.get("widgetList") or []:
                walk_widgets([child])
            for row in widget.get("rows") or []:
                for col in row.get("cols") or []:
                    walk_widgets(col.get("widgetList") or [])

    walk_widgets(form_model.get("widgetList") or [])
    return fields


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


def _extract_process_name_from_bpmn(bpmn_xml: str) -> str:
    match = re.search(r"<bpmn2:process[^>]*name=\"([^\"]+)\"", bpmn_xml or "")
    return match.group(1).strip() if match else ""


def _parse_bpmn_flow(bpmn_xml: str) -> dict[str, list[dict[str, str]]]:
    if not bpmn_xml:
        return {"nodes": []}

    nodes: dict[str, dict[str, str]] = {}
    for kind in ("startEvent", "userTask", "endEvent"):
        pattern = re.compile(
            rf"<bpmn2:{kind}[^>]*id=\"([^\"]+)\"([^>]*)>([\s\S]*?)</bpmn2:{kind}>",
            re.IGNORECASE,
        )
        for match in pattern.finditer(bpmn_xml):
            node_id = match.group(1)
            attrs = match.group(2) or ""
            label_match = re.search(r'name="([^"]+)"', attrs)
            text_match = re.search(r'flowable:text="([^"]+)"', attrs)
            label = (
                (label_match.group(1) if label_match else "")
                or (text_match.group(1) if text_match else "")
                or _default_node_label(kind)
            )
            nodes[node_id] = {
                "id": node_id,
                "label": label,
                "kind": kind,
            }

    outgoing: dict[str, str] = {}
    flow_pattern = re.compile(
        r"<bpmn2:sequenceFlow[^>]*sourceRef=\"([^\"]+)\"[^>]*targetRef=\"([^\"]+)\"",
        re.IGNORECASE,
    )
    for match in flow_pattern.finditer(bpmn_xml):
        outgoing[match.group(1)] = match.group(2)

    start_nodes = [node_id for node_id, node in nodes.items() if node["kind"] == "startEvent"]
    ordered: list[dict[str, str]] = []
    visited: set[str] = set()
    current = start_nodes[0] if start_nodes else next(iter(nodes.keys()), "")
    while current and current not in visited and current in nodes:
        ordered.append(nodes[current])
        visited.add(current)
        current = outgoing.get(current, "")
    for node_id, item in nodes.items():
        if node_id not in visited:
            ordered.append(item)
    return {"nodes": ordered}


def _default_node_label(kind: str) -> str:
    return {
        "startEvent": "开始",
        "userTask": "人工办理",
        "endEvent": "结束",
    }.get(kind, kind or "未知节点")


def _resolve_node_label(node: dict[str, Any]) -> str:
    return str(
        node.get("activityName")
        or _default_node_label(str(node.get("activityType") or ""))
        or node.get("activityType")
        or "未知节点"
    )


def _first_form_title(process_forms: list[dict[str, Any]]) -> str:
    return str((process_forms[0] or {}).get("title") or "") if process_forms else ""


def _pick_active_or_latest_node(history_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not history_nodes:
        return {}
    active_nodes = [node for node in history_nodes if not node.get("endTime")]
    if active_nodes:
        return sorted(active_nodes, key=_history_sort_key)[-1]
    return sorted(history_nodes, key=_history_sort_key)[-1]


def _history_sort_key(node: dict[str, Any]) -> tuple[str, str]:
    return (
        str(node.get("createTime") or ""),
        f"{_history_type_rank(str(node.get('activityType') or '')):02d}",
        str(node.get("endTime") or "9999-99-99 99:99:99"),
    )


def _history_type_rank(activity_type: str) -> int:
    return {
        "startEvent": 0,
        "userTask": 1,
        "serviceTask": 2,
        "exclusiveGateway": 3,
        "endEvent": 9,
    }.get(activity_type, 5)


def status_text_value(status: Any) -> str:
    normalized = str(status or "")
    if normalized == "finished":
        return "已完成"
    if normalized == "active":
        return "处理中"
    if normalized == "rejected":
        return "已驳回"
    return "未到达"
