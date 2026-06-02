# -*- coding: utf-8 -*-
"""应用成果发布 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from qwenpaw.extensions.api.app_artifacts_models import (
    AppArtifactCreate,
    AppArtifactListResponse,
    AppArtifactResponse,
    AppArtifactUpdate,
)
from qwenpaw.extensions.api.app_artifacts_service import (
    create_app,
    delete_app,
    get_app,
    get_app_versions,
    get_html_content,
    list_apps,
    update_app,
)

router = APIRouter(prefix="/app-artifacts", tags=["portal"])


@router.post("", response_model=AppArtifactResponse)
async def publish_app(body: AppArtifactCreate):
    """发布一个新应用/卡片。"""
    result = create_app(
        title=body.title,
        description=body.description,
        app_type=body.type,
        html_content=body.html_content,
        config=body.config,
        tags=body.tags,
        session_id=body.session_id,
        author="",
    )
    return result


@router.get("", response_model=AppArtifactListResponse)
async def list_artifacts(
    type: str | None = Query(default=None, description="过滤类型: app|widget|dashboard"),
    status: str | None = Query(default=None, description="过滤状态: draft|published|offline"),
    search: str | None = Query(default=None, description="搜索标题/描述/标签"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
):
    """查询应用列表。"""
    return list_apps(
        app_type=type,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/{app_id}", response_model=AppArtifactResponse)
async def get_artifact(app_id: str):
    """获取应用详情。"""
    result = get_app(app_id)
    if result is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    return result


@router.put("/{app_id}", response_model=AppArtifactResponse)
async def update_artifact(app_id: str, body: AppArtifactUpdate):
    """更新应用（可更新标题、描述、HTML、配置、标签、状态）。"""
    result = update_app(
        app_id,
        title=body.title,
        description=body.description,
        html_content=body.html_content,
        config=body.config,
        tags=body.tags,
        status=body.status,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    return result


@router.delete("/{app_id}")
async def delete_artifact(app_id: str):
    """删除应用。"""
    success = delete_app(app_id)
    if not success:
        raise HTTPException(status_code=404, detail="应用不存在")
    return {"detail": "已删除"}


@router.get("/{app_id}/versions")
async def get_artifact_versions(app_id: str):
    """获取应用版本历史。"""
    app = get_app(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    versions = get_app_versions(app_id)
    return {"app_id": app_id, "versions": versions}


@router.get("/{app_id}/preview", response_class=HTMLResponse)
async def preview_artifact(app_id: str):
    """预览应用的 HTML 内容（直接返回 HTML）。"""
    html = get_html_content(app_id)
    if html is None:
        raise HTTPException(status_code=404, detail="应用不存在或 HTML 文件缺失")
    return HTMLResponse(content=html)
