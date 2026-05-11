from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from qwenpaw.extensions.api.natural_language_customization_models import (
    NlCustomizationPreviewRequest,
    NlCustomizationPreviewResponse,
    NlCustomizationPublishRequest,
    NlCustomizationPublishResponse,
    NlCustomizationVersionListResponse,
)
from qwenpaw.extensions.api.natural_language_customization_service import (
    build_nl_customization_preview,
    list_nl_customization_versions,
    publish_nl_customization,
)

router = APIRouter(prefix="/nl-customization", tags=["portal"])


@router.post("/preview", response_model=NlCustomizationPreviewResponse)
async def preview_nl_customization(
    payload: NlCustomizationPreviewRequest,
) -> NlCustomizationPreviewResponse:
    try:
        return await build_nl_customization_preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/publish", response_model=NlCustomizationPublishResponse)
def publish_nl_customization_route(
    payload: NlCustomizationPublishRequest,
) -> NlCustomizationPublishResponse:
    try:
        result = publish_nl_customization(
            preview=payload.preview,
            requested_by=payload.requestedBy,
            title=payload.title,
        )
        return NlCustomizationPublishResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/versions", response_model=NlCustomizationVersionListResponse)
def list_nl_customization_versions_route(
    limit: int = Query(20, ge=1, le=100),
) -> NlCustomizationVersionListResponse:
    try:
        return NlCustomizationVersionListResponse(
            items=list_nl_customization_versions(limit=limit),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
