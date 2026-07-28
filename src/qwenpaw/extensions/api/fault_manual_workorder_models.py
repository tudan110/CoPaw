from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AlarmInfoPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    alarm_id: str = Field(default="", validation_alias=AliasChoices("alarm_id", "alarmId", "id"))
    title: str = ""
    visible_content: str = Field(
        default="",
        validation_alias=AliasChoices("visible_content", "visibleContent"),
    )
    device_name: str = Field(
        default="",
        validation_alias=AliasChoices("device_name", "deviceName", "devName"),
    )
    manage_ip: str = Field(
        default="",
        validation_alias=AliasChoices("manage_ip", "manageIp"),
    )
    asset_id: str = Field(
        default="",
        validation_alias=AliasChoices("asset_id", "assetId", "assetNo"),
    )
    level: str = ""
    status: str = ""
    event_time: str = Field(
        default="",
        validation_alias=AliasChoices("event_time", "eventTime"),
    )


class AnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str = ""
    root_cause: str | dict[str, Any] = Field(
        default="",
        validation_alias=AliasChoices("root_cause", "rootCause"),
    )
    suggestions: list[str] = Field(default_factory=list)
    selected_metrics: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("selected_metrics", "selectedMetrics"),
    )


class ManualWorkorderDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    chat_id: str = Field(
        ...,
        min_length=1,
        serialization_alias="chatId",
        validation_alias=AliasChoices("chat_id", "chatId", "sessionId"),
    )
    res_id: str = Field(
        default="",
        validation_alias=AliasChoices("res_id", "resId"),
    )
    metric_type: str = Field(
        default="mysql",
        validation_alias=AliasChoices("metric_type", "metricType"),
    )
    alarm: AlarmInfoPayload
    analysis: AnalysisPayload = Field(default_factory=AnalysisPayload)

    @property
    def alarm_id(self) -> str:
        return self.alarm.alarm_id


class AlarmAnalystWorkorderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    proposal_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("proposal_id", "proposalId"),
        serialization_alias="proposalId",
    )
    message_id: str = Field(
        default="",
        validation_alias=AliasChoices("message_id", "messageId"),
        serialization_alias="messageId",
    )
    chat_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("chat_id", "chatId"),
        serialization_alias="chatId",
    )
    alarm_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("alarm_id", "alarmId"),
        serialization_alias="alarmId",
    )


class AlarmAnalystWorkorderCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    proposal_id: str = Field(
        default="",
        validation_alias=AliasChoices("proposal_id", "proposalId"),
        serialization_alias="proposalId",
    )
    workorder_status: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("workorder_status", "workorderStatus"),
        serialization_alias="workorderStatus",
    )
    workorder_id: str = Field(
        default="",
        validation_alias=AliasChoices("workorder_id", "workorderId"),
        serialization_alias="workorderId",
    )
    process_id: str = Field(
        default="",
        validation_alias=AliasChoices("process_id", "processId"),
        serialization_alias="processId",
    )
    message: str = ""


class WorkorderHandlePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    workorder_no: str = Field(
        default="",
        validation_alias=AliasChoices("workorder_no", "workorderNo"),
    )
    status: str = "resolved"
    handler: str = ""
    completed_at: str = Field(
        default="",
        validation_alias=AliasChoices("completed_at", "completedAt"),
    )


class ProcessingResultPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str = ""
    details: str = ""


class ManualWorkorderCloseNotificationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    alarm_id: str = Field(
        default="",
        validation_alias=AliasChoices("alarm_id", "alarmId"),
    )
    chat_id: str = Field(
        default="",
        serialization_alias="chatId",
        validation_alias=AliasChoices("chat_id", "chatId", "sessionId"),
    )
    res_id: str = Field(
        default="",
        validation_alias=AliasChoices("res_id", "resId"),
    )
    metric_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("metric_type", "metricType"),
    )
    workorder: WorkorderHandlePayload = Field(default_factory=WorkorderHandlePayload)
    processing: ProcessingResultPayload = Field(default_factory=ProcessingResultPayload)
