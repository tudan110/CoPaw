from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError

from qwenpaw.extensions.api.alarm_analyst_card_models import (
    AlarmAnalystCard,
    AlarmAnalystCardCreateRequest,
    AlarmAnalystCardCreateResponse,
    AlarmAnalystCardListResponse,
)
from qwenpaw.extensions.api.alarm_analyst_card_service import (
    build_alarm_analyst_card,
    is_alarm_analyst_card_candidate,
)
from qwenpaw.config.utils import load_config
from qwenpaw.extensions.api.fault_manual_workorder_models import (
    ManualWorkorderCloseNotificationRequest,
    ManualWorkorderDispatchRequest,
)
from qwenpaw.extensions.api.fault_manual_workorder_service import (
    build_manual_close_history_message,
    build_manual_dispatch_history_message,
    build_manual_workorder_record,
    evaluate_metric_recovery,
    merge_manual_workorder_notification,
)
from qwenpaw.extensions.api.alarm_analyst_service import run_alarm_analyst_diagnose
from qwenpaw.extensions.integrations.alarm_workorders.query_alarm_workorders import (
    query_alarm_workorders,
)
from qwenpaw.extensions.integrations.portal_real_alarms import query_portal_real_alarms
from qwenpaw.extensions.integrations import knowledge_base
from qwenpaw.app.agent_context import get_agent_for_request
from qwenpaw.app.channels.base import ContentType, TextContent

router = APIRouter(prefix="/api/portal", tags=["portal"])
app = FastAPI(title="Portal Backend")
FAULT_DISPOSAL_SCRIPT_TIMEOUT_SECONDS = 45
PORTAL_EMPLOYEE_STATUS_IDS = (
    "query",
    "fault",
    "knowledge",
    "resource",
    "inspection",
    "order",
)
PORTAL_EMPLOYEE_STATUS_NAMES = {
    "query": "数据分析员",
    "fault": "故障分析员",
    "knowledge": "知识专员",
    "resource": "资产管理员",
    "inspection": "巡检专员",
    "order": "工单调度员",
}
PORTAL_FAULT_ALERT_LIMIT = 20
PORTAL_EMPLOYEE_STATUS_ALERT_COUNT_ENABLED = (
    os.getenv("QWENPAW_PORTAL_EMPLOYEE_STATUS_ALERT_COUNT_ENABLED", "true")
    .strip()
    .lower()
    not in {"0", "false", "off", "no"}
)
PORTAL_STATUS_ALERT_TIMEOUT_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_STATUS_ALERT_TIMEOUT", "4").strip() or "4"
)
PORTAL_STATUS_ALERT_FAST_TIMEOUT_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_STATUS_ALERT_FAST_TIMEOUT", "0.4").strip() or "0.4"
)
PORTAL_STATUS_ALERT_CACHE_TTL_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_STATUS_ALERT_CACHE_TTL", "30").strip() or "30"
)
PORTAL_STATUS_ALERT_COUNT_CACHE: dict[str, Any] = {
    "value": 0,
    "updated_at": 0.0,
}
PORTAL_STATUS_ALERT_COUNT_REFRESH_TASK: asyncio.Task | None = None
RESOURCE_IMPORT_SCRIPT_TIMEOUT_SECONDS = int(
    os.environ.get("RESOURCE_IMPORT_SCRIPT_TIMEOUT_SECONDS", "1800")
)
ALARM_ANALYST_SCRIPT_TIMEOUT_SECONDS = 180
RESOURCE_IMPORT_PREVIEW_JOBS: dict[str, dict[str, Any]] = {}
RESOURCE_IMPORT_PREVIEW_JOBS_LOCK = threading.Lock()
PORTAL_REAL_ALARM_SESSION_PREFIX = "portal-fault-alarm-"
PORTAL_REAL_ALARM_CONSOLE_CHANNEL = "console"
PORTAL_REAL_ALARM_USER_ID = "default"
PORTAL_REAL_ALARM_NAME_LIMIT = 80
PORTAL_REAL_ALARM_ENSURE_LOCK = asyncio.Lock()
PORTAL_INSPECTION_SESSION_PREFIX = "portal-inspection-target-"
PORTAL_INSPECTION_CONSOLE_CHANNEL = "console"
PORTAL_INSPECTION_USER_ID = "default"
PORTAL_INSPECTION_NAME_LIMIT = 80
PORTAL_INSPECTION_ENSURE_LOCK = asyncio.Lock()

def _load_fault_disposal_runtime():
    skill_root = (
        Path(__file__).resolve().parents[2]
        / "agents"
        / "skills"
        / "fault-disposal"
    )
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))

    from runtime.reasoners import CopawReasoner, TemplateReasoner
    from runtime.tool_adapters import FaultDisposalToolbox
    from runtime.router import TicketRouter
    from runtime.models import TicketContext
    from runtime.playbooks import ApplicationTimeoutPlaybook, GenericAlarmPlaybook

    return (
        CopawReasoner,
        TemplateReasoner,
        FaultDisposalToolbox,
        TicketRouter,
        TicketContext,
        ApplicationTimeoutPlaybook,
        GenericAlarmPlaybook,
    )


def _fault_disposal_skill_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "agents"
        / "skills"
        / "fault-disposal"
    )


def _fault_disposal_bridge_script() -> Path:
    return _fault_disposal_skill_root() / "scripts" / "chat_skill_bridge.py"


def _zgops_cmdb_query_skill_root() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "query"
        / "skills"
        / "zgops-cmdb"
    )


def _zgops_cmdb_import_skill_root() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "resource"
        / "skills"
        / "zgops-cmdb-import"
    )


def _resource_import_bridge_script() -> Path:
    return _zgops_cmdb_import_skill_root() / "scripts" / "resource_import_bridge.py"


def _alarm_analyst_skill_root() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "fault"
        / "skills"
        / "alarm-analyst"
    )


def _alarm_analyst_metric_script() -> Path:
    return _alarm_analyst_skill_root() / "scripts" / "get_metric_definitions.py"


def _compact_ui_message(message: dict) -> dict:
    compact_message = dict(message)
    compact_message["id"] = message.get("id")
    compact_message["type"] = message.get("type")
    compact_message["content"] = message.get("content", "")
    compact_message["processBlocks"] = message.get("processBlocks", []) or []
    compact_message["disposalOperation"] = message.get("disposalOperation")
    compact_message["faultScenarioResult"] = _shape_fault_scenario_result(
        message.get("faultScenarioResult")
    )
    compact_message["timestamp"] = (
        message.get("timestamp") or datetime.now(timezone.utc).isoformat()
    )
    return compact_message


def _resolve_request_agent_id(request: Request) -> str:
    target_agent_id = getattr(request.state, "agent_id", None) or request.headers.get("X-Agent-Id")
    config = load_config()

    if not target_agent_id:
        target_agent_id = config.agents.active_agent or "default"

    if target_agent_id not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{target_agent_id}' not found",
        )

    agent_ref = config.agents.profiles[target_agent_id]
    if not getattr(agent_ref, "enabled", True):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{target_agent_id}' is disabled",
        )

    return target_agent_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_portal_real_alarm_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    normalized = normalized.strip("-._")
    return normalized or uuid.uuid4().hex


def _build_portal_real_alarm_session_id(alarm: dict[str, Any]) -> str:
    alarm_id = str(alarm.get("alarmId") or alarm.get("id") or "").strip()
    return f"{PORTAL_REAL_ALARM_SESSION_PREFIX}{_sanitize_portal_real_alarm_key(alarm_id)}"


def _build_portal_inspection_session_id(
    inspection_object: str,
    *,
    session_id: str = "",
) -> str:
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        return normalized_session_id
    return f"{PORTAL_INSPECTION_SESSION_PREFIX}{_sanitize_portal_real_alarm_key(inspection_object)}"


def _build_portal_real_alarm_chat_name(alarm: dict[str, Any]) -> str:
    title = str(alarm.get("title") or "未命名告警").strip() or "未命名告警"
    device_name = str(alarm.get("deviceName") or "").strip()
    if device_name and device_name != "--":
        return f"告警分析 · {title} · {device_name}"[:PORTAL_REAL_ALARM_NAME_LIMIT]
    return f"告警分析 · {title}"[:PORTAL_REAL_ALARM_NAME_LIMIT]


def _build_portal_inspection_chat_name(inspection_object: str) -> str:
    target = str(inspection_object or "").strip() or "未命名对象"
    return f"巡检分析 · {target}"[:PORTAL_INSPECTION_NAME_LIMIT]


def _build_portal_real_alarm_prompt(alarm: dict[str, Any]) -> str:
    title = str(alarm.get("title") or "未命名告警").strip() or "未命名告警"
    device_name = str(alarm.get("deviceName") or "").strip() or "--"
    manage_ip = str(alarm.get("manageIp") or "").strip() or "--"
    lines = [
        f"{title}（{device_name} {manage_ip}）",
        f"告警流水号：{str(alarm.get('alarmId') or alarm.get('id') or '').strip()}",
        f"资源 ID（CI ID）：{str(alarm.get('resId') or '').strip()}",
        f"告警时间：{str(alarm.get('eventTime') or '').strip()}",
        f"告警摘要：{str(alarm.get('visibleContent') or '').strip()}",
        "请分析这条活动告警，并继续完成根因分析、影响范围判断、处置建议、自动建单与通知。",
    ]
    return "\n".join(line for line in lines if line and not line.endswith("："))


def _build_portal_inspection_prompt(inspection_object: str) -> str:
    target = str(inspection_object or "").strip() or "未命名对象"
    lines = [
        f"请帮我巡检一下{target}",
        "要求：",
        "1. 先协作 query 智能体使用 zgops-cmdb 确认巡检对象的拓扑、资源名称、resId/CI ID 和 ciType。",
        "2. 如果存在多个候选资源，先明确列出候选项，不要默认任选一个。",
        "3. 一旦确认 resId 和 ciType，查询该资源类型的全部指标定义，提取全部指标编码。",
        "4. 调用指标数据接口，使用 resId + 全部指标编码数组完成巡检。",
        "5. 最后输出巡检结果、拓扑确认摘要和指标数据表。",
    ]
    return "\n".join(lines)


def _build_portal_real_alarm_payload(session_id: str, alarm: dict[str, Any]) -> dict[str, Any]:
    return {
        "channel_id": PORTAL_REAL_ALARM_CONSOLE_CHANNEL,
        "sender_id": PORTAL_REAL_ALARM_USER_ID,
        "content_parts": [
            TextContent(
                type=ContentType.TEXT,
                text=_build_portal_real_alarm_prompt(alarm),
            )
        ],
        "meta": {
            "session_id": session_id,
            "user_id": PORTAL_REAL_ALARM_USER_ID,
        },
    }


def _build_portal_inspection_payload(session_id: str, inspection_object: str) -> dict[str, Any]:
    return {
        "channel_id": PORTAL_INSPECTION_CONSOLE_CHANNEL,
        "sender_id": PORTAL_INSPECTION_USER_ID,
        "content_parts": [
            TextContent(
                type=ContentType.TEXT,
                text=_build_portal_inspection_prompt(inspection_object),
            )
        ],
        "meta": {
            "session_id": session_id,
            "user_id": PORTAL_INSPECTION_USER_ID,
        },
    }


async def _drain_portal_real_alarm_stream(
    task_tracker: Any,
    queue: Any,
    chat_id: str,
) -> None:
    stream_it = task_tracker.stream_from_queue(queue, chat_id)
    try:
        async for _ in stream_it:
            pass
    except Exception:
        print(f"[WARN] drain portal real alarm stream failed for chat_id={chat_id}")
        traceback.print_exc()
    finally:
        await stream_it.aclose()


def _portal_real_alarm_has_history(state: dict[str, Any]) -> bool:
    agent_state = state.get("agent") or {}
    memory_state = agent_state.get("memory") or {}
    return bool(memory_state)


async def _ensure_portal_inspection_session(
    request: Request,
    *,
    inspection_object: str,
    session_id: str = "",
) -> dict[str, Any]:
    normalized_object = str(inspection_object or "").strip()
    if not normalized_object:
        raise HTTPException(status_code=400, detail="inspectionObject is required")

    workspace = await _get_portal_employee_workspace(request, "inspection")
    if workspace is None:
        raise HTTPException(status_code=404, detail="Inspection workspace not available")

    console_channel = await workspace.channel_manager.get_channel(
        PORTAL_INSPECTION_CONSOLE_CHANNEL
    )
    if console_channel is None:
        raise HTTPException(status_code=503, detail="Inspection console channel not available")

    final_session_id = _build_portal_inspection_session_id(
        normalized_object,
        session_id=session_id,
    )
    result = {
        "inspectionObject": normalized_object,
        "sessionId": final_session_id,
        "created": 0,
        "started": 0,
        "skipped": 0,
        "chatId": "",
    }

    async with PORTAL_INSPECTION_ENSURE_LOCK:
        existing_chat = next(
            (
                item
                for item in await workspace.chat_manager.list_chats()
                if str(item.session_id or "") == final_session_id
                and str(item.user_id or "") == PORTAL_INSPECTION_USER_ID
                and str(item.channel or "") == PORTAL_INSPECTION_CONSOLE_CHANNEL
            ),
            None,
        )
        chat = await workspace.chat_manager.get_or_create_chat(
            final_session_id,
            PORTAL_INSPECTION_USER_ID,
            PORTAL_INSPECTION_CONSOLE_CHANNEL,
            name=_build_portal_inspection_chat_name(normalized_object),
        )
        result["chatId"] = chat.id

        existing_state = await workspace.runner.session.get_session_state_dict(
            chat.session_id,
            chat.user_id,
        )
        has_history = _portal_real_alarm_has_history(existing_state)
        if existing_chat is None:
            result["created"] = 1

        should_start = not has_history
        if not should_start:
            status = await workspace.task_tracker.get_status(chat.id)
            should_start = status != "running" and not has_history

        if not should_start:
            result["skipped"] = 1
            return result

        queue, started = await workspace.task_tracker.attach_or_start(
            chat.id,
            _build_portal_inspection_payload(final_session_id, normalized_object),
            console_channel.stream_one,
        )
        if started:
            result["started"] = 1
            asyncio.create_task(
                _drain_portal_real_alarm_stream(
                    workspace.task_tracker,
                    queue,
                    chat.id,
                )
            )
        else:
            result["skipped"] = 1

    return result


async def _ensure_portal_real_alarm_sessions(
    request: Request,
    alarms_payload: dict[str, Any],
) -> dict[str, Any]:
    items = alarms_payload.get("items") or []
    result = {
        "total": len(items) if isinstance(items, list) else 0,
        "eligible": 0,
        "created": 0,
        "started": 0,
        "skipped": 0,
        "sessions": [],
    }
    if not isinstance(items, list) or not items:
        return result

    workspace = await _get_portal_employee_workspace(request, "fault")
    if workspace is None:
        return result

    console_channel = await workspace.channel_manager.get_channel(
        PORTAL_REAL_ALARM_CONSOLE_CHANNEL
    )
    if console_channel is None:
        return result

    async with PORTAL_REAL_ALARM_ENSURE_LOCK:
        chats = await workspace.chat_manager.list_chats()
        chats_by_session = {
            str(chat.session_id): chat
            for chat in chats
            if str(chat.session_id or "").startswith(PORTAL_REAL_ALARM_SESSION_PREFIX)
        }

        for alarm in items:
            if not isinstance(alarm, dict):
                continue
            if str(alarm.get("employeeId") or "").strip() not in {"", "fault"}:
                continue

            alarm_id = str(alarm.get("alarmId") or alarm.get("id") or "").strip()
            if not alarm_id:
                continue

            result["eligible"] += 1
            session_id = _build_portal_real_alarm_session_id(alarm)
            result["sessions"].append(session_id)
            chat = chats_by_session.get(session_id)
            is_new_chat = False
            if chat is None:
                chat = await workspace.chat_manager.get_or_create_chat(
                    session_id,
                    PORTAL_REAL_ALARM_USER_ID,
                    PORTAL_REAL_ALARM_CONSOLE_CHANNEL,
                    name=_build_portal_real_alarm_chat_name(alarm),
                )
                chats_by_session[session_id] = chat
                is_new_chat = True
                result["created"] += 1

            should_start = is_new_chat
            if not should_start:
                status = await workspace.task_tracker.get_status(chat.id)
                if status == "idle":
                    state = await workspace.runner.session.get_session_state_dict(
                        chat.session_id,
                        chat.user_id,
                    )
                    should_start = not _portal_real_alarm_has_history(state)

            if not should_start:
                result["skipped"] += 1
                continue

            queue, started = await workspace.task_tracker.attach_or_start(
                chat.id,
                _build_portal_real_alarm_payload(session_id, alarm),
                console_channel.stream_one,
            )
            if started:
                result["started"] += 1
                asyncio.create_task(
                    _drain_portal_real_alarm_stream(
                        workspace.task_tracker,
                        queue,
                        chat.id,
                    )
                )
            else:
                result["skipped"] += 1

    return result


def _build_portal_real_alarm_trigger_payload(
    limit: int,
    trigger_body: dict[str, Any] | None,
) -> dict[str, Any]:
    body = trigger_body or {}
    alarms = body.get("alarms")
    if alarms is None:
        return query_portal_real_alarms(limit)
    if not isinstance(alarms, list):
        raise HTTPException(status_code=400, detail="'alarms' must be a list")
    return {
        "total": len(alarms),
        "items": alarms,
        "source": "request",
    }


def _read_preview_progress(progress_file: Path) -> list[dict[str, Any]]:
    if not progress_file.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in progress_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    except OSError:
        return []
    return events


def _serialize_preview_job(job_id: str) -> dict[str, Any]:
    with RESOURCE_IMPORT_PREVIEW_JOBS_LOCK:
        job = dict(RESOURCE_IMPORT_PREVIEW_JOBS.get(job_id) or {})

    if not job:
        raise HTTPException(status_code=404, detail=f"Preview job '{job_id}' not found")

    progress_events = _read_preview_progress(Path(job["progressFile"]))
    last_event = progress_events[-1] if progress_events else {}
    return {
        "jobId": job_id,
        "status": job.get("status") or "queued",
        "createdAt": job.get("createdAt"),
        "updatedAt": job.get("updatedAt"),
        "progressStage": last_event.get("stage"),
        "progressMessage": last_event.get("message"),
        "progressPercent": last_event.get("percent"),
        "progressEvents": progress_events[-120:],
        "logs": [
            str(item.get("message"))
            for item in progress_events[-120:]
            if item.get("message")
        ],
        "preview": job.get("preview"),
        "error": job.get("error") or "",
    }


def _set_preview_job_state(job_id: str, **updates: Any) -> None:
    with RESOURCE_IMPORT_PREVIEW_JOBS_LOCK:
        job = RESOURCE_IMPORT_PREVIEW_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updatedAt"] = _utc_now_iso()


def _run_preview_job(job_id: str, *, agent_id: str, payload_files: list[dict[str, Any]], temp_dir: str) -> None:
    progress_file = Path(temp_dir) / "preview-progress.jsonl"
    payload = {
        "agentId": agent_id,
        "files": payload_files,
        "progressFile": str(progress_file),
    }
    _set_preview_job_state(job_id, status="running")
    try:
        preview = _run_resource_import_skill("preview", payload)
        _set_preview_job_state(job_id, status="completed", preview=preview)
    except Exception as exc:  # noqa: BLE001
        try:
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            with progress_file.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "timestamp": _utc_now_iso(),
                            "stage": "failed",
                            "message": f"智能解析失败：{exc}",
                            "percent": 100,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            pass
        _set_preview_job_state(job_id, status="failed", error=str(exc))


async def _get_workspace_and_session(request: Request):
    from qwenpaw.app.agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return workspace, workspace.runner.session


def _datetime_to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    text = str(value or "").strip()
    return text


def _build_portal_employee_status_payload(
    employee_id: str,
    *,
    available: bool,
    total_chat_count: int,
    active_task_count: int,
    active_chat_count: int,
    alert_count: int,
    latest_session_title: str,
    updated_at: str,
) -> dict[str, Any]:
    urgent = alert_count > 0
    status = "running" if active_task_count > 0 else "idle"
    has_conversation = total_chat_count > 0
    progress = "--"

    if urgent:
        current_job = f"待处理告警 {alert_count} 条"
        work_status = "紧急任务"
        state_label = "紧急任务"
        progress = "0%"
    elif status == "running":
        current_job = (
            f"正在处理 {active_chat_count or active_task_count} 个对话任务"
        )
        work_status = "运行中"
        state_label = "运行中"
        progress = "50%"
    elif has_conversation and latest_session_title:
        current_job = f"最近会话：{latest_session_title}"
        work_status = "待机"
        state_label = "待机"
        progress = "100%"
    else:
        current_job = "暂无对话"
        work_status = "待机"
        state_label = "待机"

    return {
        "employeeId": employee_id,
        "employeeName": PORTAL_EMPLOYEE_STATUS_NAMES.get(employee_id, employee_id),
        "available": available,
        "status": status,
        "urgent": urgent,
        "stateLabel": state_label,
        "workStatus": work_status,
        "progress": progress,
        "currentJob": current_job,
        "hasConversation": has_conversation,
        "totalChatCount": total_chat_count,
        "activeTaskCount": active_task_count,
        "activeChatCount": active_chat_count,
        "alertCount": alert_count,
        "latestSessionTitle": latest_session_title,
        "updatedAt": updated_at,
    }


async def _get_portal_employee_workspace(
    request: Request,
    employee_id: str,
):
    config = load_config()
    profile = config.agents.profiles.get(employee_id)
    if profile is None or not getattr(profile, "enabled", True):
        return None

    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )

    try:
        return await manager.get_agent(employee_id)
    except ValueError:
        return None


def _get_loaded_portal_employee_workspace_for_status(
    request: Request,
    employee_id: str,
):
    config = load_config()
    profile = config.agents.profiles.get(employee_id)
    if profile is None or not getattr(profile, "enabled", True):
        return False, None

    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )

    return True, manager.agents.get(employee_id)


def _get_cached_fault_alert_count(*, require_fresh: bool) -> int | None:
    updated_at = float(PORTAL_STATUS_ALERT_COUNT_CACHE.get("updated_at") or 0.0)
    if updated_at <= 0:
        return None
    if require_fresh and time.monotonic() - updated_at > PORTAL_STATUS_ALERT_CACHE_TTL_SECONDS:
        return None
    return int(PORTAL_STATUS_ALERT_COUNT_CACHE.get("value") or 0)


async def _refresh_fault_alert_count_cache() -> int:
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(query_alarm_workorders, PORTAL_FAULT_ALERT_LIMIT),
            timeout=PORTAL_STATUS_ALERT_TIMEOUT_SECONDS,
        )
        items = result.get("items") or []
        count = int(result.get("total") or len(items))
        PORTAL_STATUS_ALERT_COUNT_CACHE.update(
            {
                "value": count,
                "updated_at": time.monotonic(),
            }
        )
        return count
    except Exception as exc:
        print(
            "[WARN] portal employee status alert count unavailable: "
            f"{type(exc).__name__}: {exc}"
        )
        return int(PORTAL_STATUS_ALERT_COUNT_CACHE.get("value") or 0)


def _ensure_fault_alert_count_refresh() -> asyncio.Task:
    global PORTAL_STATUS_ALERT_COUNT_REFRESH_TASK

    task = PORTAL_STATUS_ALERT_COUNT_REFRESH_TASK
    if task is not None and not task.done():
        return task

    task = asyncio.create_task(_refresh_fault_alert_count_cache())
    PORTAL_STATUS_ALERT_COUNT_REFRESH_TASK = task
    return task


async def _get_employee_alert_count(employee_id: str, *, include_alert_count: bool = True) -> int:
    if (
        employee_id != "fault"
        or not include_alert_count
        or not PORTAL_EMPLOYEE_STATUS_ALERT_COUNT_ENABLED
    ):
        return 0

    cached_count = _get_cached_fault_alert_count(require_fresh=True)
    if cached_count is not None:
        return cached_count

    task = _ensure_fault_alert_count_refresh()
    stale_count = _get_cached_fault_alert_count(require_fresh=False)
    if stale_count is not None:
        return stale_count

    try:
        return await asyncio.wait_for(
            asyncio.shield(task),
            timeout=PORTAL_STATUS_ALERT_FAST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return 0


async def collect_portal_employee_statuses(
    request: Request,
    *,
    employee_ids: tuple[str, ...] = PORTAL_EMPLOYEE_STATUS_IDS,
    include_alert_count: bool = True,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for employee_id in employee_ids:
        is_configured, workspace = _get_loaded_portal_employee_workspace_for_status(
            request,
            employee_id,
        )
        if not is_configured:
            statuses.append(
                _build_portal_employee_status_payload(
                    employee_id,
                    available=False,
                    total_chat_count=0,
                    active_task_count=0,
                    active_chat_count=0,
                    alert_count=0,
                    latest_session_title="",
                    updated_at=now_iso,
                )
            )
            continue

        if workspace is None:
            statuses.append(
                _build_portal_employee_status_payload(
                    employee_id,
                    available=True,
                    total_chat_count=0,
                    active_task_count=0,
                    active_chat_count=0,
                    alert_count=0,
                    latest_session_title="",
                    updated_at=now_iso,
                )
            )
            continue

        chats = await workspace.chat_manager.list_chats()
        active_task_keys = set(await workspace.task_tracker.list_active_tasks())
        active_chat_count = sum(1 for chat in chats if chat.id in active_task_keys)
        latest_chat = max(
            chats,
            key=lambda chat: chat.updated_at or chat.created_at,
            default=None,
        )
        latest_session_title = latest_chat.name.strip() if latest_chat else ""
        updated_at = _datetime_to_iso(
            latest_chat.updated_at if latest_chat else now_iso,
        )
        alert_count = await _get_employee_alert_count(
            employee_id,
            include_alert_count=include_alert_count,
        )
        statuses.append(
            _build_portal_employee_status_payload(
                employee_id,
                available=True,
                total_chat_count=len(chats),
                active_task_count=len(active_task_keys),
                active_chat_count=active_chat_count,
                alert_count=alert_count,
                latest_session_title=latest_session_title,
                updated_at=updated_at,
            )
        )

    return statuses


async def _load_portal_fault_history(
    request: Request,
    *,
    session_id: str,
    user_id: str = "default",
) -> list[dict]:
    _workspace, session = await _get_workspace_and_session(request)
    state = await session.get_session_state_dict(session_id, user_id)
    history = state.get("portal_fault_history", {}).get("messages", [])
    return history if isinstance(history, list) else []


async def _save_portal_fault_history(
    request: Request,
    *,
    session_id: str,
    messages: list[dict],
    user_id: str = "default",
) -> None:
    _workspace, session = await _get_workspace_and_session(request)
    await session.update_session_state(
        session_id,
        ["portal_fault_history", "messages"],
        messages,
        user_id=user_id,
    )


async def _load_portal_manual_workorders(
    request: Request,
    *,
    session_id: str,
    user_id: str = "default",
) -> dict[str, dict]:
    _workspace, session = await _get_workspace_and_session(request)
    state = await session.get_session_state_dict(session_id, user_id)
    records = state.get("portal_fault_manual_workorders", {}).get("records", {})
    return records if isinstance(records, dict) else {}


async def _save_portal_manual_workorders(
    request: Request,
    *,
    session_id: str,
    records: dict[str, dict],
    user_id: str = "default",
) -> None:
    _workspace, session = await _get_workspace_and_session(request)
    await session.update_session_state(
        session_id,
        ["portal_fault_manual_workorders", "records"],
        records,
        user_id=user_id,
    )


async def _load_portal_alarm_analyst_cards(
    request: Request,
    *,
    session_id: str,
    user_id: str = "default",
) -> dict[str, dict[str, dict]]:
    _workspace, session = await _get_workspace_and_session(request)
    state = await session.get_session_state_dict(session_id, user_id)
    records = state.get("portal_alarm_analyst_cards", {}).get("records", {})
    return records if isinstance(records, dict) else {}


async def _save_portal_alarm_analyst_cards(
    request: Request,
    *,
    session_id: str,
    records: dict[str, dict[str, dict]],
    user_id: str = "default",
) -> None:
    _workspace, session = await _get_workspace_and_session(request)
    await session.update_session_state(
        session_id,
        ["portal_alarm_analyst_cards", "records"],
        records,
        user_id=user_id,
    )


def _shape_fault_scenario_result(result: Any) -> dict | None:
    if result is None:
        return None

    payload = result if isinstance(result, dict) else {}
    shaped = dict(payload)
    shaped["summary"] = str(payload.get("summary") or "诊断已完成")
    shaped["rootCause"] = (
        payload.get("rootCause") if isinstance(payload.get("rootCause"), dict) else {}
    )
    shaped["steps"] = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    shaped["logEntries"] = (
        payload.get("logEntries") if isinstance(payload.get("logEntries"), list) else []
    )
    shaped["actions"] = (
        payload.get("actions") if isinstance(payload.get("actions"), list) else []
    )
    return shaped


def _shape_fault_scenario_response(result: dict[str, Any]) -> dict[str, Any]:
    shaped = dict(result)
    shaped["result"] = _shape_fault_scenario_result(result.get("result")) or {
        "summary": "诊断已完成",
        "rootCause": {},
        "steps": [],
        "logEntries": [],
        "actions": [],
    }
    return shaped


def _normalize_portal_fault_history_messages(messages: list[dict]) -> list[dict]:
    return [_compact_ui_message(message) for message in messages if isinstance(message, dict)]


def _shape_alarm_analyst_card_payload(payload: Any) -> dict | None:
    if not isinstance(payload, dict):
        return None
    try:
        return AlarmAnalystCard.model_validate(payload).model_dump(by_alias=True)
    except ValidationError:
        return None


def _list_alarm_analyst_cards_for_chat(
    records: dict[str, dict[str, dict]],
    chat_id: str,
) -> list[dict]:
    chat_records = records.get(chat_id) if isinstance(records, dict) else {}
    if not isinstance(chat_records, dict):
        return []
    cards: list[dict] = []
    for payload in chat_records.values():
        shaped = _shape_alarm_analyst_card_payload(payload)
        if shaped:
            cards.append(shaped)
    return cards


def _build_fault_context(payload: dict, *, source: str = "portal-chat"):
    (
        _CopawReasoner,
        _TemplateReasoner,
        _FaultDisposalToolbox,
        _TicketRouter,
        TicketContext,
        _ApplicationTimeoutPlaybook,
        _GenericAlarmPlaybook,
    ) = _load_fault_disposal_runtime()
    return TicketContext(
        entry_workorder=payload.get("entryWorkorder") or {},
        workorders=payload.get("workorders") or [],
        tags=payload.get("tags") or [],
        alarm_code=payload.get("alarmCode") or "",
        source=payload.get("source") or source,
    )


def _extract_portal_action_from_markdown(markdown_text: str) -> dict | None:
    text = str(markdown_text or "").strip()
    if not text:
        return None

    match = re.search(r"```portal-action\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if not match:
        return None

    try:
        payload = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        payload.setdefault("status", "ready")
        return payload
    return None


def _run_fault_disposal_chat_skill(command: str, payload: dict) -> dict:
    script_path = _fault_disposal_bridge_script()
    if not script_path.exists():
        raise FileNotFoundError(f"fault-disposal chat skill bridge not found: {script_path}")

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        context_file = handle.name

    try:
        completed = subprocess.run(
            [sys.executable, str(script_path), command, "--context-file", context_file],
            cwd=str(_fault_disposal_skill_root()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=FAULT_DISPOSAL_SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    finally:
        try:
            Path(context_file).unlink(missing_ok=True)
        except OSError:
            pass

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    if completed.returncode != 0:
        error_text = stderr_text or stdout_text or "fault-disposal skill bridge failed"
        raise RuntimeError(error_text)

    if not stdout_text:
        raise RuntimeError("fault-disposal skill bridge returned empty output")

    message = {
        "kind": "assistant",
        "content": stdout_text,
        "processBlocks": [],
    }
    action = _extract_portal_action_from_markdown(stdout_text)
    if action:
        message["action"] = action

    return {
        "session": {
            "sessionId": payload.get("sessionId") or "",
            "playbookId": payload.get("playbookId") or "",
            "reasoner": "fault-disposal-chat-skill",
        },
        "messages": [message],
        "toolCalls": [],
    }


def _run_resource_import_skill(command: str, payload: dict | None = None) -> dict:
    script_path = _resource_import_bridge_script()
    if not script_path.exists():
        raise FileNotFoundError(f"resource-import skill bridge not found: {script_path}")

    command_args = [sys.executable, str(script_path), command]
    context_file = None
    if payload is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            context_file = handle.name
        command_args.extend(["--context-file", context_file])

    try:
        completed = subprocess.run(
            command_args,
            cwd=str(_zgops_cmdb_import_skill_root()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=RESOURCE_IMPORT_SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    finally:
        if context_file:
            try:
                Path(context_file).unlink(missing_ok=True)
            except OSError:
                pass

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    if completed.returncode != 0:
        error_text = stderr_text or stdout_text or "resource-import skill bridge failed"
        raise RuntimeError(error_text)
    if not stdout_text:
        raise RuntimeError("resource-import skill bridge returned empty output")
    return json.loads(stdout_text)


def _run_fault_disposal_diagnose(payload: dict) -> dict:
    return _run_fault_disposal_chat_skill("diagnose", payload)


def _run_fault_disposal_execute(payload: dict) -> dict:
    return _run_fault_disposal_chat_skill("execute", payload)


def _run_alarm_metric_verification(
    *,
    metric_type: str,
    res_id: str,
    max_metrics: int = 5,
) -> dict[str, Any]:
    script_path = _alarm_analyst_metric_script()
    if not script_path.exists():
        raise FileNotFoundError(f"alarm-analyst metric script not found: {script_path}")

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--metric-type",
            metric_type,
            "--res-id",
            str(res_id),
            "--max-metrics",
            str(max(1, max_metrics)),
            "--output",
            "json",
        ],
        cwd=str(_alarm_analyst_skill_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=ALARM_ANALYST_SCRIPT_TIMEOUT_SECONDS,
        check=False,
    )
    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    if completed.returncode != 0 and not stdout_text:
        raise RuntimeError(stderr_text or "alarm-analyst metric query failed")
    if not stdout_text:
        raise RuntimeError("alarm-analyst metric query returned empty output")
    return json.loads(stdout_text)


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/resource-import/metadata")
async def get_resource_import_metadata(request: Request):
    try:
        return await asyncio.to_thread(_run_resource_import_skill, "metadata")
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_resource_import_metadata failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/resource-import/start")
async def get_resource_import_start_payload():
    try:
        return await asyncio.to_thread(_run_resource_import_skill, "start")
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_resource_import_start_payload failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/resource-import/preview")
async def preview_resource_import_flow(
    request: Request,
    files: list[UploadFile] = File(...),
):
    try:
        if not files:
            raise ValueError("至少需要上传一个文件")
        agent_id = _resolve_request_agent_id(request)
        temp_dir = tempfile.mkdtemp(prefix="resource-import-preview-")
        payload_files = []
        temp_root = Path(temp_dir)
        for index, upload in enumerate(files):
            filename = upload.filename or f"unnamed-{index}"
            target = temp_root / f"{index}-{Path(filename).name}"
            target.write_bytes(await upload.read())
            payload_files.append({"name": filename, "path": str(target)})

        job_id = uuid.uuid4().hex
        progress_file = temp_root / "preview-progress.jsonl"
        with RESOURCE_IMPORT_PREVIEW_JOBS_LOCK:
            RESOURCE_IMPORT_PREVIEW_JOBS[job_id] = {
                "status": "queued",
                "createdAt": _utc_now_iso(),
                "updatedAt": _utc_now_iso(),
                "agentId": agent_id,
                "tempDir": temp_dir,
                "progressFile": str(progress_file),
                "preview": None,
                "error": "",
            }

        asyncio.create_task(
            asyncio.to_thread(
                _run_preview_job,
                job_id,
                agent_id=agent_id,
                payload_files=payload_files,
                temp_dir=temp_dir,
            )
        )
        return _serialize_preview_job(job_id)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] preview_resource_import_flow failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/resource-import/preview/{job_id}")
async def get_preview_resource_import_flow(job_id: str):
    try:
        return _serialize_preview_job(job_id)
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_preview_resource_import_flow failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/resource-import/import")
async def import_resource_import_flow(
    payload: dict = Body(default_factory=dict),
):
    try:
        return await asyncio.to_thread(
            _run_resource_import_skill,
            "import",
            {"payload": payload},
        )
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] import_resource_import_flow failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/alarm-workorders")
async def get_alarm_workorders(limit: int = 5):
    try:
        return await asyncio.to_thread(query_alarm_workorders, max(1, limit))
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_alarm_workorders failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/real-alarms")
async def get_real_alarms(
    limit: int = 10,
):
    try:
        return query_portal_real_alarms(limit)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_real_alarms failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/real-alarms/trigger-sessions")
async def trigger_real_alarm_sessions(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    limit: int = Query(10),
):
    try:
        if not hasattr(request.app.state, "multi_agent_manager"):
            raise HTTPException(
                status_code=503,
                detail="MultiAgentManager not initialized",
            )

        alarms_payload = _build_portal_real_alarm_trigger_payload(limit, payload)
        summary = await _ensure_portal_real_alarm_sessions(request, alarms_payload)
        return {
            "ok": True,
            "alarmSource": alarms_payload.get("source") or "unknown",
            "alarmTotal": int(alarms_payload.get("total") or len(alarms_payload.get("items") or [])),
            **summary,
        }
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] trigger_real_alarm_sessions failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/inspection/trigger-sessions")
async def trigger_inspection_sessions(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
):
    try:
        if not hasattr(request.app.state, "multi_agent_manager"):
            raise HTTPException(
                status_code=503,
                detail="MultiAgentManager not initialized",
            )

        body = payload or {}
        inspection_object = str(
            body.get("inspectionObject")
            or body.get("inspection_object")
            or body.get("target")
            or ""
        ).strip()
        session_id = str(body.get("sessionId") or body.get("session_id") or "").strip()
        summary = await _ensure_portal_inspection_session(
            request,
            inspection_object=inspection_object,
            session_id=session_id,
        )
        return {
            "ok": True,
            **summary,
        }
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] trigger_inspection_sessions failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/employee-status")
async def get_portal_employee_statuses(
    request: Request,
    include_alert_count: bool = Query(True),
):
    try:
        employees = await collect_portal_employee_statuses(
            request,
            include_alert_count=include_alert_count,
        )
        return {
            "employees": employees,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_portal_employee_statuses failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/recovery-visualization")
async def get_fault_disposal_recovery_visualization(
    payload: dict = Body(default_factory=dict),
):
    try:
        operation = payload.get("operation") or {}
        recovery = payload.get("recovery") or {}
        if not isinstance(operation, dict) or not operation:
            raise ValueError("operation payload is required")

        (
            _CopawReasoner,
            TemplateReasoner,
            FaultDisposalToolbox,
            _TicketRouter,
            _TicketContext,
            _ApplicationTimeoutPlaybook,
            _GenericAlarmPlaybook,
        ) = _load_fault_disposal_runtime()
        toolbox = FaultDisposalToolbox()
        reasoner = TemplateReasoner()

        if not recovery:
            simulated_result, _ = toolbox.execute_kill_slow_sql(operation)
            recovery = simulated_result.get("recovery") or {}

        verification, _ = toolbox.collect_recovery_verification(operation, recovery)
        visualization = reasoner.build_recovery_visualization_payload(
            verification=verification,
            recovery=recovery,
        )
        return {
            "status": "ok",
            "visualization": visualization,
            "verification": verification,
            "recovery": recovery,
        }
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_fault_disposal_recovery_visualization failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/diagnose")
async def fault_disposal_diagnose(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise ValueError("sessionId is required")
        visible_content = str(payload.get("visibleContent") or "").strip()
        result = _run_fault_disposal_diagnose(payload)
        history = await _load_portal_fault_history(request, session_id=session_id)
        if visible_content:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": visible_content,
                    },
                )
            )
        for message in result.get("messages", []) or []:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        "type": "agent",
                        "content": message.get("content", ""),
                        "processBlocks": message.get("processBlocks", []),
                        "disposalOperation": message.get("action"),
                    },
                )
            )
        await _save_portal_fault_history(request, session_id=session_id, messages=history)
        return result
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] fault_disposal_diagnose failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/execute")
async def fault_disposal_execute(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise ValueError("sessionId is required")
        visible_content = str(payload.get("visibleContent") or "").strip()
        result = _run_fault_disposal_execute(payload)
        history = await _load_portal_fault_history(request, session_id=session_id)
        if visible_content:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": visible_content,
                    },
                )
            )
        for message in result.get("messages", []) or []:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        "type": "agent",
                        "content": message.get("content", ""),
                        "processBlocks": message.get("processBlocks", []),
                        "disposalOperation": message.get("action"),
                    },
                )
            )
        await _save_portal_fault_history(request, session_id=session_id, messages=history)
        return result
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] fault_disposal_execute failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/manual-workorders/dispatch")
async def dispatch_fault_manual_workorder(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        parsed = ManualWorkorderDispatchRequest.model_validate(payload)
        callback_url = str(
            request.url_for("notify_fault_manual_workorder_closed")
        )
        record = build_manual_workorder_record(parsed, callback_url=callback_url)
        records = await _load_portal_manual_workorders(request, session_id=parsed.chat_id)
        records[str(parsed.res_id)] = record
        await _save_portal_manual_workorders(
            request,
            session_id=parsed.chat_id,
            records=records,
        )

        history = await _load_portal_fault_history(request, session_id=parsed.chat_id)
        history.append(
            _compact_ui_message(
                {
                    "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                    **build_manual_dispatch_history_message(record),
                }
            )
        )
        await _save_portal_fault_history(request, session_id=parsed.chat_id, messages=history)

        return {
            "status": "pending_manual",
            "chatId": parsed.chat_id,
            "resId": parsed.res_id,
            "manualWorkorder": record,
            "dispatchRequest": record.get("dispatchPayload") or {},
        }
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] dispatch_fault_manual_workorder failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/manual-workorders/notify-closed", name="notify_fault_manual_workorder_closed")
async def notify_fault_manual_workorder_closed(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        parsed = ManualWorkorderCloseNotificationRequest.model_validate(payload)
        records = await _load_portal_manual_workorders(request, session_id=parsed.chat_id)
        record = records.get(str(parsed.res_id))
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"manual workorder not found for chatId={parsed.chat_id}, resId={parsed.res_id}",
            )

        metric_type = (
            str(parsed.metric_type or "").strip()
            or str(record.get("metricType") or "").strip()
            or "mysql"
        )
        metric_result = await asyncio.to_thread(
            _run_alarm_metric_verification,
            metric_type=metric_type,
            res_id=str(parsed.res_id),
        )
        verification = evaluate_metric_recovery(metric_result)
        merged_record = merge_manual_workorder_notification(
            record,
            parsed,
            verification=verification,
        )
        merged_record["metricType"] = metric_type
        records[str(parsed.res_id)] = merged_record
        await _save_portal_manual_workorders(
            request,
            session_id=parsed.chat_id,
            records=records,
        )

        history = await _load_portal_fault_history(request, session_id=parsed.chat_id)
        history.append(
            _compact_ui_message(
                {
                    "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                    **build_manual_close_history_message(
                        merged_record,
                        verification=verification,
                    ),
                }
            )
        )
        await _save_portal_fault_history(request, session_id=parsed.chat_id, messages=history)

        return {
            "status": verification.get("status") or "unknown",
            "chatId": parsed.chat_id,
            "resId": parsed.res_id,
            "manualWorkorder": merged_record,
            "verification": verification,
        }
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] notify_fault_manual_workorder_closed failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/alarm-analyst/diagnose")
async def portal_alarm_analyst_diagnose(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise HTTPException(status_code=422, detail="sessionId is required")

        result = _shape_fault_scenario_response(run_alarm_analyst_diagnose(payload))
        if hasattr(request.app.state, "multi_agent_manager"):
            history = await _load_portal_fault_history(request, session_id=session_id)
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": payload.get("content", ""),
                    }
                )
            )
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        "type": "agent",
                        "content": result["result"]["summary"],
                        "faultScenarioResult": result["result"],
                    }
                )
            )
            await _save_portal_fault_history(
                request,
                session_id=session_id,
                messages=history,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] portal_alarm_analyst_diagnose failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/alarm-analyst/cards")
async def create_portal_alarm_analyst_card(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        parsed = AlarmAnalystCardCreateRequest.model_validate(payload)
        matched = is_alarm_analyst_card_candidate(
            employee_id=parsed.employee_id,
            report_markdown=parsed.report_markdown,
            process_blocks=parsed.process_blocks,
        )
        if not matched:
            return AlarmAnalystCardCreateResponse(matched=False).model_dump(by_alias=True)

        card = build_alarm_analyst_card(
            chat_id=parsed.chat_id,
            message_id=parsed.message_id,
            employee_id=parsed.employee_id,
            report_markdown=parsed.report_markdown,
            process_blocks=parsed.process_blocks,
        )
        if hasattr(request.app.state, "multi_agent_manager"):
            records = await _load_portal_alarm_analyst_cards(
                request,
                session_id=parsed.session_id,
            )
            chat_records = dict(records.get(parsed.chat_id) or {})
            chat_records[parsed.message_id] = card.model_dump(by_alias=True)
            records = dict(records)
            records[parsed.chat_id] = chat_records
            await _save_portal_alarm_analyst_cards(
                request,
                session_id=parsed.session_id,
                records=records,
            )
        return AlarmAnalystCardCreateResponse(
            matched=True,
            card=card,
        ).model_dump(by_alias=True)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] create_portal_alarm_analyst_card failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/alarm-analyst/cards/{chat_id}")
async def list_portal_alarm_analyst_cards(
    request: Request,
    chat_id: str,
    session_id: str = Query(..., alias="sessionId"),
):
    try:
        if not hasattr(request.app.state, "multi_agent_manager"):
            return AlarmAnalystCardListResponse(cards=[]).model_dump(by_alias=True)
        records = await _load_portal_alarm_analyst_cards(request, session_id=session_id)
        cards = _list_alarm_analyst_cards_for_chat(records, chat_id)
        return AlarmAnalystCardListResponse(
            cards=[AlarmAnalystCard.model_validate(card) for card in cards],
        ).model_dump(by_alias=True)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] list_portal_alarm_analyst_cards failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/fault-disposal/history/{session_id}")
async def fault_disposal_history(
    request: Request,
    session_id: str,
):
    try:
        history = await _load_portal_fault_history(request, session_id=session_id)
        return {
            "messages": _normalize_portal_fault_history_messages(history),
            "status": "idle",
        }
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] fault_disposal_history failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/health")
def get_knowledge_base_health():
    try:
        return knowledge_base.health()
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_knowledge_base_health failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/query")
def query_knowledge_base(payload: dict[str, Any] | None = Body(default=None)):
    try:
        return knowledge_base.query_knowledge(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] query_knowledge_base failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/rag-synthesize")
async def synthesize_knowledge_base_answer(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
):
    try:
        return await knowledge_base.synthesize_answer(
            payload,
            agent_id=request.headers.get("X-Agent-Id") or "knowledge",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] synthesize_knowledge_base_answer failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/sources")
def list_knowledge_base_sources(
    limit: int = Query(50),
    offset: int = Query(0),
    include_archived: bool = Query(False),
    source_scope: str = "",
    source_type: str = "",
    builtin_pack_id: str = "",
    filename: str = "",
):
    try:
        return knowledge_base.list_sources(
            limit=limit,
            offset=offset,
            include_archived=include_archived,
            filters={
                "source_scope": source_scope,
                "source_type": source_type,
                "builtin_pack_id": builtin_pack_id,
                "filename": filename,
            },
        )
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] list_knowledge_base_sources failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/sources/{source_record_id}")
def get_knowledge_base_source_detail(
    source_record_id: int,
    include_archived: bool = Query(False),
):
    try:
        return knowledge_base.source_detail(
            source_record_id,
            include_archived=include_archived,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_knowledge_base_source_detail failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/manual-entry")
def create_knowledge_base_manual_entry(payload: dict[str, Any] | None = Body(default=None)):
    try:
        return knowledge_base.manual_entry(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] create_knowledge_base_manual_entry failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/sources/update")
def update_knowledge_base_source(payload: dict[str, Any] | None = Body(default=None)):
    try:
        return knowledge_base.update_source(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] update_knowledge_base_source failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/sources/archive")
def archive_knowledge_base_sources(payload: dict[str, Any] | None = Body(default=None)):
    try:
        return knowledge_base.archive_sources(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] archive_knowledge_base_sources failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/sources/unarchive")
def unarchive_knowledge_base_sources(payload: dict[str, Any] | None = Body(default=None)):
    try:
        return knowledge_base.unarchive_sources(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] unarchive_knowledge_base_sources failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/embedding/toggle")
def toggle_knowledge_base_embedding(payload: dict[str, Any] | None = Body(default=None)):
    try:
        return knowledge_base.set_embedding_enabled(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] toggle_knowledge_base_embedding failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/embeddings/reindex")
def reindex_knowledge_base_embeddings(force: bool = Query(False)):
    try:
        return knowledge_base.reindex_embeddings(force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] reindex_knowledge_base_embeddings failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/ingest")
async def ingest_knowledge_base_file(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        return knowledge_base.create_ingest_job(
            file.filename or "",
            raw,
            file.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] ingest_knowledge_base_file failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/ingestion-jobs")
def list_knowledge_base_ingestion_jobs(limit: int = Query(20)):
    try:
        return knowledge_base.ingestion_jobs(limit=limit)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] list_knowledge_base_ingestion_jobs failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/ingestion-jobs/{job_id}/progress")
def get_knowledge_base_ingestion_progress(job_id: str):
    try:
        return knowledge_base.ingestion_progress(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_knowledge_base_ingestion_progress failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/source-summary")
def get_knowledge_base_source_summary():
    try:
        return knowledge_base.source_summary()
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_knowledge_base_source_summary failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/units")
def list_knowledge_base_units(
    limit: int = Query(50),
    include_archived: bool = Query(False),
    source_scope: str = "",
    source_type: str = "",
    builtin_pack_id: str = "",
    filename: str = "",
):
    try:
        return knowledge_base.units(
            limit=limit,
            include_archived=include_archived,
            filters={
                "source_scope": source_scope,
                "source_type": source_type,
                "builtin_pack_id": builtin_pack_id,
                "filename": filename,
            },
        )
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] list_knowledge_base_units failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/builtin-packs")
def list_knowledge_base_builtin_packs():
    try:
        return knowledge_base.builtin_packs()
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] list_knowledge_base_builtin_packs failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/builtin-packs/reload")
def reload_knowledge_base_builtin_packs(payload: dict[str, Any] | None = Body(default=None)):
    try:
        return knowledge_base.reload_builtin_pack(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] reload_knowledge_base_builtin_packs failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


def register_app_routes(fastapi_app) -> None:
    """Register portal routes on the main QwenPaw FastAPI app."""
    if not getattr(fastapi_app.state, "portal_api_compat_installed", False):
        @fastapi_app.middleware("http")
        async def portal_api_compat_middleware(request: Request, call_next):
            path = request.scope.get("path", "")
            if isinstance(path, str) and path.startswith("/portal-api/"):
                request.scope["path"] = f"/api/portal{path[len('/portal-api'):]}"
            return await call_next(request)

        fastapi_app.state.portal_api_compat_installed = True

    fastapi_app.include_router(router)


app.include_router(router)
