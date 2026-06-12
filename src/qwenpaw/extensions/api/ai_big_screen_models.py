# -*- coding: utf-8 -*-
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
    selectedComponentIds: list[str] = Field(default_factory=list)
    selectedRegion: dict[str, Any] = Field(default_factory=dict)
    selectionContext: dict[str, Any] = Field(default_factory=dict)
    instruction: str
    requestedBy: str = "portal"


class AiBigScreenPublishRequest(BaseModel):
    requestedBy: str = "portal"
    visibility: str = "internal"


class AiBigScreenRenameRequest(BaseModel):
    name: str
    requestedBy: str = "portal"


class AiBigScreenDuplicateRequest(BaseModel):
    name: str = ""
    requestedBy: str = "portal"


class AiBigScreenResponse(BaseModel):
    screen: dict[str, Any]


class AiBigScreenTaskResponse(BaseModel):
    task: dict[str, Any]


class AiBigScreenListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class AiBigScreenPluginsResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class AiBigScreenPatchResponse(BaseModel):
    screen: dict[str, Any]
    version: dict[str, Any]
    summary: str


class AiBigScreenMetricsResponse(BaseModel):
    """Aggregated quality signals over the recent generation window."""

    total: int = 0
    successRate: float = 0.0
    degradedRate: float = 0.0
    avgDurationMs: float = 0.0
    capabilityFailureRates: dict[str, float] = Field(default_factory=dict)
    kinds: dict[str, int] = Field(default_factory=dict)


class AiBigScreenPublishResponse(BaseModel):
    screen: dict[str, Any]
    publishTargets: list[dict[str, Any]] = Field(default_factory=list)


class AiBigScreenDeleteResponse(BaseModel):
    screenId: str
    deleted: bool = True
