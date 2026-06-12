# -*- coding: utf-8 -*-
"""AI big-screen service facade (slim).

Generation (L1/L2/L3), patching, sanitization and capability execution
live in ``qwenpaw.extensions.ai_big_screen`` (the P2 redesign). This
module keeps the HTTP-facing surface stable: asset CRUD and draft
tasks over the SQLite store (restart-safe, multi-worker consistent;
the legacy registry.json is auto-migrated on first use) plus thin
wrappers around the pipeline.
"""
from __future__ import annotations

import asyncio
import copy
import time
import uuid
from typing import Any, Mapping

from qwenpaw.extensions.ai_big_screen import store, telemetry
from qwenpaw.extensions.ai_big_screen.capabilities import (
    list_capability_metadata,
)
from qwenpaw.extensions.ai_big_screen.llm import CONFIGURE_LLM_MESSAGE
from qwenpaw.extensions.ai_big_screen.orchestration import (
    SCREEN_SCHEMA_VERSION,
    build_version,
    now_iso,
)
from qwenpaw.extensions.ai_big_screen.patch import apply_patch
from qwenpaw.extensions.ai_big_screen.pipeline import (
    refresh_screen_data,
    run_draft_pipeline,
)
from qwenpaw.extensions.api.ai_big_screen_models import (
    AiBigScreenDraftRequest,
    AiBigScreenPatchRequest,
)

__all__ = [
    "SCREEN_SCHEMA_VERSION",
    "AI_BIG_SCREEN_CONFIGURE_LLM_MESSAGE",
    "build_screen_draft",
    "create_screen_draft_task",
    "get_screen_draft_task",
    "list_builtin_plugins",
    "save_screen_asset",
    "list_screen_assets",
    "get_screen_asset",
    "delete_screen_asset",
    "rename_screen_asset",
    "duplicate_screen_asset",
    "publish_screen_asset",
    "patch_screen_asset",
    "refresh_screen_asset",
    "summarize_generation_metrics",
]

AI_BIG_SCREEN_CONFIGURE_LLM_MESSAGE = CONFIGURE_LLM_MESSAGE


def _now_iso() -> str:
    return now_iso()


def list_builtin_plugins() -> list[dict[str, Any]]:
    return list_capability_metadata()


def summarize_generation_metrics(*, limit: int = 100) -> dict[str, Any]:
    """Quality signals over the recent generation window (M2)."""
    return telemetry.summarize(limit=limit)


def _extract_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


# ---------------------------------------------------------------------------
# draft generation (delegates to the pipeline)
# ---------------------------------------------------------------------------


async def build_screen_draft(
    request: AiBigScreenDraftRequest,
) -> dict[str, Any]:
    return await run_draft_pipeline(
        prompt=str(request.prompt or ""),
        title=str(request.title or ""),
        requested_by=str(request.requestedBy or "portal"),
    )


_TASK_TTL_SECONDS = 24 * 3600


def create_screen_draft_task(
    request: AiBigScreenDraftRequest,
) -> dict[str, Any]:
    task_id = f"task-{uuid.uuid4().hex[:10]}"
    now = _now_iso()
    task = {
        "taskId": task_id,
        "status": "queued",
        "stage": "queued",
        "message": "已创建生成任务",
        "createdAt": now,
        "updatedAt": now,
        "screen": None,
        "error": "",
    }
    # SQLite-backed: tasks survive restarts and are visible from every
    # uvicorn worker (the legacy in-memory dict 404'd when the poll
    # request landed on a different worker than the creator).
    store.create_task(task=task)
    try:
        store.purge_tasks(ttl_seconds=_TASK_TTL_SECONDS)
    except Exception:  # housekeeping must never block creation
        pass
    asyncio.create_task(_run_screen_draft_task(task_id, request))
    return dict(task)


def get_screen_draft_task(task_id: str) -> dict[str, Any]:
    return store.get_task(task_id=task_id)


async def _run_screen_draft_task(
    task_id: str,
    request: AiBigScreenDraftRequest,
) -> None:
    def _on_stage(stage: str, message: str) -> None:
        _update_screen_draft_task(
            task_id,
            status="running",
            stage=stage,
            message=message,
        )

    try:
        screen = await run_draft_pipeline(
            prompt=str(request.prompt or ""),
            title=str(request.title or ""),
            requested_by=str(request.requestedBy or "portal"),
            on_stage=_on_stage,
        )
    except Exception as exc:
        _update_screen_draft_task(
            task_id,
            status="failed",
            stage="failed",
            message="生成失败",
            error=_extract_exception_message(exc),
        )
        # the success path records inside run_draft_pipeline; failures
        # would otherwise be invisible to the quality metrics
        telemetry.record_generation(
            {
                "kind": "draft",
                "success": False,
                "degraded": False,
                "error": _extract_exception_message(exc)[:300],
                "promptChars": len(str(request.prompt or "")),
            },
        )
        return
    _update_screen_draft_task(
        task_id,
        status="succeeded",
        stage="completed",
        message="生成完成",
        screen=screen,
    )


def _update_screen_draft_task(task_id: str, **updates: Any) -> None:
    store.update_task(task_id=task_id, updates=updates)


def _component_statuses(screen: Mapping[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for component in screen.get("components") or []:
        if not isinstance(component, dict):
            continue
        capability_id = str(
            component.get("capabilityId") or component.get("pluginId") or "",
        )
        data = component.get("data")
        if capability_id and isinstance(data, dict):
            statuses[capability_id] = str(data.get("sourceStatus") or "")
    return statuses


async def refresh_screen_asset(*, screen_id: str) -> dict[str, Any]:
    """Re-hydrate a saved screen's data (L2 only) and persist it."""
    started = time.monotonic()
    screen = store.get_screen(screen_id=screen_id)
    refreshed = await refresh_screen_data(screen)
    saved = store.save_screen(screen=refreshed, requested_by="auto-refresh")
    telemetry.record_generation(
        {
            "kind": "refresh",
            "success": True,
            "degraded": False,
            "durationMs": int((time.monotonic() - started) * 1000),
            "screenId": screen_id,
            "capabilityStatuses": _component_statuses(saved),
        },
    )
    return saved


# ---------------------------------------------------------------------------
# patch (delegates to the unified patch generator)
# ---------------------------------------------------------------------------


async def patch_screen_asset(
    *,
    screen_id: str,
    request: AiBigScreenPatchRequest,
) -> dict[str, Any]:
    started = time.monotonic()
    screen = store.get_screen(screen_id=screen_id)
    try:
        outcome = await apply_patch(
            screen=screen,
            instruction=str(request.instruction or ""),
            selected_component_id=str(request.selectedComponentId or ""),
            selected_component_ids=list(request.selectedComponentIds or []),
            selected_region=request.selectedRegion or {},
            selection_context=request.selectionContext or {},
            requested_by=str(request.requestedBy or "portal"),
        )
    except Exception as exc:
        telemetry.record_generation(
            {
                "kind": "patch",
                "success": False,
                "degraded": False,
                "durationMs": int((time.monotonic() - started) * 1000),
                "screenId": screen_id,
                "error": _extract_exception_message(exc)[:300],
            },
        )
        raise
    saved = store.save_screen(
        screen=outcome["screen"],
        requested_by=str(request.requestedBy or "portal"),
    )
    context = saved.get("aiConversationContext")
    telemetry.record_generation(
        {
            "kind": "patch",
            "success": True,
            "degraded": bool(
                isinstance(context, dict) and context.get("degraded"),
            ),
            "durationMs": int((time.monotonic() - started) * 1000),
            "screenId": screen_id,
            "instructionChars": len(str(request.instruction or "")),
        },
    )
    return {
        "screen": saved,
        "version": outcome["version"],
        "summary": outcome["summary"],
    }


# ---------------------------------------------------------------------------
# asset CRUD (registry-backed; SQLite replaces this in P3)
# ---------------------------------------------------------------------------


def _validate_screen(screen: Mapping[str, Any]) -> None:
    if not str(screen.get("id") or "").strip():
        raise ValueError("screen.id 不能为空")
    if not str(screen.get("name") or "").strip():
        raise ValueError("screen.name 不能为空")
    components = screen.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("screen.components 不能为空")


def save_screen_asset(
    *,
    screen: Mapping[str, Any],
    requested_by: str = "portal",
) -> dict[str, Any]:
    normalized = dict(screen)
    _validate_screen(normalized)
    return store.save_screen(screen=normalized, requested_by=requested_by)


def list_screen_assets(*, limit: int = 50) -> list[dict[str, Any]]:
    return store.list_screens(limit=limit)


def get_screen_asset(*, screen_id: str) -> dict[str, Any]:
    return store.get_screen(screen_id=screen_id)


def delete_screen_asset(*, screen_id: str) -> dict[str, Any]:
    deleted = store.delete_screen(screen_id=screen_id)
    return {
        "screenId": str(deleted.get("id") or screen_id),
        "deleted": True,
    }


def rename_screen_asset(
    *,
    screen_id: str,
    name: str,
    requested_by: str = "portal",
) -> dict[str, Any]:
    next_name = str(name or "").strip()
    if not next_name:
        raise ValueError("name 不能为空")
    screen = store.get_screen(screen_id=screen_id)
    screen["name"] = next_name[:80]
    raw_context = screen.get("aiConversationContext")
    screen["aiConversationContext"] = {
        **(dict(raw_context) if isinstance(raw_context, dict) else {}),
        "lastInstruction": "重命名大屏",
    }
    return store.save_screen(screen=screen, requested_by=requested_by)


def duplicate_screen_asset(
    *,
    screen_id: str,
    name: str = "",
    requested_by: str = "portal",
) -> dict[str, Any]:
    source = store.get_screen(screen_id=screen_id)
    now = _now_iso()
    duplicated = copy.deepcopy(source)
    duplicated["id"] = f"screen-{uuid.uuid4().hex[:10]}"
    duplicated["name"] = (
        str(name or "").strip() or f"{source.get('name') or 'AI 大屏'} 副本"
    )
    duplicated["status"] = "draft"
    duplicated["owner"] = str(requested_by or "portal").strip() or "portal"
    duplicated["createdAt"] = now
    duplicated["updatedAt"] = now
    duplicated["publishTargets"] = []
    raw_permissions = duplicated.get("permissions")
    duplicated["permissions"] = {
        **(dict(raw_permissions) if isinstance(raw_permissions, dict) else {}),
        "visibility": "private",
    }
    duplicated["versions"] = [
        build_version(
            screen=duplicated,
            version_id="v1",
            summary=f"从 {source.get('name') or screen_id} 复制生成。",
            requested_by=requested_by,
        ),
    ]
    raw_context = duplicated.get("aiConversationContext")
    duplicated["aiConversationContext"] = {
        **(dict(raw_context) if isinstance(raw_context, dict) else {}),
        "lastInstruction": "复制大屏",
        "duplicatedFrom": screen_id,
    }
    _validate_screen(duplicated)
    return store.save_screen(screen=duplicated, requested_by=requested_by)


def publish_screen_asset(
    *,
    screen_id: str,
    requested_by: str = "portal",
    visibility: str = "internal",
) -> dict[str, Any]:
    screen = store.get_screen(screen_id=screen_id)
    now = _now_iso()
    normalized_visibility = str(visibility or "internal").strip() or "internal"
    publish_targets = [
        {
            "type": "portal-center",
            "url": "/big-screens",
            "visibility": normalized_visibility,
            "createdAt": now,
            "createdBy": requested_by,
        },
        {
            "type": "external-link",
            "url": f"/big-screen/{screen_id}",
            "visibility": normalized_visibility,
            "createdAt": now,
            "createdBy": requested_by,
        },
        {
            "type": "iframe",
            "url": f"/big-screen/{screen_id}?embed=1",
            "visibility": normalized_visibility,
            "createdAt": now,
            "createdBy": requested_by,
        },
    ]
    screen["status"] = "published"
    raw_permissions = screen.get("permissions")
    screen["permissions"] = {
        **(dict(raw_permissions) if isinstance(raw_permissions, dict) else {}),
        "visibility": normalized_visibility,
    }
    screen["publishTargets"] = publish_targets
    raw_context = screen.get("aiConversationContext")
    screen["aiConversationContext"] = {
        **(dict(raw_context) if isinstance(raw_context, dict) else {}),
        "lastInstruction": "发布大屏",
    }
    saved = store.save_screen(screen=screen, requested_by=requested_by)
    return {"screen": saved, "publishTargets": publish_targets}
