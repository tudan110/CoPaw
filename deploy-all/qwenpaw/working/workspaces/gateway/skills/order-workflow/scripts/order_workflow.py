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


def _load_payload_file(payload_file: str) -> dict[str, Any]:
    raw = Path(payload_file).expanduser().read_text(encoding="utf-8")
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("Payload file must contain a JSON object")
    return payload


def _print_output(payload: dict[str, Any], *, output: str, markdown: str) -> None:
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(markdown)


def main() -> None:
    (
        OrderWorkflowClient,
        format_create_markdown,
        format_detail_markdown,
        format_list_markdown,
        format_stats_markdown,
    ) = _load_runtime_modules()

    parser = argparse.ArgumentParser(description="Traditional workorder workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    stats_parser = subparsers.add_parser("stats")
    stats_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--payload-file", required=True)
    create_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    for command in ("todo-list", "finished-list"):
        list_parser = subparsers.add_parser(command)
        list_parser.add_argument("--page-num", type=int)
        list_parser.add_argument("--page-size", type=int)
        list_parser.add_argument("--fetch-all", action="store_true")
        list_parser.add_argument("--begin-time", default="")
        list_parser.add_argument("--end-time", default="")
        list_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    detail_parser = subparsers.add_parser("detail")
    detail_parser.add_argument("--proc-ins-id", required=True)
    detail_parser.add_argument("--task-id", required=True)
    detail_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args()
    client = OrderWorkflowClient()

    if args.command == "stats":
        payload = client.get_workorder_stats()
        _print_output(
            payload,
            output=args.output,
            markdown=format_stats_markdown(payload),
        )
        return

    if args.command == "create":
        create_payload = _load_payload_file(args.payload_file)
        payload = client.create_disposal_workorder(create_payload)
        _print_output(
            payload,
            output=args.output,
            markdown=format_create_markdown(payload),
        )
        return

    if args.command == "todo-list":
        payload = client.list_todo_workorders(
            page_num=args.page_num or 1,
            page_size=args.page_size or 10,
            begin_time=args.begin_time,
            end_time=args.end_time,
            fetch_all=bool(args.fetch_all),
        )
        _print_output(
            payload,
            output=args.output,
            markdown=format_list_markdown(payload, title="待办工单", lightweight=True),
        )
        return

    if args.command == "finished-list":
        payload = client.list_finished_workorders(
            page_num=args.page_num or 1,
            page_size=args.page_size or 10,
            begin_time=args.begin_time,
            end_time=args.end_time,
            fetch_all=bool(args.fetch_all),
        )
        _print_output(
            payload,
            output=args.output,
            markdown=format_list_markdown(payload, title="已办工单", lightweight=True),
        )
        return

    if args.command == "detail":
        payload = client.get_workorder_detail(
            proc_ins_id=args.proc_ins_id,
            task_id=args.task_id,
        )
        _print_output(
            payload,
            output=args.output,
            markdown=format_detail_markdown(payload, lightweight=True),
        )
        return


if __name__ == "__main__":
    main()
