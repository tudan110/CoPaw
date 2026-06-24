# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from qwenpaw import constant

ORDER_SOURCE = "portal-order-workflow-api"


def _resolve_workspace_skill_root(workspace: str, skill: str) -> Path:
    working_root = (
        constant.WORKING_DIR / "workspaces" / workspace / "skills" / skill
    )
    repo_root = (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / workspace
        / "skills"
        / skill
    )
    if working_root.exists():
        return working_root
    if repo_root.exists():
        return repo_root
    return working_root


def _resolve_order_client_script() -> Path:
    client_script = (
        _resolve_workspace_skill_root(
            "order",
            "order-workflow",
        )
        / "runtime"
        / "client.py"
    )
    if not client_script.exists():
        raise FileNotFoundError("order-workflow runtime client not found")
    return client_script


@lru_cache(maxsize=1)
def _load_order_client_module():
    script_path = _resolve_order_client_script()
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_order_workflow_client",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def query_order_workorders(
    *,
    limit: int,
    time_range: str = "today",
) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.working_secrets import (
        ensure_working_secrets_loaded,
    )

    ensure_working_secrets_loaded()
    module = _load_order_client_module()
    client = module.OrderWorkflowClient()
    safe_limit = max(1, min(int(limit or 20), 100))
    stats_payload = client.get_workorder_stats()
    todo_payload = client.list_todo_workorders(
        page_num=1,
        page_size=safe_limit,
    )
    rows = [
        _normalize_workorder_row(row, index)
        for index, row in enumerate(
            list(todo_payload.get("rows") or [])[:safe_limit],
        )
    ]
    return {
        "source": "live",
        "provider": ORDER_SOURCE,
        "timeRange": str(time_range or "today"),
        "total": int(todo_payload.get("total") or len(rows)),
        "items": rows,
        "stats": _normalize_stats(stats_payload),
    }


def _priority_label(value: Any) -> str:
    if value in (None, "", "--"):
        return "--"
    try:
        return {3: "P1", 2: "P2", 1: "P3"}.get(int(value), str(value))
    except (TypeError, ValueError):
        return str(value)


def _normalize_workorder_row(row: Any, index: int) -> dict[str, Any]:
    # ferry list row: id/title/priority/process/process_name/state_name/
    # principals/create_time/update_time/is_end/current_state/creator.
    raw = row if isinstance(row, dict) else {}
    work_order_id = str(raw.get("id") or f"order-{index + 1}")
    is_end = str(raw.get("is_end") or "0") in {"1", "true", "True"}
    state_name = str(raw.get("state_name") or "")
    status = "已结束" if is_end else (state_name or "进行中")
    return {
        "id": work_order_id,
        "workorderNo": work_order_id,
        "title": str(raw.get("title") or "待办工单"),
        "status": status,
        "severity": _priority_label(raw.get("priority")),
        "eventTime": str(raw.get("create_time") or "--"),
        "taskId": "",
        "procInsId": "",
        "processId": str(raw.get("process") or ""),
        "processName": str(raw.get("process_name") or "--"),
        "taskName": state_name or "--",
        "starter": str(raw.get("creator") or "--"),
    }


def _normalize_stats(payload: Any) -> dict[str, int]:
    raw = payload.get("data") if isinstance(payload, dict) else {}
    data = raw if isinstance(raw, dict) else {}
    return {
        "inProgress": _safe_int(data.get("inProgressCount"), 0),
        "finished": _safe_int(data.get("finishedCount"), 0),
        "todo": _safe_int(data.get("todoCount"), 0),
    }


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
