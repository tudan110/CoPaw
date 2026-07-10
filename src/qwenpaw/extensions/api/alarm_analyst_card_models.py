from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AlarmAnalystCardProcessBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str = ""
    tool_name: str = Field(
        default="",
        validation_alias=AliasChoices("tool_name", "toolName"),
        serialization_alias="toolName",
    )
    tool_call_id: str = Field(
        default="",
        validation_alias=AliasChoices("tool_call_id", "toolCallId"),
        serialization_alias="toolCallId",
    )
    input_content: str = Field(
        default="",
        validation_alias=AliasChoices("input_content", "inputContent"),
        serialization_alias="inputContent",
    )
    output_content: str = Field(
        default="",
        validation_alias=AliasChoices("output_content", "outputContent"),
        serialization_alias="outputContent",
    )
    content: str = ""


class AlarmAnalystCardSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(
        ...,
        validation_alias=AliasChoices("chat_id", "chatId"),
        serialization_alias="chatId",
    )
    message_id: str = Field(
        ...,
        validation_alias=AliasChoices("message_id", "messageId"),
        serialization_alias="messageId",
    )
    skill_name: Literal["alarm-analyst"] = Field(
        default="alarm-analyst",
        validation_alias=AliasChoices("skill_name", "skillName"),
        serialization_alias="skillName",
    )
    content_hash: str = Field(
        ...,
        validation_alias=AliasChoices("content_hash", "contentHash"),
        serialization_alias="contentHash",
    )


class AlarmAnalystCardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    conclusion: str = ""
    severity: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    status: Literal["identified", "suspected", "unknown"] | None = None


class AlarmAnalystCardRootCauseCandidate(BaseModel):
    """One row of the report's "候选根因" Top-N table.

    ``confidence`` keeps the raw report text (e.g. ``"86%"``) instead of
    the high/medium/low enum used by the summary, so candidates can carry
    the percentage the RCA methodology asks for.
    """

    model_config = ConfigDict(extra="forbid")

    rank: int = 0
    reason: str = ""
    resource_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("resource_name", "resourceName"),
        serialization_alias="resourceName",
    )
    confidence: str = ""
    evidence: str | None = None


class AlarmAnalystCardRootCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("resource_id", "resourceId"),
        serialization_alias="resourceId",
    )
    resource_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("resource_name", "resourceName"),
        serialization_alias="resourceName",
    )
    ci_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ci_id", "ciId"),
        serialization_alias="ciId",
    )
    reason: str = ""
    # Ranked Top-N candidate root causes parsed from the report's
    # "候选根因" table; empty when the model reported a single root cause.
    candidates: list[AlarmAnalystCardRootCauseCandidate] = Field(
        default_factory=list,
    )


class AlarmAnalystCardImpactEntity(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str = ""
    type: str | None = None


class AlarmAnalystCardImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affected_applications: list[AlarmAnalystCardImpactEntity] = Field(
        default_factory=list,
        validation_alias=AliasChoices("affected_applications", "affectedApplications"),
        serialization_alias="affectedApplications",
    )
    affected_resources: list[AlarmAnalystCardImpactEntity] = Field(
        default_factory=list,
        validation_alias=AliasChoices("affected_resources", "affectedResources"),
        serialization_alias="affectedResources",
    )
    blast_radius_text: str | None = Field(
        default=None,
        validation_alias=AliasChoices("blast_radius_text", "blastRadiusText"),
        serialization_alias="blastRadiusText",
    )


class AlarmAnalystCardTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    highlighted_node_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("highlighted_node_ids", "highlightedNodeIds"),
        serialization_alias="highlightedNodeIds",
    )


class AlarmAnalystCardRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    priority: Literal["p0", "p1", "p2"] = "p1"
    description: str = ""
    risk: str | None = None
    # "emergency" = 紧急预案（止血）, "repair" = 根因处置（修复）,
    # "prevention" = 预防措施（中长期）;
    # None when the report's 处置建议 has no staged subsections.
    stage: Literal["emergency", "repair", "prevention"] | None = None
    action_type: Literal["manual", "script", "observe"] | None = Field(
        default=None,
        validation_alias=AliasChoices("action_type", "actionType"),
        serialization_alias="actionType",
    )


class AlarmAnalystCardEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["alarm", "metric", "cmdb", "tool"] = "tool"
    title: str = ""
    summary: str = ""


class AlarmAnalystCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["alarm-analyst-card"] = "alarm-analyst-card"
    version: Literal["v1"] = "v1"
    source: AlarmAnalystCardSource
    summary: AlarmAnalystCardSummary
    root_cause: AlarmAnalystCardRootCause = Field(
        validation_alias=AliasChoices("root_cause", "rootCause"),
        serialization_alias="rootCause",
    )
    impact: AlarmAnalystCardImpact
    topology: AlarmAnalystCardTopology
    recommendations: list[AlarmAnalystCardRecommendation] = Field(default_factory=list)
    evidence: list[AlarmAnalystCardEvidence] = Field(default_factory=list)
    raw_report_markdown: str = Field(
        validation_alias=AliasChoices("raw_report_markdown", "rawReportMarkdown"),
        serialization_alias="rawReportMarkdown",
    )


class AlarmAnalystCardCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("session_id", "sessionId"),
        serialization_alias="sessionId",
    )
    chat_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("chat_id", "chatId"),
        serialization_alias="chatId",
    )
    message_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("message_id", "messageId"),
        serialization_alias="messageId",
    )
    employee_id: str = Field(
        default="fault",
        validation_alias=AliasChoices("employee_id", "employeeId"),
        serialization_alias="employeeId",
    )
    report_markdown: str = Field(
        default="",
        validation_alias=AliasChoices("report_markdown", "reportMarkdown"),
        serialization_alias="reportMarkdown",
    )
    process_blocks: list[AlarmAnalystCardProcessBlock] = Field(
        default_factory=list,
        validation_alias=AliasChoices("process_blocks", "processBlocks"),
        serialization_alias="processBlocks",
    )


class AlarmAnalystCardCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool
    card: AlarmAnalystCard | None = None


class AlarmAnalystCardListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[AlarmAnalystCard] = Field(default_factory=list)
