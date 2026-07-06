# -*- coding: utf-8 -*-
"""L3 orchestration: typed plan + capability results -> screen asset.

Assembles the legacy ``AiBigScreenApp`` wire shape (components,
dataBindings, dataIntentPlan, visualPlan, versions) so the existing
frontend (``adaptLegacyScreen`` + the workshop panel) keeps working
unchanged while the pipeline internals are typed.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Mapping

from qwenpaw.extensions.ai_big_screen.capabilities import get_descriptor
from qwenpaw.extensions.ai_big_screen.capabilities.fields import (
    default_capability_fields,
    normalize_capability_fields,
)
from qwenpaw.extensions.ai_big_screen.intent import (
    clamp_screen_title,
    derive_screen_title,
    prompt_declines_title,
    prompt_is_simple_data_query,
)
from qwenpaw.extensions.ai_big_screen.schemas import (
    CapabilityResult,
    PlanComponent,
    ScreenPlan,
)

SCREEN_SCHEMA_VERSION = 1


def _default_timezone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        return local_tz
    return timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(_default_timezone()).isoformat()


def _capability_meta(capability_id: str) -> dict[str, Any]:
    descriptor = get_descriptor(capability_id)
    if descriptor is None:
        return {}
    return copy.deepcopy(descriptor.metadata)


def _component_query_params(component: Mapping[str, Any]) -> dict[str, Any]:
    query_params = component.get("queryParams")
    return dict(query_params) if isinstance(query_params, dict) else {}


# ---------------------------------------------------------------------------
# component assembly
# ---------------------------------------------------------------------------


def assemble_component(
    plan_component: PlanComponent,
    result: CapabilityResult | None,
) -> dict[str, Any]:
    """Merge an L1 plan component with its L2 data into wire shape."""
    capability = _capability_meta(plan_component.capability_id)
    refresh_interval = int(
        (capability.get("refreshPolicy") or {}).get("intervalSeconds") or 120,
    )
    component: dict[str, Any] = {
        "id": plan_component.id,
        "type": plan_component.type,
        "title": plan_component.title,
        "description": plan_component.description,
        "layoutPosition": copy.deepcopy(plan_component.layout_position or {}),
        "pluginId": plan_component.capability_id,
        "capabilityId": plan_component.capability_id,
        "queryParams": copy.deepcopy(plan_component.query_params),
        "visualConfig": copy.deepcopy(plan_component.visual_config),
        "refreshInterval": refresh_interval,
        "interactions": {"selectable": True, "selectionMode": "region"},
        "data": result.to_legacy_data() if result is not None else {},
    }
    if plan_component.visual_spec:
        component["visualSpec"] = copy.deepcopy(plan_component.visual_spec)
    role = str(plan_component.role or "")
    if role:
        # The composition role drives the pattern layout on the frontend;
        # mirror it into visualSpec.composition so legacy consumers
        # (intrinsic sizing, critique) see a consistent importance signal.
        component["compositionRole"] = role
        visual_spec = dict(component.get("visualSpec") or {})
        if not visual_spec.get("composition"):
            visual_spec["composition"] = {
                "hero": "primary",
                "support": "secondary",
                "context": "supporting",
            }[role]
            component["visualSpec"] = visual_spec
    return component


def build_binding(component: Mapping[str, Any]) -> dict[str, Any]:
    capability = _capability_meta(str(component.get("pluginId") or ""))
    return {
        "id": f"binding-{uuid.uuid4().hex[:8]}",
        "componentId": str(component.get("id") or ""),
        "pluginId": str(component.get("pluginId") or ""),
        "input": copy.deepcopy(component.get("queryParams") or {}),
        "outputMapping": {"mode": "direct"},
        "refreshPolicy": copy.deepcopy(capability.get("refreshPolicy") or {}),
        "cachePolicy": copy.deepcopy(capability.get("cachePolicy") or {}),
        "permissionScope": str(capability.get("permissionScope") or ""),
        "sourceDescription": str(capability.get("dataSource") or ""),
        "skillName": str(capability.get("skillName") or ""),
    }


def rebuild_data_bindings(
    *,
    components: list[Any],
    previous_bindings: Any,
) -> list[dict[str, Any]]:
    """Rebuild bindings, preserving stable ids across patches."""
    previous_by_component_id: dict[str, str] = {}
    if isinstance(previous_bindings, list):
        for binding in previous_bindings:
            if not isinstance(binding, dict):
                continue
            component_id = str(binding.get("componentId") or "")
            binding_id = str(binding.get("id") or "")
            if component_id and binding_id:
                previous_by_component_id[component_id] = binding_id
    bindings: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        binding = build_binding(component)
        previous_id = previous_by_component_id.get(
            str(component.get("id") or ""),
        )
        if previous_id:
            binding["id"] = previous_id
        bindings.append(binding)
    return bindings


# ---------------------------------------------------------------------------
# intent / visual plan derivation (ported)
# ---------------------------------------------------------------------------


def _infer_intent_kind(
    *,
    prompt: str,
    component: Mapping[str, Any],
) -> str:
    query_params = _component_query_params(component)
    component_type = str(component.get("type") or "")
    analysis_mode = str(query_params.get("analysisMode") or "")
    text = " ".join(
        (
            str(prompt or ""),
            str(component.get("title") or ""),
            str(component.get("description") or ""),
        ),
    )
    if prompt_is_simple_data_query(prompt):
        return "query"
    if (
        analysis_mode
        or component_type == "risk-pulse"
        or any(
            term in text
            for term in ("分析", "风险", "高危", "危险", "异常", "根因")
        )
    ):
        return "analysis"
    keyword_kinds = (
        (("对比", "比较", "同比", "环比"), "compare"),
        (("趋势", "走势", "变化"), "trend"),
        (("统计", "汇总", "数量", "总数"), "aggregate"),
        (("关联", "相关", "影响"), "correlation"),
    )
    for terms, kind in keyword_kinds:
        if any(term in text for term in terms):
            return kind
    return "query"


def _infer_time_intent(
    *,
    prompt: str,
    query_params: Mapping[str, Any],
) -> str:
    text = str(prompt or "")
    strategy = str(
        query_params.get("searchStrategy")
        or query_params.get("search_strategy")
        or "",
    )
    time_mode = str(
        query_params.get("timeMode") or query_params.get("time_mode") or "",
    )
    if strategy == "latest_non_empty" or time_mode == "latest_non_empty":
        return "latest_non_empty"
    if any(
        str(query_params.get(key) or "").strip()
        for key in ("fromTime", "from_time", "toTime", "to_time")
    ):
        return "absolute"
    if (
        "lookbackMinutes" in query_params
        or str(query_params.get("timeMode") or "") == "relative"
    ):
        return "relative"
    if any(
        term in text
        for term in ("当前", "目前", "现在", "实时", "活动", "有哪些")
    ):
        return "current"
    if "最近" in text or "分钟" in text or "小时" in text:
        return "relative"
    return "current"


def _infer_data_quality(component: Mapping[str, Any]) -> str:
    data = (
        component.get("data")
        if isinstance(component.get("data"), dict)
        else {}
    )
    capability_id = str(
        component.get("capabilityId") or component.get("pluginId") or "",
    )
    if capability_id == "capability-gap":
        return "gap"
    status = str(data.get("sourceStatus") or "").strip().lower()
    if status in {"live", "empty", "fallback", "failed", "gap"}:
        return status
    if status in {"unavailable", "error"}:
        return "failed"
    rows = data.get("rows") if isinstance(data, dict) else None
    if isinstance(rows, list):
        return "live" if rows else "empty"
    if data:
        return "live"
    return "empty"


def _build_intent_reasoning_trace(
    component: Mapping[str, Any],
) -> dict[str, Any]:
    data = (
        component.get("data")
        if isinstance(component.get("data"), dict)
        else {}
    )
    rows = data.get("rows") if isinstance(data, dict) else []
    trace: dict[str, Any] = {
        "source": str(data.get("source") or ""),
        "sourceStatus": str(data.get("sourceStatus") or ""),
        "rowCount": len(rows) if isinstance(rows, list) else 0,
    }
    total = data.get("total")
    if isinstance(total, (int, float)):
        trace["total"] = total
    return trace


def build_data_intent_plan(
    *,
    prompt: str,
    components: list[dict[str, Any]],
    mode: str,
    source: str,
) -> dict[str, Any]:
    intents: list[dict[str, Any]] = []
    for index, component in enumerate(components):
        capability_id = str(
            component.get("capabilityId") or component.get("pluginId") or "",
        )
        capability = _capability_meta(capability_id)
        query_params = _component_query_params(component)
        fields = normalize_capability_fields(
            capability_id,
            query_params.get("fields"),
            fallback=default_capability_fields(capability_id),
        )
        intent_item: dict[str, Any] = {
            "id": f"intent-{index + 1}",
            "capabilityId": capability_id,
            "name": str(
                capability.get("name")
                or component.get("title")
                or capability_id,
            ),
            "domain": str(capability.get("domain") or ""),
            "source": source,
            "confidence": 1.0 if source == "semantic-intent" else 0.82,
            "intentKind": _infer_intent_kind(
                prompt=prompt,
                component=component,
            ),
            "timeIntent": _infer_time_intent(
                prompt=prompt,
                query_params=query_params,
            ),
            "dataQuality": _infer_data_quality(component),
            "reasoningTrace": _build_intent_reasoning_trace(component),
            "queryParams": copy.deepcopy(query_params),
            "fields": fields,
            "analysisMode": str(query_params.get("analysisMode") or ""),
            "visualIntent": {
                "type": str(component.get("type") or ""),
                "title": str(component.get("title") or ""),
            },
        }
        if capability_id == "capability-gap":
            intent_item["gapReason"] = str(query_params.get("reason") or "")
            intent_item["requestedData"] = str(
                query_params.get("requestedData") or "",
            )
        intents.append(intent_item)
    return {
        "version": 1,
        "mode": str(mode or "ai-plan"),
        "sourcePrompt": str(prompt or ""),
        "intents": intents,
    }


def _component_current_fields(component: Mapping[str, Any]) -> list[str]:
    capability_id = str(
        component.get("capabilityId") or component.get("pluginId") or "",
    )
    query_fields = normalize_capability_fields(
        capability_id,
        _component_query_params(component).get("fields"),
        fallback=[],
    )
    if query_fields:
        return query_fields
    data = (
        component.get("data")
        if isinstance(component.get("data"), dict)
        else {}
    )
    raw_columns = data.get("columns") if isinstance(data, dict) else []
    columns = raw_columns if isinstance(raw_columns, list) else []
    column_keys = [
        str(column.get("key") or "")
        for column in columns
        if isinstance(column, dict) and str(column.get("key") or "").strip()
    ]
    data_fields = normalize_capability_fields(
        capability_id,
        column_keys,
        fallback=[],
    )
    if data_fields:
        return data_fields
    return default_capability_fields(capability_id)


def build_visual_plan(
    *,
    components: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index, component in enumerate(components):
        capability_id = str(
            component.get("capabilityId") or component.get("pluginId") or "",
        )
        query_params = _component_query_params(component)
        visible_fields = normalize_capability_fields(
            capability_id,
            query_params.get("fields"),
            fallback=_component_current_fields(component),
        )
        items.append(
            {
                "id": f"visual-{index + 1}",
                "componentId": str(component.get("id") or ""),
                "capabilityId": capability_id,
                "visualType": str(component.get("type") or ""),
                "title": str(component.get("title") or ""),
                "layoutPosition": copy.deepcopy(
                    component.get("layoutPosition") or {},
                ),
                "visibleFields": visible_fields,
                "visualConfig": copy.deepcopy(
                    component.get("visualConfig") or {},
                ),
                "visualSpec": copy.deepcopy(
                    component.get("visualSpec") or {},
                ),
            },
        )
    return {
        "version": 1,
        "mode": str(mode or "component-state"),
        "items": items,
    }


def extract_capability_gaps(
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for component in components:
        capability_id = str(
            component.get("pluginId") or component.get("capabilityId") or "",
        )
        if capability_id != "capability-gap":
            continue
        query_params = _component_query_params(component)
        gaps.append(
            {
                "componentId": str(component.get("id") or ""),
                "requestedData": str(
                    query_params.get("requestedData")
                    or component.get("title")
                    or "",
                ),
                "reason": str(query_params.get("reason") or ""),
                "suggestedSkillName": str(
                    query_params.get("suggestedSkillName") or "",
                ),
                "suggestedApi": str(query_params.get("suggestedApi") or ""),
            },
        )
    return gaps


# ---------------------------------------------------------------------------
# versions + screen assembly
# ---------------------------------------------------------------------------


def _snapshot_screen(screen: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = copy.deepcopy(dict(screen))
    snapshot["versions"] = []
    return snapshot


def build_version(
    *,
    screen: Mapping[str, Any],
    version_id: str,
    summary: str,
    requested_by: str = "portal",
) -> dict[str, Any]:
    versions = screen.get("versions") or [{}]
    change_summary = str(summary or "")
    changed_by = str(requested_by or "portal").strip() or "portal"
    return {
        "versionId": version_id,
        "screenId": str(screen.get("id") or ""),
        "configSnapshot": _snapshot_screen(screen),
        "changeSummary": change_summary,
        "changedBy": changed_by,
        "changedByAi": True,
        # T-014: additive audit fields — mirror changeSummary/changedBy under
        # the summary/requestedBy names the version-history surface reads, so
        # every newly appended version keeps a non-null trail of what changed
        # and who asked. Existing stored versions are not backfilled.
        "summary": change_summary,
        "requestedBy": changed_by,
        "createdAt": now_iso(),
        "basedOnVersionId": str(versions[-1].get("versionId") or ""),
    }


def _sanitize_owner(requested_by: str) -> str:
    owner = str(requested_by or "portal").strip() or "portal"
    return re.sub(r"\s+", " ", owner)[:64]


def assemble_screen(
    *,
    plan: ScreenPlan,
    results: Mapping[str, CapabilityResult],
    prompt: str,
    screen_id: str,
    requested_by: str = "portal",
    intent_mode: str = "ai-plan",
    intent_source: str = "normalized-components",
) -> dict[str, Any]:
    """Assemble the full legacy-shaped screen asset.

    ``results`` maps component id -> ``CapabilityResult`` (fetch-once
    sharing happens upstream in the pipeline).
    """
    now = now_iso()
    components = [
        assemble_component(component, results.get(component.id))
        for component in plan.components
    ]
    data_bindings = [build_binding(component) for component in components]
    data_intent_plan = build_data_intent_plan(
        prompt=prompt,
        components=components,
        mode=intent_mode,
        source=intent_source,
    )
    visual_plan_mode = (
        "data-intent-derived"
        if intent_mode in {"simple-query", "semantic-query"}
        else "component-state"
    )
    context: dict[str, Any] = {
        "sourcePrompt": prompt,
        "lastInstruction": "",
        "generationSummary": plan.summary,
        "dataCapabilities": [
            str(binding.get("pluginId") or "") for binding in data_bindings
        ],
        "capabilityGaps": extract_capability_gaps(components),
        "dataIntentPlan": data_intent_plan,
        "visualPlan": build_visual_plan(
            components=components,
            mode=visual_plan_mode,
        ),
    }
    if plan.degraded:
        context["degraded"] = True
    owner = _sanitize_owner(requested_by)
    # T-015: the draft carries a non-empty banner title (screen.title) — the
    # dedicated field setScreenTitle edits and the renderer prefers over name.
    # Clamped identically to the patch op; falls back through name → heuristic
    # so a hand-built plan without a screenTitle still renders a real banner.
    if prompt_declines_title(prompt):
        # An explicit "不要标题" wins over every fallback — auto-titles are
        # a convenience, not a mandate (the banner stays user-controllable
        # at generation time, not just via a follow-up patch).
        screen_title = clamp_screen_title(plan.screen_title)
    else:
        screen_title = (
            clamp_screen_title(plan.screen_title)
            or clamp_screen_title(plan.name)
            or derive_screen_title(prompt)
        )
    layout_plan = (
        {"pattern": plan.layout_pattern} if plan.layout_pattern else {}
    )
    screen: dict[str, Any] = {
        "schemaVersion": SCREEN_SCHEMA_VERSION,
        "id": screen_id,
        "name": plan.name,
        "title": screen_title,
        "layoutPlan": layout_plan,
        "description": plan.description or f"由自然语言生成：{prompt}",
        "owner": owner,
        "status": "draft",
        "layout": copy.deepcopy(plan.layout),
        "theme": copy.deepcopy(plan.theme),
        "components": components,
        "dataBindings": data_bindings,
        "permissions": {"visibility": "private", "roles": []},
        "versions": [],
        "publishTargets": [],
        "aiConversationContext": context,
        "createdAt": now,
        "updatedAt": now,
    }
    version = build_version(
        screen=screen,
        version_id="v1",
        summary="根据自然语言需求生成大屏草稿。",
        requested_by=owner,
    )
    screen["versions"] = [version]
    return screen
