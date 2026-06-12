# -*- coding: utf-8 -*-
"""统一轻应用货架 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from qwenpaw.extensions.api.light_apps_models import LightAppListResponse
from qwenpaw.extensions.api.light_apps_service import list_light_apps

router = APIRouter(prefix="/light-apps", tags=["portal"])


@router.get("", response_model=LightAppListResponse)
def list_light_apps_endpoint(
    limit: int = Query(default=100, ge=1, le=200, description="返回条数上限"),
) -> LightAppListResponse:
    """列出应用中心货架上的全部轻应用（任务应用 + 页面应用）。"""
    return LightAppListResponse(items=list_light_apps(limit=limit))
