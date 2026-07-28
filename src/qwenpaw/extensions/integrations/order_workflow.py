# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from qwenpaw import constant

ORDER_SOURCE = "portal-order-workflow-api"


def _normalize_order_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized:
        return normalized
    parsed = urlsplit(normalized)
    path = parsed.path.rstrip("/")
    if path.endswith("/ferry") or path.endswith("/api/v1/work-order"):
        return normalized
    if path.endswith("/flowable"):
        path = f"{path.removesuffix('/flowable')}/ferry"
    elif not path:
        path = "/ferry"
    else:
        return normalized
    rebuilt = parsed._replace(path=path)
    return urlunsplit(rebuilt).rstrip("/")


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


def _build_order_client_config(
    module: Any,
    *,
    timeout_seconds: int | None,
    disable_curl_fallback: bool,
) -> Any:
    """按需覆盖 client 配置；无覆盖时返回规范化后的配置副本。

    Portal 后端直接复用 order-workflow runtime client，但用户本机
    ``~/.qwenpaw`` 里的旧版技能脚本可能还没同步到仓库最新逻辑。
    这里在 wrapper 层兜底把 base_url 规范化成 ferry 真正入口，避免
    继续回退到裸 INOE 根地址后命中 404。
    """
    config = module.OrderWorkflowConfig.from_env()
    normalized_base_url = _normalize_order_base_url(
        getattr(config, "base_url", ""),
    )
    if normalized_base_url:
        config.base_url = normalized_base_url
        os.environ["ORDER_API_BASE_URL"] = normalized_base_url
    if timeout_seconds is None and not disable_curl_fallback:
        return config
    if timeout_seconds is not None:
        config.timeout_seconds = int(timeout_seconds)
    if disable_curl_fallback:
        config.enable_curl_fallback = False
    return config


def query_order_workorders(
    *,
    limit: int,
    time_range: str = "today",
    timeout_seconds: int | None = None,
    disable_curl_fallback: bool = False,
) -> dict[str, Any]:
    """查询待办工单 + 统计。

    ``timeout_seconds`` / ``disable_curl_fallback`` 供大屏等对时延敏感的
    调用方缩短失败成本用：跳板半死时 urllib 20s + curl 兜底 20s = 40s，
    对同一条坏链路毫无意义，只会把失败成本翻倍。默认不传时行为与聊天
    技能路径完全一致（走 ORDER_TIMEOUT_SECONDS / ORDER_ENABLE_CURL_FALLBACK
    的环境默认值）。
    """
    from qwenpaw.extensions.integrations.working_secrets import (
        ensure_working_secrets_loaded,
    )

    ensure_working_secrets_loaded()
    module = _load_order_client_module()
    client = module.OrderWorkflowClient(
        _build_order_client_config(
            module,
            timeout_seconds=timeout_seconds,
            disable_curl_fallback=disable_curl_fallback,
        )
    )
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


def create_disposal_workorder(
    payload: dict[str, Any],
    *,
    timeout_seconds: int | None = None,
    disable_curl_fallback: bool = False,
) -> dict[str, Any]:
    """Create a disposal workorder through the order-workflow runtime client."""
    from qwenpaw.extensions.integrations.working_secrets import (
        ensure_working_secrets_loaded,
    )

    ensure_working_secrets_loaded()
    module = _load_order_client_module()
    client = module.OrderWorkflowClient(
        _build_order_client_config(
            module,
            timeout_seconds=timeout_seconds,
            disable_curl_fallback=disable_curl_fallback,
        )
    )
    if not isinstance(payload, dict):
        raise RuntimeError("workorder payload must be a JSON object")
    return client.create_disposal_workorder(payload)


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
