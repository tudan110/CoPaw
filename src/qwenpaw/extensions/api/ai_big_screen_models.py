from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AiBigScreenDraftRequest(BaseModel):
    prompt: str
    title: str = ""
    requestedBy: str = "portal"


class AiBigScreenSaveRequest(BaseModel):
    screen: dict[str, Any]
    requestedBy: str = "portal"


class AiBigScreenPatchRequest(BaseModel):
    baseVersionId: str = ""
    selectedComponentId: str = ""
    instruction: str
    requestedBy: str = "portal"


class AiBigScreenPublishRequest(BaseModel):
    requestedBy: str = "portal"
    visibility: str = "internal"


class AiBigScreenResponse(BaseModel):
    screen: dict[str, Any]


class AiBigScreenListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class AiBigScreenPluginsResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class AiBigScreenPatchResponse(BaseModel):
    screen: dict[str, Any]
    version: dict[str, Any]
    summary: str


class AiBigScreenPublishResponse(BaseModel):
    screen: dict[str, Any]
    publishTargets: list[dict[str, Any]] = Field(default_factory=list)
