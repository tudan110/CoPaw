# -*- coding: utf-8 -*-
"""Pydantic models for INOE alarm-clear notifications.

The INOE platform pushes a notification when an alarm is cleared on
their side. The exact field names are owned by INOE, so every field
accepts both snake_case and camelCase aliases (plus the raw INOE names
where known, e.g. ``alarmuniqueid``). Unknown extra fields are kept via
``extra="allow"`` so the raw payload can be persisted for auditing.
"""
from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AlarmClearNotificationRequest(BaseModel):
    """Body of ``POST /api/portal/real-alarms/clear-notifications``."""

    model_config = ConfigDict(extra="allow")

    alarm_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "alarm_id",
            "alarmId",
            "alarmuniqueid",
            "id",
        ),
    )
    res_id: str = Field(
        default="",
        validation_alias=AliasChoices("res_id", "resId", "devId"),
    )
    clear_time: str = Field(
        default="",
        validation_alias=AliasChoices(
            "clear_time",
            "clearTime",
            "cleartime",
            "cancel_time",
            "canceltime",
        ),
    )
    clear_type: str = Field(
        default="",
        validation_alias=AliasChoices("clear_type", "clearType"),
    )
    operator: str = ""
    reason: str = ""
    metric_type: str = Field(
        default="",
        validation_alias=AliasChoices("metric_type", "metricType"),
    )
