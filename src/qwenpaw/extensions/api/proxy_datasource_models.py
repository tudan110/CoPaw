# -*- coding: utf-8 -*-
"""External datasource config models for the HTTP proxy."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DatasourceConfig(BaseModel):
    """A single external API datasource definition.

    Stored on disk as JSON; ``headers`` contain auth tokens
    that the proxy injects at request time — never exposed to the client.
    """

    id: str = Field(..., min_length=1, max_length=64, description="唯一标识,用于 URL 路径")
    name: str = Field(..., min_length=1, max_length=200, description="可读名称")
    description: str = Field(default="", max_length=2000, description="简要描述")
    url_template: str = Field(
        ..., min_length=1, description="请求 URL 模板,支持 {param} 占位符"
    )
    method: str = Field(
        default="GET",
        pattern=r"^(GET|POST|PUT|DELETE)$",
        description="HTTP 方法",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="请求头(含鉴权信息,仅服务端可见)",
    )
    default_params: dict[str, Any] = Field(
        default_factory=dict,
        description="默认查询/路径参数",
    )
    body_template: dict[str, Any] | str | None = Field(
        default=None,
        description="POST/PUT 请求体模板(JSON 对象或字符串模板)",
    )
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="超时(秒)")
    enabled: bool = Field(default=True, description="是否启用")


class DatasourceSummary(BaseModel):
    """Datasource info safe to return to the client (no headers)."""

    id: str
    name: str
    description: str
    url_template: str
    method: str
    default_params: dict[str, Any]
    timeout: float
    enabled: bool