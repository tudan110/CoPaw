# -*- coding: utf-8 -*-
"""Typed domain models for the AI big-screen pipeline.

These mirror the semantics of the frontend domain model in
``portal/src/components/big-screen/types.ts``. LLM payloads arrive in
camelCase, so every model accepts camelCase aliases and dumps back to
camelCase via ``model_dump(by_alias=True)``.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

SourceStatus = Literal["live", "empty", "failed", "gap"]

PatchOp = Literal[
    "addComponent",
    "setThemePalette",
    "setComponentPalette",
    "setComponentType",
    "setComponentLayout",
    "setComponentTitle",
    "setComponentQueryParams",
    "setComponentFields",
]

_MAX_ID_LENGTH = 64
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class _CamelModel(BaseModel):
    """Base model: camelCase wire names, snake_case python names."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


class CapabilityField(_CamelModel):
    key: str
    label: str = ""


class CapabilityResult(_CamelModel):
    """Honest result of one data-capability execution (L2 output)."""

    capability_id: str
    source_status: SourceStatus
    rows: list[dict[str, Any]] | None = None
    series: list[Any] | None = None
    nodes: list[dict[str, Any]] | None = None
    categories: list[Any] | None = None
    metrics: dict[str, Any] | None = None
    columns: list[dict[str, Any]] | None = None
    fields: list[CapabilityField] | None = None
    total: int | None = None
    message: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_legacy_data(self) -> dict[str, Any]:
        """Serialize to the legacy ``component.data`` dict shape."""
        data: dict[str, Any] = dict(self.extra)
        data["sourceStatus"] = self.source_status
        if self.message:
            data["message"] = self.message
        for key, value in (
            ("rows", self.rows),
            ("series", self.series),
            ("nodes", self.nodes),
            ("categories", self.categories),
            ("metrics", self.metrics),
            ("columns", self.columns),
            ("total", self.total),
        ):
            if value is not None:
                data[key] = value
        if self.fields is not None:
            data["fields"] = [
                field.model_dump(by_alias=True) for field in self.fields
            ]
        return data


class PlanComponent(_CamelModel):
    """One component requested by the L1 planner.

    ``id`` may be empty on raw LLM output — the L1 normalizer assigns
    canonical component ids. The legacy prompt vocabulary uses
    ``visualType``; it is accepted as an alias for ``type``.
    """

    id: str = ""
    type: str = "table"
    title: str = ""
    description: str = ""
    capability_id: str = ""
    query_params: dict[str, Any] = Field(default_factory=dict)
    visual_config: dict[str, Any] = Field(default_factory=dict)
    visual_spec: dict[str, Any] = Field(default_factory=dict)
    layout_position: dict[str, Any] | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _clip_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value[:_MAX_ID_LENGTH]
        return value

    @model_validator(mode="before")
    @classmethod
    def _accept_visual_type_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            visual_type = str(data.get("visualType") or "").strip()
            if visual_type and not str(data.get("type") or "").strip():
                data = dict(data)
                data["type"] = visual_type
        return data


class ScreenPlan(_CamelModel):
    """L1 output: what the screen should contain (no data yet)."""

    name: str = ""
    description: str = ""
    summary: str = ""
    theme: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    components: list[PlanComponent] = Field(default_factory=list)
    degraded: bool = False

    @field_validator("components", mode="before")
    @classmethod
    def _drop_invalid_components(cls, value: Any) -> Any:
        """Drop non-dict component entries; keep id-less ones.

        Raw LLM plans legitimately omit ``id`` (the L1 normalizer
        assigns canonical ids), so only structurally invalid entries
        are removed here.
        """
        if not isinstance(value, list):
            return value
        return [
            item for item in value if isinstance(item, (dict, PlanComponent))
        ]


class DataIntent(_CamelModel):
    """One capability fetch the pipeline intends to run."""

    id: str
    capability_id: str
    name: str = ""
    domain: str = ""
    source: str = ""
    confidence: float = 0.0
    intent_kind: str = ""
    query_params: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    reasoning_trace: list[str] = Field(default_factory=list)


class DataIntentPlan(_CamelModel):
    version: int = 1
    mode: str = "ai-plan"
    source_prompt: str = ""
    intents: list[DataIntent] = Field(default_factory=list)


class PatchOperation(_CamelModel):
    """A single whitelisted patch operation (no arbitrary mutation)."""

    op: PatchOp
    component_id: str = ""
    value: Any = None


class PatchPlan(_CamelModel):
    """L1 output in patch mode."""

    operations: list[PatchOperation] = Field(default_factory=list)
    summary: str = ""
    degraded: bool = False


def extract_json_object(text: str) -> str:
    """Extract a JSON object string from raw LLM text.

    Prefers a fenced ```json block; falls back to the outermost
    ``{...}`` slice. Raises ``ValueError`` when no candidate is found.
    """
    raw = str(text or "").strip()
    fenced = _FENCED_JSON_RE.search(raw)
    if fenced:
        return fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        return raw[start : end + 1]
    raise ValueError("LLM 响应中未找到 JSON 对象")


def parse_screen_plan(text: str) -> ScreenPlan:
    """Parse + schema-validate an LLM response into a ``ScreenPlan``.

    Raises ``ValueError`` for non-JSON text and
    ``pydantic.ValidationError`` for schema violations, so callers can
    feed precise errors back to the model for bounded repair.
    """
    candidate = extract_json_object(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 响应 JSON 解析失败: {exc}") from exc
    return ScreenPlan.model_validate(payload)


def parse_patch_plan(text: str) -> PatchPlan:
    """Parse + schema-validate an LLM response into a ``PatchPlan``."""
    candidate = extract_json_object(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 响应 JSON 解析失败: {exc}") from exc
    return PatchPlan.model_validate(payload)
