# -*- coding: utf-8 -*-
"""Draft pipeline: L1 intent -> L2 fetch-once data -> L3 assembly.

Drives real stage progression (the legacy task only ever reported
``planning``/``completed`` while the UI pretended five stages):

    意图解析 -> 取数 -> 视觉编排 -> 资产固化

A failed capability never blocks the screen — the component renders
with an honest ``failed`` badge instead.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from qwenpaw.extensions.ai_big_screen import telemetry
from qwenpaw.extensions.ai_big_screen.capabilities import (
    CapabilityCache,
    execute_capability,
)
from qwenpaw.extensions.ai_big_screen.critique import run_critique
from qwenpaw.extensions.ai_big_screen.rebalance import (
    rebalance_screen_by_data,
)
from qwenpaw.extensions.ai_big_screen.intent import (
    build_screen_plan,
    prompt_is_simple_data_query,
    reconcile_gap_title,
    should_use_semantic_fast_path,
)
from qwenpaw.extensions.ai_big_screen.llm import ModelCallable
from qwenpaw.extensions.ai_big_screen.orchestration import assemble_screen
from qwenpaw.extensions.ai_big_screen.schemas import CapabilityResult

DRAFT_STAGES = ("意图解析", "取数", "视觉编排", "资产固化")

StageCallback = Callable[[str, str], None]


def _notify(
    on_stage: StageCallback | None,
    stage: str,
    message: str,
) -> None:
    if on_stage is None:
        return
    try:
        on_stage(stage, message)
    except Exception:  # stage reporting must never break the pipeline
        pass


async def run_draft_pipeline(
    *,
    prompt: str,
    title: str = "",
    requested_by: str = "portal",
    model: ModelCallable | None = None,
    on_stage: StageCallback | None = None,
    llm_timeout: float = 300.0,
    max_repair: int = 2,
) -> dict[str, Any]:
    """Generate a full screen draft (legacy ``AiBigScreenApp`` dict)."""
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        raise ValueError("prompt 不能为空")

    started = time.monotonic()
    stage_ms: dict[str, int] = {}

    def _lap(stage: str, since: float) -> float:
        now = time.monotonic()
        stage_ms[stage] = int((now - since) * 1000)
        return now

    # L1 — intent
    _notify(on_stage, DRAFT_STAGES[0], "正在理解需求并规划数据能力")
    lap = started
    plan = await build_screen_plan(
        normalized_prompt,
        title,
        model=model,
        max_repair=max_repair,
        timeout=llm_timeout,
    )
    lap = _lap(DRAFT_STAGES[0], lap)

    # L2 — fetch-once data hydration
    _notify(
        on_stage,
        DRAFT_STAGES[1],
        f"正在通过 {len(plan.components)} 个组件实时取数",
    )
    cache = CapabilityCache()

    async def _fetch(component_id: str, capability_id: str, params: Any):
        result = await execute_capability(
            params,
            capability_id=capability_id,
            cache=cache,
        )
        return component_id, result

    fetched = await asyncio.gather(
        *(
            _fetch(
                component.id,
                component.capability_id,
                component.query_params,
            )
            for component in plan.components
        ),
    )
    results: dict[str, CapabilityResult] = dict(fetched)
    lap = _lap(DRAFT_STAGES[1], lap)

    # L3 — visual orchestration + asset assembly
    _notify(on_stage, DRAFT_STAGES[2], "正在编排大屏视觉与组件")
    if should_use_semantic_fast_path(normalized_prompt):
        intent_mode = (
            "simple-query"
            if prompt_is_simple_data_query(normalized_prompt)
            else "semantic-query"
        )
        intent_source = "semantic-intent"
    else:
        intent_mode = "ai-plan"
        intent_source = "normalized-components"
    screen = assemble_screen(
        plan=plan,
        results=results,
        prompt=normalized_prompt,
        screen_id=f"screen-{uuid.uuid4().hex[:10]}",
        requested_by=requested_by,
        intent_mode=intent_mode,
        intent_source=intent_source,
    )

    # M3-A: deterministic data-aware rebalance — resize each panel's
    # importance from its REAL data volume (sparse → small, dense →
    # primary anchor) before the optional LLM polish. All paths, no LLM.
    rebalance_summary = rebalance_screen_by_data(screen)
    context = screen.get("aiConversationContext")
    if isinstance(context, dict):
        context["dataRebalance"] = rebalance_summary

    # M2 quality loop: one spec-level critique + bounded visual
    # revision. LLM path only (the fast path is deterministic by
    # design), and skipped for degraded plans — the model is already
    # failing, a second call would just burn the timeout again.
    # run_critique swallows every failure itself.
    critique_info = None
    if intent_mode == "ai-plan" and not plan.degraded:
        _notify(on_stage, DRAFT_STAGES[2], "正在进行视觉评审与修订")
        critique_info = await run_critique(screen, model=model)
    _lap(DRAFT_STAGES[2], lap)

    _notify(on_stage, DRAFT_STAGES[3], "正在固化大屏资产")
    telemetry.record_generation(
        {
            "kind": "draft",
            "success": True,
            "degraded": bool(plan.degraded),
            "lastError": plan.last_error[:300],
            "durationMs": int((time.monotonic() - started) * 1000),
            "screenId": str(screen.get("id") or ""),
            "promptChars": len(normalized_prompt),
            "intentMode": intent_mode,
            "rebalancedCount": len(rebalance_summary.get("adjusted") or []),
            "stages": stage_ms,
            "capabilityStatuses": {
                component.capability_id: result.source_status
                for component in plan.components
                for result in [results.get(component.id)]
                if result is not None
            },
            "componentTypes": [
                component.type for component in plan.components
            ],
            **(
                {"critique": critique_info}
                if critique_info is not None
                else {}
            ),
        },
    )
    return screen


async def refresh_screen_data(screen: dict[str, Any]) -> dict[str, Any]:
    """Re-run L2 only for a saved screen — the live-data heartbeat.

    Layout, visualSpec and versions are untouched (data is not config,
    so no version is appended); each component's ``data`` is replaced
    by a fresh honest fetch, failures becoming ``failed`` badges
    without blocking the rest. Fetch-once dedupes identical
    (capability, params) pairs within one refresh.
    """
    components = [
        component
        for component in (screen.get("components") or [])
        if isinstance(component, dict)
    ]
    if not components:
        return screen
    cache = CapabilityCache()

    async def _fetch(component: dict[str, Any]):
        capability_id = str(
            component.get("capabilityId") or component.get("pluginId") or "",
        )
        result = await execute_capability(
            component.get("queryParams") or {},
            capability_id=capability_id,
            cache=cache,
            fresh=True,  # refresh semantics: bypass the TTL read
        )
        return component, result

    fetched = await asyncio.gather(
        *(_fetch(component) for component in components),
    )
    for component, result in fetched:
        component["data"] = result.to_legacy_data()
        reconcile_gap_title(component)
    return screen
