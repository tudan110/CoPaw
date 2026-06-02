from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Mapping

from qwenpaw.exceptions import ProviderError
from qwenpaw.extensions import ai_big_screen_registry as registry
from qwenpaw.extensions.api.ai_big_screen_models import (
    AiBigScreenDraftRequest,
    AiBigScreenPatchRequest,
)

SCREEN_SCHEMA_VERSION = 1


def _default_timezone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        return local_tz
    return timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(_default_timezone()).isoformat()


DATA_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "system-logs",
        "name": "系统日志",
        "domain": "log",
        "description": "读取当前系统后端运行日志，用于排查近期运行状态。",
        "inputSchema": {"lookbackMinutes": 15, "limit": 50},
        "outputSchema": {"columns": "array", "rows": "array", "sourceStatus": "string"},
        "supportedVisuals": ["table", "text"],
        "permissionScope": "system-log:read",
        "cachePolicy": {"ttlSeconds": 30},
        "refreshPolicy": {"intervalSeconds": 30},
        "dataSource": "backend-log",
        "examplePrompts": ["最近15分钟系统日志", "看一下系统日志"],
    },
    {
        "id": "real-alarms",
        "name": "系统告警",
        "domain": "alarm",
        "description": "调用资源告警接口读取指定时间窗口内的活动告警。",
        "inputSchema": {"lookbackMinutes": 15, "limit": 100},
        "outputSchema": {"columns": "array", "rows": "array", "total": "number"},
        "supportedVisuals": ["table", "metric-card", "bar-chart"],
        "permissionScope": "alarm:read",
        "cachePolicy": {"ttlSeconds": 60},
        "refreshPolicy": {"intervalSeconds": 60},
        "dataSource": "portal-real-alarm-api",
        "examplePrompts": ["最近15分钟告警", "当前活动告警"],
    },
    {
        "id": "cmdb-resources",
        "name": "CMDB 资源信息",
        "domain": "resource",
        "description": "调用资源/资产概览接口读取 CMDB 资源统计和资源状态。",
        "inputSchema": {"scope": "all"},
        "outputSchema": {"value": "number", "unit": "string", "rows": "array"},
        "supportedVisuals": ["metric-card", "table", "bar-chart"],
        "permissionScope": "resource:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-asset-overview-api",
        "examplePrompts": ["CMDB资源信息", "资产资源概览"],
    },
    {
        "id": "workorders",
        "name": "工单信息",
        "domain": "workorder",
        "description": "调用告警工单接口读取当前工单和处置对象。",
        "inputSchema": {"timeRange": "today", "limit": 20},
        "outputSchema": {"columns": "array", "rows": "array", "total": "number"},
        "supportedVisuals": ["table", "metric-card", "bar-chart"],
        "permissionScope": "workorder:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-alarm-workorder-api",
        "examplePrompts": ["今日工单", "待处理工单", "工单处置情况"],
    },
    {
        "id": "alarm-top5",
        "name": "告警对象 Top5",
        "domain": "alarm",
        "description": "调用告警统计接口读取告警对象排行。",
        "inputSchema": {"limit": 5},
        "outputSchema": {"categories": "array", "series": "array", "rows": "array"},
        "supportedVisuals": ["bar-chart", "table"],
        "permissionScope": "alarm:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-alarm-statistics-api",
        "examplePrompts": ["告警排行", "告警最多的资源"],
    },
    {
        "id": "topology-impact",
        "name": "拓扑影响范围",
        "domain": "topology",
        "description": "调用拓扑接口读取资源拓扑和影响关系。",
        "inputSchema": {"scope": "active"},
        "outputSchema": {"nodes": "array"},
        "supportedVisuals": ["topology", "table"],
        "permissionScope": "topology:read",
        "cachePolicy": {"ttlSeconds": 180},
        "refreshPolicy": {"intervalSeconds": 180},
        "dataSource": "portal-topology-api",
        "examplePrompts": ["拓扑影响范围", "资源链路影响"],
    },
]


def list_builtin_plugins() -> list[dict[str, Any]]:
    return [copy.deepcopy(item) for item in DATA_CAPABILITIES]


async def build_screen_draft(request: AiBigScreenDraftRequest) -> dict[str, Any]:
    prompt = str(request.prompt or "").strip()
    if not prompt:
        raise ValueError("prompt 不能为空")

    screen_id = f"screen-{uuid.uuid4().hex[:10]}"
    requested_title = str(request.title or "").strip()
    now = _now_iso()
    raw_plan = await _build_screen_plan_with_ai(prompt=prompt, title=requested_title)
    plan = _normalize_screen_plan(raw_plan, prompt=prompt, title=requested_title)
    components = await _hydrate_components_with_data(plan["components"])
    data_bindings = [_build_binding(component) for component in components]
    screen = {
        "schemaVersion": SCREEN_SCHEMA_VERSION,
        "id": screen_id,
        "name": plan["name"],
        "description": plan["description"] or f"由自然语言生成：{prompt}",
        "owner": str(request.requestedBy or "portal").strip() or "portal",
        "status": "draft",
        "layout": plan["layout"],
        "theme": plan["theme"],
        "components": components,
        "dataBindings": data_bindings,
        "permissions": {"visibility": "private", "roles": []},
        "versions": [],
        "publishTargets": [],
        "aiConversationContext": {
            "sourcePrompt": prompt,
            "lastInstruction": "",
            "generationSummary": plan["summary"],
            "dataCapabilities": [item["pluginId"] for item in data_bindings],
        },
        "createdAt": now,
        "updatedAt": now,
    }
    version = _build_version(
        screen=screen,
        version_id="v1",
        summary="根据自然语言需求生成大屏草稿。",
        requested_by=screen["owner"],
    )
    screen["versions"] = [version]
    return screen


def save_screen_asset(
    *,
    screen: Mapping[str, Any],
    requested_by: str = "portal",
) -> dict[str, Any]:
    normalized = dict(screen)
    _validate_screen(normalized)
    return registry.save_screen(screen=normalized, requested_by=requested_by)


def list_screen_assets(*, limit: int = 50) -> list[dict[str, Any]]:
    return registry.list_screens(limit=limit)


def get_screen_asset(*, screen_id: str) -> dict[str, Any]:
    return registry.get_screen(screen_id=screen_id)


def publish_screen_asset(
    *,
    screen_id: str,
    requested_by: str = "portal",
    visibility: str = "internal",
) -> dict[str, Any]:
    screen = registry.get_screen(screen_id=screen_id)
    now = _now_iso()
    normalized_visibility = str(visibility or "internal").strip() or "internal"
    publish_targets = [
        {
            "type": "portal-center",
            "url": "/big-screens",
            "visibility": normalized_visibility,
            "createdAt": now,
            "createdBy": requested_by,
        },
        {
            "type": "external-link",
            "url": f"/big-screen/{screen_id}",
            "visibility": normalized_visibility,
            "createdAt": now,
            "createdBy": requested_by,
        },
        {
            "type": "iframe",
            "url": f"/big-screen/{screen_id}?embed=1",
            "visibility": normalized_visibility,
            "createdAt": now,
            "createdBy": requested_by,
        },
    ]
    screen["status"] = "published"
    screen["permissions"] = {
        **(screen.get("permissions") if isinstance(screen.get("permissions"), dict) else {}),
        "visibility": normalized_visibility,
    }
    screen["publishTargets"] = publish_targets
    screen["aiConversationContext"] = {
        **(
            screen.get("aiConversationContext")
            if isinstance(screen.get("aiConversationContext"), dict)
            else {}
        ),
        "lastInstruction": "发布大屏",
    }
    saved = registry.save_screen(screen=screen, requested_by=requested_by)
    return {"screen": saved, "publishTargets": publish_targets}


AI_BIG_SCREEN_CONFIGURE_LLM_MESSAGE = (
    "未配置默认大模型，请先到“模型配置”里设置默认 LLM 后再生成或修改 AI 大屏。"
)

_ALLOWED_PALETTES = {"professional", "warm", "cool", "executive", "industrial", "aurora", "mono"}
_ALLOWED_COMPONENT_TYPES = {"metric-card", "line-chart", "bar-chart", "table", "topology", "text"}


async def patch_screen_asset(
    *,
    screen_id: str,
    request: AiBigScreenPatchRequest,
) -> dict[str, Any]:
    instruction = str(request.instruction or "").strip()
    if not instruction:
        raise ValueError("instruction 不能为空")

    screen = registry.get_screen(screen_id=screen_id)
    components = screen.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("大屏没有可修改组件")

    selected_component_id = str(request.selectedComponentId or "").strip()
    selected_index = _find_component_index(components, selected_component_id)
    if selected_component_id and selected_index < 0:
        raise ValueError(f"未找到组件：{selected_component_id}")

    plan = await _build_patch_plan_with_ai(
        screen=screen,
        selected_component_id=selected_component_id,
        instruction=instruction,
    )
    summary = _apply_patch_plan(screen=screen, plan=plan)

    screen["aiConversationContext"] = {
        **(
            screen.get("aiConversationContext")
            if isinstance(screen.get("aiConversationContext"), dict)
            else {}
        ),
        "lastInstruction": instruction,
        "selectedComponentId": selected_component_id,
    }

    version_id = f"v{len(screen.get('versions') or []) + 1}"
    if not summary:
        summary = "AI 已理解请求，但未生成可执行的大屏配置变更"
    version = _build_version(
        screen=screen,
        version_id=version_id,
        summary=summary,
        requested_by=request.requestedBy,
    )
    screen["versions"] = [*(screen.get("versions") or []), version]
    saved = registry.save_screen(screen=screen, requested_by=request.requestedBy)
    return {"screen": saved, "version": version, "summary": summary}


async def _build_patch_plan_with_ai(
    *,
    screen: Mapping[str, Any],
    selected_component_id: str,
    instruction: str,
) -> dict[str, Any]:
    from qwenpaw.agents.model_factory import create_model_and_formatter

    component_catalog = [
        {
            "id": str(item.get("id") or ""),
            "type": str(item.get("type") or ""),
            "title": str(item.get("title") or ""),
            "pluginId": str(item.get("pluginId") or ""),
            "visualConfig": copy.deepcopy(item.get("visualConfig") or {}),
            "queryParams": copy.deepcopy(item.get("queryParams") or {}),
        }
        for item in screen.get("components", [])
        if isinstance(item, dict)
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是 AI 运维大屏配置设计助手。"
                "你只输出严格 JSON，不要输出 Markdown、代码块或解释。"
                "你的任务是根据用户自然语言，对当前大屏生成结构化 patch plan，"
                "由后端执行，不允许生成前端源码、SQL 或任意脚本。"
                "JSON 固定字段：summary, operations。"
                "operations 是数组，每项 type 只能是："
                "setThemePalette、setComponentPalette、setComponentType、"
                "setComponentTitle、setComponentQueryParams。"
                "palette 只能是 professional、warm、cool、executive；"
                "component type 只能是 metric-card、line-chart、bar-chart、table、topology、text。"
                "componentIds 必须来自用户给定组件清单；如果用户在说整个大屏，"
                "可以对多个 componentIds 生效。"
                "如果用户说太丑、美化、高级、领导看、换颜色但没指定具体颜色，"
                "优先使用 executive。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": instruction,
                    "selectedComponentId": selected_component_id,
                    "screen": {
                        "id": screen.get("id"),
                        "name": screen.get("name"),
                        "theme": screen.get("theme"),
                        "components": component_catalog,
                    },
                    "outputExample": {
                        "summary": "视觉风格调整为领导驾驶舱风格",
                        "operations": [
                            {
                                "type": "setThemePalette",
                                "palette": "executive",
                            },
                            {
                                "type": "setComponentPalette",
                                "componentIds": ["component-1"],
                                "palette": "executive",
                                "emphasis": "strong",
                            },
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]

    try:
        model, _ = create_model_and_formatter()
    except ProviderError as exc:
        raise _map_provider_error(exc) from exc
    except Exception as exc:
        raise ValueError(f"默认大模型初始化失败：{_extract_exception_message(exc)}") from exc

    try:
        response_text = await _consume_model_response(model, messages)
    except ProviderError as exc:
        raise ValueError(f"默认大模型调用失败：{_extract_exception_message(exc)}") from exc
    except Exception as exc:
        raise ValueError(f"默认大模型调用失败：{_extract_exception_message(exc)}") from exc

    parsed = _parse_llm_json_payload(response_text)
    if not isinstance(parsed, dict):
        raise ValueError("默认大模型未返回可执行的大屏配置 JSON，请重新描述修改要求。")
    return _normalize_patch_plan(parsed, screen=screen, selected_component_id=selected_component_id)


async def _build_screen_plan_with_ai(*, prompt: str, title: str) -> dict[str, Any]:
    from qwenpaw.agents.model_factory import create_model_and_formatter

    capabilities = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "domain": str(item.get("domain") or ""),
            "description": str(item.get("description") or ""),
            "inputSchema": copy.deepcopy(item.get("inputSchema") or {}),
            "supportedVisuals": copy.deepcopy(item.get("supportedVisuals") or []),
            "dataSource": str(item.get("dataSource") or ""),
        }
        for item in DATA_CAPABILITIES
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是面向运维场景的 AI 大屏产品设计师和数据需求分析师。"
                "你必须先理解用户语义中真正需要的数据，再从给定 dataCapabilities 中选择能力。"
                "同一句话出现多个数据对象时必须全部覆盖，例如日志和告警要生成两个独立数据需求。"
                "你需要创造性设计版式、标题、描述、视觉调性和组件组合，但不得输出前端源码、SQL、脚本或未授权接口。"
                "只输出严格 JSON，不要输出 Markdown、解释或代码块。"
                "JSON 字段固定为：name, description, theme, layout, components, summary。"
                "theme.palette 只能是 professional、industrial、aurora、mono、warm、cool、executive。"
                "components 是数组；每项必须包含 title, description, capabilityId, visualType, queryParams, layoutPosition。"
                "capabilityId 必须来自 dataCapabilities；visualType 必须是 metric-card、line-chart、bar-chart、table、topology、text。"
                "queryParams 只写普通 JSON 参数。layoutPosition 使用 12 列网格 x,y,w,h。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "prompt": prompt,
                    "titleOverride": title,
                    "dataCapabilities": capabilities,
                    "outputExample": {
                        "name": "15分钟运行态势",
                        "description": "围绕近期日志、告警和资源状态的实时大屏。",
                        "theme": {
                            "mode": "dark",
                            "palette": "industrial",
                            "density": "dashboard",
                        },
                        "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
                        "components": [
                            {
                                "title": "15分钟系统日志",
                                "description": "最近 15 分钟系统运行日志。",
                                "capabilityId": "system-logs",
                                "visualType": "table",
                                "queryParams": {"lookbackMinutes": 15, "limit": 50},
                                "layoutPosition": {"x": 0, "y": 0, "w": 6, "h": 4},
                            },
                            {
                                "title": "15分钟系统告警",
                                "description": "最近 15 分钟活动告警。",
                                "capabilityId": "real-alarms",
                                "visualType": "table",
                                "queryParams": {"lookbackMinutes": 15, "limit": 80},
                                "layoutPosition": {"x": 6, "y": 0, "w": 6, "h": 4},
                            },
                        ],
                        "summary": "覆盖日志和告警两个实时数据需求。",
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]

    try:
        model, _ = create_model_and_formatter()
    except ProviderError as exc:
        raise _map_provider_error(exc) from exc
    except Exception as exc:
        raise ValueError(f"默认大模型初始化失败：{_extract_exception_message(exc)}") from exc

    try:
        response_text = await _consume_model_response(model, messages)
    except ProviderError as exc:
        raise ValueError(f"默认大模型调用失败：{_extract_exception_message(exc)}") from exc
    except Exception as exc:
        raise ValueError(f"默认大模型调用失败：{_extract_exception_message(exc)}") from exc

    parsed = _parse_llm_json_payload(response_text)
    if not isinstance(parsed, dict):
        raise ValueError("默认大模型未返回可执行的大屏方案 JSON，请重新描述大屏需求。")
    return parsed


def _normalize_screen_plan(
    plan: Mapping[str, Any],
    *,
    prompt: str,
    title: str,
) -> dict[str, Any]:
    inferred_lookback_minutes = _extract_lookback_minutes(prompt)
    normalized_components = [
        _normalize_plan_component(
            component,
            index=index,
            inferred_lookback_minutes=inferred_lookback_minutes,
        )
        for index, component in enumerate(
            plan.get("components") if isinstance(plan.get("components"), list) else []
        )
        if isinstance(component, dict)
    ]
    normalized_components = [item for item in normalized_components if item]
    normalized_components = _ensure_semantic_capabilities(
        prompt=prompt,
        components=normalized_components,
        inferred_lookback_minutes=inferred_lookback_minutes,
    )
    if not normalized_components:
        raise ValueError("默认大模型没有生成可执行的数据能力组件，请重新描述需要展示的数据。")

    requested_title = str(title or "").strip()
    plan_name = str(plan.get("name") or "").strip()
    return {
        "name": requested_title or plan_name or "AI 实时运维大屏",
        "description": str(plan.get("description") or "").strip(),
        "theme": _normalize_theme(plan.get("theme")),
        "layout": _normalize_layout(plan.get("layout")),
        "components": normalized_components,
        "summary": str(plan.get("summary") or "").strip(),
    }


def _normalize_plan_component(
    component: Mapping[str, Any],
    *,
    index: int,
    inferred_lookback_minutes: int,
) -> dict[str, Any]:
    capability_id = str(
        component.get("capabilityId")
        or component.get("pluginId")
        or component.get("dataCapabilityId")
        or "",
    ).strip()
    capability = _plugin_by_id(capability_id)
    if not capability:
        return {}

    supported_visuals = [
        str(item)
        for item in capability.get("supportedVisuals", [])
        if str(item) in _ALLOWED_COMPONENT_TYPES
    ]
    requested_type = str(component.get("visualType") or component.get("type") or "").strip()
    component_type = requested_type if requested_type in supported_visuals else ""
    if not component_type:
        component_type = supported_visuals[0] if supported_visuals else "table"

    query_params = _normalize_query_params(
        component.get("queryParams"),
        capability=capability,
        inferred_lookback_minutes=inferred_lookback_minutes,
    )
    return {
        "id": f"component-{index + 1}-{uuid.uuid4().hex[:6]}",
        "type": component_type,
        "title": (str(component.get("title") or "").strip() or str(capability["name"]))[:80],
        "description": (
            str(component.get("description") or "").strip()
            or str(capability.get("description") or "")
        )[:220],
        "layoutPosition": _normalize_layout_position(component.get("layoutPosition"), index),
        "pluginId": capability_id,
        "capabilityId": capability_id,
        "queryParams": query_params,
        "visualConfig": _normalize_visual_config(component.get("visualConfig")),
        "refreshInterval": int((capability.get("refreshPolicy") or {}).get("intervalSeconds") or 120),
        "interactions": {"selectable": True, "selectionMode": "region"},
        "data": {},
    }


def _normalize_theme(raw_theme: Any) -> dict[str, Any]:
    theme = raw_theme if isinstance(raw_theme, dict) else {}
    palette = _normalize_palette(theme.get("palette")) or "industrial"
    return {
        "mode": "dark",
        "palette": palette,
        "density": str(theme.get("density") or "dashboard").strip() or "dashboard",
    }


def _normalize_layout(raw_layout: Any) -> dict[str, Any]:
    layout = raw_layout if isinstance(raw_layout, dict) else {}
    return {
        "type": "grid",
        "columns": 12,
        "rowHeight": max(64, min(120, _safe_int(layout.get("rowHeight"), 84))),
    }


def _normalize_layout_position(raw_position: Any, index: int) -> dict[str, int]:
    position = raw_position if isinstance(raw_position, dict) else {}
    fallback_positions = [
        {"x": 0, "y": 0, "w": 6, "h": 4},
        {"x": 6, "y": 0, "w": 6, "h": 4},
        {"x": 0, "y": 4, "w": 4, "h": 3},
        {"x": 4, "y": 4, "w": 4, "h": 3},
        {"x": 8, "y": 4, "w": 4, "h": 3},
        {"x": 0, "y": 7, "w": 12, "h": 4},
    ]
    fallback = fallback_positions[index % len(fallback_positions)]
    x = max(0, min(11, _safe_int(position.get("x"), fallback["x"])))
    w = max(1, min(12 - x, _safe_int(position.get("w"), fallback["w"])))
    return {
        "x": x,
        "y": max(0, _safe_int(position.get("y"), fallback["y"])),
        "w": w,
        "h": max(1, min(8, _safe_int(position.get("h"), fallback["h"]))),
    }


def _normalize_visual_config(raw_visual_config: Any) -> dict[str, str]:
    visual_config = raw_visual_config if isinstance(raw_visual_config, dict) else {}
    palette = _normalize_palette(visual_config.get("palette")) or "industrial"
    emphasis = str(visual_config.get("emphasis") or "standard").strip()
    return {
        "palette": palette,
        "emphasis": emphasis if emphasis in {"standard", "strong"} else "standard",
    }


def _normalize_query_params(
    raw_query_params: Any,
    *,
    capability: Mapping[str, Any],
    inferred_lookback_minutes: int,
) -> dict[str, Any]:
    query_params = copy.deepcopy(capability.get("inputSchema") or {})
    if isinstance(raw_query_params, dict):
        query_params.update(copy.deepcopy(raw_query_params))
    if "lookbackMinutes" in query_params:
        query_params["lookbackMinutes"] = max(
            1,
            min(24 * 60, _safe_int(query_params.get("lookbackMinutes"), inferred_lookback_minutes)),
        )
    if inferred_lookback_minutes and str(capability.get("id") or "") in {"system-logs", "real-alarms"}:
        query_params["lookbackMinutes"] = inferred_lookback_minutes
    if "limit" in query_params:
        query_params["limit"] = max(1, min(200, _safe_int(query_params.get("limit"), 50)))
    return query_params


def _ensure_semantic_capabilities(
    *,
    prompt: str,
    components: list[dict[str, Any]],
    inferred_lookback_minutes: int,
) -> list[dict[str, Any]]:
    present = {str(item.get("capabilityId") or item.get("pluginId") or "") for item in components}
    next_components = list(components)
    for capability_id in _extract_semantic_capability_ids(prompt):
        if capability_id in present:
            continue
        next_components.append(
            _build_semantic_component(
                capability_id=capability_id,
                index=len(next_components),
                inferred_lookback_minutes=inferred_lookback_minutes,
            ),
        )
        present.add(capability_id)
    return next_components


def _build_semantic_component(
    *,
    capability_id: str,
    index: int,
    inferred_lookback_minutes: int,
) -> dict[str, Any]:
    capability = _plugin_by_id(capability_id)
    if not capability:
        return {}
    visual_type = (capability.get("supportedVisuals") or ["table"])[0]
    title_prefix = f"{inferred_lookback_minutes}分钟" if inferred_lookback_minutes else ""
    title = f"{title_prefix}{capability['name']}"
    component = {
        "title": title,
        "description": capability.get("description") or "",
        "capabilityId": capability_id,
        "visualType": visual_type,
        "queryParams": copy.deepcopy(capability.get("inputSchema") or {}),
        "layoutPosition": _normalize_layout_position({}, index),
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
    }
    if inferred_lookback_minutes and capability_id in {"system-logs", "real-alarms"}:
        component["queryParams"]["lookbackMinutes"] = inferred_lookback_minutes
    return _normalize_plan_component(
        component,
        index=index,
        inferred_lookback_minutes=inferred_lookback_minutes,
    )


def _extract_semantic_capability_ids(prompt: str) -> list[str]:
    normalized = str(prompt or "").lower()
    capability_ids: list[str] = []
    checks = [
        ("system-logs", ("日志", "log", "logs")),
        ("real-alarms", ("告警", "报警", "alarm", "alarms")),
        ("workorders", ("工单", "workorder", "ticket", "tickets")),
        ("cmdb-resources", ("cmdb", "资源", "资产", "resource", "asset")),
        ("topology-impact", ("拓扑", "链路", "影响范围", "topology")),
    ]
    for capability_id, terms in checks:
        if any(term in normalized for term in terms):
            capability_ids.append(capability_id)
    return capability_ids


def _extract_lookback_minutes(prompt: str) -> int:
    normalized = str(prompt or "")
    minute_match = re.search(r"(\d{1,4})\s*分钟", normalized)
    if minute_match:
        return max(1, min(24 * 60, int(minute_match.group(1))))
    hour_match = re.search(r"(\d{1,3})\s*(?:小时|钟头)", normalized)
    if hour_match:
        return max(1, min(24 * 60, int(hour_match.group(1)) * 60))
    return 15


async def _hydrate_components_with_data(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not components:
        return []
    return list(await asyncio.gather(*(_hydrate_component_with_data(component) for component in components)))


async def _hydrate_component_with_data(component: dict[str, Any]) -> dict[str, Any]:
    next_component = dict(component)
    capability_id = str(component.get("capabilityId") or component.get("pluginId") or "")
    query_params = _component_query_params(component)
    next_component["data"] = await asyncio.to_thread(
        _execute_data_capability,
        capability_id,
        query_params,
    )
    return next_component


def _execute_data_capability(capability_id: str, query_params: dict[str, Any]) -> dict[str, Any]:
    try:
        if capability_id == "system-logs":
            return _query_system_logs(query_params)
        if capability_id == "real-alarms":
            return _query_real_alarms(query_params)
        if capability_id == "cmdb-resources":
            return _query_cmdb_resources(query_params)
        if capability_id == "workorders":
            return _query_workorders(query_params)
        if capability_id == "alarm-top5":
            return _query_alarm_top5(query_params)
        if capability_id == "topology-impact":
            return _query_topology_impact(query_params)
    except Exception as exc:  # noqa: BLE001
        return {
            "source": _plugin_by_id(capability_id).get("dataSource") or "unknown",
            "sourceStatus": "unavailable",
            "message": f"{type(exc).__name__}: {_extract_exception_message(exc)}",
        }
    return {
        "source": "unsupported",
        "sourceStatus": "unavailable",
        "message": f"未接入数据能力：{capability_id}",
    }


def _query_system_logs(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.app.runner.daemon_commands import run_daemon_logs

    limit = max(1, min(200, _safe_int(query_params.get("limit"), 50)))
    raw_text = run_daemon_logs(lines=limit)
    content = _extract_fenced_content(raw_text)
    rows = [
        _normalize_log_line(line)
        for line in content.splitlines()
        if line.strip()
    ][:limit]
    source_status = "live" if rows else "empty"
    if content.startswith("(Log file not found") or content.startswith("(Error reading log"):
        source_status = "unavailable"
    return {
        "source": "backend-log",
        "sourceStatus": source_status,
        "lookbackMinutes": _safe_int(query_params.get("lookbackMinutes"), 15),
        "columns": [
            {"key": "time", "label": "时间"},
            {"key": "level", "label": "级别"},
            {"key": "message", "label": "日志内容"},
        ],
        "rows": rows,
    }


def _query_real_alarms(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.portal_real_alarms import query_portal_real_alarms

    limit = max(1, min(200, _safe_int(query_params.get("limit"), 100)))
    lookback_minutes = max(1, min(24 * 60, _safe_int(query_params.get("lookbackMinutes"), 15)))
    payload = query_portal_real_alarms(limit=limit, lookback_minutes=lookback_minutes)
    rows = list(payload.get("items") or [])
    return {
        "source": "portal-real-alarm-api",
        "sourceStatus": "live" if rows else "empty",
        "lookbackMinutes": lookback_minutes,
        "total": int(payload.get("total") or len(rows)),
        "value": int(payload.get("total") or len(rows)),
        "unit": "起",
        "trend": f"最近 {lookback_minutes} 分钟活动告警",
        "columns": [
            {"key": "eventTime", "label": "时间"},
            {"key": "level", "label": "级别"},
            {"key": "title", "label": "告警"},
            {"key": "deviceName", "label": "资源"},
            {"key": "manageIp", "label": "IP"},
        ],
        "rows": rows[:limit],
    }


def _query_cmdb_resources(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.portal_monitoring_overview import query_asset_overview

    envelope = query_asset_overview()
    source_status = _envelope_source_status(envelope)
    data = envelope.get("data") if isinstance(envelope, dict) else None
    message = str(envelope.get("msg") or "接口不可用") if isinstance(envelope, dict) else "接口不可用"
    rows = _build_metric_rows(data)
    value = _first_numeric_value(data)
    if value is None:
        value = len(rows)
    return {
        "source": "portal-asset-overview-api",
        "sourceStatus": source_status,
        "scope": str(query_params.get("scope") or "all"),
        "value": value,
        "unit": "项",
        "trend": "来自 CMDB/资源概览接口" if source_status == "live" else message,
        "columns": [
            {"key": "name", "label": "指标"},
            {"key": "value", "label": "值"},
        ],
        "rows": rows,
        "raw": data,
    }


def _query_workorders(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.alarm_workorders.query_alarm_workorders import (
        query_alarm_workorders,
    )

    limit = max(1, min(100, _safe_int(query_params.get("limit"), 20)))
    payload = query_alarm_workorders(limit=limit)
    rows = list(payload.get("items") or [])
    return {
        "source": "portal-alarm-workorder-api",
        "sourceStatus": "live" if rows else "empty",
        "timeRange": str(query_params.get("timeRange") or "today"),
        "total": int(payload.get("total") or len(rows)),
        "value": int(payload.get("total") or len(rows)),
        "unit": "单",
        "trend": "今日工单" if str(query_params.get("timeRange") or "today") == "today" else "工单查询结果",
        "columns": [
            {"key": "workorderNo", "label": "工单号"},
            {"key": "title", "label": "标题"},
            {"key": "status", "label": "状态"},
            {"key": "severity", "label": "级别"},
            {"key": "eventTime", "label": "时间"},
        ],
        "rows": rows[:limit],
    }


def _query_alarm_top5(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.portal_monitoring_overview import query_alarm_top5

    limit = max(1, min(20, _safe_int(query_params.get("limit"), 5)))
    envelope = query_alarm_top5()
    data = envelope.get("data") if isinstance(envelope, dict) else None
    rows = _build_metric_rows(data)[:limit]
    return {
        "source": "portal-alarm-statistics-api",
        "sourceStatus": _envelope_source_status(envelope),
        "columns": [
            {"key": "name", "label": "对象"},
            {"key": "value", "label": "数量"},
        ],
        "rows": rows,
        "categories": [str(row.get("name") or "") for row in rows],
        "series": [_safe_int(row.get("value"), 0) for row in rows],
    }


def _query_topology_impact(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.portal_monitoring_overview import query_topology

    envelope = query_topology()
    data = envelope.get("data") if isinstance(envelope, dict) else None
    nodes = _build_topology_nodes(data)
    return {
        "source": "portal-topology-api",
        "sourceStatus": _envelope_source_status(envelope),
        "scope": str(query_params.get("scope") or "active"),
        "nodes": nodes,
        "raw": data,
    }


def _extract_fenced_content(raw_text: str) -> str:
    match = re.search(r"```\s*(.*?)\s*```", str(raw_text or ""), flags=re.DOTALL)
    return match.group(1) if match else str(raw_text or "")


def _normalize_log_line(line: str) -> dict[str, str]:
    text = line.strip()
    level = "INFO"
    level_match = re.search(r"\b(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|CRITICAL)\b", text, re.I)
    if level_match:
        level = level_match.group(1).upper()
    time_match = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", text)
    return {
        "time": time_match.group(0) if time_match else "--",
        "level": level,
        "message": text[:500],
    }


def _envelope_source_status(envelope: Any) -> str:
    if not isinstance(envelope, dict):
        return "unavailable"
    code = _safe_int(envelope.get("code"), 200)
    if code >= 400:
        return "unavailable"
    data = envelope.get("data")
    if data in (None, [], {}):
        return "empty"
    return "live"


def _build_metric_rows(data: Any, *, prefix: str = "", limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            label = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                rows.append({"name": label, "value": "--" if value is None else value})
            elif isinstance(value, list):
                rows.append({"name": label, "value": len(value)})
            elif isinstance(value, dict):
                rows.extend(_build_metric_rows(value, prefix=label, limit=limit - len(rows)))
            if len(rows) >= limit:
                break
    elif isinstance(data, list):
        for index, item in enumerate(data[:limit]):
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or item.get("resName") or f"item-{index + 1}"
                value = (
                    item.get("value")
                    or item.get("count")
                    or item.get("total")
                    or item.get("num")
                    or 0
                )
                rows.append({"name": str(name), "value": value})
            else:
                rows.append({"name": f"item-{index + 1}", "value": str(item)})
    return rows[:limit]


def _first_numeric_value(data: Any) -> int | float | None:
    if isinstance(data, (int, float)):
        return data
    if isinstance(data, dict):
        for key in ("total", "count", "assetTotal", "resourceTotal", "hostTotal", "value"):
            value = data.get(key)
            if isinstance(value, (int, float)):
                return value
        for value in data.values():
            nested = _first_numeric_value(value)
            if nested is not None:
                return nested
    if isinstance(data, list):
        return len(data)
    return None


def _build_topology_nodes(data: Any) -> list[dict[str, str]]:
    rows = _build_metric_rows(data, limit=18)
    return [
        {
            "name": str(row.get("name") or "--"),
            "status": "warning" if index == 0 else "normal",
        }
        for index, row in enumerate(rows)
    ]


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _build_binding(component: Mapping[str, Any]) -> dict[str, Any]:
    plugin = _plugin_by_id(str(component.get("pluginId") or ""))
    return {
        "id": f"binding-{uuid.uuid4().hex[:8]}",
        "componentId": str(component.get("id") or ""),
        "pluginId": str(component.get("pluginId") or ""),
        "input": copy.deepcopy(component.get("queryParams") or {}),
        "outputMapping": {"mode": "direct"},
        "refreshPolicy": copy.deepcopy(plugin.get("refreshPolicy") or {}),
        "cachePolicy": copy.deepcopy(plugin.get("cachePolicy") or {}),
        "permissionScope": str(plugin.get("permissionScope") or ""),
        "sourceDescription": str(plugin.get("dataSource") or ""),
    }


def _plugin_by_id(plugin_id: str) -> dict[str, Any]:
    for plugin in DATA_CAPABILITIES:
        if plugin["id"] == plugin_id:
            return copy.deepcopy(plugin)
    return {}


def _snapshot_screen(screen: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = copy.deepcopy(dict(screen))
    snapshot["versions"] = []
    return snapshot


def _build_version(
    *,
    screen: Mapping[str, Any],
    version_id: str,
    summary: str,
    requested_by: str = "portal",
) -> dict[str, Any]:
    return {
        "versionId": version_id,
        "screenId": str(screen.get("id") or ""),
        "configSnapshot": _snapshot_screen(screen),
        "changeSummary": summary,
        "changedBy": str(requested_by or "portal").strip() or "portal",
        "changedByAi": True,
        "createdAt": _now_iso(),
        "basedOnVersionId": str((screen.get("versions") or [{}])[-1].get("versionId") or ""),
    }


def _find_component_index(components: list[Any], component_id: str) -> int:
    for index, item in enumerate(components):
        if isinstance(item, dict) and str(item.get("id") or "") == component_id:
            return index
    return -1


def _map_provider_error(exc: ProviderError) -> ValueError:
    message = _extract_exception_message(exc)
    if "No active model configured" in message:
        return ValueError(AI_BIG_SCREEN_CONFIGURE_LLM_MESSAGE)
    return ValueError(f"默认大模型不可用：{message}")


async def _consume_model_response(model: Any, messages: list[dict[str, str]]) -> str:
    response = await model(messages)
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            text = _extract_model_text(chunk)
            if text:
                accumulated = text
        return accumulated
    return _extract_model_text(response)


def _extract_model_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "\n".join(filter(None, (_extract_model_text(item) for item in payload)))
    if isinstance(payload, dict):
        for key in ("text", "content", "response", "message"):
            value = payload.get(key)
            if value:
                return _extract_model_text(value)
        return ""

    text = getattr(payload, "text", None)
    if text:
        return _extract_model_text(text)
    content = getattr(payload, "content", None)
    if content:
        return _extract_model_text(content)
    message = getattr(payload, "message", None)
    if message:
        return _extract_model_text(message)
    return str(payload)


def _extract_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _parse_llm_json_payload(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    candidate = fenced_match.group(1) if fenced_match else text
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_patch_plan(
    plan: Mapping[str, Any],
    *,
    screen: Mapping[str, Any],
    selected_component_id: str,
) -> dict[str, Any]:
    allowed_component_ids = {
        str(item.get("id") or "")
        for item in screen.get("components", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    operations: list[dict[str, Any]] = []
    raw_operations = plan.get("operations")
    for raw_operation in raw_operations if isinstance(raw_operations, list) else []:
        if not isinstance(raw_operation, dict):
            continue
        operation_type = str(raw_operation.get("type") or "").strip()
        normalized = _normalize_patch_operation(
            operation_type=operation_type,
            operation=raw_operation,
            allowed_component_ids=allowed_component_ids,
            selected_component_id=selected_component_id,
        )
        if normalized:
            operations.append(normalized)
    return {
        "summary": str(plan.get("summary") or "").strip(),
        "operations": operations,
    }


def _normalize_patch_operation(
    *,
    operation_type: str,
    operation: Mapping[str, Any],
    allowed_component_ids: set[str],
    selected_component_id: str,
) -> dict[str, Any]:
    if operation_type == "setThemePalette":
        palette = _normalize_palette(operation.get("palette"))
        return {"type": operation_type, "palette": palette} if palette else {}

    component_ids = _normalize_component_ids(
        operation.get("componentIds"),
        allowed_component_ids=allowed_component_ids,
        selected_component_id=selected_component_id,
    )
    if operation_type == "setComponentPalette":
        palette = _normalize_palette(operation.get("palette"))
        if not palette or not component_ids:
            return {}
        emphasis = str(operation.get("emphasis") or "").strip()
        return {
            "type": operation_type,
            "componentIds": component_ids,
            "palette": palette,
            "emphasis": emphasis if emphasis in {"standard", "strong"} else "",
        }
    if operation_type == "setComponentType":
        component_type = str(operation.get("componentType") or "").strip()
        if component_type not in _ALLOWED_COMPONENT_TYPES or not component_ids:
            return {}
        return {
            "type": operation_type,
            "componentIds": component_ids,
            "componentType": component_type,
        }
    if operation_type == "setComponentTitle":
        title = str(operation.get("title") or "").strip()
        if not title or not component_ids:
            return {}
        return {"type": operation_type, "componentIds": component_ids[:1], "title": title[:80]}
    if operation_type == "setComponentQueryParams":
        query_params = operation.get("queryParams")
        if not isinstance(query_params, dict) or not component_ids:
            return {}
        return {
            "type": operation_type,
            "componentIds": component_ids,
            "queryParams": copy.deepcopy(query_params),
        }
    return {}


def _normalize_component_ids(
    raw_component_ids: Any,
    *,
    allowed_component_ids: set[str],
    selected_component_id: str,
) -> list[str]:
    if raw_component_ids == "*":
        return sorted(allowed_component_ids)
    if isinstance(raw_component_ids, str):
        values = [raw_component_ids]
    elif isinstance(raw_component_ids, list):
        values = [str(item) for item in raw_component_ids]
    else:
        values = [selected_component_id] if selected_component_id else []
    return [
        item
        for item in values
        if item in allowed_component_ids
    ]


def _normalize_palette(value: Any) -> str:
    palette = str(value or "").strip()
    return palette if palette in _ALLOWED_PALETTES else ""


def _apply_patch_plan(*, screen: dict[str, Any], plan: Mapping[str, Any]) -> str:
    components = screen.get("components")
    if not isinstance(components, list):
        return ""

    for operation in plan.get("operations", []) if isinstance(plan.get("operations"), list) else []:
        if not isinstance(operation, dict):
            continue
        operation_type = operation.get("type")
        if operation_type == "setThemePalette":
            theme = screen.get("theme")
            screen["theme"] = dict(theme) if isinstance(theme, dict) else {}
            screen["theme"]["palette"] = operation.get("palette")
            continue

        component_ids = operation.get("componentIds")
        target_ids = component_ids if isinstance(component_ids, list) else []
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                continue
            if str(component.get("id") or "") not in target_ids:
                continue
            components[index] = _apply_component_operation(component, operation)

    screen["components"] = components
    return str(plan.get("summary") or "").strip()


def _apply_component_operation(
    component: Mapping[str, Any],
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    next_component = dict(component)
    operation_type = operation.get("type")
    if operation_type == "setComponentPalette":
        visual_config = _component_visual_config(next_component)
        visual_config["palette"] = operation.get("palette")
        emphasis = str(operation.get("emphasis") or "").strip()
        if emphasis:
            visual_config["emphasis"] = emphasis
        next_component["visualConfig"] = visual_config
    elif operation_type == "setComponentType":
        component_type = str(operation.get("componentType") or "").strip()
        if component_type in _ALLOWED_COMPONENT_TYPES:
            next_component["type"] = component_type
    elif operation_type == "setComponentTitle":
        title = str(operation.get("title") or "").strip()
        if title:
            next_component["title"] = title
    elif operation_type == "setComponentQueryParams":
        query_params = _component_query_params(next_component)
        patch_params = operation.get("queryParams")
        if isinstance(patch_params, dict):
            query_params.update(copy.deepcopy(patch_params))
            next_component["queryParams"] = query_params
    return next_component


def _component_visual_config(component: Mapping[str, Any]) -> dict[str, Any]:
    visual_config = component.get("visualConfig")
    return dict(visual_config) if isinstance(visual_config, dict) else {}


def _component_query_params(component: Mapping[str, Any]) -> dict[str, Any]:
    query_params = component.get("queryParams")
    return dict(query_params) if isinstance(query_params, dict) else {}


def _validate_screen(screen: Mapping[str, Any]) -> None:
    if not str(screen.get("id") or "").strip():
        raise ValueError("screen.id 不能为空")
    if not str(screen.get("name") or "").strip():
        raise ValueError("screen.name 不能为空")
    components = screen.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("screen.components 不能为空")
