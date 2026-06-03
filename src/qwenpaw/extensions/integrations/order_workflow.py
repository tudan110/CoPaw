from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from qwenpaw import constant

ORDER_SOURCE = "portal-order-workflow-api"


def _resolve_workspace_skill_root(workspace: str, skill: str) -> Path:
    working_root = constant.WORKING_DIR / "workspaces" / workspace / "skills" / skill
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
    client_script = _resolve_workspace_skill_root(
        "order",
        "order-workflow",
    ) / "runtime" / "client.py"
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
    from qwenpaw.extensions.integrations.working_secrets import ensure_working_secrets_loaded

    ensure_working_secrets_loaded()
    module = _load_order_client_module()
    client = module.OrderWorkflowClient()
    safe_limit = max(1, min(int(limit or 20), 100))
    stats_payload = client.get_workorder_stats()
    todo_payload = client.list_todo_workorders(page_num=1, page_size=safe_limit)
    rows = [
        _normalize_workorder_row(row, index)
        for index, row in enumerate(list(todo_payload.get("rows") or [])[:safe_limit])
    ]
    return {
        "source": "live",
        "provider": ORDER_SOURCE,
        "timeRange": str(time_range or "today"),
        "total": int(todo_payload.get("total") or len(rows)),
        "items": rows,
        "stats": _normalize_stats(stats_payload),
    }


def _normalize_workorder_row(row: Any, index: int) -> dict[str, Any]:
    raw = row if isinstance(row, dict) else {}
    proc_vars = raw.get("procVars") if isinstance(raw.get("procVars"), dict) else {}
    return {
        "id": str(raw.get("taskId") or raw.get("procInsId") or f"order-{index + 1}"),
        "workorderNo": str(raw.get("taskId") or raw.get("procInsId") or f"order-{index + 1}"),
        "title": str(
            proc_vars.get("title")
            or proc_vars.get("alarmTitle")
            or raw.get("procDefName")
            or "待办工单"
        ),
        "status": str(proc_vars.get("processStatus") or raw.get("taskName") or "待处理"),
        "severity": str(proc_vars.get("priority") or proc_vars.get("level") or "--"),
        "eventTime": str(raw.get("createTime") or raw.get("receiveTime") or "--"),
        "taskId": str(raw.get("taskId") or ""),
        "procInsId": str(raw.get("procInsId") or ""),
        "processName": str(raw.get("procDefName") or "--"),
        "taskName": str(raw.get("taskName") or "--"),
        "starter": str(raw.get("startUserName") or "--"),
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
