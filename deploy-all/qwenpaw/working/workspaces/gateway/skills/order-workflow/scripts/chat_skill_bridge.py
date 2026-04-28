#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _load_runtime_modules():
    skill_root = Path(__file__).resolve().parents[1]
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))

    from runtime.client import OrderWorkflowClient
    from runtime.formatters import (
        format_create_markdown,
        format_detail_markdown,
        format_list_markdown,
        format_stats_markdown,
    )

    return (
        OrderWorkflowClient,
        format_create_markdown,
        format_detail_markdown,
        format_list_markdown,
        format_stats_markdown,
    )


def _load_context(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8") or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("Context JSON must be an object")
    return payload


def main() -> None:
    (
        OrderWorkflowClient,
        format_create_markdown,
        format_detail_markdown,
        format_list_markdown,
        format_stats_markdown,
    ) = _load_runtime_modules()

    parser = argparse.ArgumentParser(description="Standard chat bridge for order-workflow")
    parser.add_argument("--context-file", required=True)
    args = parser.parse_args()

    context = _load_context(args.context_file)
    action = str(context.get("action") or context.get("intent") or "").strip()
    client = OrderWorkflowClient()

    if action == "stats":
        print(format_stats_markdown(client.get_workorder_stats()))
        return
    if action == "todo-list":
        payload = client.list_todo_workorders(
            page_num=int(context.get("pageNum") or 1),
            page_size=int(context.get("pageSize") or 10),
            begin_time=str(context.get("beginTime") or ""),
            end_time=str(context.get("endTime") or ""),
            fetch_all=bool(context.get("fetchAll")),
        )
        print(format_list_markdown(payload, title="待办工单", lightweight=True))
        return
    if action == "finished-list":
        payload = client.list_finished_workorders(
            page_num=int(context.get("pageNum") or 1),
            page_size=int(context.get("pageSize") or 10),
            begin_time=str(context.get("beginTime") or ""),
            end_time=str(context.get("endTime") or ""),
            fetch_all=bool(context.get("fetchAll")),
        )
        print(format_list_markdown(payload, title="已办工单", lightweight=True))
        return
    if action == "detail":
        payload = client.get_workorder_detail(
            proc_ins_id=str(context.get("procInsId") or ""),
            task_id=str(context.get("taskId") or ""),
        )
        print(format_detail_markdown(payload, lightweight=True))
        return
    if action == "create":
        create_payload = context.get("payload")
        if not isinstance(create_payload, dict):
            create_payload = context
        payload = client.create_disposal_workorder(create_payload)
        print(format_create_markdown(payload))
        return

    raise RuntimeError(
        "Unsupported action. Use one of: stats, todo-list, finished-list, detail, create"
    )


if __name__ == "__main__":
    main()
