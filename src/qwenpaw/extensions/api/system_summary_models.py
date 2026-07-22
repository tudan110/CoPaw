# -*- coding: utf-8 -*-
"""Minimal public response contract for the AI system-summary endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AiSystemSummaryResponse(BaseModel):
    """The concise AI narrative exposed to external callers.

    Collection facts, source state and model fallback details remain internal
    implementation data.  The generated narrative itself contains the
    operational overview, key problems and recommended priority.
    """

    summary: str
    summaryHtml: str
    healthStatus: Literal["normal", "abnormal"]
