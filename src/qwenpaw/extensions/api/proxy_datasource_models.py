# -*- coding: utf-8 -*-
"""External datasource config models for the HTTP proxy."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BigScreenField(BaseModel):
    """One column the big-screen renders from a response row."""

    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=64)


class BigScreenParam(BaseModel):
    """A query param the big-screen LLM may fill for this datasource."""

    name: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=400)
    required: bool = False
    default: Any = None


class BigScreenBinding(BaseModel):
    """Maps a registered datasource into a big-screen data capability.

    The operator declares how to read the JSON response (``rows_path``
    to the row array, ``fields`` for columns) and which params the LLM
    may fill. The LLM can only *select* this capability and fill the
    declared params — it can never change the URL/host (that stays the
    operator-registered template), so no-arbitrary-call / SSRF holds.
    """

    enabled: bool = Field(default=False, description="是否暴露为大屏能力")
    domain: str = Field(default="custom", max_length=40)
    rows_path: str = Field(
        default="",
        max_length=200,
        description="响应中行数组的点路径(如 data.items);空=响应即数组",
    )
    value_path: str = Field(
        default="",
        max_length=200,
        description="标量 KPI 值的点路径(可选)",
    )
    total_path: str = Field(
        default="",
        max_length=200,
        description="总数的点路径(可选,默认取行数)",
    )
    unit: str = Field(default="", max_length=16)
    fields: list[BigScreenField] = Field(default_factory=list)
    params: list[BigScreenParam] = Field(default_factory=list)
    example_prompts: list[str] = Field(default_factory=list)


class DatasourceConfig(BaseModel):
    """A single external API datasource definition.

    Stored on disk as JSON; ``headers`` contain auth tokens
    that the proxy injects at request time — never exposed to the client.
    """

    id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="唯一标识,用于 URL 路径",
    )
    name: str = Field(..., min_length=1, max_length=200, description="可读名称")
    description: str = Field(default="", max_length=2000, description="简要描述")
    url_template: str = Field(
        ...,
        min_length=1,
        description="请求 URL 模板,支持 {param} 占位符",
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
    big_screen: BigScreenBinding | None = Field(
        default=None,
        description="可选:把该数据源暴露为 AI 大屏数据能力的绑定声明",
    )


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
