#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bridge real-alarm skill output into portal workorder cards.

This script does not modify CoPaw core code or the real-alarm skill itself.
It loads the active workspace skill dynamically, executes it, and normalizes
the returned alarm rows into a stable JSON payload for the portal frontend.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


SEVERITY_LABELS = {
    "1": "一级告警",
    "2": "二级告警",
    "3": "三级告警",
    "4": "四级告警",
}

STATUS_LABELS = {
    "0": "已恢复",
    "1": "处理中",
    "2": "已确认",
    "3": "已关闭",
}

SPECIALITY_LABELS = {
    "1": "网络",
    "2": "应用",
    "3": "传输",
    "4": "数据",
    "5": "安全",
}


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _candidate_project_roots() -> list[Path]:
    candidates: list[Path] = []

    for env_name in (
        "QWENPAW_PORTAL_PROJECT_ROOT",
        "QWENPAW_FAULT_DISPOSAL_PROJECT_ROOT",
    ):
        raw = os.getenv(env_name, "").strip()
        if raw:
            candidates.append(Path(raw).expanduser().resolve())

    current = Path.cwd().resolve()
    candidates.extend([current, *current.parents])

    here = Path(__file__).resolve()
    candidates.extend([*here.parents])

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _default_project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[5]


def _resolve_project_root() -> Path:
    for root in _candidate_project_roots():
        if (root / "src" / "qwenpaw" / "agents" / "skills").exists():
            return root
    return _default_project_root()


PROJECT_ROOT = _resolve_project_root()


def _default_working_dir() -> Path:
    env_dir = os.getenv("QWENPAW_WORKING_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    return Path("~/.qwenpaw").expanduser().resolve()


def _read_active_workspace_dir() -> Path:
    env_workspace = os.getenv("QWENPAW_PORTAL_WORKSPACE_DIR", "").strip()
    if env_workspace:
        return Path(env_workspace).expanduser().resolve()

    config_path = _default_working_dir() / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        agents = config.get("agents", {})
        active_agent = agents.get("active_agent") or "default"
        profile = (agents.get("profiles") or {}).get(active_agent) or {}
        workspace_dir = profile.get("workspace_dir")
        if workspace_dir:
            return Path(workspace_dir).expanduser().resolve()

    return (_default_working_dir() / "workspaces" / "default").resolve()


def _resolve_real_alarm_script() -> Path:
    env_script = os.getenv("QWENPAW_PORTAL_REAL_ALARM_SCRIPT", "").strip()
    if env_script:
        return Path(env_script).expanduser().resolve()

    candidates = [
        _default_working_dir()
        / "workspaces"
        / "query"
        / "skills"
        / "real-alarm"
        / "scripts"
        / "get_alarms.py",
        _read_active_workspace_dir() / "skills" / "real-alarm" / "scripts" / "get_alarms.py",
        PROJECT_ROOT
        / "src"
        / "qwenpaw"
        / "agents"
        / "skills"
        / "real-alarm"
        / "scripts"
        / "get_alarms.py",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError("real-alarm skill script not found")


@lru_cache(maxsize=1)
def _load_real_alarm_module():
    script_path = _resolve_real_alarm_script()
    spec = importlib.util.spec_from_file_location(
        "copaw_portal_real_alarm",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _execute_with_timeout(module, *, page_size: int, token: Any, alarm_status: str):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            module.execute,
            page_num=1,
            page_size=page_size,
            token=token,
            alarm_status=alarm_status,
        )
        return future.result(timeout=_real_alarm_timeout_seconds())


def _with_mock_retry(limit: int) -> tuple[dict[str, Any], str]:
    module = _load_real_alarm_module()
    token = getattr(module, "get_token", lambda: None)()

    try:
        result = _execute_with_timeout(
            module,
            page_size=max(limit, 10),
            token=token,
            alarm_status="1",
        )
        if isinstance(result, dict) and result.get("code") == 200:
            return result, "live"
    except concurrent.futures.TimeoutError:
        result = {
            "code": 504,
            "msg": (
                "real-alarm query timeout after "
                f"{_real_alarm_timeout_seconds():.0f}s"
            ),
        }

    previous_flag = os.environ.get("USE_MOCK_DATA")
    try:
        os.environ["USE_MOCK_DATA"] = "true"
        fallback = _execute_with_timeout(
            module,
            page_size=max(limit, 10),
            token=token,
            alarm_status="1",
        )
    finally:
        if previous_flag is None:
            os.environ.pop("USE_MOCK_DATA", None)
        else:
            os.environ["USE_MOCK_DATA"] = previous_flag

    return fallback, "mock"


def _safe_text(value: Any, fallback: str = "--") -> str:
    text = "" if value is None else str(value).strip()
    return text or fallback


def _format_time(value: Any) -> str:
    raw = _safe_text(value, "")
    if not raw:
        return "--"

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return raw


def _build_workorder_no(row: dict[str, Any], index: int) -> str:
    unique_id = _safe_text(row.get("alarmuniqueid"), "")
    suffix = unique_id[-6:] if unique_id else f"{index + 1:06d}"
    event_time = _safe_text(row.get("eventtime"), "")
    prefix = "WO"
    if event_time:
        try:
            prefix = datetime.strptime(event_time, "%Y-%m-%d %H:%M:%S").strftime(
                "WO-%Y%m%d"
            )
        except ValueError:
            prefix = "WO"
    return f"{prefix}-{suffix}"


def _format_severity(row: dict[str, Any]) -> tuple[str, str]:
    value = _safe_text(row.get("alarmseverity"), "4")
    return SEVERITY_LABELS.get(value, f"{value}级告警"), value


def _format_status(row: dict[str, Any]) -> tuple[str, str]:
    value = _safe_text(row.get("alarmstatus"), "1")
    return STATUS_LABELS.get(value, "处理中"), value


def _format_speciality(value: Any) -> str:
    text = _safe_text(value)
    return SPECIALITY_LABELS.get(text, text)


def _build_description(row: dict[str, Any]) -> str:
    # New hisAlarmList API carries the alarm text in ``additionalText``;
    # fall back to the legacy ``alarmtext`` for older payloads.
    alarm_text = _safe_text(
        row.get("additionalText") or row.get("alarmtext"), ""
    )
    if alarm_text:
        return alarm_text

    segments = [
        f"设备：{_safe_text(row.get('devName'))}",
        f"管理 IP：{_safe_text(row.get('manageIp'))}",
        f"定位对象：{_safe_text(row.get('locatenename'))}",
        f"告警标题：{_safe_text(row.get('alarmtitle'))}",
    ]
    return "；".join(segments)


def _normalize_workorder(row: dict[str, Any], index: int) -> dict[str, Any]:
    severity, severity_level = _format_severity(row)
    status, status_value = _format_status(row)
    title = _safe_text(row.get("alarmtitle"), "未命名告警")
    return {
        "id": _safe_text(row.get("alarmuniqueid"), f"alarm-{index + 1}"),
        "workorderNo": _build_workorder_no(row, index),
        "title": title,
        "description": _build_description(row),
        "deviceName": _safe_text(row.get("devName")),
        "manageIp": _safe_text(row.get("manageIp")),
        "locateName": _safe_text(row.get("locatenename")),
        "eventTime": _format_time(row.get("eventtime")),
        "severity": severity,
        "severityLevel": severity_level,
        "status": status,
        "statusValue": status_value,
        "speciality": _format_speciality(row.get("speciality")),
        "region": _safe_text(row.get("alarmregion")),
        "actionCount": int(row.get("alarmactcount") or 0),
        "alarmText": _safe_text(
            row.get("additionalText") or row.get("alarmtext"), ""
        ),
    }


def query_alarm_workorders(limit: int) -> dict[str, Any]:
    result, source = _with_mock_retry(limit)
    if not isinstance(result, dict):
        raise RuntimeError("real-alarm returned invalid payload")
    if result.get("code") != 200:
        message = result.get("msg") or "告警查询失败"
        raise RuntimeError(str(message))

    rows = result.get("rows") or []
    items = [_normalize_workorder(row, index) for index, row in enumerate(rows[:limit])]
    total = int(result.get("total") or len(items))
    return {
        "total": total,
        "items": items,
        "source": source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Query alarm workorders for portal.")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    payload = query_alarm_workorders(max(args.limit, 1))
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
REAL_ALARM_TIMEOUT_SECONDS = float(
    os.getenv("INOE_API_TIMEOUT", "8").strip() or "8"
)


def _real_alarm_timeout_seconds() -> float:
    """Resolve the INOE timeout via the shared accessor (page > env > default).

    Lazily imports the store so this module stays loadable as a standalone
    script (it is sometimes executed via importlib/subprocess).
    """
    try:
        from qwenpaw.extensions.api import inoe_settings_store

        return inoe_settings_store.get_timeout_seconds()
    except Exception:
        return REAL_ALARM_TIMEOUT_SECONDS
