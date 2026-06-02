from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Mapping

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


def patch_screen_asset(
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
    if selected_index < 0:
        raise ValueError(f"未找到组件：{selected_component_id}")

    component = dict(components[selected_index])
    visual_config = (
        dict(component.get("visualConfig"))
        if isinstance(component.get("visualConfig"), dict)
        else {}
    )
    query_params = (
        dict(component.get("queryParams"))
        if isinstance(component.get("queryParams"), dict)
        else {}
    )
    changes: list[str] = []

    if "暖色" in instruction or "暖一点" in instruction or "暖" in instruction:
        visual_config["palette"] = "warm"
        changes.append("颜色调整为暖色")
    if "冷色" in instruction:
        visual_config["palette"] = "cool"
        changes.append("颜色调整为冷色")
    if "柱状" in instruction and component.get("type") in {"line-chart", "bar-chart"}:
        component["type"] = "bar-chart"
        changes.append("图表类型调整为柱状图")
    if "折线" in instruction and component.get("type") in {"line-chart", "bar-chart"}:
        component["type"] = "line-chart"
        changes.append("图表类型调整为折线图")
    if "最近 7 天" in instruction or "近7天" in instruction or "7天" in instruction:
        query_params["timeRange"] = "last_7_days"
        changes.append("时间范围调整为最近 7 天")

    next_title = _extract_title_instruction(instruction)
    if next_title:
        component["title"] = next_title
        changes.append(f"标题改为{next_title}")

    component["visualConfig"] = visual_config
    component["queryParams"] = query_params
    components[selected_index] = component
    screen["components"] = components
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
    summary = "；".join(changes) if changes else "记录自然语言修改请求，配置保持不变"
    version = _build_version(
        screen=screen,
        version_id=version_id,
        summary=summary,
        requested_by=request.requestedBy,
    )
    screen["versions"] = [*(screen.get("versions") or []), version]
    saved = registry.save_screen(screen=screen, requested_by=request.requestedBy)
    return {"screen": saved, "version": version, "summary": summary}


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


def _extract_title_instruction(instruction: str) -> str:
    match = re.search(r"标题(?:改成|改为|换成)\s*([^，,。；;]+)", instruction)
    if not match:
        return ""
    return match.group(1).strip().strip("\"'")


def _validate_screen(screen: Mapping[str, Any]) -> None:
    if not str(screen.get("id") or "").strip():
        raise ValueError("screen.id 不能为空")
    if not str(screen.get("name") or "").strip():
        raise ValueError("screen.name 不能为空")
    components = screen.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("screen.components 不能为空")
