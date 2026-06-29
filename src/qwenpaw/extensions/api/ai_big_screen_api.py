# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from qwenpaw.extensions.api.ai_big_screen_models import (
    AiBigScreenCapabilityConfigResponse,
    AiBigScreenDeleteResponse,
    AiBigScreenDuplicateRequest,
    AiBigScreenDraftRequest,
    AiBigScreenListResponse,
    AiBigScreenMetricsResponse,
    AiBigScreenPatchRequest,
    AiBigScreenPatchResponse,
    AiBigScreenPluginsResponse,
    AiBigScreenPublishRequest,
    AiBigScreenPublishResponse,
    AiBigScreenRenameRequest,
    AiBigScreenResponse,
    AiBigScreenSaveRequest,
    AiBigScreenTaskResponse,
)
from qwenpaw.extensions.api.ai_big_screen_service import (
    build_screen_draft,
    create_screen_draft_task,
    delete_screen_asset,
    duplicate_screen_asset,
    get_screen_asset,
    get_screen_draft_task,
    list_builtin_plugins,
    list_screen_assets,
    patch_screen_asset,
    publish_screen_asset,
    refresh_screen_asset,
    rename_screen_asset,
    save_screen_asset,
    summarize_capability_config,
    summarize_generation_metrics,
)

router = APIRouter(prefix="/ai-big-screens", tags=["portal"])


@router.get("/plugins", response_model=AiBigScreenPluginsResponse)
def list_ai_big_screen_plugins() -> AiBigScreenPluginsResponse:
    return AiBigScreenPluginsResponse(items=list_builtin_plugins())


# NOTE: must be registered before the catch-all "/{screen_id}" route.
@router.get("/metrics", response_model=AiBigScreenMetricsResponse)
def get_ai_big_screen_metrics(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> AiBigScreenMetricsResponse:
    """Generation quality over the recent window (success/degraded/…)."""
    return AiBigScreenMetricsResponse(
        **summarize_generation_metrics(
            limit=limit,
        ),
    )


# NOTE: must be registered before the catch-all "/{screen_id}" route.
@router.get(
    "/capability-config",
    response_model=AiBigScreenCapabilityConfigResponse,
)
def get_ai_big_screen_capability_config() -> (
    AiBigScreenCapabilityConfigResponse
):
    """Each capability's functional domain + backing-connection health."""
    return AiBigScreenCapabilityConfigResponse(
        **summarize_capability_config(),
    )


@router.get("", response_model=AiBigScreenListResponse)
def list_ai_big_screens(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AiBigScreenListResponse:
    return AiBigScreenListResponse(items=list_screen_assets(limit=limit))


@router.post("/draft", response_model=AiBigScreenResponse)
async def generate_ai_big_screen_draft(
    payload: AiBigScreenDraftRequest,
) -> AiBigScreenResponse:
    try:
        return AiBigScreenResponse(screen=await build_screen_draft(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/draft-tasks", response_model=AiBigScreenTaskResponse)
async def create_ai_big_screen_draft_task(
    payload: AiBigScreenDraftRequest,
) -> AiBigScreenTaskResponse:
    try:
        return AiBigScreenTaskResponse(task=create_screen_draft_task(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/draft-tasks/{task_id}", response_model=AiBigScreenTaskResponse)
def get_ai_big_screen_draft_task(task_id: str) -> AiBigScreenTaskResponse:
    try:
        return AiBigScreenTaskResponse(task=get_screen_draft_task(task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("", response_model=AiBigScreenResponse)
def save_ai_big_screen(payload: AiBigScreenSaveRequest) -> AiBigScreenResponse:
    try:
        return AiBigScreenResponse(
            screen=save_screen_asset(
                screen=payload.screen,
                requested_by=payload.requestedBy,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{screen_id}", response_model=AiBigScreenResponse)
def get_ai_big_screen(screen_id: str) -> AiBigScreenResponse:
    try:
        return AiBigScreenResponse(
            screen=get_screen_asset(screen_id=screen_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{screen_id}", response_model=AiBigScreenDeleteResponse)
def delete_ai_big_screen(screen_id: str) -> AiBigScreenDeleteResponse:
    try:
        return AiBigScreenDeleteResponse(
            **delete_screen_asset(screen_id=screen_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{screen_id}/rename", response_model=AiBigScreenResponse)
def rename_ai_big_screen(
    screen_id: str,
    payload: AiBigScreenRenameRequest,
) -> AiBigScreenResponse:
    try:
        return AiBigScreenResponse(
            screen=rename_screen_asset(
                screen_id=screen_id,
                name=payload.name,
                requested_by=payload.requestedBy,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{screen_id}/duplicate", response_model=AiBigScreenResponse)
def duplicate_ai_big_screen(
    screen_id: str,
    payload: AiBigScreenDuplicateRequest,
) -> AiBigScreenResponse:
    try:
        return AiBigScreenResponse(
            screen=duplicate_screen_asset(
                screen_id=screen_id,
                name=payload.name,
                requested_by=payload.requestedBy,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{screen_id}/refresh", response_model=AiBigScreenResponse)
async def refresh_ai_big_screen(screen_id: str) -> AiBigScreenResponse:
    """Re-run data hydration only — keeps published screens alive."""
    try:
        return AiBigScreenResponse(
            screen=await refresh_screen_asset(screen_id=screen_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{screen_id}/patch", response_model=AiBigScreenPatchResponse)
async def patch_ai_big_screen(
    screen_id: str,
    payload: AiBigScreenPatchRequest,
) -> AiBigScreenPatchResponse:
    try:
        return AiBigScreenPatchResponse(
            **await patch_screen_asset(screen_id=screen_id, request=payload),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{screen_id}/publish", response_model=AiBigScreenPublishResponse)
def publish_ai_big_screen(
    screen_id: str,
    payload: AiBigScreenPublishRequest,
) -> AiBigScreenPublishResponse:
    try:
        return AiBigScreenPublishResponse(
            **publish_screen_asset(
                screen_id=screen_id,
                requested_by=payload.requestedBy,
                visibility=payload.visibility,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
