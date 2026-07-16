# -*- coding: utf-8 -*-
"""Read-only external API for the AI system situation summary."""

from __future__ import annotations

from fastapi import APIRouter, Query

from qwenpaw.extensions.api.system_summary_models import AiSystemSummaryResponse
from qwenpaw.extensions.api.system_summary_service import build_system_summary

router = APIRouter(prefix="/ai", tags=["portal", "ai"])


@router.get("/system-summary", response_model=AiSystemSummaryResponse)
async def get_system_summary(
    fresh: bool = Query(default=False),
) -> AiSystemSummaryResponse:
    """Return the concise AI-written overview of current operations."""
    return AiSystemSummaryResponse(
        **await build_system_summary(fresh=fresh),
    )
