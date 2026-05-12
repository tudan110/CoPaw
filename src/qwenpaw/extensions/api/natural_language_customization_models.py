from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NlCustomizationPreviewRequest(BaseModel):
    prompt: str
    title: str = ""
    appId: str = ""


class NlCustomizationPreviewResponse(BaseModel):
    previewId: str
    appId: str = ""
    title: str
    prompt: str
    intent: dict[str, Any]
    matchedTemplate: dict[str, Any]
    bundle: dict[str, Any]
    summaryMarkdown: str
    warnings: list[str] = Field(default_factory=list)
    missingInputs: list[str] = Field(default_factory=list)


class NlCustomizationPublishRequest(BaseModel):
    preview: NlCustomizationPreviewResponse
    requestedBy: str = "portal"
    title: str = ""


class NlCustomizationPublishResponse(BaseModel):
    versionId: str
    publishedAt: str
    bundlePath: str
    record: dict[str, Any]


class NlCustomizationApplyRequest(BaseModel):
    versionId: str
    requestedBy: str = "portal"


class NlCustomizationApplyResponse(BaseModel):
    versionId: str
    appliedAt: str
    activePath: str
    record: dict[str, Any]


class NlCustomizationListingRequest(BaseModel):
    versionId: str
    listed: bool
    requestedBy: str = "portal"


class NlCustomizationListingResponse(BaseModel):
    versionId: str
    listed: bool
    listedAt: str = ""
    record: dict[str, Any]


class NlCustomizationVersionDetailResponse(BaseModel):
    versionId: str
    record: dict[str, Any]
    preview: dict[str, Any]
    bundlePath: str


class NlCustomizationDeleteResponse(BaseModel):
    versionId: str
    deleted: bool = True
    bundlePath: str = ""
    record: dict[str, Any]


class NlCustomizationActiveResponse(BaseModel):
    activeVersionId: str = ""
    appliedAt: str = ""
    activePath: str = ""
    record: dict[str, Any] | None = None
    preview: dict[str, Any] | None = None
    effectiveBundle: dict[str, Any] = Field(default_factory=dict)


class NlCustomizationAppListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class NlCustomizationVersionListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
