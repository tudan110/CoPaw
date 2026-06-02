from __future__ import annotations

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


BUILTIN_PLUGINS: list[dict[str, Any]] = [
    {
        "id": "alarm-overview",
        "name": "今日告警总览",
        "domain": "alarm",
        "description": "统计今日活跃告警、严重告警和处置趋势。",
        "inputSchema": {"timeRange": "today"},
        "outputSchema": {"value": "number", "unit": "起", "trend": "string"},
        "supportedVisuals": ["metric-card"],
        "permissionScope": "alarm:read",
        "cachePolicy": {"ttlSeconds": 60},
        "refreshPolicy": {"intervalSeconds": 60},
        "dataSource": "builtin-sample",
        "sampleData": {"value": 128, "unit": "起", "trend": "较昨日 -12%"},
        "examplePrompts": ["今日告警总览", "领导驾驶舱告警数量"],
    },
    {
        "id": "alarm-trend",
        "name": "P1/P2 告警趋势",
        "domain": "alarm",
        "description": "按时间展示高优先级告警趋势。",
        "inputSchema": {"timeRange": "last_7_days"},
        "outputSchema": {"categories": "string[]", "series": "number[]"},
        "supportedVisuals": ["line-chart", "bar-chart"],
        "permissionScope": "alarm:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "builtin-sample",
        "sampleData": {
            "categories": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
            "series": [18, 22, 16, 28, 24, 14, 12],
        },
        "examplePrompts": ["最近 7 天告警趋势", "P1/P2 告警曲线"],
    },
    {
        "id": "workorder-risk",
        "name": "待处理工单风险",
        "domain": "workorder",
        "description": "展示待处理工单和超时风险。",
        "inputSchema": {"status": "pending"},
        "outputSchema": {"rows": "array"},
        "supportedVisuals": ["table", "bar-chart", "metric-card"],
        "permissionScope": "workorder:read",
        "cachePolicy": {"ttlSeconds": 180},
        "refreshPolicy": {"intervalSeconds": 180},
        "dataSource": "builtin-sample",
        "sampleData": {
            "rows": [
                {"name": "数据库连接异常", "count": 12, "risk": "高"},
                {"name": "接口超时", "count": 9, "risk": "中"},
                {"name": "磁盘容量预警", "count": 7, "risk": "中"},
            ],
        },
        "examplePrompts": ["待处理工单", "工单超时风险"],
    },
    {
        "id": "resource-utilization",
        "name": "资源利用率 TopN",
        "domain": "resource",
        "description": "展示 CPU、内存、存储等资源利用率 TopN。",
        "inputSchema": {"resourceType": "host", "metric": "cpu"},
        "outputSchema": {"categories": "string[]", "series": "number[]"},
        "supportedVisuals": ["bar-chart", "table"],
        "permissionScope": "resource:read",
        "cachePolicy": {"ttlSeconds": 180},
        "refreshPolicy": {"intervalSeconds": 180},
        "dataSource": "builtin-sample",
        "sampleData": {
            "categories": ["核心库主机", "订单服务", "网关节点", "监控节点", "批处理集群"],
            "series": [91, 86, 78, 73, 69],
        },
        "examplePrompts": ["资源利用率", "容量风险 TopN"],
    },
    {
        "id": "system-health",
        "name": "重点系统健康度",
        "domain": "health",
        "description": "展示重点业务系统健康率和风险状态。",
        "inputSchema": {"scope": "key_systems"},
        "outputSchema": {"value": "number", "unit": "%", "trend": "string"},
        "supportedVisuals": ["metric-card", "bar-chart"],
        "permissionScope": "resource:read",
        "cachePolicy": {"ttlSeconds": 180},
        "refreshPolicy": {"intervalSeconds": 180},
        "dataSource": "builtin-sample",
        "sampleData": {"value": 96, "unit": "%", "trend": "稳定"},
        "examplePrompts": ["重点系统健康度", "业务健康率"],
    },
    {
        "id": "topology-impact",
        "name": "拓扑影响范围",
        "domain": "topology",
        "description": "展示当前风险对象的上下游影响范围。",
        "inputSchema": {"scope": "active_risk"},
        "outputSchema": {"nodes": "array"},
        "supportedVisuals": ["topology"],
        "permissionScope": "topology:read",
        "cachePolicy": {"ttlSeconds": 300},
        "refreshPolicy": {"intervalSeconds": 300},
        "dataSource": "builtin-sample",
        "sampleData": {
            "nodes": [
                {"name": "核心交易", "status": "warning"},
                {"name": "网关集群", "status": "normal"},
                {"name": "数据库主库", "status": "critical"},
            ],
        },
        "examplePrompts": ["拓扑影响范围", "风险影响链路"],
    },
]


def list_builtin_plugins() -> list[dict[str, Any]]:
    return [copy.deepcopy(item) for item in BUILTIN_PLUGINS]


def build_screen_draft(request: AiBigScreenDraftRequest) -> dict[str, Any]:
    prompt = str(request.prompt or "").strip()
    if not prompt:
        raise ValueError("prompt 不能为空")

    screen_id = f"screen-{uuid.uuid4().hex[:10]}"
    title = str(request.title or "").strip() or "AI 运维驾驶舱"
    now = _now_iso()
    components = _build_components(prompt)
    data_bindings = [_build_binding(component) for component in components]
    screen = {
        "schemaVersion": SCREEN_SCHEMA_VERSION,
        "id": screen_id,
        "name": title,
        "description": f"由自然语言生成：{prompt}",
        "owner": str(request.requestedBy or "portal").strip() or "portal",
        "status": "draft",
        "layout": {"type": "grid", "columns": 12, "rowHeight": 84},
        "theme": {
            "mode": "dark",
            "palette": "professional",
            "density": "dashboard",
        },
        "components": components,
        "dataBindings": data_bindings,
        "permissions": {"visibility": "private", "roles": []},
        "versions": [],
        "publishTargets": [],
        "aiConversationContext": {
            "sourcePrompt": prompt,
            "lastInstruction": "",
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
    "未配置默认大模型，请先到“模型配置”里设置默认 LLM 后再修改 AI 大屏。"
)

_ALLOWED_PALETTES = {"professional", "warm", "cool", "executive"}
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


def _build_components(prompt: str) -> list[dict[str, Any]]:
    selected_plugins = _select_plugins(prompt)
    components: list[dict[str, Any]] = []
    positions = [
        {"x": 0, "y": 0, "w": 3, "h": 2},
        {"x": 3, "y": 0, "w": 5, "h": 3},
        {"x": 8, "y": 0, "w": 4, "h": 3},
        {"x": 0, "y": 3, "w": 4, "h": 3},
        {"x": 4, "y": 3, "w": 4, "h": 3},
        {"x": 8, "y": 3, "w": 4, "h": 3},
    ]
    type_by_plugin = {
        "alarm-overview": "metric-card",
        "alarm-trend": "line-chart",
        "workorder-risk": "table",
        "resource-utilization": "bar-chart",
        "system-health": "metric-card",
        "topology-impact": "topology",
    }
    for index, plugin in enumerate(selected_plugins):
        plugin_id = str(plugin["id"])
        sample_data = copy.deepcopy(plugin.get("sampleData") or {})
        components.append(
            {
                "id": f"component-{index + 1}-{uuid.uuid4().hex[:6]}",
                "type": type_by_plugin.get(plugin_id, "metric-card"),
                "title": str(plugin["name"]),
                "description": str(plugin.get("description") or ""),
                "layoutPosition": positions[index % len(positions)],
                "pluginId": plugin_id,
                "queryParams": copy.deepcopy(plugin.get("inputSchema") or {}),
                "visualConfig": {"palette": "professional", "emphasis": "standard"},
                "refreshInterval": int(
                    (plugin.get("refreshPolicy") or {}).get("intervalSeconds") or 180,
                ),
                "interactions": {"selectable": True},
                "data": sample_data,
            },
        )
    return components


def _select_plugins(prompt: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    normalized = prompt.lower()
    keywords = {
        "alarm-overview": ("告警", "报警", "alarm"),
        "alarm-trend": ("趋势", "p1", "p2", "7 天", "7天"),
        "workorder-risk": ("工单", "超时", "待处理"),
        "resource-utilization": ("资源", "容量", "cpu", "内存", "利用率"),
        "system-health": ("健康", "系统", "业务"),
        "topology-impact": ("拓扑", "影响", "链路"),
    }
    by_id = {str(item["id"]): item for item in BUILTIN_PLUGINS}
    for plugin_id, terms in keywords.items():
        if any(term in prompt or term in normalized for term in terms):
            selected.append(copy.deepcopy(by_id[plugin_id]))
    for fallback_id in (
        "alarm-overview",
        "alarm-trend",
        "workorder-risk",
        "resource-utilization",
    ):
        if len(selected) >= 4:
            break
        if not any(item["id"] == fallback_id for item in selected):
            selected.append(copy.deepcopy(by_id[fallback_id]))
    return selected


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
    for plugin in BUILTIN_PLUGINS:
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
