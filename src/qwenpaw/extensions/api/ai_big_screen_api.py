from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from qwenpaw.extensions.api.ai_big_screen_models import (
    AiBigScreenDraftRequest,
    AiBigScreenListResponse,
    AiBigScreenPatchRequest,
    AiBigScreenPatchResponse,
    AiBigScreenPluginsResponse,
    AiBigScreenPublishRequest,
    AiBigScreenPublishResponse,
    AiBigScreenResponse,
    AiBigScreenSaveRequest,
)
from qwenpaw.extensions.api.ai_big_screen_service import (
    build_screen_draft,
    get_screen_asset,
    list_builtin_plugins,
    list_screen_assets,
    patch_screen_asset,
    publish_screen_asset,
    save_screen_asset,
)

router = APIRouter(prefix="/ai-big-screens", tags=["portal"])


@router.get("/plugins", response_model=AiBigScreenPluginsResponse)
def list_ai_big_screen_plugins() -> AiBigScreenPluginsResponse:
    return AiBigScreenPluginsResponse(items=list_builtin_plugins())


@router.get("", response_model=AiBigScreenListResponse)
def list_ai_big_screens(
    limit: int = Query(50, ge=1, le=200),
) -> AiBigScreenListResponse:
    return AiBigScreenListResponse(items=list_screen_assets(limit=limit))


@router.post("/draft", response_model=AiBigScreenResponse)
def generate_ai_big_screen_draft(
    payload: AiBigScreenDraftRequest,
) -> AiBigScreenResponse:
    try:
        return AiBigScreenResponse(screen=build_screen_draft(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        return AiBigScreenResponse(screen=get_screen_asset(screen_id=screen_id))
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
