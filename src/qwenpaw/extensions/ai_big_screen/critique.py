# -*- coding: utf-8 -*-
"""Spec-level visual critique loop (M2): generate → review → revise.

After the LLM path assembles a screen, a critic pass reviews its
*structure* (component types, layout, titles, palette — never data
rows) and may apply one bounded round of visual-only revisions.

Safety properties:

- the critic's operations are hard-limited to a visual whitelist —
  query params, fields and component addition are filtered out, so
  the loop can never change data semantics;
- every failure (no model, timeout, bad JSON after repair, applier
  error) silently skips the critique — generation never blocks;
- ``AI_BIG_SCREEN_CRITIQUE=off`` disables the loop entirely.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any

from qwenpaw.extensions.ai_big_screen.llm import (
    ModelCallable,
    create_pipeline_model,
    structured_call,
)
from qwenpaw.extensions.ai_big_screen.orchestration import (
    rebuild_data_bindings,
)
from qwenpaw.extensions.ai_big_screen.patch import _apply_operations
from qwenpaw.extensions.ai_big_screen.schemas import parse_critique_plan

_LOGGER = logging.getLogger(__name__)

CRITIQUE_ENV_SWITCH = "AI_BIG_SCREEN_CRITIQUE"

#: visual-only subset of the patch op whitelist; the critic may never
#: touch query params / fields / component addition (data semantics)
CRITIQUE_ALLOWED_OPS = frozenset(
    {
        "setComponentTitle",
        "setComponentType",
        "setComponentLayout",
        "setComponentPalette",
        "setComponentComposition",
        "setThemePalette",
    },
)

_MAX_OPERATIONS = 5
_MAX_ISSUES = 5

_CRITIC_SYSTEM_PROMPT = (
    "你是数据大屏的视觉评审专家。你会收到一份大屏的结构概要"
    "（组件类型/标题/布局/配色，不含数据），请从布局平衡、"
    "类型多样性、标题清晰度、主题一致性四个维度评审，并给出"
    "有限的视觉修订建议。\n"
    '只输出一个 JSON 对象：{"score": 0-100 整数, '
    '"issues": ["问题描述"], "operations": [...]}。\n'
    "operations 仅允许这些 op："
    "setComponentTitle / setComponentType / setComponentLayout / "
    "setComponentPalette / setComponentComposition（带 componentId）"
    "和 setThemePalette。"
    "绝对不允许修改数据查询、字段或新增组件。\n"
    "概要里每个组件带 rowCount(实际数据行数)与 sourceStatus，"
    "请据此重排:数据稀疏的组件改更紧凑形态(如 1 行表格→翻牌/KPI)"
    "并把 composition 调成 supporting/secondary;数据丰富的提升为 "
    "primary 主体。只动视觉,绝不改查询。\n"
    "composition 取值仅 primary/secondary/supporting。"
    "屏幕已经合格时返回空 operations。最多 5 个 operations。"
)


def critique_enabled() -> bool:
    """The loop is on by default; ``off``/``0``/``false`` disables."""
    return os.environ.get(CRITIQUE_ENV_SWITCH, "").strip().lower() not in {
        "off",
        "0",
        "false",
    }


def _row_count(data: Any) -> int:
    """Data volume signal for the critic — counts, never the rows."""
    if not isinstance(data, dict):
        return 0
    counts = [
        len(data.get(key) or [])
        for key in ("rows", "series", "nodes", "categories")
        if isinstance(data.get(key), list)
    ]
    return max(counts) if counts else 0


def summarize_screen_spec(screen: dict[str, Any]) -> dict[str, Any]:
    """Structure-only summary for the critic — no data rows leak."""
    components = []
    for component in screen.get("components") or []:
        if not isinstance(component, dict):
            continue
        data = component.get("data")
        components.append(
            {
                "id": str(component.get("id") or ""),
                "type": str(component.get("type") or ""),
                "title": str(component.get("title") or "")[:80],
                "capabilityId": str(
                    component.get("capabilityId")
                    or component.get("pluginId")
                    or "",
                ),
                "layoutPosition": component.get("layoutPosition"),
                "palette": (component.get("visualConfig") or {}).get(
                    "palette",
                ),
                "sourceStatus": (
                    str(data.get("sourceStatus") or "")
                    if isinstance(data, dict)
                    else ""
                ),
                "rowCount": _row_count(data),
                "composition": str(
                    (component.get("visualSpec") or {}).get("composition")
                    or "",
                ),
                "composed": bool(component.get("composition")),
            },
        )
    theme = screen.get("theme")
    return {
        "name": str(screen.get("name") or "")[:80],
        "themePalette": (
            theme.get("palette") if isinstance(theme, dict) else None
        ),
        "components": components,
    }


def _build_messages(screen: dict[str, Any]) -> list[dict[str, str]]:
    spec = json.dumps(
        summarize_screen_spec(screen),
        ensure_ascii=False,
        sort_keys=True,
    )
    return [
        {"role": "system", "content": _CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": f"大屏结构概要：\n{spec}"},
    ]


async def run_critique(
    screen: dict[str, Any],
    *,
    model: ModelCallable | None = None,
    max_repair: int = 0,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Critique ``screen`` in place; returns the critique info or None.

    Mutates the screen only through the visual op whitelist and
    records ``aiConversationContext.critique``. Any failure returns
    None and leaves the screen exactly as it was.

    Single attempt with a 15s wall: critique is a bonus pass on the
    user's critical path, so its latency must stay tightly bounded.
    A fast model finishes well within 15s; a slow/heavy model can't
    finish anyway, so failing fast is strictly better than burning
    60s on a call that will time out regardless (measured: on the
    slow model critique added a flat ~60s and produced nothing).
    """
    if not critique_enabled():
        return None
    try:
        active_model = (
            model if model is not None else (create_pipeline_model())
        )
        result = await structured_call(
            active_model,
            _build_messages(screen),
            parser=parse_critique_plan,
            max_repair=max_repair,
            timeout=timeout,
        )
    except Exception:  # critique must never block generation
        _LOGGER.warning("big-screen critique skipped", exc_info=True)
        return None

    plan = result.value
    allowed = [
        operation
        for operation in plan.operations
        if operation.op in CRITIQUE_ALLOWED_OPS
    ][:_MAX_OPERATIONS]
    applied: list[str] = []
    if allowed:
        # ``_apply_operations`` mutates ``screen["components"]``/``["theme"]``
        # in place. If ``rebuild_data_bindings`` (or the apply itself) then
        # throws partway through, the mutation has already landed — without
        # a snapshot, the except below would report applied=[] while the
        # screen was in fact changed, breaking this function's documented
        # "leaves the screen exactly as it was" contract.
        components_snapshot = copy.deepcopy(screen.get("components"))
        theme_snapshot = copy.deepcopy(screen.get("theme"))
        bindings_snapshot = copy.deepcopy(screen.get("dataBindings"))
        try:
            _refetch, applied, _rejected = _apply_operations(
                screen=screen,
                operations=allowed,
                selected_component_ids=[],
                instruction="",
            )
            if applied:
                screen["dataBindings"] = rebuild_data_bindings(
                    components=[
                        component
                        for component in (screen.get("components") or [])
                        if isinstance(component, dict)
                    ],
                    previous_bindings=screen.get("dataBindings"),
                )
        except Exception:
            _LOGGER.warning(
                "big-screen critique revision failed",
                exc_info=True,
            )
            screen["components"] = components_snapshot
            screen["theme"] = theme_snapshot
            screen["dataBindings"] = bindings_snapshot
            applied = []

    info = {
        "score": int(plan.score),
        "issuesCount": len(plan.issues),
        "issues": [str(issue)[:200] for issue in plan.issues[:_MAX_ISSUES]],
        "applied": applied,
    }
    raw_context = screen.get("aiConversationContext")
    context = dict(raw_context) if isinstance(raw_context, dict) else {}
    context["critique"] = info
    screen["aiConversationContext"] = context
    return info
