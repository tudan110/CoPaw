# -*- coding: utf-8 -*-
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import (
    APIRouter,
    Body,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from qwenpaw.extensions.api.alarm_analyst_card_models import (
    AlarmAnalystCard,
    AlarmAnalystCardCreateRequest,
    AlarmAnalystCardCreateResponse,
    AlarmAnalystCardListResponse,
)
from qwenpaw.extensions.api.alarm_analyst_card_service import (
    build_alarm_analyst_card,
    extract_display_fields as extract_card_display_fields,
    is_alarm_analyst_card_candidate,
)
from qwenpaw.extensions.api.natural_language_customization_api import (
    router as nl_customization_router,
)
from qwenpaw.extensions.api.ai_big_screen_api import (
    router as ai_big_screen_router,
)
from qwenpaw.extensions.api.notification_settings_api import (
    router as notification_settings_router,
)
from qwenpaw.extensions.api.light_apps_api import (
    router as light_apps_router,
)
from qwenpaw.extensions.api.app_artifacts_api import (
    router as app_artifacts_router,
)
from qwenpaw.extensions.api.agent_reports import (
    router as agent_reports_router,
)
from qwenpaw.extensions.api.qiming_openai_adapter import (
    router as qiming_openai_adapter_router,
)
from qwenpaw.extensions.api.xingchen_openai_adapter import (
    router as xingchen_openai_adapter_router,
)
from qwenpaw.extensions.api.proxy_api import (
    router as proxy_router,
)
from qwenpaw.extensions.api.sso_backend import (
    router as sso_router,
)
from qwenpaw.config.utils import load_config
from qwenpaw.extensions.api.fault_manual_workorder_models import (
    ManualWorkorderCloseNotificationRequest,
    ManualWorkorderDispatchRequest,
)
from qwenpaw.extensions.api.fault_manual_workorder_service import (
    build_analysis_close_history_message,
    build_analysis_dispatch_history_message,
    build_analysis_record,
    evaluate_metric_recovery,
    merge_manual_workorder_notification,
)
from qwenpaw.extensions.api.alarm_analyst_service import (
    run_alarm_analyst_diagnose,
)
from qwenpaw.extensions.api.alarm_clear_models import (
    AlarmClearNotificationRequest,
)
from qwenpaw.extensions.api.recovery_verification_service import (
    build_recovery_history_message,
    decide_observation_outcome,
    decide_verification_outcome,
    send_recovery_notification_safe,
)
from qwenpaw.extensions.portal_alarm_clear_events import (
    fetch_due_clear_events,
    list_clear_events,
    local_now as clear_events_local_now,
    record_clear_notification,
    reset_zombie_verifying_events,
    update_clear_event,
)
from qwenpaw.extensions.portal_real_alarm_registry import (
    filter_visible_alarms,
    get_alarm_record,
    load_alarm_records,
    reset_zombie_analyzing_records,
    update_alarm_record,
)
from qwenpaw.extensions.portal_alarm_analyst_card_store import (
    load_cards_for_chat as _load_cards_for_chat_from_db,
    save_card as _save_card_to_db,
)
from qwenpaw.extensions.integrations.alarm_workorders.query_alarm_workorders import (
    query_alarm_workorders,
)
from qwenpaw.extensions.integrations.portal_real_alarms import (
    MAX_REAL_ALARM_LIMIT,
    build_empty_portal_real_alarms_payload,
    filter_alarms_started_after,
    query_portal_real_alarms,
    query_real_alarm_active_status,
)
from qwenpaw.extensions.integrations.portal_monitoring_overview import (
    query_active_alarm_total as query_monitoring_active_alarm_total,
    query_alarm_top5 as query_monitoring_alarm_top5,
    query_asset_overview as query_monitoring_asset_overview,
    query_topology as query_monitoring_topology,
    query_workorder_stats as query_monitoring_workorder_stats,
    query_severity_trend as query_monitoring_severity_trend,
    query_cmdb_summary as query_monitoring_cmdb_summary,
)
from qwenpaw.extensions.integrations import knowledge_base
from qwenpaw.extensions.api import diagnosis_settings_store
from qwenpaw.extensions.api import inoe_settings_store
from qwenpaw.extensions.api import qiming_settings_store
from qwenpaw.extensions.api import xingchen_settings_store
from qwenpaw.extensions.api import zgops_settings_store
from qwenpaw.extensions.api import operator_settings_store
from qwenpaw.extensions.api import order_settings_store
from qwenpaw.extensions.api import resource_import_llm_settings_api
from qwenpaw.extensions.api import n9e_settings_store
from qwenpaw.extensions.api import fde_workbench_service
from qwenpaw.extensions.api.fde_workbench_models import (
    FdeCopyInstalledRequest,
    FdeEditFieldsRequest,
    FdeEditFilesRequest,
    FdeEnvWriteRequest,
    FdeGenerateRequest,
    FdeInstallRequest,
    FdeProbeRequest,
    FdeReviewRequest,
)
from qwenpaw.app.agent_context import get_agent_for_request
from qwenpaw.app.channels.base import ContentType, TextContent

router = APIRouter(prefix="/api/portal", tags=["portal"])
router.include_router(nl_customization_router)
router.include_router(ai_big_screen_router)
router.include_router(notification_settings_router)
router.include_router(app_artifacts_router)
router.include_router(light_apps_router)
router.include_router(agent_reports_router)
router.include_router(qiming_openai_adapter_router)
router.include_router(xingchen_openai_adapter_router)
router.include_router(proxy_router)
router.include_router(sso_router)
app = FastAPI(title="Portal Backend")
FAULT_DISPOSAL_SCRIPT_TIMEOUT_SECONDS = 45
PORTAL_REAL_ALARM_ROUTE_DEFAULT_LIMIT = 20
PORTAL_REAL_ALARM_ROUTE_FETCH_MULTIPLIER = 3
PORTAL_REAL_ALARM_ROUTE_TIMEOUT_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_REAL_ALARM_ROUTE_TIMEOUT", "5").strip() or "5",
)
PORTAL_REAL_ALARM_CACHE_TTL_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_REAL_ALARM_CACHE_TTL", "30").strip() or "30",
)
PORTAL_REAL_ALARM_DEGRADED_COOLDOWN_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_REAL_ALARM_DEGRADED_COOLDOWN", "30").strip()
    or "30",
)
PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED = os.getenv(
    "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED",
    "true",
).strip().lower() not in {"0", "false", "off", "no"}
PORTAL_REAL_ALARM_AUTO_TAKEOVER_MIN_INTERVAL_SECONDS = 60.0
PORTAL_REAL_ALARM_AUTO_TAKEOVER_INTERVAL_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_INTERVAL", "60").strip()
    or "60",
)
PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT = int(
    os.getenv("QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT", "100").strip()
    or "100",
)
PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES = max(
    1,
    int(
        os.getenv("QWENPAW_PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES", "1").strip()
        or "1",
    ),
)
PORTAL_REAL_ALARM_DEDUP_WINDOW_SECONDS = 120.0
_portal_real_alarm_last_sent: dict[str, float] = {}
PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK: asyncio.Task | None = None
# Set to interrupt the auto-takeover loop's sleep, so flipping the
# real-time-analysis switch on starts a round immediately instead of
# waiting out the polling interval.
PORTAL_REAL_ALARM_WAKE_EVENT: asyncio.Event | None = None
PORTAL_REAL_ALARM_REFRESH_TASK: asyncio.Task | None = None
PORTAL_REAL_ALARM_REFRESH_LIMIT = 0
PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC = 0.0
PORTAL_REAL_ALARM_PAYLOAD_CACHE: dict[str, Any] = {
    "payload": None,
    "limit": 0,
    "updated_at": 0.0,
}
PORTAL_EMPLOYEE_STATUS_IDS = (
    "query",
    "fault",
    "knowledge",
    "resource",
    "inspection",
    "order",
)
PORTAL_EMPLOYEE_STATUS_NAMES = {
    "query": "数据分析专家",
    "fault": "故障分析专家",
    "knowledge": "知识库助手",
    "resource": "资产管理专员",
    "inspection": "运维巡检专员",
    "order": "工单处置专员",
}
PORTAL_FAULT_ALERT_LIMIT = 20
PORTAL_EMPLOYEE_STATUS_ALERT_COUNT_ENABLED = os.getenv(
    "QWENPAW_PORTAL_EMPLOYEE_STATUS_ALERT_COUNT_ENABLED",
    "true",
).strip().lower() not in {"0", "false", "off", "no"}
PORTAL_STATUS_ALERT_TIMEOUT_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_STATUS_ALERT_TIMEOUT", "4").strip() or "4",
)
PORTAL_STATUS_ALERT_FAST_TIMEOUT_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_STATUS_ALERT_FAST_TIMEOUT", "0.4").strip()
    or "0.4",
)
PORTAL_STATUS_ALERT_CACHE_TTL_SECONDS = float(
    os.getenv("QWENPAW_PORTAL_STATUS_ALERT_CACHE_TTL", "30").strip() or "30",
)
PORTAL_STATUS_ALERT_COUNT_CACHE: dict[str, Any] = {
    "value": 0,
    "updated_at": 0.0,
}
PORTAL_STATUS_ALERT_COUNT_REFRESH_TASK: asyncio.Task | None = None
RESOURCE_IMPORT_SCRIPT_TIMEOUT_SECONDS = int(
    os.environ.get("RESOURCE_IMPORT_SCRIPT_TIMEOUT_SECONDS", "1800"),
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
    from runtime.playbooks import (
        ApplicationTimeoutPlaybook,
        GenericAlarmPlaybook,
    )

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


def _resolve_workspace_skill_root(workspace: str, skill: str) -> Path:
    """Resolve a workspace skill directory.

    These skills ship under ``deploy-all/qwenpaw/working/workspaces`` in the
    repo, but at runtime they are copied into ``$QWENPAW_WORKING_DIR``
    (e.g. ``/app/working`` in the container). The installed package lives in
    site-packages, so a path computed relative to ``__file__`` would point
    into the venv where the skill does not exist. Prefer the working-dir copy
    (the same one the agent loads), then fall back to the repo bundle.
    """
    from qwenpaw import constant

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


def _zgops_cmdb_query_skill_root() -> Path:
    return _resolve_workspace_skill_root("query", "zgops-cmdb")


def _zgops_cmdb_import_skill_root() -> Path:
    return _resolve_workspace_skill_root("resource", "zgops-cmdb-import")


def _resource_import_bridge_script() -> Path:
    return (
        _zgops_cmdb_import_skill_root()
        / "scripts"
        / "resource_import_bridge.py"
    )


def _skill_subprocess_env() -> dict[str, str]:
    """Environment for skill-bridge subprocesses.

    Forces UTF-8 stdio in the child so the parent — which decodes stdout as
    UTF-8 — does not hit a ``UnicodeDecodeError`` on Windows, where a child
    Python's piped stdout otherwise defaults to the locale codec (e.g. GBK).
    Without this, any Chinese text in the bridge output makes the reader
    thread crash, ``subprocess.run`` returns empty stdout, and the caller
    raises "skill bridge returned empty output".
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _alarm_analyst_skill_root() -> Path:
    return _resolve_workspace_skill_root("fault", "alarm-analyst")


def _alarm_analyst_metric_script() -> Path:
    return (
        _alarm_analyst_skill_root() / "scripts" / "get_metric_definitions.py"
    )


def _compact_ui_message(message: dict) -> dict:
    compact_message = dict(message)
    compact_message["id"] = message.get("id")
    compact_message["type"] = message.get("type")
    compact_message["content"] = message.get("content", "")
    compact_message["processBlocks"] = message.get("processBlocks", []) or []
    compact_message["disposalOperation"] = message.get("disposalOperation")
    compact_message["faultScenarioResult"] = _shape_fault_scenario_result(
        message.get("faultScenarioResult"),
    )
    compact_message["timestamp"] = (
        message.get("timestamp") or datetime.now(timezone.utc).isoformat()
    )
    return compact_message


def _resolve_request_agent_id(request: Request) -> str:
    target_agent_id = getattr(
        request.state,
        "agent_id",
        None,
    ) or request.headers.get("X-Agent-Id")
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
    severity_map = {
        "1": "紧急",
        "2": "严重",
        "3": "普通",
        "4": "预警",
        "critical": "紧急",
        "urgent": "严重",
        "warning": "普通",
        "info": "预警",
    }
    raw_severity = str(
        alarm.get("alarmseverity") or alarm.get("level") or "",
    ).strip()
    severity_label = severity_map.get(raw_severity, raw_severity)
    severity_line = (
        f"告警等级：{raw_severity}（{severity_label}）"
        if raw_severity and severity_label != raw_severity
        else f"告警等级：{severity_label}"
        if raw_severity
        else ""
    )
    lines = [
        f"{title}（{device_name} {manage_ip}）",
        f"告警流水号：{str(alarm.get('alarmId') or alarm.get('id') or '').strip()}",
        f"资源 ID（CI ID）：{str(alarm.get('resId') or '').strip()}",
        severity_line,
        f"告警时间：{str(alarm.get('eventTime') or '').strip()}",
        f"告警摘要：{str(alarm.get('visibleContent') or '').strip()}",
        "请分析这条活动告警，并继续完成异常指标分析、根因分析、影响范围判断、处置建议与通知推送。",
        "通知推送内容的章节顺序必须严格按照：异常指标 → 根因方向 → 处置建议。不允许调换顺序，不可省略异常指标。",
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


def _build_portal_real_alarm_payload(
    session_id: str,
    alarm: dict[str, Any],
) -> dict[str, Any]:
    return {
        "channel_id": PORTAL_REAL_ALARM_CONSOLE_CHANNEL,
        "sender_id": PORTAL_REAL_ALARM_USER_ID,
        "content_parts": [
            TextContent(
                type=ContentType.TEXT,
                text=_build_portal_real_alarm_prompt(alarm),
            ),
        ],
        "meta": {
            "session_id": session_id,
            "user_id": PORTAL_REAL_ALARM_USER_ID,
        },
    }


def _build_portal_inspection_payload(
    session_id: str,
    inspection_object: str,
) -> dict[str, Any]:
    return {
        "channel_id": PORTAL_INSPECTION_CONSOLE_CHANNEL,
        "sender_id": PORTAL_INSPECTION_USER_ID,
        "content_parts": [
            TextContent(
                type=ContentType.TEXT,
                text=_build_portal_inspection_prompt(inspection_object),
            ),
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
    session_id: str = "",
) -> None:
    chunks: list[str] = []
    stream_it = task_tracker.stream_from_queue(queue, chat_id)
    try:
        async for chunk in stream_it:
            chunks.append(chunk)
    except Exception:
        print(
            f"[WARN] drain portal real alarm stream failed for chat_id={chat_id}",
        )
        traceback.print_exc()
    finally:
        await stream_it.aclose()
    _update_portal_real_alarm_registry_safe(
        chat_id=chat_id,
        status="analyzed",
        source="auto-stream-done",
    )
    if session_id and chunks:
        _try_persist_analysis_result_from_stream(
            chunks=chunks,
            chat_id=chat_id,
            session_id=session_id,
        )


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
        raise HTTPException(
            status_code=400,
            detail="inspectionObject is required",
        )

    workspace = await _get_portal_employee_workspace(request, "inspection")
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail="Inspection workspace not available",
        )

    console_channel = await workspace.channel_manager.get_channel(
        PORTAL_INSPECTION_CONSOLE_CHANNEL,
    )
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Inspection console channel not available",
        )

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
                and str(item.channel or "")
                == PORTAL_INSPECTION_CONSOLE_CHANNEL
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

        existing_state = await workspace.session.get_session_state_dict(
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
            _build_portal_inspection_payload(
                final_session_id,
                normalized_object,
            ),
            console_channel.stream_one,
        )
        if started:
            result["started"] = 1
            asyncio.create_task(
                _drain_portal_real_alarm_stream(
                    workspace.task_tracker,
                    queue,
                    chat.id,
                ),
            )
        else:
            result["skipped"] = 1

    return result


async def _ensure_portal_real_alarm_sessions(
    request: Request,
    alarms_payload: dict[str, Any],
    *,
    takeover_source: str = "manual-trigger",
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
        PORTAL_REAL_ALARM_CONSOLE_CHANNEL,
    )
    if console_channel is None:
        return result

    async with PORTAL_REAL_ALARM_ENSURE_LOCK:
        chats = await workspace.chat_manager.list_chats()
        chats_by_session = {
            str(chat.session_id): chat
            for chat in chats
            if str(chat.session_id or "").startswith(
                PORTAL_REAL_ALARM_SESSION_PREFIX,
            )
        }
        active_alarm_analyses = 0
        for chat in chats_by_session.values():
            if await workspace.task_tracker.get_status(chat.id) == "running":
                active_alarm_analyses += 1
        start_budget = max(
            0,
            diagnosis_settings_store.resolve_int(
                "max_active_analyses",
                "QWENPAW_PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES",
                PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES,
                min_value=1,
            )
            - active_alarm_analyses,
        )

        for alarm in items:
            if not isinstance(alarm, dict):
                continue
            if str(alarm.get("employeeId") or "").strip() not in {"", "fault"}:
                continue

            alarm_id = str(
                alarm.get("alarmId") or alarm.get("id") or "",
            ).strip()
            if not alarm_id:
                continue

            result["eligible"] += 1
            session_id = _build_portal_real_alarm_session_id(alarm)
            result["sessions"].append(session_id)
            chat = chats_by_session.get(session_id)
            is_new_chat = chat is None
            should_start = is_new_chat
            current_status = ""
            has_history = False
            if chat is not None:
                current_status = await workspace.task_tracker.get_status(
                    chat.id,
                )
                if current_status == "idle":
                    state = await workspace.session.get_session_state_dict(
                        chat.session_id,
                        chat.user_id,
                    )
                    has_history = _portal_real_alarm_has_history(state)
                    if has_history:
                        _portal_real_alarm_last_sent.pop(session_id, None)
                        should_start = False
                    else:
                        # No AI reply yet – check dedup window to decide
                        # whether this is a stuck session (allow retry) or
                        # a message that was just sent (skip duplicate).
                        last_sent = _portal_real_alarm_last_sent.get(
                            session_id,
                            0.0,
                        )
                        elapsed = time.monotonic() - last_sent
                        should_start = (
                            elapsed > PORTAL_REAL_ALARM_DEDUP_WINDOW_SECONDS
                        )
                else:
                    should_start = False

            if should_start and start_budget <= 0:
                result["skipped"] += 1
                continue

            if should_start and chat is None:
                chat = await workspace.chat_manager.get_or_create_chat(
                    session_id,
                    PORTAL_REAL_ALARM_USER_ID,
                    PORTAL_REAL_ALARM_CONSOLE_CHANNEL,
                    name=_build_portal_real_alarm_chat_name(alarm),
                )
                chats_by_session[session_id] = chat
                result["created"] += 1

            if not should_start:
                registry_status = (
                    "analyzing"
                    if current_status == "running"
                    else "taken_over"
                )
                if (
                    not is_new_chat
                    or has_history
                    or current_status == "running"
                ):
                    _update_portal_real_alarm_registry_safe(
                        alarm=alarm,
                        status=registry_status,
                        session_id=session_id,
                        chat_id=chat.id if chat is not None else "",
                        res_id=str(alarm.get("resId") or "").strip(),
                        source=takeover_source,
                    )
                result["skipped"] += 1
                continue

            queue, started = await workspace.task_tracker.attach_or_start(
                chat.id,
                _build_portal_real_alarm_payload(session_id, alarm),
                console_channel.stream_one,
            )
            # Record send time for dedup window
            _portal_real_alarm_last_sent[session_id] = time.monotonic()
            if started:
                _update_portal_real_alarm_registry_safe(
                    alarm=alarm,
                    status="analyzing",
                    session_id=session_id,
                    chat_id=chat.id,
                    res_id=str(alarm.get("resId") or "").strip(),
                    source=takeover_source,
                )
                start_budget -= 1
                result["started"] += 1
                asyncio.create_task(
                    _drain_portal_real_alarm_stream(
                        workspace.task_tracker,
                        queue,
                        chat.id,
                        session_id=session_id,
                    ),
                )
            else:
                _update_portal_real_alarm_registry_safe(
                    alarm=alarm,
                    status="taken_over",
                    session_id=session_id,
                    chat_id=chat.id,
                    res_id=str(alarm.get("resId") or "").strip(),
                    source=takeover_source,
                )
                result["skipped"] += 1

    return result


async def _build_portal_real_alarm_trigger_payload(
    limit: int,
    trigger_body: dict[str, Any] | None,
    *,
    allow_stale: bool = True,
) -> dict[str, Any]:
    body = trigger_body or {}
    alarms = body.get("alarms")
    if alarms is None:
        return await _get_visible_portal_real_alarms(
            limit,
            timeout_seconds=PORTAL_REAL_ALARM_ROUTE_TIMEOUT_SECONDS,
            require_fresh=True,
            allow_stale=allow_stale,
        )
    if not isinstance(alarms, list):
        raise HTTPException(status_code=400, detail="'alarms' must be a list")
    return filter_visible_alarms(
        {
            "total": len(alarms),
            "items": alarms,
            "source": "request",
        },
    )


def _get_portal_auto_takeover_runtime_app() -> FastAPI | None:
    candidates: list[FastAPI] = []
    if isinstance(app, FastAPI):
        candidates.append(app)
    try:
        from qwenpaw.app._app import app as main_app
    except Exception:
        main_app = None
    if isinstance(main_app, FastAPI):
        candidates.append(main_app)

    seen_ids: set[int] = set()
    for candidate in candidates:
        if id(candidate) in seen_ids:
            continue
        seen_ids.add(id(candidate))
        if hasattr(candidate.state, "multi_agent_manager"):
            return candidate
    return None


async def _run_portal_real_alarm_auto_takeover_once() -> dict[str, Any]:
    runtime_app = _get_portal_auto_takeover_runtime_app()
    if runtime_app is None:
        return {
            "ok": False,
            "reason": "runtime-unavailable",
            "alarmTotal": 0,
            "eligible": 0,
            "created": 0,
            "started": 0,
            "skipped": 0,
            "sessions": [],
        }

    takeover_limit = diagnosis_settings_store.resolve_int(
        "auto_takeover_limit",
        "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT",
        PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT,
        min_value=1,
    )
    anchor = diagnosis_settings_store.get_analysis_anchor()
    # The visible-alarm payload sorts ascending by event time and slices
    # to the limit, i.e. it keeps the OLDEST alarms. With the analysis
    # window active that would let old out-of-window alarms crowd the
    # newest ones out of the slice and the round would see 0 eligible —
    # so fetch up to the INOE page cap first, window-filter, and only
    # then truncate to the per-round takeover limit.
    fetch_limit = (
        MAX_REAL_ALARM_LIMIT if anchor is not None else takeover_limit
    )
    alarms_payload = await _build_portal_real_alarm_trigger_payload(
        fetch_limit,
        None,
        allow_stale=False,
    )
    if alarms_payload.get("source") != "live":
        return {
            "ok": False,
            "reason": "alarm-source-unavailable",
            "alarmSource": alarms_payload.get("source") or "unknown",
            "alarmTotal": 0,
            "eligible": 0,
            "created": 0,
            "started": 0,
            "skipped": 0,
            "sessions": [],
        }
    # Analysis window: only alarms born after "the moment real-time
    # analysis was switched on, minus the configured lookback hours" are
    # auto-analyzed. The portal alarm list and manual takeover are not
    # affected. Without an anchor (legacy state) behaviour is unchanged.
    if anchor is not None:
        lookback_hours = diagnosis_settings_store.resolve_float(
            "analysis_lookback_hours",
            "QWENPAW_PORTAL_REAL_ALARM_LOOKBACK_HOURS",
            0,
            min_value=0,
            max_value=720,
        )
        alarms_payload = filter_alarms_started_after(
            alarms_payload,
            anchor - timedelta(hours=lookback_hours),
        )
        eligible_items = list(alarms_payload.get("items") or [])
        if len(eligible_items) > takeover_limit:
            alarms_payload = {
                **alarms_payload,
                "items": eligible_items[:takeover_limit],
                "total": takeover_limit,
            }
    summary = await _ensure_portal_real_alarm_sessions(
        SimpleNamespace(app=runtime_app),
        alarms_payload,
        takeover_source="auto-poll",
    )
    return {
        "ok": True,
        "alarmSource": alarms_payload.get("source") or "unknown",
        "alarmTotal": int(
            alarms_payload.get("total")
            or len(alarms_payload.get("items") or []),
        ),
        **summary,
    }


def _portal_real_alarm_auto_takeover_enabled() -> bool:
    """Runtime master switch: page (DB) override wins over env."""
    return diagnosis_settings_store.resolve_bool(
        "auto_takeover_enabled",
        "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED",
        PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED,
    )


def _portal_real_alarm_auto_takeover_interval() -> float:
    return diagnosis_settings_store.resolve_float(
        "auto_takeover_interval_seconds",
        "QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_INTERVAL",
        PORTAL_REAL_ALARM_AUTO_TAKEOVER_INTERVAL_SECONDS,
        min_value=PORTAL_REAL_ALARM_AUTO_TAKEOVER_MIN_INTERVAL_SECONDS,
    )


def _portal_real_alarm_list_limit() -> int:
    """Max alarms in the portal list / status badge count."""
    return diagnosis_settings_store.resolve_int(
        "alarm_list_limit",
        "QWENPAW_PORTAL_REAL_ALARM_LIST_LIMIT",
        PORTAL_REAL_ALARM_ROUTE_DEFAULT_LIMIT,
        min_value=1,
        max_value=200,
    )


def _get_portal_real_alarm_wake_event() -> asyncio.Event:
    global PORTAL_REAL_ALARM_WAKE_EVENT
    if PORTAL_REAL_ALARM_WAKE_EVENT is None:
        PORTAL_REAL_ALARM_WAKE_EVENT = asyncio.Event()
    return PORTAL_REAL_ALARM_WAKE_EVENT


def _wake_portal_real_alarm_auto_takeover() -> None:
    """Interrupt the loop's sleep so the next round starts right away."""
    _get_portal_real_alarm_wake_event().set()


async def _portal_real_alarm_auto_takeover_loop() -> None:
    # The loop runs for the whole app lifetime; the master switch is
    # checked every iteration so toggling it on the settings page takes
    # effect without a restart. When disabled we only sleep — no alarm
    # query, no model call, no token spend.
    while True:
        try:
            if _portal_real_alarm_auto_takeover_enabled():
                if diagnosis_settings_store.get_analysis_anchor() is None:
                    # First enabled iteration (e.g. enabled via env at
                    # startup): anchor "now" so only alarms born from
                    # this point on (minus lookback) get analyzed.
                    diagnosis_settings_store.set_analysis_anchor(
                        datetime.now(timezone.utc),
                    )
                summary = await _run_portal_real_alarm_auto_takeover_once()
                if summary.get("started") or summary.get("created"):
                    print(
                        "[INFO] portal real alarm auto takeover: "
                        f"created={summary.get('created', 0)} "
                        f"started={summary.get('started', 0)} "
                        f"skipped={summary.get('skipped', 0)}",
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                "[WARN] portal real alarm auto takeover failed: "
                f"{type(exc).__name__}: {exc}",
            )
            traceback.print_exc()
        # Interruptible sleep: a wake event (switch flipped on) cuts the
        # wait short so the first round runs immediately.
        wake_event = _get_portal_real_alarm_wake_event()
        wake_event.clear()
        try:
            await asyncio.wait_for(
                wake_event.wait(),
                timeout=max(
                    PORTAL_REAL_ALARM_AUTO_TAKEOVER_MIN_INTERVAL_SECONDS,
                    _portal_real_alarm_auto_takeover_interval(),
                ),
            )
        except asyncio.TimeoutError:
            pass


@router.on_event("startup")
async def start_portal_real_alarm_auto_takeover() -> None:
    global PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK

    # Reset zombie records stuck in 'analyzing' from previous unclean shutdown
    try:
        reset_count = reset_zombie_analyzing_records()
        if reset_count > 0:
            print(
                f"[INFO] portal real alarm startup: reset {reset_count} zombie "
                f"'analyzing' record(s) to pending_retry",
            )
    except Exception:
        traceback.print_exc()

    # The loop always starts; the master switch (env or page override) is
    # evaluated inside the loop on every iteration, so it can be toggled at
    # runtime from the settings page without restarting the app.
    if (
        PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK is not None
        and not PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK.done()
    ):
        return
    PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK = asyncio.create_task(
        _portal_real_alarm_auto_takeover_loop(),
    )


@router.on_event("shutdown")
async def stop_portal_real_alarm_auto_takeover() -> None:
    global PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK

    task = PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK
    PORTAL_REAL_ALARM_AUTO_TAKEOVER_TASK = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Recovery verification for INOE alarm-clear notifications
# ---------------------------------------------------------------------------
#
# INOE pushes a notification when an alarm is cleared on their side. We
# persist it as an alarm_clear_events row and let the background loop
# below verify (INOE recheck + metric check + recurrence observation)
# that the underlying problem actually recovered. The webhook handler
# itself only validates and stores, so INOE's call returns fast.

RECOVERY_VERIFICATION_TASK: asyncio.Task | None = None
RECOVERY_VERIFICATION_LOOP_INTERVAL_SECONDS = 30.0


def _recovery_verification_enabled() -> bool:
    return diagnosis_settings_store.resolve_bool(
        "recovery_verification_enabled",
        "QWENPAW_RECOVERY_VERIFICATION_ENABLED",
        True,
    )


def _recovery_verification_settings() -> dict[str, Any]:
    return {
        "delay_seconds": diagnosis_settings_store.resolve_float(
            "recovery_verify_delay_seconds",
            "QWENPAW_RECOVERY_VERIFY_DELAY",
            120,
            min_value=0,
        ),
        "retry_count": diagnosis_settings_store.resolve_int(
            "recovery_verify_retry_count",
            "QWENPAW_RECOVERY_VERIFY_RETRY_COUNT",
            3,
            min_value=0,
        ),
        "retry_interval_seconds": diagnosis_settings_store.resolve_float(
            "recovery_verify_retry_interval_seconds",
            "QWENPAW_RECOVERY_VERIFY_RETRY_INTERVAL",
            300,
            min_value=10,
        ),
        "observation_minutes": diagnosis_settings_store.resolve_float(
            "recovery_observation_minutes",
            "QWENPAW_RECOVERY_OBSERVATION_MINUTES",
            30,
            min_value=0,
        ),
        "batch_limit": diagnosis_settings_store.resolve_int(
            "recovery_verify_batch_limit",
            "QWENPAW_RECOVERY_VERIFY_BATCH_LIMIT",
            5,
            min_value=1,
        ),
    }


@router.post(
    "/real-alarms/clear-notifications",
    name="receive_real_alarm_clear_notification",
)
async def receive_real_alarm_clear_notification(
    payload: dict = Body(default_factory=dict),
):
    """Receive an alarm-clear notification pushed by the INOE platform.

    Deliberately unauthenticated (per integration agreement): the
    endpoint only schedules a verification, it can never directly mark
    an alarm as recovered, and repeated pushes for the same alarm are
    deduplicated into one pending event.
    """
    try:
        parsed = AlarmClearNotificationRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        alarm_id = parsed.alarm_id.strip()
        registry_record = get_alarm_record(alarm_id)
        tracked = registry_record is not None
        res_id = parsed.res_id.strip() or (
            str(registry_record.get("resId") or "").strip()
            if registry_record
            else ""
        )

        settings = _recovery_verification_settings()
        if tracked:
            next_verify_at = (
                clear_events_local_now()
                + timedelta(seconds=settings["delay_seconds"])
            ).isoformat()
            initial_status = "pending"
        else:
            # The alarm is not in our registry: the upstream alarm feed
            # converged it away, so we never analyzed it and have no
            # disposal context to verify against. Record the notification
            # for audit only — no schedule, no INOE recheck / metric
            # query / notification, and no new registry row.
            next_verify_at = ""
            initial_status = "ignored"

        event = await asyncio.to_thread(
            record_clear_notification,
            alarm_id=alarm_id,
            res_id=res_id,
            clear_time=parsed.clear_time,
            clear_type=parsed.clear_type,
            operator=parsed.operator,
            reason=parsed.reason,
            metric_type=parsed.metric_type,
            raw_payload=json.dumps(payload, ensure_ascii=False),
            next_verify_at=next_verify_at,
            initial_status=initial_status,
        )

        if tracked:
            _update_portal_real_alarm_registry_safe(
                alarm_id=alarm_id,
                verification_status="clear_reported",
                source="inoe-clear-notification",
            )

        return {
            "status": "accepted",
            "eventId": event.get("id"),
            "alarmId": alarm_id,
            "tracked": tracked,
            "eventStatus": event.get("verifyStatus"),
            "deduped": bool(event.get("deduped")),
            "nextVerifyAt": event.get("nextVerifyAt"),
            "verificationEnabled": _recovery_verification_enabled(),
        }
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            "[ERROR] receive_real_alarm_clear_notification failed: "
            f"{error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/real-alarms/clear-events")
async def get_real_alarm_clear_events(
    alarmId: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=500),
):
    """List received clear notifications and their verification state."""
    try:
        items = await asyncio.to_thread(
            list_clear_events,
            alarm_id=alarmId,
            limit=limit,
        )
        return {"total": len(items), "items": items}
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_real_alarm_clear_events failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


async def _append_recovery_history_message(
    *,
    chat_id: str,
    event: dict[str, Any],
    outcome: dict[str, Any],
    verification: dict[str, Any] | None,
    alarm_record: dict[str, Any] | None,
) -> None:
    if not chat_id:
        return
    runtime_app = _get_portal_auto_takeover_runtime_app()
    if runtime_app is None:
        return
    request = SimpleNamespace(app=runtime_app)
    history = await _load_portal_fault_history(request, session_id=chat_id)
    history.append(
        _compact_ui_message(
            {
                "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                **build_recovery_history_message(
                    event=event,
                    outcome=outcome,
                    verification=verification,
                    alarm_record=alarm_record,
                ),
            },
        ),
    )
    await _save_portal_fault_history(
        request,
        session_id=chat_id,
        messages=history,
    )


async def _process_clear_event(
    event: dict[str, Any],
    settings: dict[str, Any],
) -> None:
    event_id = int(event.get("id") or 0)
    alarm_id = str(event.get("alarmId") or "").strip()
    phase = str(event.get("verifyStatus") or "pending").strip()
    await asyncio.to_thread(
        update_clear_event,
        event_id,
        verify_status="verifying",
    )

    alarm_record = get_alarm_record(alarm_id)
    if alarm_record is None:
        # Defense in depth: the alarm is not (or no longer) in our
        # registry, so there is nothing to verify against. Drop the event
        # to a terminal 'ignored' state without INOE recheck, metric
        # query, notification or registry write. Untracked alarms are
        # normally recorded as 'ignored' at intake and never reach here;
        # this covers the race where the registry row vanished after the
        # event was queued.
        await asyncio.to_thread(
            update_clear_event,
            event_id,
            verify_status="ignored",
            next_verify_at="",
            verify_result=json.dumps(
                {"phase": phase, "reason": "alarm_not_in_registry"},
                ensure_ascii=False,
            ),
        )
        print(
            "[INFO] recovery verification skipped (not in registry): "
            f"alarm={alarm_id} event={event_id}",
        )
        return

    inoe_recheck = await asyncio.to_thread(
        query_real_alarm_active_status,
        alarm_id,
    )

    verification: dict[str, Any] | None = None
    if phase == "observing":
        outcome = decide_observation_outcome(inoe_recheck=inoe_recheck)
        attempts = int(event.get("verifyAttempts") or 0)
    else:
        res_id = str(event.get("resId") or "").strip() or (
            str(alarm_record.get("resId") or "").strip()
            if alarm_record
            else ""
        )
        metric_type = str(event.get("metricType") or "").strip() or "mysql"
        if inoe_recheck != "still_active":
            if res_id:
                try:
                    metric_result = await asyncio.to_thread(
                        _run_alarm_metric_verification,
                        metric_type=metric_type,
                        res_id=res_id,
                    )
                    verification = evaluate_metric_recovery(metric_result)
                except Exception as exc:
                    verification = {
                        "status": "unknown",
                        "summary": f"指标查询失败：{exc}",
                        "usedMock": False,
                        "checkedMetrics": [],
                        "abnormalMetrics": [],
                        "metricDataResults": [],
                        "source": "error",
                    }
            else:
                verification = {
                    "status": "unknown",
                    "summary": "缺少资源 ID (resId)，无法执行指标验证",
                    "usedMock": False,
                    "checkedMetrics": [],
                    "abnormalMetrics": [],
                    "metricDataResults": [],
                    "source": "skipped",
                }
        attempts = int(event.get("verifyAttempts") or 0) + 1
        outcome = decide_verification_outcome(
            inoe_recheck=inoe_recheck,
            metric_verification=verification,
            attempt_number=attempts,
            retry_count=settings["retry_count"],
            observation_minutes=settings["observation_minutes"],
        )

    now = clear_events_local_now()
    next_verify_at = ""
    if outcome.get("retry"):
        next_verify_at = (
            now + timedelta(seconds=settings["retry_interval_seconds"])
        ).isoformat()
    elif outcome.get("eventStatus") == "observing":
        next_verify_at = (
            now + timedelta(minutes=settings["observation_minutes"])
        ).isoformat()

    verify_result = json.dumps(
        {
            "phase": phase,
            "inoeRecheck": inoe_recheck,
            "outcome": outcome,
            "verification": verification,
        },
        ensure_ascii=False,
    )
    await asyncio.to_thread(
        update_clear_event,
        event_id,
        verify_status=str(outcome.get("eventStatus") or "unknown"),
        verify_attempts=attempts,
        next_verify_at=next_verify_at,
        verify_result=verify_result,
    )

    if outcome.get("registryStatus") or outcome.get("verificationStatus"):
        _update_portal_real_alarm_registry_safe(
            alarm_id=alarm_id,
            status=str(outcome.get("registryStatus") or ""),
            verification_status=str(
                outcome.get("verificationStatus") or "",
            ),
            source="recovery-verification",
        )

    if outcome.get("notify"):
        chat_id = (
            str(alarm_record.get("chatId") or "").strip()
            if alarm_record
            else ""
        )
        try:
            await _append_recovery_history_message(
                chat_id=chat_id,
                event=event,
                outcome=outcome,
                verification=verification,
                alarm_record=alarm_record,
            )
        except Exception as exc:
            print(
                "[WARN] recovery verification history append failed: "
                f"{type(exc).__name__}: {exc}",
            )
        await asyncio.to_thread(
            send_recovery_notification_safe,
            event=event,
            outcome=outcome,
            alarm_record=alarm_record,
        )

    print(
        "[INFO] recovery verification: "
        f"alarm={alarm_id} phase={phase} attempts={attempts} "
        f"inoe={inoe_recheck} -> {outcome.get('eventStatus')}",
    )


async def _run_recovery_verification_once() -> dict[str, Any]:
    settings = _recovery_verification_settings()
    events = await asyncio.to_thread(
        fetch_due_clear_events,
        limit=settings["batch_limit"],
    )
    for event in events:
        try:
            await _process_clear_event(event, settings)
        except Exception as exc:
            event_id = int(event.get("id") or 0)
            print(
                "[WARN] recovery verification event failed: "
                f"event={event_id} {type(exc).__name__}: {exc}",
            )
            traceback.print_exc()
            # Put the event back into the queue with a retry delay so a
            # transient failure (DB lock, network) cannot wedge it in
            # 'verifying' forever.
            try:
                await asyncio.to_thread(
                    update_clear_event,
                    event_id,
                    verify_status="pending",
                    next_verify_at=(
                        clear_events_local_now()
                        + timedelta(
                            seconds=settings["retry_interval_seconds"],
                        )
                    ).isoformat(),
                )
            except Exception:
                traceback.print_exc()
    return {"processed": len(events)}


async def _recovery_verification_loop() -> None:
    # Mirrors the auto-takeover loop: runs for the app lifetime, checks
    # the runtime switch every tick so the settings page takes effect
    # without a restart. Scheduling state lives in the DB, so pending
    # verifications survive restarts.
    while True:
        try:
            if _recovery_verification_enabled():
                await _run_recovery_verification_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                "[WARN] recovery verification loop failed: "
                f"{type(exc).__name__}: {exc}",
            )
            traceback.print_exc()
        await asyncio.sleep(RECOVERY_VERIFICATION_LOOP_INTERVAL_SECONDS)


@router.on_event("startup")
async def start_recovery_verification_loop() -> None:
    global RECOVERY_VERIFICATION_TASK

    try:
        reset_count = reset_zombie_verifying_events()
        if reset_count > 0:
            print(
                "[INFO] recovery verification startup: reset "
                f"{reset_count} zombie 'verifying' event(s) to pending",
            )
    except Exception:
        traceback.print_exc()

    if (
        RECOVERY_VERIFICATION_TASK is not None
        and not RECOVERY_VERIFICATION_TASK.done()
    ):
        return
    RECOVERY_VERIFICATION_TASK = asyncio.create_task(
        _recovery_verification_loop(),
    )


@router.on_event("shutdown")
async def stop_recovery_verification_loop() -> None:
    global RECOVERY_VERIFICATION_TASK

    task = RECOVERY_VERIFICATION_TASK
    RECOVERY_VERIFICATION_TASK = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@router.get("/diagnosis-settings")
async def get_diagnosis_settings() -> dict[str, Any]:
    """Return alarm-diagnosis settings as ``{effective, env, overrides}``.

    ``effective`` is what currently applies (page override > env > default);
    ``env`` is what would apply with no page override (for the "reset to
    default" hint). Sensitive fields (token) are masked in both layers.
    """
    return diagnosis_settings_store.build_settings_payload()


@router.put("/diagnosis-settings")
async def put_diagnosis_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of alarm-diagnosis settings.

    Page values win over env. A token field left empty keeps the stored
    secret; sending ``diagnosis_settings_store.CLEAR_SENTINEL`` clears it.
    """
    previous_enabled = _portal_real_alarm_auto_takeover_enabled()
    try:
        diagnosis_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    current_enabled = _portal_real_alarm_auto_takeover_enabled()
    diagnosis_settings_store.sync_analysis_anchor_on_toggle(
        previous_enabled,
        current_enabled,
    )
    if not previous_enabled and current_enabled:
        # Kick the poller so the first round runs immediately instead of
        # waiting out the remaining polling interval.
        _wake_portal_real_alarm_auto_takeover()
    _refresh_alarm_analyst_environ()
    return diagnosis_settings_store.build_settings_payload()


@router.post("/diagnosis-settings/reset")
async def reset_diagnosis_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one field's override so it falls back to env/default.

    Body: ``{"key": "<field>"}``.
    """
    key = str(body.get("key") or "").strip()
    previous_enabled = _portal_real_alarm_auto_takeover_enabled()
    try:
        diagnosis_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Dropping the auto_takeover_enabled override may flip the effective
    # switch (falls back to env) — keep the analysis anchor in sync.
    current_enabled = _portal_real_alarm_auto_takeover_enabled()
    diagnosis_settings_store.sync_analysis_anchor_on_toggle(
        previous_enabled,
        current_enabled,
    )
    if not previous_enabled and current_enabled:
        _wake_portal_real_alarm_auto_takeover()
    _refresh_alarm_analyst_environ()
    return diagnosis_settings_store.build_settings_payload()


def _refresh_inoe_environ() -> None:
    """Push the just-saved INOE settings into ``os.environ``.

    Skill subprocesses read the gateway connection from ``os.getenv``; this
    re-materialises the resolved values so the next spawned skill inherits
    the change made on the settings page. Best-effort — a failure here must
    not turn a successful save into an HTTP error.
    """
    try:
        from qwenpaw.extensions.integrations import working_secrets

        working_secrets.refresh_inoe_environ()
    except Exception:  # noqa: BLE001 - settings already persisted
        pass


def _refresh_alarm_analyst_environ() -> None:
    """Push just-saved alarm-analyst metric settings into ``os.environ``.

    The alarm-analyst skill reads ``ALARM_ANALYST_METRIC_*`` via env in a
    subprocess, so re-materialise after a diagnosis-settings save/reset.
    Best-effort — never turn a successful save into an HTTP error.
    """
    try:
        from qwenpaw.extensions.integrations import working_secrets

        working_secrets.refresh_alarm_analyst_environ()
    except Exception:  # noqa: BLE001 - settings already persisted
        pass


@router.get("/inoe-settings")
async def get_inoe_settings() -> dict[str, Any]:
    """Return INOE gateway settings as ``{effective, env, overrides}``.

    The INOE connection (base URL / token / timeout) is shared by the
    monitoring overview, real-alarm list, and workorder bridge — see
    :mod:`inoe_settings_store`. The token is masked in both layers.
    """
    return inoe_settings_store.build_settings_payload()


@router.put("/inoe-settings")
async def put_inoe_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the INOE gateway settings.

    Page values win over env. The token left empty keeps the stored secret;
    sending ``inoe_settings_store.CLEAR_SENTINEL`` clears it.
    """
    try:
        inoe_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_inoe_environ()
    return inoe_settings_store.build_settings_payload()


@router.post("/inoe-settings/reset")
async def reset_inoe_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one INOE field's override so it falls back to env/default.

    Body: ``{"key": "<field>"}``.
    """
    key = str(body.get("key") or "").strip()
    try:
        inoe_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_inoe_environ()
    return inoe_settings_store.build_settings_payload()


# ---------------------------------------------------------------------------
# Model-provider settings (Qiming / Xingchen). Same {effective, env,
# overrides, groups} shape as INOE; the adapters read these in-process, so
# no os.environ refresh is needed. See qiming/xingchen_settings_store.
# ---------------------------------------------------------------------------


@router.get("/qiming-settings")
async def get_qiming_settings() -> dict[str, Any]:
    """Return Qiming adapter settings as ``{effective, env, overrides}``."""
    return qiming_settings_store.build_settings_payload()


@router.put("/qiming-settings")
async def put_qiming_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the Qiming adapter settings.

    Sensitive fields left empty keep the stored secret; sending
    ``CLEAR_SENTINEL`` clears them.
    """
    try:
        qiming_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return qiming_settings_store.build_settings_payload()


@router.post("/qiming-settings/reset")
async def reset_qiming_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one Qiming field's override. Body: ``{"key": "<field>"}``."""
    key = str(body.get("key") or "").strip()
    try:
        qiming_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return qiming_settings_store.build_settings_payload()


@router.get("/xingchen-settings")
async def get_xingchen_settings() -> dict[str, Any]:
    """Return Xingchen adapter settings as ``{effective, env, overrides}``."""
    return xingchen_settings_store.build_settings_payload()


@router.put("/xingchen-settings")
async def put_xingchen_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the Xingchen adapter settings.

    Sensitive fields left empty keep the stored secret; sending
    ``CLEAR_SENTINEL`` clears them.
    """
    try:
        xingchen_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return xingchen_settings_store.build_settings_payload()


@router.post("/xingchen-settings/reset")
async def reset_xingchen_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one Xingchen field's override. Body: ``{"key": "<field>"}``."""
    key = str(body.get("key") or "").strip()
    try:
        xingchen_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return xingchen_settings_store.build_settings_payload()


# ---------------------------------------------------------------------------
# zgops CMDB connection + resource-import LLM pool. Materialised into
# os.environ (skill subprocesses + resource_import bridge inherit it).
# ---------------------------------------------------------------------------


def _refresh_zgops_environ() -> None:
    try:
        from qwenpaw.extensions.integrations import working_secrets

        working_secrets.refresh_zgops_environ()
    except Exception:  # noqa: BLE001 - settings already persisted
        pass


def _refresh_resource_import_llm_environ() -> None:
    try:
        from qwenpaw.extensions.integrations import working_secrets

        working_secrets.refresh_resource_import_llm_environ()
    except Exception:  # noqa: BLE001 - settings already persisted
        pass


def _refresh_operator_environ() -> None:
    try:
        from qwenpaw.extensions.integrations import working_secrets

        working_secrets.refresh_operator_environ()
    except Exception:  # noqa: BLE001 - settings already persisted
        pass


def _refresh_order_environ() -> None:
    try:
        from qwenpaw.extensions.integrations import working_secrets

        working_secrets.refresh_order_environ()
    except Exception:  # noqa: BLE001 - settings already persisted
        pass


@router.get("/zgops-settings")
async def get_zgops_settings() -> dict[str, Any]:
    """Return zgops CMDB settings as ``{effective, env, overrides}``."""
    return zgops_settings_store.build_settings_payload()


@router.put("/zgops-settings")
async def put_zgops_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the zgops CMDB settings."""
    try:
        zgops_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_zgops_environ()
    return zgops_settings_store.build_settings_payload()


@router.post("/zgops-settings/reset")
async def reset_zgops_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one zgops field's override. Body: ``{"key": "<field>"}``."""
    key = str(body.get("key") or "").strip()
    try:
        zgops_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_zgops_environ()
    return zgops_settings_store.build_settings_payload()


# ---------------------------------------------------------------------------
# operator (page-operator) menu connection. Independent OPERATOR_MENU_* env
# vars (the 操作 settings tab), materialised into os.environ so the
# page-operator skill subprocess inherits them. See operator_settings_store.
# ---------------------------------------------------------------------------


@router.get("/operator-settings")
async def get_operator_settings() -> dict[str, Any]:
    """Return operator menu settings as ``{effective, env, overrides}``."""
    return operator_settings_store.build_settings_payload()


@router.put("/operator-settings")
async def put_operator_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the operator menu settings."""
    try:
        operator_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_operator_environ()
    return operator_settings_store.build_settings_payload()


@router.post("/operator-settings/reset")
async def reset_operator_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one operator field's override. Body: ``{"key": "<field>"}``."""
    key = str(body.get("key") or "").strip()
    try:
        operator_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_operator_environ()
    return operator_settings_store.build_settings_payload()


# ---------------------------------------------------------------------------
# work-order (order-workflow / ferry) connection. Independent ORDER_* env vars
# (the 工单 settings tab), materialised into os.environ so the order-workflow
# skill subprocess inherits them; empty fields fall back to the shared INOE
# connection. See order_settings_store.
# ---------------------------------------------------------------------------


@router.get("/order-settings")
async def get_order_settings() -> dict[str, Any]:
    """Return work-order settings as ``{effective, env, overrides}``."""
    return order_settings_store.build_settings_payload()


@router.put("/order-settings")
async def put_order_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the work-order settings."""
    try:
        order_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_order_environ()
    return order_settings_store.build_settings_payload()


@router.post("/order-settings/reset")
async def reset_order_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one work-order field's override. Body: ``{"key": "<field>"}``."""
    key = str(body.get("key") or "").strip()
    try:
        order_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_order_environ()
    return order_settings_store.build_settings_payload()


@router.get("/resource-import-llm-settings")
async def get_resource_import_llm_settings() -> dict[str, Any]:
    """Return the resource-import LLM pool ``{scalars, models}``.

    Each model's ``api_key`` is masked.
    """
    return resource_import_llm_settings_api.build_settings_payload()


@router.put("/resource-import-llm-settings")
async def put_resource_import_llm_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Replace the resource-import LLM pool from ``{scalars?, models?}``."""
    try:
        resource_import_llm_settings_api.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_resource_import_llm_environ()
    return resource_import_llm_settings_api.build_settings_payload()


def _refresh_n9e_environ() -> None:
    try:
        from qwenpaw.extensions.integrations import working_secrets

        working_secrets.refresh_n9e_environ()
    except Exception:  # noqa: BLE001 - settings already persisted
        pass


@router.get("/n9e-settings")
async def get_n9e_settings() -> dict[str, Any]:
    """Return N9E log settings as ``{effective, env, overrides}``."""
    return n9e_settings_store.build_settings_payload()


@router.put("/n9e-settings")
async def put_n9e_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the N9E log settings."""
    try:
        n9e_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_n9e_environ()
    return n9e_settings_store.build_settings_payload()


@router.post("/n9e-settings/reset")
async def reset_n9e_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one N9E field's override. Body: ``{"key": "<field>"}``."""
    key = str(body.get("key") or "").strip()
    try:
        n9e_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _refresh_n9e_environ()
    return n9e_settings_store.build_settings_payload()


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
        raise HTTPException(
            status_code=404,
            detail=f"Preview job '{job_id}' not found",
        )

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


def _run_preview_job(
    job_id: str,
    *,
    agent_id: str,
    payload_files: list[dict[str, Any]],
    temp_dir: str,
) -> None:
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
                    + "\n",
                )
        except OSError:
            pass
        _set_preview_job_state(job_id, status="failed", error=str(exc))


async def _get_workspace_and_session(request: Request):
    from qwenpaw.app.agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return workspace, workspace.session


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
        current_job = f"正在处理 {active_chat_count or active_task_count} 个对话任务"
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
        "employeeName": PORTAL_EMPLOYEE_STATUS_NAMES.get(
            employee_id,
            employee_id,
        ),
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
    updated_at = float(
        PORTAL_STATUS_ALERT_COUNT_CACHE.get("updated_at") or 0.0,
    )
    if updated_at <= 0:
        return None
    if (
        require_fresh
        and time.monotonic() - updated_at
        > PORTAL_STATUS_ALERT_CACHE_TTL_SECONDS
    ):
        return None
    return int(PORTAL_STATUS_ALERT_COUNT_CACHE.get("value") or 0)


async def _refresh_fault_alert_count_cache() -> int:
    try:
        result = await _get_visible_portal_real_alarms(
            _portal_real_alarm_list_limit(),
            timeout_seconds=PORTAL_STATUS_ALERT_TIMEOUT_SECONDS,
            require_fresh=True,
        )
        items = result.get("items") or []
        count = int(result.get("total") or len(items))
        PORTAL_STATUS_ALERT_COUNT_CACHE.update(
            {
                "value": count,
                "updated_at": time.monotonic(),
            },
        )
        return count
    except Exception as exc:
        print(
            "[WARN] portal employee status alert count unavailable: "
            f"{type(exc).__name__}: {exc}",
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


def _normalize_portal_real_alarm_limit(limit: int) -> int:
    try:
        return max(1, int(limit or PORTAL_REAL_ALARM_ROUTE_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return PORTAL_REAL_ALARM_ROUTE_DEFAULT_LIMIT


def _slice_portal_real_alarm_payload(
    payload: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    items = list(payload.get("items") or [])[:normalized_limit]
    return {
        **payload,
        "items": items,
        "total": len(items),
    }


def _get_cached_portal_real_alarm_payload(
    limit: int,
    *,
    require_fresh: bool,
) -> dict[str, Any] | None:
    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    payload = PORTAL_REAL_ALARM_PAYLOAD_CACHE.get("payload")
    updated_at = float(
        PORTAL_REAL_ALARM_PAYLOAD_CACHE.get("updated_at") or 0.0,
    )
    cached_limit = int(PORTAL_REAL_ALARM_PAYLOAD_CACHE.get("limit") or 0)
    if (
        not isinstance(payload, dict)
        or updated_at <= 0
        or cached_limit < normalized_limit
    ):
        return None
    cache_ttl = diagnosis_settings_store.resolve_float(
        "cache_ttl_seconds",
        "QWENPAW_PORTAL_REAL_ALARM_CACHE_TTL",
        PORTAL_REAL_ALARM_CACHE_TTL_SECONDS,
        min_value=0,
    )
    if require_fresh and time.monotonic() - updated_at > cache_ttl:
        return None
    return _slice_portal_real_alarm_payload(payload, normalized_limit)


def _store_cached_portal_real_alarm_payload(
    limit: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    sliced_payload = _slice_portal_real_alarm_payload(
        payload,
        normalized_limit,
    )
    PORTAL_REAL_ALARM_PAYLOAD_CACHE.update(
        {
            "payload": sliced_payload,
            "limit": normalized_limit,
            "updated_at": time.monotonic(),
        },
    )
    return sliced_payload


def _enter_portal_real_alarm_degraded_mode(reason: str) -> None:
    global PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC
    PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC = max(
        PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC,
        time.monotonic()
        + max(0.0, PORTAL_REAL_ALARM_DEGRADED_COOLDOWN_SECONDS),
    )
    print(f"[WARN] portal real alarm backend degraded: {reason}")


def _clear_portal_real_alarm_degraded_mode() -> None:
    global PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC
    PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC = 0.0


def _portal_real_alarm_backend_is_degraded() -> bool:
    return time.monotonic() < PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC


def _load_visible_portal_real_alarm_fallback_payload(
    limit: int,
) -> dict[str, Any]:
    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    return build_empty_portal_real_alarms_payload(normalized_limit)


def _query_visible_portal_real_alarms(limit: int) -> dict[str, Any]:
    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    raw_payload = query_portal_real_alarms(
        normalized_limit * PORTAL_REAL_ALARM_ROUTE_FETCH_MULTIPLIER,
    )
    visible_payload = filter_visible_alarms(raw_payload)
    visible_items = list(visible_payload.get("items") or [])[:normalized_limit]
    return {
        **visible_payload,
        "items": visible_items,
        "total": len(visible_items),
    }


async def _refresh_portal_real_alarm_payload(limit: int) -> dict[str, Any]:
    global PORTAL_REAL_ALARM_REFRESH_TASK
    global PORTAL_REAL_ALARM_REFRESH_LIMIT

    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    try:
        payload = await asyncio.to_thread(
            _query_visible_portal_real_alarms,
            normalized_limit,
        )
        cached_payload = _store_cached_portal_real_alarm_payload(
            normalized_limit,
            payload,
        )
        if cached_payload.get("source") == "live":
            _clear_portal_real_alarm_degraded_mode()
        return cached_payload
    finally:
        current_task = asyncio.current_task()
        if PORTAL_REAL_ALARM_REFRESH_TASK is current_task:
            PORTAL_REAL_ALARM_REFRESH_TASK = None
            PORTAL_REAL_ALARM_REFRESH_LIMIT = 0


def _ensure_portal_real_alarm_refresh(limit: int) -> asyncio.Task:
    global PORTAL_REAL_ALARM_REFRESH_TASK
    global PORTAL_REAL_ALARM_REFRESH_LIMIT

    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    task = PORTAL_REAL_ALARM_REFRESH_TASK
    if task is not None and not task.done():
        return task

    task = asyncio.create_task(
        _refresh_portal_real_alarm_payload(normalized_limit),
    )
    PORTAL_REAL_ALARM_REFRESH_TASK = task
    PORTAL_REAL_ALARM_REFRESH_LIMIT = normalized_limit
    return task


async def _get_visible_portal_real_alarms(
    limit: int,
    *,
    timeout_seconds: float = PORTAL_REAL_ALARM_ROUTE_TIMEOUT_SECONDS,
    require_fresh: bool = False,
    allow_stale: bool = True,
) -> dict[str, Any]:
    normalized_limit = _normalize_portal_real_alarm_limit(limit)
    fresh_cached = _get_cached_portal_real_alarm_payload(
        normalized_limit,
        require_fresh=True,
    )
    stale_cached = (
        _get_cached_portal_real_alarm_payload(
            normalized_limit,
            require_fresh=False,
        )
        if allow_stale
        else None
    )

    if fresh_cached is not None and not require_fresh:
        return fresh_cached

    if stale_cached is not None and not require_fresh:
        if not _portal_real_alarm_backend_is_degraded():
            _ensure_portal_real_alarm_refresh(normalized_limit)
        return stale_cached

    if _portal_real_alarm_backend_is_degraded():
        return (
            stale_cached
            or _load_visible_portal_real_alarm_fallback_payload(
                normalized_limit,
            )
        )

    task = _ensure_portal_real_alarm_refresh(normalized_limit)
    try:
        payload = await asyncio.wait_for(
            asyncio.shield(task),
            timeout=max(0.1, float(timeout_seconds)),
        )
    except asyncio.TimeoutError:
        _enter_portal_real_alarm_degraded_mode(
            f"timeout after {float(timeout_seconds):.1f}s",
        )
        return (
            stale_cached
            or _load_visible_portal_real_alarm_fallback_payload(
                normalized_limit,
            )
        )
    except Exception as exc:
        _enter_portal_real_alarm_degraded_mode(f"{type(exc).__name__}: {exc}")
        return (
            stale_cached
            or _load_visible_portal_real_alarm_fallback_payload(
                normalized_limit,
            )
        )

    return _slice_portal_real_alarm_payload(payload, normalized_limit)


def _build_portal_registry_status_from_verification(
    verification: dict[str, Any],
) -> str:
    status = str(verification.get("status") or "").strip().lower()
    if status == "recovered":
        return "manual_recovered"
    if status == "unrecovered":
        return "manual_unrecovered"
    return "manual_unknown"


def _update_portal_real_alarm_registry_safe(
    *,
    alarm: dict[str, Any] | None = None,
    alarm_id: str = "",
    status: str = "",
    session_id: str = "",
    chat_id: str = "",
    res_id: str = "",
    source: str = "",
    verification_status: str = "",
    last_error: str | None = None,
    analysis_result: str | None = None,
) -> dict[str, Any] | None:
    try:
        return update_alarm_record(
            alarm=alarm,
            alarm_id=alarm_id,
            status=status,
            session_id=session_id,
            chat_id=chat_id,
            res_id=res_id,
            source=source,
            verification_status=verification_status,
            last_error=last_error,
            analysis_result=analysis_result,
        )
    except ValueError as exc:
        print(
            "[WARN] portal real alarm registry skipped update: "
            f"{type(exc).__name__}: {exc}",
        )
    except Exception as exc:
        print(
            "[WARN] portal real alarm registry update failed: "
            f"{type(exc).__name__}: {exc}",
        )
        traceback.print_exc()
    return None


def _persist_analysis_result_to_registry(
    *,
    session_id: str,
    card: dict[str, Any],
) -> None:
    """Persist the card display fields as analysis_result JSON in the alarm registry."""
    try:
        alarm_id = session_id.removeprefix(
            PORTAL_REAL_ALARM_SESSION_PREFIX,
        ).strip()
        if not alarm_id:
            return
        display_fields = extract_card_display_fields(card)
        result_json = json.dumps(display_fields, ensure_ascii=False)
        _update_portal_real_alarm_registry_safe(
            alarm_id=alarm_id,
            analysis_result=result_json,
        )
    except Exception as exc:
        print(
            f"[WARN] _persist_analysis_result_to_registry failed: "
            f"{type(exc).__name__}: {exc}",
        )


def _extract_text_from_sse_message_content(content: Any) -> str:
    """Extract plain text from a message event's content field (str or list)."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
        return "\n".join(filter(None, parts))
    return ""


def _collect_sse_report_messages(
    chunks: list[str],
) -> list[tuple[str, str]]:
    """Parse collected SSE event strings and return ``(message_id, text)``
    for every completed assistant message. The alarm analyst report is the
    last candidate among them; keeping each message's real ``id`` lets the
    eagerly-saved card de-duplicate with any later frontend backfill (the
    frontend matches cards by that same backend message id)."""
    messages: list[tuple[str, str]] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk.startswith("data:"):
            continue
        payload = chunk[len("data:") :].strip()
        try:
            event = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            continue
        if (
            event.get("object") == "message"
            and event.get("role") == "assistant"
            and event.get("type") == "message"
            and event.get("status") == "completed"
        ):
            text = _extract_text_from_sse_message_content(
                event.get("content"),
            )
            if text:
                messages.append((str(event.get("id") or ""), text.strip()))
    return messages


def _try_persist_analysis_result_from_stream(
    *,
    chunks: list[str],
    chat_id: str,
    session_id: str,
) -> None:
    """After agent streaming ends, parse SSE chunks to extract the alarm
    analyst report, build a card, and persist it to BOTH the alarm registry
    (for external callers) AND the card DB the portal frontend reads — so the
    card shows up immediately without the frontend having to open the
    conversation and backfill it."""
    try:
        if not session_id.startswith(PORTAL_REAL_ALARM_SESSION_PREFIX):
            return
        # Pick the last completed assistant message that looks like an alarm
        # analyst report, and keep its real message id (the same id the
        # frontend matches cards by) so the eager card de-dupes with any
        # later frontend backfill.
        chosen_id = ""
        report_markdown = ""
        for message_id, text in _collect_sse_report_messages(chunks):
            if is_alarm_analyst_card_candidate(
                employee_id="fault",
                report_markdown=text,
                process_blocks=[],
            ):
                chosen_id = message_id
                report_markdown = text
        if not report_markdown:
            return
        # Synthetic id only when the stream carried none (frontend then
        # falls back to rawReportMarkdown-hash matching).
        message_id = chosen_id or f"auto-stream-{chat_id}"
        card = build_alarm_analyst_card(
            chat_id=chat_id,
            message_id=message_id,
            employee_id="fault",
            report_markdown=report_markdown,
            process_blocks=[],
        )
        card_payload = card.model_dump(by_alias=True)
        _persist_analysis_result_to_registry(
            session_id=session_id,
            card=card_payload,
        )
        # Eagerly upsert into the card DB the frontend GET reads, keyed by
        # the real message id (idempotent on (chat_id, message_id)).
        _save_card_to_db(
            chat_id=chat_id,
            message_id=message_id,
            card=card_payload,
            session_id=session_id,
        )
    except Exception as exc:
        print(
            f"[WARN] _try_persist_analysis_result_from_stream failed: "
            f"{type(exc).__name__}: {exc}",
        )


async def _get_employee_alert_count(
    employee_id: str,
    *,
    include_alert_count: bool = True,
) -> int:
    if (
        employee_id != "fault"
        or not include_alert_count
        or not PORTAL_EMPLOYEE_STATUS_ALERT_COUNT_ENABLED
    ):
        return 0

    cached = _get_cached_fault_alert_count(require_fresh=False)
    if cached is not None:
        if _get_cached_fault_alert_count(require_fresh=True) is None:
            _ensure_fault_alert_count_refresh()
        return cached

    task = _ensure_fault_alert_count_refresh()
    try:
        return await asyncio.wait_for(
            asyncio.shield(task),
            timeout=max(0.1, PORTAL_STATUS_ALERT_FAST_TIMEOUT_SECONDS),
        )
    except Exception:
        return int(PORTAL_STATUS_ALERT_COUNT_CACHE.get("value") or 0)


async def collect_portal_employee_statuses(
    request: Request,
    *,
    employee_ids: tuple[str, ...] = PORTAL_EMPLOYEE_STATUS_IDS,
    include_alert_count: bool = True,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for employee_id in employee_ids:
        (
            is_configured,
            workspace,
        ) = _get_loaded_portal_employee_workspace_for_status(
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
                ),
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
                ),
            )
            continue

        chats = await workspace.chat_manager.list_chats()
        active_task_keys = set(
            await workspace.task_tracker.list_active_tasks(),
        )
        active_chat_count = sum(
            1 for chat in chats if chat.id in active_task_keys
        )
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
            ),
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
    records = state.get("portal_fault_manual_workorders", {}).get(
        "records",
        {},
    )
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
    """Load cards from SQLite, falling back to session state for migration."""
    # Try SQLite first (new path)
    db_records = _load_cards_for_chat_from_db_by_session(session_id)
    if db_records:
        return db_records

    # Fallback: read from legacy session state and migrate to SQLite
    _workspace, session = await _get_workspace_and_session(request)
    state = await session.get_session_state_dict(session_id, user_id)
    records = state.get("portal_alarm_analyst_cards", {}).get("records", {})
    if not isinstance(records, dict) or not records:
        return {}

    # Migrate existing cards to SQLite
    for chat_id, msgs in records.items():
        if not isinstance(msgs, dict):
            continue
        for message_id, card in msgs.items():
            if isinstance(card, dict):
                _save_card_to_db(
                    chat_id=chat_id,
                    message_id=message_id,
                    card=card,
                    session_id=session_id,
                )
    return records


def _load_cards_for_chat_from_db_by_session(
    session_id: str,
) -> dict[str, dict[str, dict]]:
    """Load all cards for a session from SQLite."""
    from qwenpaw.extensions.portal_alarm_analyst_card_store import (
        load_all_cards_for_session,
    )

    return load_all_cards_for_session(session_id)


async def _save_portal_alarm_analyst_cards(
    request: Request,
    *,
    session_id: str,
    records: dict[str, dict[str, dict]],
    user_id: str = "default",
) -> None:
    """Save cards to SQLite (primary) and session state (backward compat)."""
    # Save to SQLite
    for chat_id, msgs in records.items():
        if not isinstance(msgs, dict):
            continue
        for message_id, card in msgs.items():
            if isinstance(card, dict):
                _save_card_to_db(
                    chat_id=chat_id,
                    message_id=message_id,
                    card=card,
                    session_id=session_id,
                )
    # Also write to session state for backward compatibility
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
        payload.get("rootCause")
        if isinstance(payload.get("rootCause"), dict)
        else {}
    )
    shaped["steps"] = (
        payload.get("steps") if isinstance(payload.get("steps"), list) else []
    )
    shaped["logEntries"] = (
        payload.get("logEntries")
        if isinstance(payload.get("logEntries"), list)
        else []
    )
    shaped["actions"] = (
        payload.get("actions")
        if isinstance(payload.get("actions"), list)
        else []
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


def _normalize_portal_fault_history_messages(
    messages: list[dict],
) -> list[dict]:
    return [
        _compact_ui_message(message)
        for message in messages
        if isinstance(message, dict)
    ]


def _shape_alarm_analyst_card_payload(payload: Any) -> dict | None:
    if not isinstance(payload, dict):
        return None
    try:
        return AlarmAnalystCard.model_validate(payload).model_dump(
            by_alias=True,
        )
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

    match = re.search(
        r"```portal-action\s*([\s\S]*?)```",
        text,
        flags=re.IGNORECASE,
    )
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
        raise FileNotFoundError(
            f"fault-disposal chat skill bridge not found: {script_path}",
        )

    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".json",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        context_file = handle.name

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(script_path),
                command,
                "--context-file",
                context_file,
            ],
            cwd=str(_fault_disposal_skill_root()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_skill_subprocess_env(),
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
        error_text = (
            stderr_text or stdout_text or "fault-disposal skill bridge failed"
        )
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


def _run_resource_import_skill(
    command: str,
    payload: dict | None = None,
) -> dict:
    script_path = _resource_import_bridge_script()
    if not script_path.exists():
        raise FileNotFoundError(
            f"resource-import skill bridge not found: {script_path}",
        )

    command_args = [sys.executable, str(script_path), command]
    context_file = None
    if payload is not None:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as handle:
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
            env=_skill_subprocess_env(),
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
        error_text = (
            stderr_text or stdout_text or "resource-import skill bridge failed"
        )
        raise RuntimeError(error_text)
    if not stdout_text:
        raise RuntimeError(
            "resource-import skill bridge returned empty output",
        )
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
        raise FileNotFoundError(
            f"alarm-analyst metric script not found: {script_path}",
        )

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
        env=_skill_subprocess_env(),
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
        print(
            f"[ERROR] get_resource_import_start_payload failed: {error_detail}",
        )
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
            ),
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
        print(
            f"[ERROR] get_preview_resource_import_flow failed: {error_detail}",
        )
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


@router.get("/monitoring-overview/alarm-top5")
async def get_monitoring_alarm_top5():
    return await asyncio.to_thread(query_monitoring_alarm_top5)


@router.get("/monitoring-overview/topology")
async def get_monitoring_topology():
    return await asyncio.to_thread(query_monitoring_topology)


@router.get("/monitoring-overview/asset-overview")
async def get_monitoring_asset_overview():
    return await asyncio.to_thread(query_monitoring_asset_overview)


@router.get("/monitoring-overview/dashboard")
async def get_monitoring_overview_dashboard():
    (
        asset_overview,
        alarm_top5,
        topology,
        workorder_stats,
        severity_trend,
        cmdb_summary,
        active_alarm_total,
    ) = await asyncio.gather(
        asyncio.to_thread(query_monitoring_asset_overview),
        asyncio.to_thread(query_monitoring_alarm_top5),
        asyncio.to_thread(query_monitoring_topology),
        asyncio.to_thread(query_monitoring_workorder_stats),
        asyncio.to_thread(query_monitoring_severity_trend),
        asyncio.to_thread(query_monitoring_cmdb_summary),
        asyncio.to_thread(query_monitoring_active_alarm_total),
    )
    return {
        "assetOverview": asset_overview,
        "alarmTop5": alarm_top5,
        "topology": topology,
        "workorderStats": workorder_stats,
        "severityTrend": severity_trend,
        "cmdbSummary": cmdb_summary,
        "activeAlarmTotal": active_alarm_total,
    }


@router.get("/real-alarms")
async def get_real_alarms(
    limit: int | None = None,
):
    # Without an explicit ?limit= the configurable list size applies
    # (settings page > env > default 20).
    try:
        return await _get_visible_portal_real_alarms(
            limit or _portal_real_alarm_list_limit(),
            timeout_seconds=PORTAL_REAL_ALARM_ROUTE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_real_alarms failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/real-alarms/trigger-sessions")
async def trigger_real_alarm_sessions(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    limit: int = Query(PORTAL_REAL_ALARM_ROUTE_DEFAULT_LIMIT),
):
    try:
        if not hasattr(request.app.state, "multi_agent_manager"):
            raise HTTPException(
                status_code=503,
                detail="MultiAgentManager not initialized",
            )

        alarms_payload = await _build_portal_real_alarm_trigger_payload(
            limit,
            payload,
        )
        summary = await _ensure_portal_real_alarm_sessions(
            request,
            alarms_payload,
            takeover_source="manual-trigger",
        )
        return {
            "ok": True,
            "alarmSource": alarms_payload.get("source") or "unknown",
            "alarmTotal": int(
                alarms_payload.get("total")
                or len(alarms_payload.get("items") or []),
            ),
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
            or "",
        ).strip()
        session_id = str(
            body.get("sessionId") or body.get("session_id") or "",
        ).strip()
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

        verification, _ = toolbox.collect_recovery_verification(
            operation,
            recovery,
        )
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
        print(
            f"[ERROR] get_fault_disposal_recovery_visualization failed: {error_detail}",
        )
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
        history = await _load_portal_fault_history(
            request,
            session_id=session_id,
        )
        if visible_content:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": visible_content,
                    },
                ),
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
                ),
            )
        await _save_portal_fault_history(
            request,
            session_id=session_id,
            messages=history,
        )
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
        history = await _load_portal_fault_history(
            request,
            session_id=session_id,
        )
        if visible_content:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": visible_content,
                    },
                ),
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
                ),
            )
        await _save_portal_fault_history(
            request,
            session_id=session_id,
            messages=history,
        )
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
        alarm_id = parsed.alarm_id
        if not alarm_id:
            raise HTTPException(
                status_code=422,
                detail="alarm.alarmId is required",
            )
        callback_url = str(
            request.url_for("notify_fault_manual_workorder_closed"),
        )
        record = build_analysis_record(parsed, callback_url=callback_url)
        records = await _load_portal_manual_workorders(
            request,
            session_id=parsed.chat_id,
        )
        records[alarm_id] = record
        await _save_portal_manual_workorders(
            request,
            session_id=parsed.chat_id,
            records=records,
        )
        _update_portal_real_alarm_registry_safe(
            alarm=parsed.alarm.model_dump(mode="json"),
            status="manual_pending",
            chat_id=parsed.chat_id,
            res_id=str(parsed.res_id),
            source="manual-dispatch",
        )

        history = await _load_portal_fault_history(
            request,
            session_id=parsed.chat_id,
        )
        history.append(
            _compact_ui_message(
                {
                    "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                    **build_analysis_dispatch_history_message(record),
                },
            ),
        )
        await _save_portal_fault_history(
            request,
            session_id=parsed.chat_id,
            messages=history,
        )

        return {
            "status": "pending_manual",
            "alarmId": alarm_id,
            "chatId": parsed.chat_id,
            "resId": parsed.res_id,
            "analysisRecord": record,
            "callbackUrl": callback_url,
        }
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] dispatch_fault_manual_workorder failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post(
    "/fault-disposal/manual-workorders/notify-closed",
    name="notify_fault_manual_workorder_closed",
)
async def notify_fault_manual_workorder_closed(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        parsed = ManualWorkorderCloseNotificationRequest.model_validate(
            payload,
        )

        # Resolve alarm_id and chat_id for record lookup
        alarm_id = parsed.alarm_id.strip()
        chat_id = parsed.chat_id.strip()
        res_id = parsed.res_id.strip()

        # When alarm_id is provided but chat_id is missing, look up from alarm registry
        if alarm_id and not chat_id:
            registry_record = get_alarm_record(alarm_id)
            if registry_record:
                chat_id = str(registry_record.get("chatId") or "").strip()
                if not res_id:
                    res_id = str(registry_record.get("resId") or "").strip()

        if not alarm_id and not chat_id:
            raise HTTPException(
                status_code=422,
                detail="alarm_id or chat_id is required to locate the analysis record",
            )

        # Try to find the record: first by alarm_id, then fall back to res_id (legacy)
        record = None
        if chat_id:
            records = await _load_portal_manual_workorders(
                request,
                session_id=chat_id,
            )
            if alarm_id:
                record = records.get(alarm_id)
            if not record and res_id:
                record = records.get(res_id)
        else:
            records = {}

        if not record:
            detail_parts = []
            if alarm_id:
                detail_parts.append(f"alarmId={alarm_id}")
            if chat_id:
                detail_parts.append(f"chatId={chat_id}")
            if res_id:
                detail_parts.append(f"resId={res_id}")
            raise HTTPException(
                status_code=404,
                detail=f"analysis record not found for {', '.join(detail_parts)}",
            )

        # Use res_id from stored record for metric verification if not in request
        effective_res_id = res_id or str(record.get("resId") or "").strip()
        metric_type = (
            str(parsed.metric_type or "").strip()
            or str(record.get("metricType") or "").strip()
            or "mysql"
        )

        verification: dict[str, Any]
        if effective_res_id:
            metric_result = await asyncio.to_thread(
                _run_alarm_metric_verification,
                metric_type=metric_type,
                res_id=effective_res_id,
            )
            verification = evaluate_metric_recovery(metric_result)
        else:
            verification = {
                "status": "unknown",
                "summary": "缺少资源 ID (resId)，跳过恢复验证",
                "usedMock": False,
                "checkedMetrics": [],
                "abnormalMetrics": [],
                "metricDataResults": [],
                "source": "skipped",
            }

        merged_record = merge_manual_workorder_notification(
            record,
            parsed,
            verification=verification,
        )
        merged_record["metricType"] = metric_type
        record_key = alarm_id or res_id
        records[record_key] = merged_record
        if chat_id:
            await _save_portal_manual_workorders(
                request,
                session_id=chat_id,
                records=records,
            )
        _update_portal_real_alarm_registry_safe(
            alarm_id=alarm_id,
            status=_build_portal_registry_status_from_verification(
                verification,
            ),
            chat_id=chat_id,
            res_id=effective_res_id,
            source="manual-close",
            verification_status=str(verification.get("status") or "").strip(),
        )

        if chat_id:
            history = await _load_portal_fault_history(
                request,
                session_id=chat_id,
            )
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        **build_analysis_close_history_message(
                            merged_record,
                            verification=verification,
                        ),
                    },
                ),
            )
            await _save_portal_fault_history(
                request,
                session_id=chat_id,
                messages=history,
            )

        return {
            "status": verification.get("status") or "unknown",
            "alarmId": alarm_id,
            "chatId": chat_id,
            "resId": effective_res_id,
            "analysisRecord": merged_record,
            "verification": verification,
        }
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] notify_fault_manual_workorder_closed failed: {error_detail}",
        )
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
            raise HTTPException(
                status_code=422,
                detail="sessionId is required",
            )

        result = _shape_fault_scenario_response(
            run_alarm_analyst_diagnose(payload),
        )
        if hasattr(request.app.state, "multi_agent_manager"):
            history = await _load_portal_fault_history(
                request,
                session_id=session_id,
            )
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": payload.get("content", ""),
                    },
                ),
            )
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        "type": "agent",
                        "content": result["result"]["summary"],
                        "faultScenarioResult": result["result"],
                    },
                ),
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
            return AlarmAnalystCardCreateResponse(matched=False).model_dump(
                by_alias=True,
            )

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

        # Persist card data to alarm registry for external API access
        if parsed.session_id.startswith(PORTAL_REAL_ALARM_SESSION_PREFIX):
            _persist_analysis_result_to_registry(
                session_id=parsed.session_id,
                card=card.model_dump(by_alias=True),
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
        print(
            f"[ERROR] create_portal_alarm_analyst_card failed: {error_detail}",
        )
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
            return AlarmAnalystCardListResponse(cards=[]).model_dump(
                by_alias=True,
            )

        # Fast path: load from SQLite directly by chat_id
        db_chat_records = _load_cards_for_chat_from_db(chat_id)
        if db_chat_records:
            cards = []
            for payload in db_chat_records.values():
                shaped = _shape_alarm_analyst_card_payload(payload)
                if shaped:
                    cards.append(shaped)
            return AlarmAnalystCardListResponse(
                cards=[
                    AlarmAnalystCard.model_validate(card) for card in cards
                ],
            ).model_dump(by_alias=True)

        # Fallback: load from session state (triggers migration)
        records = await _load_portal_alarm_analyst_cards(
            request,
            session_id=session_id,
        )
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
        print(
            f"[ERROR] list_portal_alarm_analyst_cards failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/alarm-analyst/result/{alarm_id:path}")
async def get_alarm_analysis_result(alarm_id: str):
    """Get the AI analysis result for an alarm by alarm ID.

    Returns the structured analysis card data that was persisted
    when the alarm analysis completed. Used by external systems
    (e.g., the alarm platform) to retrieve AI analysis conclusions.
    """
    try:
        record = get_alarm_record(alarm_id)
        if not record:
            return {
                "code": 200,
                "analyst_result": 1,
                "message": f"Alarm not found: {alarm_id}",
                "data": None,
            }

        analysis_json = record.get("analysisResult", "")
        if not analysis_json:
            status = record.get("status", "")
            if status == "analyzing":
                return {
                    "code": 200,
                    "analyst_result": 0,
                    "message": "分析进行中",
                    "data": None,
                }
            return {
                "code": 200,
                "analyst_result": 0,
                "message": "暂无分析结果",
                "data": None,
            }

        analysis_data = json.loads(analysis_json)
        return {
            "code": 200,
            "analyst_result": 0,
            "message": "success",
            "data": analysis_data,
        }
    except HTTPException:
        raise
    except json.JSONDecodeError:
        return {
            "code": 200,
            "analyst_result": 0,
            "message": "分析结果数据异常",
            "data": None,
        }
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_alarm_analysis_result failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/fault-disposal/history/{session_id}")
async def fault_disposal_history(
    request: Request,
    session_id: str,
):
    try:
        history = await _load_portal_fault_history(
            request,
            session_id=session_id,
        )
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
        print(
            f"[ERROR] synthesize_knowledge_base_answer failed: {error_detail}",
        )
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
        print(
            f"[ERROR] get_knowledge_base_source_detail failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/manual-entry")
def create_knowledge_base_manual_entry(
    payload: dict[str, Any] | None = Body(default=None),
):
    try:
        return knowledge_base.manual_entry(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] create_knowledge_base_manual_entry failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/sources/update")
def update_knowledge_base_source(
    payload: dict[str, Any] | None = Body(default=None),
):
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
def archive_knowledge_base_sources(
    payload: dict[str, Any] | None = Body(default=None),
):
    try:
        return knowledge_base.archive_sources(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] archive_knowledge_base_sources failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/sources/unarchive")
def unarchive_knowledge_base_sources(
    payload: dict[str, Any] | None = Body(default=None),
):
    try:
        return knowledge_base.unarchive_sources(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] unarchive_knowledge_base_sources failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/sources/delete")
def delete_knowledge_base_sources(
    payload: dict[str, Any] | None = Body(default=None),
):
    """Permanently delete sources (rows + vectors + uploaded files).

    POST by convention: the global DeleteBlockMiddleware rejects the HTTP
    DELETE method when ``security.delete_ops_disabled`` is on; this endpoint
    is an explicit, user-confirmed exception scoped to knowledge sources.
    """
    try:
        return knowledge_base.delete_sources(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] delete_knowledge_base_sources failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/embedding/toggle")
def toggle_knowledge_base_embedding(
    payload: dict[str, Any] | None = Body(default=None),
):
    try:
        return knowledge_base.set_embedding_enabled(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] toggle_knowledge_base_embedding failed: {error_detail}",
        )
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
        print(
            f"[ERROR] reindex_knowledge_base_embeddings failed: {error_detail}",
        )
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
        print(
            f"[ERROR] list_knowledge_base_ingestion_jobs failed: {error_detail}",
        )
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
        print(
            f"[ERROR] get_knowledge_base_ingestion_progress failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/knowledge-base/source-summary")
def get_knowledge_base_source_summary():
    try:
        return knowledge_base.source_summary()
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] get_knowledge_base_source_summary failed: {error_detail}",
        )
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
        print(
            f"[ERROR] list_knowledge_base_builtin_packs failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/knowledge-base/builtin-packs/reload")
def reload_knowledge_base_builtin_packs(
    payload: dict[str, Any] | None = Body(default=None),
):
    try:
        return knowledge_base.reload_builtin_pack(payload)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(
            f"[ERROR] reload_knowledge_base_builtin_packs failed: {error_detail}",
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


# ---------------------------------------------------------------------------
# Domain guard: register the skill-side analyzer at app startup, and expose a
# domain-checked MCP import endpoint that the Portal uses instead of POST /api/mcp.
# ---------------------------------------------------------------------------
@router.on_event("startup")
async def _register_domain_guard() -> None:
    try:
        from qwenpaw.extensions.api.domain_guard import (
            register_skill_domain_analyzer,
        )

        register_skill_domain_analyzer()
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[WARN] domain_guard skill analyzer registration failed: {exc}")


class _PortalMcpImportClient(BaseModel):
    name: str = ""
    description: str = ""
    enabled: bool = False
    transport: str = "streamable_http"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""


class _PortalMcpImportRequest(BaseModel):
    client_key: str
    client: _PortalMcpImportClient


@router.post("/mcp/import")
async def portal_mcp_import(request: Request, body: _PortalMcpImportRequest):
    """Domain-checked MCP client creation for the Portal.

    Runs the domain-relevance judge on the client spec; off-domain or
    审核不可用 -> 422 with a structured ``domain_rejected`` payload. Otherwise
    creates the client (mirroring ``POST /api/mcp``).
    """
    from qwenpaw.app.agent_context import get_agent_for_request
    from qwenpaw.app.utils import schedule_agent_reload
    from qwenpaw.config.config import (
        MCPClientConfig,
        MCPConfig,
        save_agent_config,
    )
    from qwenpaw.extensions.api.domain_guard import judge_text_async

    client_key = (body.client_key or "").strip()
    if not client_key:
        raise HTTPException(status_code=400, detail="client_key 不能为空")
    c = body.client
    transport = (c.transport or "streamable_http").strip()
    if transport not in ("stdio", "streamable_http", "sse"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 transport: {transport}",
        )

    agent = await get_agent_for_request(request)

    # ---- domain relevance check ----
    cmd_line = " ".join(
        x for x in [(c.command or "").strip(), " ".join(c.args or [])] if x
    ).strip()
    extra = {
        "transport": transport,
        "url": (c.url or "").strip(),
        "command": cmd_line,
    }
    content = "\n".join(
        x for x in [c.description, extra["url"], cmd_line] if x
    )
    verdict = await judge_text_async(
        kind="mcp",
        name=(c.name or client_key),
        description=c.description or "",
        content=content,
        extra=extra,
    )
    if not verdict.allowed:
        return JSONResponse(
            status_code=422,
            content=verdict.to_payload(
                kind="mcp",
                name=(c.name or client_key),
            ),
        )

    # ---- create (mirror app/routers/mcp.py::create_mcp_client) ----
    if agent.config.mcp is None:
        agent.config.mcp = MCPConfig(clients={})
    if client_key in agent.config.mcp.clients:
        raise HTTPException(
            status_code=400,
            detail=f"MCP client '{client_key}' already exists. Use PUT to update.",
        )
    agent.config.mcp.clients[client_key] = MCPClientConfig(
        name=(c.name or client_key),
        description=c.description or "",
        enabled=bool(c.enabled),
        transport=transport,
        url=(c.url or "").strip(),
        headers=dict(c.headers or {}),
        command=(c.command or "").strip(),
        args=list(c.args or []),
        env=dict(c.env or {}),
        cwd=(c.cwd or "").strip(),
    )
    save_agent_config(agent.agent_id, agent.config)
    schedule_agent_reload(request, agent.agent_id)
    return {
        "created": True,
        "key": client_key,
        "name": (c.name or client_key),
        "domain_category": verdict.category,
    }


# ---------------------------------------------------------------------------
# FDE delivery workbench (Forward Deployed Engineer assistant)
#
# The ``fde`` agent (a dedicated digital employee) interviews delivery
# engineers in chat and scaffolds business skills into its own workspace's
# ``staged/`` dir. These endpoints let the Portal panel read those staged
# bundles, re-run self-checks, sandbox-probe them, and discard them. The
# actual install into a business agent's workspace is **not** done here —
# the panel calls the existing ``POST /api/skills`` (with ``X-Agent-Id``,
# which runs the security scan) after a human confirms.
# ---------------------------------------------------------------------------
def _fde_error_response(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"reason": "fde_workbench_error", "detail": str(exc)},
    )


# Every FDE service call shells out to ``fde_tools.py`` (and some of those runs
# import qwenpaw / scan the skill / probe it), which is blocking and can take a
# few seconds. Run them on a worker thread so the FastAPI event loop — which
# also serves the portal's status polling — never stalls behind one.
@router.get("/fde/workspace")
async def fde_workspace_info():
    try:
        return await asyncio.to_thread(fde_workbench_service.workbench_info)
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.get("/fde/staged")
async def fde_list_staged():
    try:
        return await asyncio.to_thread(
            fde_workbench_service.list_staged_skills,
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.post("/fde/generate")
async def fde_generate(body: FdeGenerateRequest):
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.generate_skill(
                name=body.name,
                target_workspace=body.target_workspace,
                brief=body.brief,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.get("/fde/staged/{skill_name}")
async def fde_show_staged(skill_name: str):
    try:
        return await asyncio.to_thread(
            fde_workbench_service.staged_detail_with_review,
            skill_name,
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.post("/fde/staged/{skill_name}/selfcheck")
async def fde_selfcheck_staged(skill_name: str):
    try:
        return await asyncio.to_thread(
            fde_workbench_service.selfcheck_staged_skill,
            skill_name,
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.put("/fde/staged/{skill_name}/fields")
async def fde_edit_staged_fields(
    skill_name: str,
    body: FdeEditFieldsRequest,
):
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.edit_staged_fields(
                skill_name,
                description=body.description,
                triggers=body.triggers,
                category=body.category,
                tags=body.tags,
                env=body.env,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.put("/fde/staged/{skill_name}/files")
async def fde_edit_staged_files(
    skill_name: str,
    body: FdeEditFilesRequest,
):
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.edit_staged_files(
                skill_name,
                [{"path": f.path, "content": f.content} for f in body.files],
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.post("/fde/staged/{skill_name}/review")
async def fde_review_staged(skill_name: str, body: FdeReviewRequest):
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.set_staged_review(
                skill_name,
                action=body.action,
                approved_by=body.approved_by,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.post("/fde/staged/{skill_name}/probe")
async def fde_probe_staged(
    skill_name: str,
    body: FdeProbeRequest | None = None,
):
    context = body.context if body else {}
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.probe_staged_skill(
                skill_name,
                context=context,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.post("/fde/staged/{skill_name}/install")
async def fde_install_staged(
    request: Request,
    skill_name: str,
    body: FdeInstallRequest | None = None,
):
    """Human-confirmed install of a staged skill into a business workspace.

    Goes through ``SkillService.create_skill`` (which runs the security scan),
    tags it ``二开``, leaves it enabled, then schedules the target agent's
    reload — same end state as installing via the skill panel. An optional
    ``target_workspace`` redirects it to a different existing agent (e.g. one
    the operator just created).
    """
    target_override = (body.target_workspace if body else "") or None
    skip_domain_check = bool(body.skip_domain_check) if body else False
    env_values = body.env_values if body else None
    mirror_to_gateway = (
        bool(body.mirror_to_gateway) if body is not None else True
    )
    try:
        result = await asyncio.to_thread(
            lambda: fde_workbench_service.install_staged_skill(
                skill_name,
                target_override=target_override,
                skip_domain_check=skip_domain_check,
                env_values=env_values,
                mirror_to_gateway=mirror_to_gateway,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)
    target_agent = result.get("target_workspace")
    if target_agent:
        try:
            from qwenpaw.app.utils import schedule_agent_reload

            schedule_agent_reload(request, str(target_agent))
        except Exception:  # noqa: BLE001 - reload is best-effort
            pass
    mirror = result.get("gateway_mirror") or {}
    if mirror.get("mirrored"):
        try:
            from qwenpaw.app.utils import schedule_agent_reload

            schedule_agent_reload(request, str(mirror.get("gateway_agent")))
        except Exception:  # noqa: BLE001
            pass
    return result


@router.delete("/fde/staged/{skill_name}")
async def fde_discard_staged(skill_name: str):
    try:
        return await asyncio.to_thread(
            fde_workbench_service.discard_staged_skill,
            skill_name,
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.get(
    "/fde/installed",
    summary="List FDE-installed (二开) skills across all business agents",
)
async def fde_list_installed():
    """Cross-agent view: every skill tagged ``二开`` in any workspace.

    The upstream skill-pool panel is scoped to the gateway agent only, so
    FDE-installed skills in other agents are invisible there. This feeds
    the workbench's own "已交付技能" view.
    """
    try:
        return await asyncio.to_thread(
            fde_workbench_service.list_installed_erkai_skills,
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


# --- installed-skill .env configuration -----------------------------------
# Lets operators fill credentials from the panel after install instead of
# SSH'ing to ``~/.qwenpaw/workspaces/<agent>/skills/<skill>/.env``.


@router.get(
    "/fde/installed/{target_workspace}/{skill_name}/env",
    summary="Read .env.example schema + current .env values for a "
    "FDE-installed skill",
)
async def fde_read_installed_env(target_workspace: str, skill_name: str):
    try:
        return await asyncio.to_thread(
            fde_workbench_service.read_skill_env_state,
            target_workspace,
            skill_name,
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


@router.post(
    "/fde/installed/{source_agent}/{skill_name}/copy",
    summary="Copy (or move) an installed 二开 skill to another agent",
)
async def fde_copy_installed(
    request: Request,
    source_agent: str,
    skill_name: str,
    body: FdeCopyInstalledRequest,
):
    """Cross-agent migration for FDE-installed skills.

    Fix path for "FDE put the skill in the wrong workspace, so gateway's
    routing never reaches it": the operator picks the correct destination
    from the panel and clicks 复制/迁移. Backend reads the source files,
    re-runs ``SkillService.create_skill`` against the target (security scan
    included), tags it ``二开``, and optionally deletes the source.
    """
    try:
        result = await asyncio.to_thread(
            lambda: fde_workbench_service.copy_installed_skill(
                source_agent=source_agent,
                skill_name=skill_name,
                target_workspace=body.target_workspace,
                remove_source=body.remove_source,
                skip_domain_check=body.skip_domain_check,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)
    target_agent = result.get("target_workspace")
    if target_agent:
        try:
            from qwenpaw.app.utils import schedule_agent_reload

            schedule_agent_reload(request, str(target_agent))
        except Exception:  # noqa: BLE001 - reload is best-effort
            pass
    if body.remove_source and result.get("removed_source"):
        try:
            from qwenpaw.app.utils import schedule_agent_reload

            schedule_agent_reload(request, source_agent)
        except Exception:  # noqa: BLE001
            pass
    mirror = result.get("gateway_mirror") or {}
    if mirror.get("mirrored"):
        try:
            from qwenpaw.app.utils import schedule_agent_reload

            schedule_agent_reload(request, str(mirror.get("gateway_agent")))
        except Exception:  # noqa: BLE001
            pass
    return result


@router.delete(
    "/fde/installed/{target_workspace}/{skill_name}",
    summary="Delete an FDE-installed skill (+ its gateway mirror, if any)",
)
async def fde_delete_installed(
    request: Request,
    target_workspace: str,
    skill_name: str,
):
    """Remove an installed 二开 skill from its agent (and the gateway mirror
    by default). Disables before deleting since SkillService refuses to
    delete an enabled skill."""
    try:
        result = await asyncio.to_thread(
            lambda: fde_workbench_service.delete_installed_skill(
                target_workspace=target_workspace,
                skill_name=skill_name,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)
    try:
        from qwenpaw.app.utils import schedule_agent_reload

        schedule_agent_reload(request, target_workspace)
        if result.get("gateway_mirror_removed"):
            schedule_agent_reload(
                request,
                fde_workbench_service.GATEWAY_AGENT_ID,
            )
    except Exception:  # noqa: BLE001 - reload is best-effort
        pass
    return result


@router.put("/fde/installed/{target_workspace}/{skill_name}/env")
async def fde_write_installed_env(
    target_workspace: str,
    skill_name: str,
    body: FdeEnvWriteRequest,
):
    """Write/update the installed skill's ``.env`` (mode 0600)."""
    try:
        return await asyncio.to_thread(
            lambda: fde_workbench_service.write_skill_env(
                target_workspace=target_workspace,
                skill_name=skill_name,
                values=body.values,
            ),
        )
    except fde_workbench_service.FdeWorkbenchError as exc:
        return _fde_error_response(exc)


def register_app_routes(fastapi_app) -> None:
    """Register portal routes on the main QwenPaw FastAPI app."""
    if not getattr(fastapi_app.state, "portal_api_compat_installed", False):

        @fastapi_app.middleware("http")
        async def portal_api_compat_middleware(request: Request, call_next):
            path = request.scope.get("path", "")
            if isinstance(path, str) and path.startswith("/portal-api/"):
                request.scope[
                    "path"
                ] = f"/api/portal{path[len('/portal-api'):]}"
            return await call_next(request)

        @fastapi_app.middleware("http")
        async def inoe_token_passthrough_middleware(
            request: Request, call_next
        ):
            # SSO pass-through (see portal/src/auth/ssoSession.ts): when
            # the logged-in user's own INOE token is sent on this header,
            # every INOE call made while handling this request uses it
            # instead of the shared configured token — so query results
            # reflect that user's own INOE/CMDB permissions. Absent for
            # background tasks and non-SSO setups, which keep using the
            # configured token via inoe_settings_store.get_token().
            token = request.headers.get("X-Inoe-Token")
            ctx_token = inoe_settings_store.CURRENT_REQUEST_TOKEN.set(
                token or None
            )
            try:
                return await call_next(request)
            finally:
                inoe_settings_store.CURRENT_REQUEST_TOKEN.reset(ctx_token)

        fastapi_app.state.portal_api_compat_installed = True

    fastapi_app.include_router(router)


# ---------------------------------------------------------------------------
# Alarm Registry Management API
# ---------------------------------------------------------------------------


@router.get("/alarm-registry/records")
async def list_alarm_registry_records(
    status: str = Query(
        default="",
        description="Filter by status (comma-separated)",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str = Query(
        default="",
        description="Search in title/deviceName/manageIp/alarmId",
    ),
):
    """List all alarm registry records with filtering and pagination."""
    try:
        all_records = load_alarm_records()
        items = list(all_records.values())

        # Filter by status
        if status.strip():
            allowed_statuses = {
                s.strip() for s in status.split(",") if s.strip()
            }
            items = [
                r for r in items if r.get("status", "") in allowed_statuses
            ]

        # Search filter
        search_term = search.strip().lower()
        if search_term:
            items = [
                r
                for r in items
                if search_term in str(r.get("title", "")).lower()
                or search_term in str(r.get("deviceName", "")).lower()
                or search_term in str(r.get("manageIp", "")).lower()
                or search_term in str(r.get("alarmId", "")).lower()
                or search_term in str(r.get("resId", "")).lower()
            ]

        # Sort: eventLastTime → eventTime → handledAt/takenOverAt/updatedAt, all desc
        items.sort(
            key=lambda r: (
                r.get("eventLastTime", "") or "",
                r.get("eventTime", "") or "",
                r.get("handledAt", "")
                or r.get("takenOverAt", "")
                or r.get("updatedAt", "")
                or "",
            ),
            reverse=True,
        )

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]

        return {
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": (
                (total + page_size - 1) // page_size if total > 0 else 0
            ),
            "items": page_items,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/alarm-registry/records/{alarm_id}/status")
async def update_alarm_registry_status(
    alarm_id: str,
    payload: dict = Body(default_factory=dict),
):
    """Update the status and/or chatId of an alarm registry record."""
    new_status = str(payload.get("status", "")).strip()
    new_chat_id = str(payload.get("chatId", "")).strip()
    if not new_status and not new_chat_id:
        raise HTTPException(
            status_code=422,
            detail="status or chatId is required",
        )
    if new_status:
        allowed_statuses = {
            "new",
            "taken_over",
            "analyzing",
            "analyzed",
            "manual_pending",
            "manual_recovered",
            "manual_unrecovered",
            "manual_unknown",
            "resolved",
            "ignored",
        }
        if new_status not in allowed_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{new_status}'. Allowed: {sorted(allowed_statuses)}",
            )
    try:
        kwargs: dict[str, Any] = {"alarm_id": alarm_id}
        if new_status:
            kwargs["status"] = new_status
        if new_chat_id:
            kwargs["chat_id"] = new_chat_id
        record = update_alarm_record(**kwargs)
        return {"ok": True, "record": record}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/alarm-registry/register")
async def register_alarm_registry_record(
    payload: dict = Body(default_factory=dict),
):
    """Register an alarm in the registry (upsert). Used by manual bell dispatch."""
    alarm_id = str(payload.get("alarmId", "")).strip()
    if not alarm_id:
        raise HTTPException(status_code=422, detail="alarmId is required")
    alarm_data = {
        "id": alarm_id,
        "resId": str(payload.get("resId", "")).strip(),
        "title": str(payload.get("title", "")).strip(),
        "deviceName": str(payload.get("deviceName", "")).strip(),
        "manageIp": str(payload.get("manageIp", "")).strip(),
        "eventTime": str(payload.get("eventTime", "")).strip(),
        "eventLastTime": str(payload.get("eventLastTime", "")).strip(),
        "actCount": str(payload.get("actCount", "")).strip(),
        "visibleContent": str(payload.get("visibleContent", "")).strip(),
    }
    try:
        record = update_alarm_record(
            alarm=alarm_data,
            alarm_id=alarm_id,
            status=str(payload.get("status", "analyzing")).strip(),
            source=str(payload.get("source", "manual-bell")).strip(),
        )
        return {"ok": True, "record": record}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/alarm-registry/export")
async def export_alarm_registry_records(
    status: str = Query(
        default="",
        description="Filter by status (comma-separated)",
    ),
):
    """Export alarm registry records as JSON."""
    try:
        all_records = load_alarm_records()
        items = list(all_records.values())

        if status.strip():
            allowed_statuses = {
                s.strip() for s in status.split(",") if s.strip()
            }
            items = [
                r for r in items if r.get("status", "") in allowed_statuses
            ]

        items.sort(
            key=lambda r: (
                r.get("eventTime", "") or "",
                r.get("handledAt", "")
                or r.get("takenOverAt", "")
                or r.get("updatedAt", "")
                or "",
            ),
            reverse=True,
        )

        return JSONResponse(
            content={"total": len(items), "items": items},
            headers={
                "Content-Disposition": "attachment; filename=alarm_registry_export.json",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/alarm-registry/stats")
async def alarm_registry_stats():
    """Get summary statistics of alarm registry records."""
    try:
        all_records = load_alarm_records()
        status_counts: dict[str, int] = {}
        for record in all_records.values():
            s = record.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        return {
            "total": len(all_records),
            "byStatus": status_counts,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


app.include_router(router)
