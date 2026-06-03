from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qwenpaw import constant

LOG_SOURCE = "zhiguan-log-service"


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


def _resolve_nightingale_log_script() -> Path:
    script = _resolve_workspace_skill_root(
        "query",
        "nightingale-log",
    ) / "scripts" / "n9e_log_query.py"
    if not script.exists():
        raise FileNotFoundError("nightingale-log skill script not found")
    return script


@lru_cache(maxsize=1)
def _load_nightingale_log_module():
    script_path = _resolve_nightingale_log_script()
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_nightingale_log_query",
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


def query_nightingale_logs(
    *,
    limit: int,
    lookback_minutes: int | None = 15,
    query: str = "",
    from_time: str = "",
    to_time: str = "",
    search_strategy: str = "",
    max_lookback_days: int = 45,
) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.working_secrets import ensure_working_secrets_loaded

    ensure_working_secrets_loaded()
    module = _load_nightingale_log_module()
    safe_limit = max(1, min(int(limit or 50), 200))
    safe_lookback = max(1, min(int(lookback_minutes or 15), 24 * 60))
    strategy = str(search_strategy or "").strip()
    if strategy == "latest_non_empty":
        return _query_latest_non_empty_logs(
            module=module,
            limit=safe_limit,
            lookback_minutes=safe_lookback,
            query=str(query or ""),
            max_lookback_days=max(1, min(int(max_lookback_days or 45), 365)),
        )

    resolved_from = str(from_time or "").strip() or f"now-{safe_lookback}m"
    resolved_to = str(to_time or "").strip() or "now"
    payload = _search_logs(
        module=module,
        limit=safe_limit,
        query=str(query or ""),
        from_time=resolved_from,
        to_time=resolved_to,
    )
    payload["lookbackMinutes"] = safe_lookback
    payload["searchStrategy"] = "single_window"
    payload["resolvedTimeRange"] = {"from": resolved_from, "to": resolved_to}
    return payload


def _query_latest_non_empty_logs(
    *,
    module: Any,
    limit: int,
    lookback_minutes: int,
    query: str,
    max_lookback_days: int,
) -> dict[str, Any]:
    attempted_ranges: list[dict[str, str]] = []
    last_payload: dict[str, Any] | None = None
    for from_time, to_time in _latest_non_empty_windows(
        lookback_minutes=lookback_minutes,
        max_lookback_days=max_lookback_days,
    ):
        attempted_ranges.append({"from": from_time, "to": to_time})
        payload = _search_logs(
            module=module,
            limit=limit,
            query=query,
            from_time=from_time,
            to_time=to_time,
        )
        payload["searchStrategy"] = "latest_non_empty"
        payload["resolvedTimeRange"] = {"from": from_time, "to": to_time}
        payload["attemptedTimeRanges"] = attempted_ranges
        payload["maxLookbackDays"] = max_lookback_days
        last_payload = payload
        if payload.get("sourceStatus") == "live" and payload.get("rows"):
            return payload
        if payload.get("sourceStatus") == "unavailable":
            return payload

    fallback = last_payload or {
        "source": LOG_SOURCE,
        "sourceStatus": "empty",
        "rows": [],
        "total": 0,
    }
    fallback["searchStrategy"] = "latest_non_empty"
    fallback["attemptedTimeRanges"] = attempted_ranges
    fallback["maxLookbackDays"] = max_lookback_days
    fallback["message"] = fallback.get("message") or f"近 {max_lookback_days} 天未命中日志"
    return fallback


def _latest_non_empty_windows(
    *,
    lookback_minutes: int,
    max_lookback_days: int,
) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    if lookback_minutes <= 60:
        windows.append((f"now-{lookback_minutes}m", "now"))
    windows.extend(
        [
            ("now-1h", "now"),
            ("now-6h", "now"),
            ("now-1d", "now"),
            ("now-7d", "now"),
        ],
    )
    day_edges = [14, 30, 45, 60, 90, 180, 365]
    previous = 7
    for edge in day_edges:
        if previous >= max_lookback_days:
            break
        current = min(edge, max_lookback_days)
        windows.append((f"now-{current}d", f"now-{previous}d"))
        previous = current

    deduped: list[tuple[str, str]] = []
    for window in windows:
        if window not in deduped:
            deduped.append(window)
    return deduped


def _search_logs(
    *,
    module: Any,
    limit: int,
    query: str,
    from_time: str,
    to_time: str,
) -> dict[str, Any]:
    args = SimpleNamespace(
        datasource=None,
        index=None,
        query=str(query or ""),
        from_time=from_time,
        to_time=to_time,
        size=limit,
        fields=None,
        sort_field=None,
        sort_order="desc",
        level_field=None,
        host_field=None,
        service_field=None,
    )
    envelope = module._do_search(args)  # type: ignore[attr-defined]  # noqa: SLF001
    if int(envelope.get("code") or 0) != 200:
        return {
            "source": LOG_SOURCE,
            "sourceStatus": "unavailable",
            "message": str(envelope.get("msg") or "日志服务查询失败"),
            "rows": [],
            "total": 0,
            "resolvedTimeRange": {"from": from_time, "to": to_time},
        }

    data = envelope.get("data") if isinstance(envelope, dict) else {}
    data = data if isinstance(data, dict) else {}
    rows = [_normalize_log_row(row, module) for row in list(data.get("rows") or [])[:limit]]
    return {
        "source": LOG_SOURCE,
        "sourceStatus": "live" if rows else "empty",
        "total": int(data.get("total") or len(rows)),
        "rows": rows,
        "datasourceId": data.get("datasource_id"),
        "index": data.get("index"),
        "query": data.get("query") or "",
        "resolvedTimeRange": {"from": from_time, "to": to_time},
    }


def _normalize_log_row(row: Any, module: Any) -> dict[str, Any]:
    raw = row if isinstance(row, dict) else {}
    ts_ms = raw.get("ts_ms")
    formatter = getattr(getattr(module, "nc", None), "format_ms", None)
    time_text = formatter(ts_ms) if formatter and ts_ms else "--"
    return {
        "time": time_text,
        "level": str(raw.get("level") or "--"),
        "host": str(raw.get("host") or "--"),
        "service": str(raw.get("service") or "--"),
        "message": str(raw.get("message") or "")[:500],
        "index": str(raw.get("_index") or ""),
        "id": str(raw.get("_id") or ""),
    }
