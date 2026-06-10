# -*- coding: utf-8 -*-
"""Unified patch generator — one path for all incremental edits.

Replaces the legacy triple-duplication (semantic-guard heuristics +
separate LLM patch prompt + 770-line normalize machinery) with a single
structured-output plan over a whitelisted operation set (spec §9):

- selection is enforced mechanically: operations targeting components
  outside the user's selection are dropped, not heuristically guessed;
- visual-only edits never touch data; only query-param/field changes
  and new components re-run L2 (fetch-once cache within one patch);
- every patch appends an immutable version snapshot for rollback.
"""
from __future__ import annotations

import copy
import json
import uuid
from typing import Any, Mapping

from qwenpaw.extensions.ai_big_screen.capabilities import (
    CapabilityCache,
    execute_capability,
)
from qwenpaw.extensions.ai_big_screen.capabilities.fields import (
    CAPABILITY_FIELD_DEFINITIONS,
    normalize_capability_fields,
)
from qwenpaw.extensions.ai_big_screen.intent import (
    ALLOWED_COMPONENT_TYPES,
    ALLOWED_PALETTES,
    extract_lookback_minutes,
    normalize_layout_position,
    normalize_plan_component,
)
from qwenpaw.extensions.ai_big_screen.llm import (
    ModelCallable,
    create_pipeline_model,
    structured_call,
)
from qwenpaw.extensions.ai_big_screen.orchestration import (
    assemble_component,
    build_data_intent_plan,
    build_version,
    build_visual_plan,
    now_iso,
    rebuild_data_bindings,
)
from qwenpaw.extensions.ai_big_screen.sanitizer import sanitize_visual_spec
from qwenpaw.extensions.ai_big_screen.schemas import (
    PatchOperation,
    PatchPlan,
    parse_patch_plan,
)

DEGRADED_PATCH_SUMMARY = "AI 降级：未生成可执行的大屏配置变更，已保持原状。"

_DATA_AFFECTING_OPS = {"setComponentQueryParams", "setComponentFields"}


def _component_index(components: list[Any], component_id: str) -> int:
    for index, item in enumerate(components):
        if isinstance(item, dict) and str(item.get("id") or "") == (
            component_id
        ):
            return index
    return -1


def _normalize_selection(
    selected_component_ids: list[str] | None,
    fallback: str,
) -> list[str]:
    ids: list[str] = []
    for raw in list(selected_component_ids or []) + (
        [fallback] if fallback else []
    ):
        normalized = str(raw or "").strip()
        if normalized and normalized not in ids:
            ids.append(normalized)
    return ids


def _build_patch_messages(
    *,
    screen: Mapping[str, Any],
    instruction: str,
    selected_component_ids: list[str],
) -> list[dict[str, str]]:
    component_catalog = [
        {
            "id": str(item.get("id") or ""),
            "type": str(item.get("type") or ""),
            "title": str(item.get("title") or ""),
            "capabilityId": str(
                item.get("capabilityId") or item.get("pluginId") or "",
            ),
            "queryParams": copy.deepcopy(item.get("queryParams") or {}),
            "visualConfig": copy.deepcopy(item.get("visualConfig") or {}),
            "visualSpec": copy.deepcopy(item.get("visualSpec") or {}),
            "layoutPosition": copy.deepcopy(item.get("layoutPosition") or {}),
            "availableFields": copy.deepcopy(
                CAPABILITY_FIELD_DEFINITIONS.get(
                    str(
                        item.get("capabilityId") or item.get("pluginId") or "",
                    ),
                    [],
                ),
            ),
        }
        for item in screen.get("components", [])
        if isinstance(item, dict)
    ]
    system_prompt = (
        "你是 AI 运维大屏配置设计助手。只输出严格 JSON，"
        "不要输出 Markdown、代码块或解释。"
        "你的任务是根据用户自然语言对当前大屏生成结构化 patch plan，"
        "由后端执行，不允许生成前端源码、SQL 或任意脚本。"
        "JSON 固定字段：summary, operations。"
        "operations 是数组，每项字段为 op、componentId 或 componentIds、value。"
        "op 只能是：addComponent、setThemePalette、setComponentPalette、"
        "setComponentType、setComponentLayout、setComponentTitle、"
        "setComponentQueryParams、setComponentFields。"
        "value 语义：setComponentTitle=新标题字符串；"
        "setComponentType=组件类型字符串；"
        "setComponentLayout={x,y,w,h}(12 列网格数字)；"
        "setThemePalette=palette 字符串；"
        "setComponentPalette={palette, emphasis}；"
        "setComponentQueryParams=要合并的查询参数对象；"
        "setComponentFields={mode: add|replace|remove, fields: [字段key]}，"
        "字段 key 必须来自该组件 availableFields；"
        "addComponent=完整组件描述 "
        "{title, description, capabilityId, visualType, queryParams, "
        "layoutPosition, visualSpec?}。"
        "palette 只能是 professional、industrial、aurora、mono、warm、cool、"
        "executive；用户说太丑、美化、高级、领导看且未指定颜色时优先 executive。"
        "componentId 必须来自给定组件清单；用户说整个大屏时可对多个 "
        "componentIds 生效。"
        "如果用户选择了组件(selectedComponentIds 非空)，"
        "只允许修改选中的组件，不要生成针对其他组件的操作。"
        "如果用户要求查询最后一次有数据/最近有日志/空结果后继续找历史日志，"
        "对系统日志组件使用 setComponentQueryParams 设置 "
        "searchStrategy=latest_non_empty、timeMode=latest_non_empty、"
        "maxLookbackDays=45。"
        "如果用户要求分析系统日志高危/风险情况并动态突出，"
        "新增或修改系统日志组件时优先 visualType=risk-pulse、"
        "queryParams.analysisMode=risk_summary。"
        "visualSpec 只能描述数据绑定、动效、高亮和层次，"
        "不允许输出 HTML、CSS、JS、URL 或代码。"
    )
    output_example = {
        "summary": "视觉风格调整为领导驾驶舱风格",
        "operations": [
            {"op": "setThemePalette", "value": "executive"},
            {
                "op": "setComponentPalette",
                "componentIds": ["component-1"],
                "value": {"palette": "executive", "emphasis": "strong"},
            },
        ],
    }
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": instruction,
                    "selectedComponentIds": selected_component_ids,
                    "screen": {
                        "id": screen.get("id"),
                        "name": screen.get("name"),
                        "theme": screen.get("theme"),
                        "components": component_catalog,
                    },
                    "outputExample": output_example,
                },
                ensure_ascii=False,
            ),
        },
    ]


# ---------------------------------------------------------------------------
# operation application
# ---------------------------------------------------------------------------


def _apply_set_title(component: dict[str, Any], value: Any) -> bool:
    title = str(value or "").strip()[:80]
    if not title or component.get("title") == title:
        return False
    component["title"] = title
    return True


def _apply_set_type(component: dict[str, Any], value: Any) -> bool:
    new_type = str(value or "").strip()
    if new_type not in ALLOWED_COMPONENT_TYPES:
        return False
    if component.get("type") == new_type:
        return False
    component["type"] = new_type
    return True


def _apply_set_layout(component: dict[str, Any], value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    component["layoutPosition"] = normalize_layout_position(value, 0)
    return True


def _apply_set_palette(component: dict[str, Any], value: Any) -> bool:
    payload = value if isinstance(value, dict) else {"palette": value}
    visual_config = dict(component.get("visualConfig") or {})
    changed = False
    palette = str(payload.get("palette") or "").strip()
    if palette in ALLOWED_PALETTES and visual_config.get("palette") != (
        palette
    ):
        visual_config["palette"] = palette
        changed = True
    emphasis = str(payload.get("emphasis") or "").strip()
    if (
        emphasis in {"standard", "strong"}
        and visual_config.get(
            "emphasis",
        )
        != emphasis
    ):
        visual_config["emphasis"] = emphasis
        changed = True
    if changed:
        component["visualConfig"] = visual_config
    return changed


def _apply_set_query_params(component: dict[str, Any], value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    query_params = dict(component.get("queryParams") or {})
    query_params.update(copy.deepcopy(value))
    component["queryParams"] = query_params
    return True


def _apply_set_fields(component: dict[str, Any], value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    capability_id = str(
        component.get("capabilityId") or component.get("pluginId") or "",
    )
    requested = normalize_capability_fields(
        capability_id,
        value.get("fields"),
        fallback=[],
    )
    if not requested:
        return False
    mode = str(value.get("mode") or "replace").strip()
    query_params = dict(component.get("queryParams") or {})
    current = normalize_capability_fields(
        capability_id,
        query_params.get("fields"),
        fallback=[],
    )
    if mode == "add":
        merged = current + [f for f in requested if f not in current]
    elif mode == "remove":
        merged = [f for f in current if f not in requested]
    else:
        merged = requested
    if merged == current:
        return False
    query_params["fields"] = merged
    component["queryParams"] = query_params
    return True


_COMPONENT_OP_HANDLERS = {
    "setComponentTitle": _apply_set_title,
    "setComponentType": _apply_set_type,
    "setComponentLayout": _apply_set_layout,
    "setComponentPalette": _apply_set_palette,
    "setComponentQueryParams": _apply_set_query_params,
    "setComponentFields": _apply_set_fields,
}


def _apply_operations(
    *,
    screen: dict[str, Any],
    operations: list[PatchOperation],
    selected_component_ids: list[str],
    instruction: str,
) -> tuple[set[str], list[str]]:
    """Apply whitelisted operations in place.

    Returns ``(component ids needing refetch, applied summaries)``.
    """
    components: list[Any] = screen.get("components") or []
    selection = set(selected_component_ids)
    needs_refetch: set[str] = set()
    applied: list[str] = []

    for operation in operations:
        if operation.op == "setThemePalette":
            palette = str(operation.value or "").strip()
            theme = dict(screen.get("theme") or {})
            if palette in ALLOWED_PALETTES and theme.get("palette") != (
                palette
            ):
                theme["palette"] = palette
                screen["theme"] = theme
                applied.append("setThemePalette")
            continue

        if operation.op == "addComponent":
            raw = operation.value if isinstance(operation.value, dict) else {}
            if not raw:
                continue
            raw = dict(raw)
            raw["visualSpec"] = sanitize_visual_spec(raw.get("visualSpec"))
            plan_component = normalize_plan_component(
                raw,
                index=len(components),
                inferred_lookback_minutes=extract_lookback_minutes(
                    instruction,
                ),
                prompt=instruction,
            )
            component_dict = assemble_component(plan_component, None)
            components.append(component_dict)
            needs_refetch.add(plan_component.id)
            applied.append("addComponent")
            continue

        handler = _COMPONENT_OP_HANDLERS.get(operation.op)
        if handler is None:
            continue
        for component_id in operation.target_ids():
            if selection and component_id not in selection:
                continue  # 局部修改只影响选中
            index = _component_index(components, component_id)
            if index < 0:
                continue
            if handler(components[index], operation.value):
                applied.append(operation.op)
                if operation.op in _DATA_AFFECTING_OPS:
                    needs_refetch.add(component_id)
    screen["components"] = components
    return needs_refetch, applied


async def _refetch_components(
    screen: dict[str, Any],
    component_ids: set[str],
) -> None:
    if not component_ids:
        return
    cache = CapabilityCache()
    components: list[Any] = screen.get("components") or []
    for component in components:
        if not isinstance(component, dict):
            continue
        if str(component.get("id") or "") not in component_ids:
            continue
        capability_id = str(
            component.get("capabilityId") or component.get("pluginId") or "",
        )
        result = await execute_capability(
            component.get("queryParams") or {},
            capability_id=capability_id,
            cache=cache,
        )
        component["data"] = result.to_legacy_data()


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


async def apply_patch(
    *,
    screen: dict[str, Any],
    instruction: str,
    selected_component_id: str = "",
    selected_component_ids: list[str] | None = None,
    selected_region: Mapping[str, Any] | None = None,
    selection_context: Mapping[str, Any] | None = None,
    requested_by: str = "portal",
    model: ModelCallable | None = None,
    max_repair: int = 2,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Patch a screen in place; returns ``{screen, version, summary}``.

    Persistence is the caller's concern — this operates on the dict.
    """
    normalized_instruction = str(instruction or "").strip()
    if not normalized_instruction:
        raise ValueError("instruction 不能为空")
    components = screen.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("大屏没有可修改组件")

    selection = _normalize_selection(
        selected_component_ids,
        str(selected_component_id or "").strip(),
    )
    for component_id in selection:
        if _component_index(components, component_id) < 0:
            raise ValueError(f"未找到组件：{component_id}")

    active_model = model if model is not None else create_pipeline_model()
    result = await structured_call(
        active_model,
        _build_patch_messages(
            screen=screen,
            instruction=normalized_instruction,
            selected_component_ids=selection,
        ),
        parser=parse_patch_plan,
        max_repair=max_repair,
        timeout=timeout,
        fallback=lambda: PatchPlan(
            operations=[],
            summary=DEGRADED_PATCH_SUMMARY,
            degraded=True,
        ),
    )
    plan = result.value

    needs_refetch, applied = _apply_operations(
        screen=screen,
        operations=plan.operations,
        selected_component_ids=selection,
        instruction=normalized_instruction,
    )
    await _refetch_components(screen, needs_refetch)

    next_components = [
        component
        for component in (screen.get("components") or [])
        if isinstance(component, dict)
    ]
    screen["dataBindings"] = rebuild_data_bindings(
        components=next_components,
        previous_bindings=screen.get("dataBindings"),
    )
    raw_context = screen.get("aiConversationContext")
    previous_context: dict[str, Any] = (
        dict(raw_context) if isinstance(raw_context, dict) else {}
    )
    source_prompt = str(
        previous_context.get("sourcePrompt") or normalized_instruction,
    )
    context: dict[str, Any] = {
        **previous_context,
        "lastInstruction": normalized_instruction,
        "selectedComponentId": selection[0] if selection else "",
        "selectedComponentIds": selection,
        "selectedRegion": copy.deepcopy(dict(selected_region or {})),
        "selectionContext": copy.deepcopy(dict(selection_context or {})),
        "dataIntentPlan": build_data_intent_plan(
            prompt=source_prompt,
            components=next_components,
            mode="component-state",
            source="component-state",
        ),
        "visualPlan": build_visual_plan(
            components=next_components,
            mode="component-state",
        ),
    }
    if plan.degraded:
        context["degraded"] = True
    screen["aiConversationContext"] = context
    screen["updatedAt"] = now_iso()

    summary = str(plan.summary or "").strip()
    if not applied:
        summary = (
            DEGRADED_PATCH_SUMMARY
            if plan.degraded
            else (summary or "AI 已理解请求，但未生成可执行的大屏配置变更")
        )
    elif not summary:
        summary = f"已应用 {len(applied)} 项大屏变更。"

    version_id = f"v{len(screen.get('versions') or []) + 1}"
    version = build_version(
        screen=screen,
        version_id=version_id,
        summary=summary,
        requested_by=requested_by,
    )
    screen["versions"] = [*(screen.get("versions") or []), version]
    return {"screen": screen, "version": version, "summary": summary}


def patch_component_id() -> str:
    """Generate a component id for additions (kept for symmetry)."""
    return f"component-{uuid.uuid4().hex[:6]}"
