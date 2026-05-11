from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NlCustomizationPreviewRequest(BaseModel):
    prompt: str
    title: str = ""


class NlCustomizationPreviewResponse(BaseModel):
    previewId: str
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


class NlCustomizationVersionListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
