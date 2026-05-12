from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from qwenpaw.extensions.api.natural_language_customization_models import (
    NlCustomizationActiveResponse,
    NlCustomizationAppListResponse,
    NlCustomizationApplyRequest,
    NlCustomizationApplyResponse,
    NlCustomizationDeleteResponse,
    NlCustomizationListingRequest,
    NlCustomizationListingResponse,
    NlCustomizationPreviewRequest,
    NlCustomizationPreviewResponse,
    NlCustomizationPublishRequest,
    NlCustomizationPublishResponse,
    NlCustomizationVersionDetailResponse,
    NlCustomizationVersionListResponse,
)
from qwenpaw.extensions.api.natural_language_customization_service import (
    apply_nl_customization_version,
    build_nl_customization_preview,
    delete_nl_customization_version,
    get_nl_customization_version,
    get_active_nl_customization,
    list_nl_customization_apps,
    list_nl_customization_versions,
    publish_nl_customization,
    update_nl_customization_listing,
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


@router.post("/apply", response_model=NlCustomizationApplyResponse)
def apply_nl_customization_route(
    payload: NlCustomizationApplyRequest,
) -> NlCustomizationApplyResponse:
    try:
        result = apply_nl_customization_version(
            version_id=payload.versionId,
            requested_by=payload.requestedBy,
        )
        return NlCustomizationApplyResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/listing", response_model=NlCustomizationListingResponse)
def update_nl_customization_listing_route(
    payload: NlCustomizationListingRequest,
) -> NlCustomizationListingResponse:
    try:
        result = update_nl_customization_listing(request=payload)
        return NlCustomizationListingResponse(**result)
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


@router.get("/versions/{version_id}", response_model=NlCustomizationVersionDetailResponse)
def get_nl_customization_version_route(
    version_id: str,
) -> NlCustomizationVersionDetailResponse:
    try:
        return NlCustomizationVersionDetailResponse(
            **get_nl_customization_version(version_id=version_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/versions/{version_id}", response_model=NlCustomizationDeleteResponse)
def delete_nl_customization_version_route(
    version_id: str,
) -> NlCustomizationDeleteResponse:
    try:
        return NlCustomizationDeleteResponse(
            **delete_nl_customization_version(version_id=version_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/active", response_model=NlCustomizationActiveResponse)
def get_active_nl_customization_route() -> NlCustomizationActiveResponse:
    try:
        return NlCustomizationActiveResponse(**get_active_nl_customization())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/apps", response_model=NlCustomizationAppListResponse)
def list_nl_customization_apps_route(
    limit: int = Query(50, ge=1, le=200),
) -> NlCustomizationAppListResponse:
    try:
        return NlCustomizationAppListResponse(
            items=list_nl_customization_apps(limit=limit),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
