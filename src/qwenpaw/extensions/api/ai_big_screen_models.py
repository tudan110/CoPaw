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
    # actual on-screen geometry at request time, keyed by component id —
    # see apply_patch()'s rendered_layout docstring
    renderedLayout: dict[str, Any] = Field(default_factory=dict)
    instruction: str
    requestedBy: str = "portal"
    # preview mode: compute the patch on a copy and return the diff
    # without persisting or appending a version
    preview: bool = False


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
    version: dict[str, Any] | None = None
    summary: str
    preview: bool = False
    diff: list[dict[str, Any]] = Field(default_factory=list)


class AiBigScreenMetricsResponse(BaseModel):
    """Aggregated quality signals over the recent generation window."""

    total: int = 0
    successRate: float = 0.0
    degradedRate: float = 0.0
    avgDurationMs: float = 0.0
    capabilityFailureRates: dict[str, float] = Field(default_factory=dict)
    kinds: dict[str, int] = Field(default_factory=dict)


class AiBigScreenCapabilityConfigItem(BaseModel):
    """One capability's functional domain + backing-connection health."""

    id: str
    name: str = ""
    category: str = ""
    connection: str = ""
    configured: bool = True
    settingsTab: str = ""
    reason: str = ""


class AiBigScreenCapabilityConfigResponse(BaseModel):
    items: list[AiBigScreenCapabilityConfigItem] = Field(
        default_factory=list,
    )


class AiBigScreenPublishResponse(BaseModel):
    screen: dict[str, Any]
    publishTargets: list[dict[str, Any]] = Field(default_factory=list)


class AiBigScreenDeleteResponse(BaseModel):
    screenId: str
    deleted: bool = True
