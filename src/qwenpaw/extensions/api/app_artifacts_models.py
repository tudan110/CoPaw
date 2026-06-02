# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AppArtifactCreate(BaseModel):
    """发布应用/卡片的请求体。"""

    title: str = Field(..., min_length=1, max_length=200, description="应用标题")
    description: str = Field(default="", max_length=2000, description="应用描述")
    type: str = Field(default="app", pattern=r"^(app|widget|dashboard)$", description="类型")
    html_content: str = Field(..., min_length=1, description="HTML 内容")
    config: dict[str, Any] | None = Field(default=None, description="配置信息")
    tags: list[str] = Field(default_factory=list, description="标签")
    session_id: str | None = Field(default=None, description="关联的开发会话 ID")


class AppArtifactUpdate(BaseModel):
    """更新应用的请求体。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    html_content: str | None = Field(default=None, min_length=1)
    config: dict[str, Any] | None = None
    tags: list[str] | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|published|offline)$")


class AppArtifactResponse(BaseModel):
    """应用详情响应。"""

    id: str
    title: str
    description: str
    type: str
    status: str
    author: str
    session_id: str | None
    html_path: str
    url: str
    config: dict[str, Any] | None
    tags: list[str]
    version: int
    created_at: str
    updated_at: str


class AppArtifactListItem(BaseModel):
    """应用列表项（不含 HTML 内容）。"""

    id: str
    title: str
    description: str
    type: str
    status: str
    author: str
    url: str
    tags: list[str]
    version: int
    created_at: str
    updated_at: str


class AppArtifactListResponse(BaseModel):
    """应用列表响应。"""

    items: list[AppArtifactListItem]
    total: int
    page: int
    page_size: int


class DashboardItemCreate(BaseModel):
    """仪表盘卡片项。"""

    widget_id: str
    position_x: int = 0
    position_y: int = 0
    width: int = 1
    height: int = 1
    config: dict[str, Any] | None = None


class DashboardCreate(BaseModel):
    """创建仪表盘的请求体。"""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    items: list[DashboardItemCreate] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
