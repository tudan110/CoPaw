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
import uuid
from typing import Any, Callable

from qwenpaw.extensions.ai_big_screen.capabilities import (
    CapabilityCache,
    execute_capability,
)
from qwenpaw.extensions.ai_big_screen.intent import (
    build_screen_plan,
    prompt_is_simple_data_query,
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
    llm_timeout: float = 120.0,
    max_repair: int = 2,
) -> dict[str, Any]:
    """Generate a full screen draft (legacy ``AiBigScreenApp`` dict)."""
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        raise ValueError("prompt 不能为空")

    # L1 — intent
    _notify(on_stage, DRAFT_STAGES[0], "正在理解需求并规划数据能力")
    plan = await build_screen_plan(
        normalized_prompt,
        title,
        model=model,
        max_repair=max_repair,
        timeout=llm_timeout,
    )

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

    _notify(on_stage, DRAFT_STAGES[3], "正在固化大屏资产")
    return screen
