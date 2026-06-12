# -*- coding: utf-8 -*-
"""统一轻应用货架（应用中心）的数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LightAppLaunch(BaseModel):
    """轻应用的启动描述符。

    type 为 chat-dispatch 时使用 employeeId + prompt（任务应用，
    派发到数字员工对话执行）；为 open-url 时使用 url（页面应用，
    新标签页打开）。
    """

    type: str  # "chat-dispatch" | "open-url"
    employeeId: str = ""
    prompt: str = ""
    url: str = ""


class LightAppRecord(BaseModel):
    """应用中心货架上的一条轻应用记录。"""

    kind: str  # "page" | "task"
    id: str
    appId: str = ""
    title: str
    description: str = ""
    scenarioType: str = ""
    artifactType: str = ""  # page 专用: app|widget|dashboard
    tags: list[str] = Field(default_factory=list)
    listedAt: str = ""
    updatedAt: str = ""
    launch: LightAppLaunch


class LightAppListResponse(BaseModel):
    """应用中心货架列表响应。"""

    items: list[LightAppRecord]
