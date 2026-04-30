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

    from runtime import (
        WebMonitorClient,
        format_dashboard_markdown,
        format_health_markdown,
        format_monitor_detail_markdown,
        format_monitor_list_markdown,
        format_monitor_mutation_markdown,
        format_run_detail_markdown,
        format_run_list_markdown,
        format_selector_helper_markdown,
    )

    return (
        WebMonitorClient,
        format_dashboard_markdown,
        format_health_markdown,
        format_monitor_detail_markdown,
        format_monitor_list_markdown,
        format_monitor_mutation_markdown,
        format_run_detail_markdown,
        format_run_list_markdown,
        format_selector_helper_markdown,
    )


def _load_json_payload(*, payload_file: str | None, payload_json: str | None) -> dict[str, Any]:
    if payload_file:
        raw = Path(payload_file).expanduser().read_text(encoding="utf-8")
    elif payload_json:
        raw = payload_json
    else:
        raise RuntimeError("missing payload source")
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("payload must be a JSON object")
    return payload


def _resolve_monitor_id(client: Any, *, monitor_id: str | None, monitor_name: str | None) -> str:
    if monitor_id:
        return monitor_id
    if monitor_name:
        resolved = client.resolve_monitor(monitor_name)
        resolved_id = str(resolved.get("id") or "").strip()
        if not resolved_id:
            raise RuntimeError(f"无法解析监测任务：{monitor_name}")
        return resolved_id
    raise RuntimeError("monitor-id or monitor-name is required")


def _filter_monitors(payload: dict[str, Any], *, keyword: str, status: str, limit: int) -> dict[str, Any]:
    monitors = payload.get("monitors") or []
    if keyword:
        lowered = keyword.casefold()
        monitors = [
            item
            for item in monitors
            if lowered in str(item.get("name") or "").casefold()
            or lowered in str(item.get("description") or "").casefold()
            or lowered in str(item.get("targetUrl") or "").casefold()
        ]
    if status:
        normalized = status.strip().lower()
        monitors = [item for item in monitors if str(item.get("status") or "").strip().lower() == normalized]
    if limit > 0:
        monitors = monitors[:limit]
    return {"monitors": monitors}


def _filter_runs(payload: dict[str, Any], *, status: str, limit: int) -> dict[str, Any]:
    runs = payload.get("runs") or []
    if status:
        normalized = status.strip().lower()
        runs = [item for item in runs if str(item.get("status") or "").strip().lower() == normalized]
    if limit > 0:
        runs = runs[:limit]
    return {"runs": runs}


def _print_output(payload: dict[str, Any], *, output: str, markdown: str) -> None:
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(markdown)


def main() -> None:
    (
        WebMonitorClient,
        format_dashboard_markdown,
        format_health_markdown,
        format_monitor_detail_markdown,
        format_monitor_list_markdown,
        format_monitor_mutation_markdown,
        format_run_detail_markdown,
        format_run_list_markdown,
        format_selector_helper_markdown,
    ) = _load_runtime_modules()

    parser = argparse.ArgumentParser(description="Web availability monitor helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("health", "dashboard"):
        common_parser = subparsers.add_parser(command)
        common_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    list_parser = subparsers.add_parser("list-monitors")
    list_parser.add_argument("--keyword", default="")
    list_parser.add_argument("--status", choices=["enabled", "disabled"], default="")
    list_parser.add_argument("--limit", type=int, default=10)
    list_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    detail_parser = subparsers.add_parser("detail")
    detail_parser.add_argument("--monitor-id")
    detail_parser.add_argument("--monitor-name")
    detail_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    runs_parser = subparsers.add_parser("runs")
    runs_parser.add_argument("--monitor-id")
    runs_parser.add_argument("--monitor-name")
    runs_parser.add_argument("--status", choices=["success", "failed", "running", "warning", "skipped"], default="")
    runs_parser.add_argument("--limit", type=int, default=10)
    runs_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    selector_parser = subparsers.add_parser("selector-helper")
    selector_parser.add_argument("--url", required=True)
    selector_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    for command in ("create", "update"):
        mutation_parser = subparsers.add_parser(command)
        mutation_parser.add_argument("--payload-file")
        mutation_parser.add_argument("--payload-json")
        mutation_parser.add_argument("--publish", action="store_true")
        if command == "update":
            mutation_parser.add_argument("--monitor-id")
            mutation_parser.add_argument("--monitor-name")
        mutation_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--monitor-id")
    publish_parser.add_argument("--monitor-name")
    publish_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    trigger_parser = subparsers.add_parser("trigger")
    trigger_parser.add_argument("--monitor-id")
    trigger_parser.add_argument("--monitor-name")
    trigger_parser.add_argument("--definition-file")
    trigger_parser.add_argument("--definition-json")
    trigger_parser.add_argument("--wait-seconds", type=int, default=0)
    trigger_parser.add_argument("--poll-interval", type=float, default=3.0)
    trigger_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    delete_monitor_parser = subparsers.add_parser("delete-monitor")
    delete_monitor_parser.add_argument("--monitor-id")
    delete_monitor_parser.add_argument("--monitor-name")
    delete_monitor_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    delete_run_parser = subparsers.add_parser("delete-run")
    delete_run_parser.add_argument("--run-id", required=True)
    delete_run_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    delete_runs_parser = subparsers.add_parser("delete-runs")
    delete_runs_parser.add_argument("--run-ids", nargs="+", required=True)
    delete_runs_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args()
    client = WebMonitorClient()
    base_url = client.config.base_url

    if args.command == "health":
        payload = client.health()
        _print_output(payload, output=args.output, markdown=format_health_markdown(payload))
        return

    if args.command == "dashboard":
        payload = client.dashboard()
        _print_output(payload, output=args.output, markdown=format_dashboard_markdown(payload))
        return

    if args.command == "list-monitors":
        payload = _filter_monitors(
            client.list_monitors(),
            keyword=args.keyword,
            status=args.status,
            limit=args.limit,
        )
        _print_output(
            payload,
            output=args.output,
            markdown=format_monitor_list_markdown(payload, limit=args.limit),
        )
        return

    if args.command == "detail":
        monitor_id = _resolve_monitor_id(client, monitor_id=args.monitor_id, monitor_name=args.monitor_name)
        payload = client.get_monitor(monitor_id)
        _print_output(payload, output=args.output, markdown=format_monitor_detail_markdown(payload))
        return

    if args.command == "runs":
        monitor_id = _resolve_monitor_id(client, monitor_id=args.monitor_id, monitor_name=args.monitor_name)
        payload = _filter_runs(client.list_runs(monitor_id), status=args.status, limit=args.limit)
        _print_output(
            payload,
            output=args.output,
            markdown=format_run_list_markdown(payload, limit=args.limit),
        )
        return

    if args.command == "run":
        payload = client.get_run(args.run_id)
        _print_output(
            payload,
            output=args.output,
            markdown=format_run_detail_markdown(payload, base_url=base_url),
        )
        return

    if args.command == "selector-helper":
        payload = client.selector_helper(args.url)
        _print_output(
            payload,
            output=args.output,
            markdown=format_selector_helper_markdown(payload),
        )
        return

    if args.command == "create":
        payload = _load_json_payload(payload_file=args.payload_file, payload_json=args.payload_json)
        response = client.create_monitor(payload)
        if args.publish:
            monitor = response.get("monitor") or {}
            monitor_id = str(monitor.get("id") or "").strip()
            if monitor_id:
                client.publish_monitor(monitor_id)
                response = client.get_monitor(monitor_id)
        _print_output(
            response,
            output=args.output,
            markdown=format_monitor_mutation_markdown("create", response, base_url=base_url),
        )
        return

    if args.command == "update":
        monitor_id = _resolve_monitor_id(client, monitor_id=args.monitor_id, monitor_name=args.monitor_name)
        payload = _load_json_payload(payload_file=args.payload_file, payload_json=args.payload_json)
        response = client.update_monitor(monitor_id, payload)
        if args.publish:
            client.publish_monitor(monitor_id)
            response = client.get_monitor(monitor_id)
        _print_output(
            response,
            output=args.output,
            markdown=format_monitor_mutation_markdown("update", response, base_url=base_url),
        )
        return

    if args.command == "publish":
        monitor_id = _resolve_monitor_id(client, monitor_id=args.monitor_id, monitor_name=args.monitor_name)
        response = client.publish_monitor(monitor_id)
        try:
            response = client.get_monitor(monitor_id)
        except Exception:
            pass
        _print_output(
            response,
            output=args.output,
            markdown=format_monitor_mutation_markdown("publish", response, base_url=base_url),
        )
        return

    if args.command == "trigger":
        monitor_id = _resolve_monitor_id(client, monitor_id=args.monitor_id, monitor_name=args.monitor_name)
        definition = None
        if args.definition_file or args.definition_json:
            definition = _load_json_payload(payload_file=args.definition_file, payload_json=args.definition_json)
        response = client.trigger_monitor(monitor_id, definition=definition)
        if args.wait_seconds and response.get("run", {}).get("id"):
            run_id = str(response["run"]["id"])
            response = client.wait_for_run(
                run_id,
                timeout_seconds=args.wait_seconds,
                poll_interval=args.poll_interval,
            )
            _print_output(
                response,
                output=args.output,
                markdown=format_run_detail_markdown(response, base_url=base_url),
            )
            return
        _print_output(
            response,
            output=args.output,
            markdown=format_monitor_mutation_markdown("trigger", response, base_url=base_url),
        )
        return

    if args.command == "delete-monitor":
        monitor_id = _resolve_monitor_id(client, monitor_id=args.monitor_id, monitor_name=args.monitor_name)
        response = client.delete_monitor(monitor_id)
        _print_output(
            response,
            output=args.output,
            markdown=format_monitor_mutation_markdown("delete-monitor", response, base_url=base_url),
        )
        return

    if args.command == "delete-run":
        response = client.delete_run(args.run_id)
        _print_output(
            response,
            output=args.output,
            markdown=format_monitor_mutation_markdown("delete-run", response, base_url=base_url),
        )
        return

    if args.command == "delete-runs":
        response = client.delete_runs(args.run_ids)
        _print_output(
            response,
            output=args.output,
            markdown=format_monitor_mutation_markdown("delete-runs", response, base_url=base_url),
        )
        return


if __name__ == "__main__":
    main()
