from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Mapping

from qwenpaw.exceptions import ProviderError
from qwenpaw.extensions import ai_big_screen_registry as registry
from qwenpaw.extensions.api.ai_big_screen_models import (
    AiBigScreenDraftRequest,
    AiBigScreenPatchRequest,
)

SCREEN_SCHEMA_VERSION = 1

_CAPABILITY_FIELD_DEFINITIONS: dict[str, list[dict[str, Any]]] = {
    "system-logs": [
        {"key": "time", "label": "时间", "aliases": ["日志时间", "发生时间"]},
        {"key": "level", "label": "级别", "aliases": ["日志级别"]},
        {"key": "host", "label": "主机", "aliases": ["机器", "节点"]},
        {"key": "service", "label": "服务", "aliases": ["应用", "系统"]},
        {"key": "message", "label": "日志内容", "aliases": ["内容", "消息"]},
    ],
    "real-alarms": [
        {"key": "eventTime", "label": "时间", "aliases": ["告警时间", "发生时间"]},
        {"key": "level", "label": "级别", "aliases": ["告警级别", "严重级别"]},
        {"key": "title", "label": "告警", "aliases": ["告警标题", "标题"]},
        {"key": "deviceName", "label": "资源", "aliases": ["设备", "对象"]},
        {"key": "manageIp", "label": "IP", "aliases": ["管理IP", "资源IP"]},
    ],
    "cmdb-resources": [
        {"key": "name", "label": "指标", "aliases": ["名称", "资源指标"]},
        {"key": "value", "label": "值", "aliases": ["数量", "指标值"]},
    ],
    "workorders": [
        {"key": "workorderNo", "label": "工单号", "aliases": ["工单编号", "编号"]},
        {"key": "title", "label": "标题", "aliases": ["工单标题", "名称"]},
        {"key": "status", "label": "状态", "aliases": ["工单状态", "处理状态"]},
        {"key": "severity", "label": "级别", "aliases": ["优先级", "严重级别"]},
        {"key": "eventTime", "label": "时间", "aliases": ["创建时间", "接收时间"]},
        {"key": "starter", "label": "流程发起人", "aliases": ["发起人", "startUserName"]},
        {"key": "taskName", "label": "任务节点", "aliases": ["当前节点", "流程节点"]},
        {"key": "processName", "label": "流程名称", "aliases": ["工单流程名称"]},
        {"key": "taskId", "label": "任务编号", "aliases": ["任务ID"]},
        {"key": "procInsId", "label": "流程实例", "aliases": ["流程实例ID"]},
    ],
}

_DEFAULT_CAPABILITY_FIELDS: dict[str, list[str]] = {
    "system-logs": ["time", "level", "host", "service", "message"],
    "real-alarms": ["eventTime", "level", "title", "deviceName", "manageIp"],
    "cmdb-resources": ["name", "value"],
    "workorders": ["workorderNo", "title", "status", "severity", "eventTime"],
}


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
        "description": (
            "查询智观日志服务接入的业务/应用/系统日志，默认最近 15 分钟；"
            "不是 QwenPaw 智能体运行日志、控制台输出、本机 /var/log 或会话历史。"
        ),
        "inputSchema": {
            "lookbackMinutes": 15,
            "limit": 50,
            "query": "",
            "analysisMode": "",
            "riskKeywords": [],
            "fromTime": "",
            "toTime": "",
            "timeMode": "relative",
            "searchStrategy": "single_window",
            "maxLookbackDays": 45,
            "fields": _DEFAULT_CAPABILITY_FIELDS["system-logs"],
        },
        "outputSchema": {"columns": "array", "rows": "array", "sourceStatus": "string"},
        "availableFields": _CAPABILITY_FIELD_DEFINITIONS["system-logs"],
        "supportedVisuals": ["table", "text", "risk-pulse", "status-stream"],
        "permissionScope": "nightingale-log:read",
        "cachePolicy": {"ttlSeconds": 30},
        "refreshPolicy": {"intervalSeconds": 30},
        "dataSource": "zhiguan-log-service",
        "skillName": "nightingale-log",
        "examplePrompts": ["最近15分钟系统日志", "看一下智观日志", "最近业务日志"],
    },
    {
        "id": "real-alarms",
        "name": "系统告警",
        "domain": "alarm",
        "description": "调用资源告警接口读取指定时间窗口内的活动告警。",
        "inputSchema": {
            "limit": 100,
            "alarmStatus": "",
            "fields": _DEFAULT_CAPABILITY_FIELDS["real-alarms"],
        },
        "outputSchema": {"columns": "array", "rows": "array", "total": "number"},
        "availableFields": _CAPABILITY_FIELD_DEFINITIONS["real-alarms"],
        "supportedVisuals": ["table", "metric-card", "bar-chart", "status-stream", "risk-pulse"],
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
        "inputSchema": {"scope": "all", "fields": _DEFAULT_CAPABILITY_FIELDS["cmdb-resources"]},
        "outputSchema": {"value": "number", "unit": "string", "rows": "array"},
        "availableFields": _CAPABILITY_FIELD_DEFINITIONS["cmdb-resources"],
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
        "description": (
            "调用 order-workflow 传统工单系统能力读取今日工单统计和待办工单；"
            "不使用告警 mock 数据伪装工单。"
        ),
        "inputSchema": {
            "timeRange": "today",
            "limit": 20,
            "fields": _DEFAULT_CAPABILITY_FIELDS["workorders"],
        },
        "outputSchema": {"columns": "array", "rows": "array", "total": "number"},
        "availableFields": _CAPABILITY_FIELD_DEFINITIONS["workorders"],
        "supportedVisuals": ["table", "metric-card", "bar-chart", "status-stream"],
        "permissionScope": "workorder:read",
        "cachePolicy": {"ttlSeconds": 120},
        "refreshPolicy": {"intervalSeconds": 120},
        "dataSource": "portal-order-workflow-api",
        "skillName": "order-workflow",
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
    {
        "id": "capability-gap",
        "name": "待接入数据能力",
        "domain": "planning",
        "description": (
            "当用户提出的数据对象无法由已接入 skill/API 真实查询时使用。"
            "只输出取数方案、所需接口和接入建议，不展示编造业务数据。"
        ),
        "inputSchema": {
            "requestedData": "",
            "reason": "",
            "suggestedSkillName": "",
            "suggestedApi": "",
            "requiredInputs": [],
            "validationPlan": "",
        },
        "outputSchema": {"columns": "array", "rows": "array", "sourceStatus": "string"},
        "supportedVisuals": ["table", "text"],
        "permissionScope": "capability-plan:read",
        "cachePolicy": {"ttlSeconds": 0},
        "refreshPolicy": {"intervalSeconds": 0},
        "dataSource": "ai-capability-planning",
        "skillName": "",
        "examplePrompts": ["需要还没接入的数据", "帮我设计新的取数逻辑"],
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
    components = await _hydrate_components_with_data(plan["components"], instruction=prompt)
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
            "capabilityGaps": _extract_capability_gaps(components),
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


def delete_screen_asset(*, screen_id: str) -> dict[str, Any]:
    deleted = registry.delete_screen(screen_id=screen_id)
    return {
        "screenId": str(deleted.get("id") or screen_id),
        "deleted": True,
    }


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
_ALLOWED_COMPONENT_TYPES = {
    "metric-card",
    "line-chart",
    "bar-chart",
    "table",
    "topology",
    "text",
    "risk-pulse",
    "status-stream",
}
_ALLOWED_VISUAL_SPEC_KINDS = {
    "risk-field",
    "signal-stream",
    "timeline",
    "heatmap-matrix",
    "metric-cluster",
}
_ALLOWED_VISUAL_SPEC_MOTIONS = {"none", "pulse", "scan", "flow", "stagger"}
_ALLOWED_VISUAL_SPEC_DENSITIES = {"compact", "balanced", "showcase"}
_ALLOWED_VISUAL_SPEC_BINDINGS = {
    "time",
    "title",
    "message",
    "severity",
    "status",
    "value",
    "group",
    "riskScore",
    "riskLevel",
}
_ALLOWED_VISUAL_SPEC_LAYER_TYPES = {"score", "list", "stream", "timeline", "matrix", "metrics"}
_ALLOWED_VISUAL_SPEC_SOURCES = {"rows", "riskItems", "series", "categories"}
_ALLOWED_VISUAL_SPEC_OPERATORS = {">", ">=", "<", "<=", "=", "contains"}
_ALLOWED_VISUAL_SPEC_TONES = {"critical", "high", "medium", "normal", "cool", "warm"}
_DATA_PLANNER_MAX_ATTEMPTS = 3


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
    summary = await _apply_patch_plan(screen=screen, plan=plan, instruction=instruction)
    next_components = screen.get("components")
    if isinstance(next_components, list):
        screen["dataBindings"] = _rebuild_data_bindings(
            components=next_components,
            previous_bindings=screen.get("dataBindings"),
        )

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
            "visualSpec": copy.deepcopy(item.get("visualSpec") or {}),
            "layoutPosition": copy.deepcopy(item.get("layoutPosition") or {}),
            "queryParams": copy.deepcopy(item.get("queryParams") or {}),
            "currentFields": _component_current_fields(item),
            "availableFields": copy.deepcopy(
                _CAPABILITY_FIELD_DEFINITIONS.get(
                    str(item.get("pluginId") or item.get("capabilityId") or ""),
                    [],
                ),
            ),
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
                "addComponent、setThemePalette、setComponentPalette、setComponentType、setComponentLayout、"
                "setComponentTitle、setComponentQueryParams、setComponentFields。"
                "palette 只能是 professional、warm、cool、executive；"
                "component type 只能是 metric-card、line-chart、bar-chart、table、topology、text、risk-pulse、status-stream。"
                "如果用户要求在现有大屏基础上新增、加入、追加一个模块，"
                "使用 addComponent，component 必须包含 title, description, capabilityId, visualType, queryParams, layoutPosition。"
                "如果用户要求分析系统日志高危/风险/危险情况并动态突出，"
                "新增或修改系统日志组件时优先使用 visualType=risk-pulse，queryParams.analysisMode=risk_summary。"
                "可以输出 visualSpec 描述安全视觉规格，但只能使用字段："
                "kind, motion, density, bindings, highlightRules, layers；"
                "kind 只能是 risk-field、signal-stream、timeline、heatmap-matrix、metric-cluster。"
                "visualSpec 只能描述数据绑定、动效、高亮和层次，不允许输出 HTML、CSS、JS、URL 或代码。"
                "如果用户要求组件对齐、平齐、调整宽度、高度、尺寸、长度或位置，"
                "使用 setComponentLayout，layoutPosition 只能包含 12 列网格中的 x,y,w,h 数字。"
                "componentIds 必须来自用户给定组件清单；如果用户在说整个大屏，"
                "可以对多个 componentIds 生效。"
                "如果用户要求增加、删除、显示、隐藏或返回某个表格字段，"
                "使用 setComponentFields，字段名必须来自对应组件 availableFields 的 key；"
                "mode 只能是 add、replace、remove。"
                "如果用户对系统日志组件要求查询最后一次有数据、最近有日志、空结果后继续找历史日志，"
                "使用 setComponentQueryParams 设置 searchStrategy=latest_non_empty、"
                "timeMode=latest_non_empty、maxLookbackDays=45。"
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
    return _normalize_patch_plan(
        parsed,
        screen=screen,
        selected_component_id=selected_component_id,
        instruction=instruction,
    )


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
            "skillName": str(item.get("skillName") or ""),
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
                "如果用户需要的数据没有可真实查询的已接入能力，必须使用 capability-gap，"
                "在 queryParams 中写明 requestedData、reason、suggestedSkillName、suggestedApi、requiredInputs、validationPlan，"
                "不得用已有能力或样例数据伪装。"
                "只输出严格 JSON，不要输出 Markdown、解释或代码块。"
                "JSON 字段固定为：name, description, theme, layout, components, summary。"
                "theme.palette 只能是 professional、industrial、aurora、mono、warm、cool、executive。"
                "components 是数组；每项必须包含 title, description, capabilityId, visualType, queryParams, layoutPosition。"
                "capabilityId 必须来自 dataCapabilities；visualType 必须是 metric-card、line-chart、bar-chart、table、topology、text、risk-pulse、status-stream。"
                "如果用户要求分析系统日志高危/风险/危险情况并动态突出，"
                "系统日志组件优先使用 visualType=risk-pulse，queryParams.analysisMode=risk_summary。"
                "components 每项可以包含 visualSpec 安全视觉规格；"
                "visualSpec.kind 只能是 risk-field、signal-stream、timeline、heatmap-matrix、metric-cluster，"
                "motion 只能是 none、pulse、scan、flow、stagger；"
                "bindings 用于声明 time/title/message/severity/status/value/group 等字段如何绑定数据，"
                "highlightRules 用于声明条件高亮，layers 用于声明 score/list/stream/timeline/matrix/metrics 等层。"
                "不要输出 HTML、CSS、JS、URL 或代码。"
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
                                "description": "最近 15 分钟智观日志服务接入的业务/应用/系统日志。",
                                "capabilityId": "system-logs",
                                "visualType": "table",
                                "queryParams": {"lookbackMinutes": 15, "limit": 50, "query": ""},
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
            prompt=prompt,
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
        normalized_components = [
            _build_capability_gap_component(
                index=0,
                requested_data=prompt,
                reason="未匹配到可真实查询的已接入数据能力",
                query_params={},
            ),
        ]

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
    prompt: str = "",
) -> dict[str, Any]:
    raw_capability_id = str(
        component.get("capabilityId")
        or component.get("pluginId")
        or component.get("dataCapabilityId")
        or "",
    ).strip()
    capability_id = _resolve_component_capability_id(
        raw_capability_id=raw_capability_id,
        component=component,
    )
    capability = _plugin_by_id(capability_id)
    if not capability:
        return _build_capability_gap_component(
            index=index,
            requested_data=(
                str(component.get("title") or "").strip()
                or str(component.get("description") or "").strip()
                or capability_id
            ),
            reason=f"默认大模型返回了未接入的数据能力：{capability_id}",
            query_params={
                "suggestedCapabilityId": capability_id,
                "originalCapabilityId": raw_capability_id,
                "originalQueryParams": copy.deepcopy(component.get("queryParams") or {}),
            },
            layout_position=component.get("layoutPosition"),
            visual_config=component.get("visualConfig"),
        )

    supported_visuals = [
        str(item)
        for item in capability.get("supportedVisuals", [])
        if str(item) in _ALLOWED_COMPONENT_TYPES
    ]
    requested_type = str(component.get("visualType") or component.get("type") or "").strip()
    component_type = requested_type if requested_type in supported_visuals else ""
    if not component_type:
        component_type = supported_visuals[0] if supported_visuals else "table"
    if (
        capability_id == "workorders"
        and component_type == "status-stream"
        and not _text_requests_workorder_stream_visual(prompt)
    ):
        component_type = "table"

    query_params = _normalize_query_params(
        component.get("queryParams"),
        capability=capability,
        inferred_lookback_minutes=inferred_lookback_minutes,
        prompt=prompt,
        component=component,
    )
    visual_config = _normalize_visual_config(component.get("visualConfig"))
    visual_spec = _normalize_visual_spec(component.get("visualSpec"))
    if capability_id == "system-logs" and _component_requests_log_risk_analysis(
        prompt=prompt,
        component=component,
    ):
        component_type = "risk-pulse"
        query_params["analysisMode"] = "risk_summary"
        query_params.setdefault("limit", 100)
        visual_config["palette"] = "warm"
        visual_config["emphasis"] = "strong"
        if not visual_spec:
            visual_spec = _default_log_risk_visual_spec()
    elif capability_id == "real-alarms" and component_type == "status-stream":
        if not visual_spec:
            visual_spec = _default_status_stream_visual_spec()
    component_payload = {
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
        "visualConfig": visual_config,
        "refreshInterval": int((capability.get("refreshPolicy") or {}).get("intervalSeconds") or 120),
        "interactions": {"selectable": True, "selectionMode": "region"},
        "data": {},
    }
    if visual_spec:
        component_payload["visualSpec"] = visual_spec
    return component_payload


def _resolve_component_capability_id(
    *,
    raw_capability_id: str,
    component: Mapping[str, Any],
) -> str:
    if raw_capability_id and not _plugin_by_id(raw_capability_id):
        return raw_capability_id
    inferred_capability_id = _infer_component_capability_id(component)
    if inferred_capability_id:
        return inferred_capability_id
    return raw_capability_id


def _infer_component_capability_id(component: Mapping[str, Any]) -> str:
    text = " ".join(
        str(component.get(key) or "")
        for key in ("title", "description", "name", "summary")
    ).strip()
    if not text:
        return ""
    lowered = text.lower()
    scores: dict[str, int] = {}

    if any(term in text for term in ("工单", "待办", "待处理", "流程", "派单", "处置单")) or any(
        term in lowered for term in ("workorder", "work order", "ticket", "tickets")
    ):
        scores["workorders"] = 10
    if any(term in text for term in ("日志", "智观日志")) or any(
        term in lowered for term in ("log", "logs")
    ):
        scores["system-logs"] = 8
    if any(term in text for term in ("告警", "报警")) or any(
        term in lowered for term in ("alarm", "alarms")
    ):
        scores["real-alarms"] = 7
    if any(term in text for term in ("CMDB", "资源", "资产")) or any(
        term in lowered for term in ("cmdb", "resource", "asset")
    ):
        scores["cmdb-resources"] = 6
    if any(term in text for term in ("拓扑", "链路", "影响范围")) or "topology" in lowered:
        scores["topology-impact"] = 6

    if not scores:
        return ""
    return max(scores.items(), key=lambda item: item[1])[0]


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


def _normalize_visual_spec(raw_visual_spec: Any) -> dict[str, Any]:
    if not isinstance(raw_visual_spec, dict):
        return {}
    kind = str(raw_visual_spec.get("kind") or "").strip()
    if kind not in _ALLOWED_VISUAL_SPEC_KINDS:
        return {}
    motion = str(raw_visual_spec.get("motion") or "none").strip()
    density = str(raw_visual_spec.get("density") or "balanced").strip()
    visual_spec: dict[str, Any] = {
        "kind": kind,
        "motion": motion if motion in _ALLOWED_VISUAL_SPEC_MOTIONS else "none",
        "density": density if density in _ALLOWED_VISUAL_SPEC_DENSITIES else "balanced",
    }
    bindings = _normalize_visual_spec_bindings(raw_visual_spec.get("bindings"))
    if bindings:
        visual_spec["bindings"] = bindings
    highlight_rules = _normalize_visual_spec_highlight_rules(raw_visual_spec.get("highlightRules"))
    if highlight_rules:
        visual_spec["highlightRules"] = highlight_rules
    layers = _normalize_visual_spec_layers(raw_visual_spec.get("layers"))
    if layers:
        visual_spec["layers"] = layers
    return visual_spec


def _normalize_visual_spec_bindings(raw_bindings: Any) -> dict[str, str]:
    if not isinstance(raw_bindings, dict):
        return {}
    bindings: dict[str, str] = {}
    for key, value in raw_bindings.items():
        normalized_key = str(key or "").strip()
        if normalized_key not in _ALLOWED_VISUAL_SPEC_BINDINGS:
            continue
        field = _safe_visual_spec_token(value, max_length=80)
        if field:
            bindings[normalized_key] = field
    return bindings


def _normalize_visual_spec_highlight_rules(raw_rules: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rules, list):
        return []
    rules: list[dict[str, Any]] = []
    for raw_rule in raw_rules[:8]:
        if not isinstance(raw_rule, dict):
            continue
        field = _safe_visual_spec_token(raw_rule.get("field"), max_length=80)
        operator = str(raw_rule.get("operator") or "").strip()
        tone = str(raw_rule.get("tone") or "").strip()
        if not field or operator not in _ALLOWED_VISUAL_SPEC_OPERATORS or tone not in _ALLOWED_VISUAL_SPEC_TONES:
            continue
        value = raw_rule.get("value")
        if isinstance(value, (int, float)):
            safe_value: Any = value
        else:
            safe_value = _safe_visual_spec_token(value, max_length=80)
        if safe_value == "":
            continue
        rules.append({"field": field, "operator": operator, "value": safe_value, "tone": tone})
    return rules


def _normalize_visual_spec_layers(raw_layers: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_layers, list):
        return []
    layers: list[dict[str, Any]] = []
    for raw_layer in raw_layers[:6]:
        if not isinstance(raw_layer, dict):
            continue
        layer_type = str(raw_layer.get("type") or "").strip()
        source = str(raw_layer.get("source") or "rows").strip()
        if layer_type not in _ALLOWED_VISUAL_SPEC_LAYER_TYPES or source not in _ALLOWED_VISUAL_SPEC_SOURCES:
            continue
        layer = {"type": layer_type, "source": source}
        if "limit" in raw_layer:
            layer["limit"] = max(1, min(20, _safe_int(raw_layer.get("limit"), 6)))
        if "field" in raw_layer:
            field = _safe_visual_spec_token(raw_layer.get("field"), max_length=80)
            if field:
                layer["field"] = field
        layers.append(layer)
    return layers


def _safe_visual_spec_token(value: Any, *, max_length: int) -> str:
    token = str(value or "").strip()[:max_length]
    if not token:
        return ""
    lowered = token.lower()
    blocked_fragments = ("<", ">", "script", "javascript:", "data:", "onerror", "onclick", "style=", "http://", "https://")
    if any(fragment in lowered for fragment in blocked_fragments):
        return ""
    return token


def _default_log_risk_visual_spec() -> dict[str, Any]:
    return {
        "kind": "risk-field",
        "motion": "pulse",
        "density": "showcase",
        "bindings": {
            "time": "time",
            "message": "message",
            "severity": "riskLevel",
            "value": "riskScore",
            "title": "riskReason",
        },
        "highlightRules": [
            {"field": "riskScore", "operator": ">=", "value": 88, "tone": "critical"},
            {"field": "riskScore", "operator": ">=", "value": 72, "tone": "high"},
        ],
        "layers": [
            {"type": "score", "source": "rows"},
            {"type": "list", "source": "rows", "limit": 5},
        ],
    }


def _default_status_stream_visual_spec() -> dict[str, Any]:
    return {
        "kind": "signal-stream",
        "motion": "flow",
        "density": "balanced",
        "bindings": {
            "time": "eventTime",
            "title": "title",
            "severity": "level",
            "status": "status",
            "message": "visibleContent",
        },
        "highlightRules": [
            {"field": "level", "operator": "contains", "value": "critical", "tone": "critical"},
            {"field": "level", "operator": "contains", "value": "urgent", "tone": "high"},
        ],
        "layers": [
            {"type": "stream", "source": "rows", "limit": 8},
        ],
    }


def _normalize_query_params(
    raw_query_params: Any,
    *,
    capability: Mapping[str, Any],
    inferred_lookback_minutes: int,
    prompt: str = "",
    component: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    query_params = copy.deepcopy(capability.get("inputSchema") or {})
    if isinstance(raw_query_params, dict):
        query_params.update(copy.deepcopy(raw_query_params))
    capability_id = str(capability.get("id") or "")
    if capability_id == "real-alarms" and _component_requests_current_alarm(
        prompt=prompt,
        component=component or {},
    ):
        _remove_real_alarm_builtin_filters(query_params)
    if "lookbackMinutes" in query_params:
        query_params["lookbackMinutes"] = max(
            1,
            min(24 * 60, _safe_int(query_params.get("lookbackMinutes"), inferred_lookback_minutes)),
        )
    if inferred_lookback_minutes and capability_id == "system-logs":
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
                force_lookback=_capability_time_window_applies(prompt, capability_id),
            ),
        )
        present.add(capability_id)
    return next_components


def _build_capability_gap_component(
    *,
    index: int,
    requested_data: str,
    reason: str,
    query_params: Mapping[str, Any],
    layout_position: Any | None = None,
    visual_config: Any | None = None,
) -> dict[str, Any]:
    capability = _plugin_by_id("capability-gap")
    title = (requested_data or "待接入数据能力").strip()[:80]
    merged_query_params = copy.deepcopy(capability.get("inputSchema") or {})
    merged_query_params.update(copy.deepcopy(dict(query_params)))
    merged_query_params["requestedData"] = title
    merged_query_params["reason"] = reason
    if not merged_query_params.get("validationPlan"):
        merged_query_params["validationPlan"] = "接入真实接口后以 sourceStatus=live 的响应作为展示依据。"
    if not merged_query_params.get("requiredInputs"):
        merged_query_params["requiredInputs"] = ["数据源地址", "鉴权方式", "查询参数", "返回字段映射"]
    component = {
        "title": f"待接入：{title}",
        "description": f"{reason}。AI 已保留取数方案位置，接入真实能力前不展示模拟数据。",
        "capabilityId": "capability-gap",
        "visualType": "table",
        "queryParams": merged_query_params,
        "layoutPosition": layout_position or _normalize_layout_position({}, index),
        "visualConfig": visual_config or {"palette": "cool", "emphasis": "standard"},
    }
    return _normalize_plan_component(
        component,
        index=index,
        inferred_lookback_minutes=15,
    )


def _build_semantic_component(
    *,
    capability_id: str,
    index: int,
    inferred_lookback_minutes: int,
    force_lookback: bool = False,
) -> dict[str, Any]:
    capability = _plugin_by_id(capability_id)
    if not capability:
        return {}
    visual_type = (capability.get("supportedVisuals") or ["table"])[0]
    uses_time_window = capability_id == "system-logs" or (
        capability_id == "real-alarms" and force_lookback
    )
    title_prefix = f"{inferred_lookback_minutes}分钟" if inferred_lookback_minutes and uses_time_window else ""
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
    if inferred_lookback_minutes and (
        capability_id == "system-logs" or (capability_id == "real-alarms" and force_lookback)
    ):
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


def _remove_real_alarm_builtin_filters(query_params: dict[str, Any]) -> None:
    for key in (
        "lookbackMinutes",
        "fromTime",
        "toTime",
        "timeMode",
        "searchStrategy",
        "beginEventtime",
        "endEventtime",
        "alarmStatus",
        "alarmstatus",
    ):
        query_params.pop(key, None)


def _component_requests_current_alarm(
    *,
    prompt: str,
    component: Mapping[str, Any],
) -> bool:
    title = str(component.get("title") or "")
    description = str(component.get("description") or "")
    query_text = " ".join((str(prompt or ""), title, description))
    if _capability_time_window_applies(query_text, "real-alarms"):
        return False
    return _text_requests_current_alarm(query_text)


def _component_requests_log_risk_analysis(
    *,
    prompt: str,
    component: Mapping[str, Any],
) -> bool:
    title = str(component.get("title") or "")
    description = str(component.get("description") or "")
    query_text = " ".join((str(prompt or ""), title, description))
    return _text_requests_log_risk_analysis(query_text)


def _text_requests_current_alarm(text: str) -> bool:
    normalized = str(text or "")
    if not re.search(r"告警|报警|alarm|alarms", normalized, flags=re.I):
        return False
    current_terms = r"当前|目前|现在|现有|实时|活动|有哪些|共有|总数|全部|所有"
    alarm_terms = r"告警|报警|alarm|alarms"
    return bool(
        re.search(rf"(?:{current_terms}).{{0,18}}(?:{alarm_terms})", normalized, flags=re.I)
        or re.search(rf"(?:{alarm_terms}).{{0,18}}(?:{current_terms})", normalized, flags=re.I)
    )


def _text_requests_log_risk_analysis(text: str) -> bool:
    normalized = str(text or "")
    if not re.search(r"日志|log|logs", normalized, flags=re.I):
        return False
    risk_terms = (
        "高危",
        "危险",
        "风险",
        "严重",
        "异常",
        "故障",
        "错误",
        "失败",
        "超时",
        "攻击",
        "突出",
        "动态",
        "渲染",
        "critical",
        "error",
        "fatal",
        "risk",
    )
    return any(term in normalized.lower() for term in risk_terms)


def _text_requests_workorder_stream_visual(text: str) -> bool:
    normalized = str(text or "")
    lowered = normalized.lower()
    if not any(term in normalized for term in ("工单", "待办")) and not any(
        term in lowered for term in ("workorder", "ticket", "tickets")
    ):
        return False
    return any(
        term in normalized
        for term in ("流转", "动态", "时间线", "状态流", "轮播")
    ) or any(term in lowered for term in ("stream", "timeline", "dynamic"))


def _capability_time_window_applies(prompt: str, capability_id: str) -> bool:
    if capability_id == "system-logs":
        return True
    if capability_id != "real-alarms":
        return False

    text = str(prompt or "")
    time_matches = list(re.finditer(r"\d{1,4}\s*分钟|\d{1,3}\s*(?:小时|钟头)", text))
    if not time_matches:
        return False
    alarm_matches = list(re.finditer(r"告警|报警|alarm|alarms", text, flags=re.I))
    if not alarm_matches:
        return False
    for alarm_match in alarm_matches:
        prefix = text[max(0, alarm_match.start() - 8) : alarm_match.start()]
        if "当前" in prefix or "活动" in prefix or "实时" in prefix:
            continue
        if any(time_match.start() <= alarm_match.start() for time_match in time_matches):
            return True
    return False


def _extract_lookback_minutes(prompt: str) -> int:
    normalized = str(prompt or "")
    minute_match = re.search(r"(\d{1,4})\s*分钟", normalized)
    if minute_match:
        return max(1, min(24 * 60, int(minute_match.group(1))))
    hour_match = re.search(r"(\d{1,3})\s*(?:小时|钟头)", normalized)
    if hour_match:
        return max(1, min(24 * 60, int(hour_match.group(1)) * 60))
    return 15


async def _hydrate_components_with_data(
    components: list[dict[str, Any]],
    *,
    instruction: str = "",
) -> list[dict[str, Any]]:
    if not components:
        return []
    if not str(instruction or "").strip():
        max_workers = min(8, max(1, len(components)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(_hydrate_component_with_data_sync, components))

    hydrated: list[dict[str, Any]] = []
    for component in components:
        hydrated.append(await _hydrate_component_with_data(component, instruction=instruction))
    return hydrated


async def _hydrate_component_with_data(
    component: dict[str, Any],
    *,
    instruction: str = "",
) -> dict[str, Any]:
    next_component = dict(component)
    capability_id = str(component.get("capabilityId") or component.get("pluginId") or "")
    query_params = _component_query_params(component)
    observations: list[dict[str, Any]] = []
    planner_used = False

    for attempt in range(_DATA_PLANNER_MAX_ATTEMPTS):
        data = _execute_data_capability(capability_id, query_params)
        next_component["data"] = data
        observation = _build_data_planning_observation(
            attempt=attempt + 1,
            query_params=query_params,
            data=data,
        )
        observations.append(observation)
        if not _should_invoke_data_planner(
            capability_id=capability_id,
            instruction=instruction,
            data=data,
            attempt=attempt,
        ):
            break

        planner_used = True
        raw_plan = await _build_data_query_plan_with_ai(
            component=next_component,
            capability_id=capability_id,
            instruction=instruction,
            observations=observations,
        )
        data_plan = _normalize_data_query_plan(
            raw_plan,
            capability_id=capability_id,
            current_query_params=query_params,
        )
        observation["plannerAction"] = data_plan["action"]
        observation["plannerReason"] = data_plan["reason"]
        if data_plan["action"] != "retry" or not data_plan["queryParams"]:
            break
        query_params = {
            **query_params,
            **data_plan["queryParams"],
        }
        next_component["queryParams"] = query_params

    if planner_used or len(observations) > 1:
        next_component["dataPlanningTrace"] = observations
    return next_component


def _hydrate_component_with_data_sync(component: dict[str, Any]) -> dict[str, Any]:
    next_component = dict(component)
    capability_id = str(component.get("capabilityId") or component.get("pluginId") or "")
    query_params = _component_query_params(component)
    next_component["data"] = _execute_data_capability(capability_id, query_params)
    return next_component


def _build_data_planning_observation(
    *,
    attempt: int,
    query_params: Mapping[str, Any],
    data: Mapping[str, Any],
) -> dict[str, Any]:
    rows = data.get("rows")
    row_count = len(rows) if isinstance(rows, list) else 0
    return {
        "attempt": attempt,
        "queryParams": copy.deepcopy(dict(query_params)),
        "source": str(data.get("source") or ""),
        "sourceStatus": str(data.get("sourceStatus") or ""),
        "total": _safe_int(data.get("total"), row_count),
        "rowCount": row_count,
        "message": str(data.get("message") or "")[:500],
        "trend": str(data.get("trend") or "")[:200],
        "resolvedTimeRange": copy.deepcopy(data.get("resolvedTimeRange") or {}),
    }


def _should_invoke_data_planner(
    *,
    capability_id: str,
    instruction: str,
    data: Mapping[str, Any],
    attempt: int,
) -> bool:
    if attempt >= _DATA_PLANNER_MAX_ATTEMPTS - 1:
        return False
    if not str(instruction or "").strip():
        return False
    if capability_id == "capability-gap":
        return False
    source_status = str(data.get("sourceStatus") or "")
    if source_status not in {"empty", "unavailable"}:
        return False
    if source_status == "unavailable" and "未接入数据能力" in str(data.get("message") or ""):
        return False
    return True


async def _build_data_query_plan_with_ai(
    *,
    component: Mapping[str, Any],
    capability_id: str,
    instruction: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    from qwenpaw.agents.model_factory import create_model_and_formatter

    capability = _plugin_by_id(capability_id)
    allowed_query_params = copy.deepcopy(capability.get("inputSchema") or {})
    messages = [
        {
            "role": "system",
            "content": (
                "你是 AI 大屏数据查询规划器。你只输出严格 JSON，不要输出 Markdown。"
                "你不能生成源码、SQL、脚本或新接口，只能决定是否在同一个数据能力内重试查询。"
                "JSON 固定字段：action, reason, queryParams。"
                "action 只能是 retry 或 stop。"
                "queryParams 只能使用用户给定 allowedQueryParams 中已有的 key。"
                "当观察结果为空且用户要求查到有数据、历史数据、最后一次有数据时，"
                "可以扩大时间窗口、改成绝对时间、或选择 latest_non_empty 策略。"
                "如果错误是配置、鉴权或接口不可用，优先 stop 并说明原因。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": instruction,
                    "capability": {
                        "id": capability_id,
                        "name": capability.get("name"),
                        "description": capability.get("description"),
                        "allowedQueryParams": allowed_query_params,
                    },
                    "component": {
                        "id": component.get("id"),
                        "title": component.get("title"),
                        "queryParams": copy.deepcopy(component.get("queryParams") or {}),
                    },
                    "observations": copy.deepcopy(observations),
                    "outputExample": {
                        "action": "retry",
                        "reason": "最近窗口为空，按用户要求继续查询历史窗口。",
                        "queryParams": {
                            "timeMode": "absolute",
                            "fromTime": "2026-05-01 00:00:00",
                            "toTime": "2026-06-01 00:00:00",
                        },
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        model, _ = create_model_and_formatter()
        response_text = await _consume_model_response(model, messages)
        parsed = _parse_llm_json_payload(response_text)
    except Exception as exc:  # noqa: BLE001
        return {
            "action": "stop",
            "reason": f"AI 数据规划不可用：{_extract_exception_message(exc)}",
            "queryParams": {},
        }
    if not isinstance(parsed, dict):
        return {
            "action": "stop",
            "reason": "AI 数据规划未返回可执行 JSON",
            "queryParams": {},
        }
    return parsed


def _normalize_data_query_plan(
    plan: Mapping[str, Any],
    *,
    capability_id: str,
    current_query_params: Mapping[str, Any],
) -> dict[str, Any]:
    action = str(plan.get("action") or "").strip()
    if action not in {"retry", "stop"}:
        action = "stop"
    reason = str(plan.get("reason") or "").strip()[:300]
    raw_query_params = plan.get("queryParams")
    query_params = (
        _normalize_data_query_params_patch(
            capability_id=capability_id,
            query_params=raw_query_params,
            current_query_params=current_query_params,
        )
        if isinstance(raw_query_params, dict)
        else {}
    )
    if action == "retry" and not query_params:
        action = "stop"
        reason = reason or "AI 数据规划没有给出可执行查询参数"
    return {
        "action": action,
        "reason": reason,
        "queryParams": query_params,
    }


def _normalize_data_query_params_patch(
    *,
    capability_id: str,
    query_params: Mapping[str, Any],
    current_query_params: Mapping[str, Any],
) -> dict[str, Any]:
    capability = _plugin_by_id(capability_id)
    allowed_keys = set((capability.get("inputSchema") or {}).keys())
    normalized: dict[str, Any] = {}
    for key, value in query_params.items():
        normalized_key = str(key or "").strip()
        if normalized_key not in allowed_keys:
            continue
        if normalized_key == "limit":
            normalized[normalized_key] = max(1, min(200, _safe_int(value, 50)))
        elif normalized_key == "lookbackMinutes":
            normalized[normalized_key] = max(1, min(24 * 60, _safe_int(value, 15)))
        elif normalized_key == "maxLookbackDays":
            normalized[normalized_key] = max(1, min(365, _safe_int(value, 45)))
        elif normalized_key == "fields":
            fields = _normalize_capability_fields(capability_id, value, fallback=[])
            if fields:
                normalized[normalized_key] = fields
        elif normalized_key == "riskKeywords":
            if isinstance(value, list):
                normalized[normalized_key] = [str(item).strip()[:80] for item in value if str(item).strip()]
            else:
                normalized[normalized_key] = [
                    item
                    for item in re.split(r"[,，、\s]+", str(value or ""))
                    if item
                ][:20]
        elif normalized_key in {
            "fromTime",
            "toTime",
            "timeMode",
            "searchStrategy",
            "query",
            "analysisMode",
            "timeRange",
            "scope",
        }:
            normalized[normalized_key] = str(value or "").strip()[:300]
        else:
            normalized[normalized_key] = copy.deepcopy(value)
    return {
        key: value
        for key, value in normalized.items()
        if current_query_params.get(key) != value
    }


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
        if capability_id == "capability-gap":
            return _build_capability_gap_data(query_params)
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
    from qwenpaw.extensions.integrations.nightingale_logs import (
        LOG_SOURCE,
        query_nightingale_logs,
    )

    limit = max(1, min(200, _safe_int(query_params.get("limit"), 50)))
    lookback_minutes = max(1, min(24 * 60, _safe_int(query_params.get("lookbackMinutes"), 15)))
    search_strategy = str(
        query_params.get("searchStrategy")
        or query_params.get("search_strategy")
        or "single_window",
    ).strip()
    time_mode = str(query_params.get("timeMode") or query_params.get("time_mode") or "").strip()
    max_lookback_days = max(
        1,
        min(365, _safe_int(query_params.get("maxLookbackDays"), 45)),
    )
    payload = query_nightingale_logs(
        limit=limit,
        lookback_minutes=lookback_minutes,
        query=str(query_params.get("query") or ""),
        from_time=str(query_params.get("fromTime") or query_params.get("from_time") or ""),
        to_time=str(query_params.get("toTime") or query_params.get("to_time") or ""),
        search_strategy=search_strategy,
        max_lookback_days=max_lookback_days,
    )
    rows = list(payload.get("rows") or [])
    columns = _columns_for_capability_fields("system-logs", query_params.get("fields"))
    analysis_mode = str(query_params.get("analysisMode") or query_params.get("analysis_mode") or "").strip()
    resolved_time_range = (
        payload.get("resolvedTimeRange")
        if isinstance(payload.get("resolvedTimeRange"), dict)
        else {}
    )
    if search_strategy == "latest_non_empty":
        trend = (
            f"最近有日志窗口：{resolved_time_range.get('from') or '--'} ~ "
            f"{resolved_time_range.get('to') or '--'}"
            if rows
            else f"近 {max_lookback_days} 天未命中智观日志"
        )
    else:
        trend = f"最近 {lookback_minutes} 分钟智观日志"
    data = {
        "source": LOG_SOURCE,
        "sourceStatus": str(payload.get("sourceStatus") or ("live" if rows else "empty")),
        "lookbackMinutes": lookback_minutes,
        "timeMode": time_mode or ("latest_non_empty" if search_strategy == "latest_non_empty" else "relative"),
        "searchStrategy": str(payload.get("searchStrategy") or search_strategy),
        "maxLookbackDays": max_lookback_days,
        "resolvedTimeRange": resolved_time_range,
        "attemptedTimeRanges": copy.deepcopy(payload.get("attemptedTimeRanges") or []),
        "total": int(payload.get("total") or len(rows)),
        "value": int(payload.get("total") or len(rows)),
        "unit": "条",
        "trend": trend,
        "message": str(payload.get("message") or ""),
        "columns": columns,
        "rows": rows[:limit],
    }
    if analysis_mode == "risk_summary":
        data.update(_build_system_log_risk_summary(rows=rows, limit=limit, query_params=query_params))
    return data


def _build_system_log_risk_summary(
    *,
    rows: list[Any],
    limit: int,
    query_params: Mapping[str, Any],
) -> dict[str, Any]:
    risk_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        risk = _score_system_log_risk(row, query_params)
        if risk["riskScore"] <= 0:
            continue
        risk_rows.append({**row, **risk})
    risk_rows.sort(key=lambda item: int(item.get("riskScore") or 0), reverse=True)
    top_rows = risk_rows[:limit]
    max_score = max([int(item.get("riskScore") or 0) for item in top_rows], default=0)
    return {
        "visualKind": "risk-pulse",
        "analysisMode": "risk_summary",
        "value": max_score,
        "unit": "风险分",
        "riskScore": max_score,
        "riskItems": top_rows,
        "total": len(risk_rows),
        "trend": f"识别 {len(risk_rows)} 条高危日志线索",
        "summary": (
            "未识别到明显高危日志"
            if not risk_rows
            else f"最高风险 {max_score}，请优先关注前 {min(len(top_rows), 5)} 条日志。"
        ),
        "columns": [
            {"key": "time", "label": "时间"},
            {"key": "level", "label": "级别"},
            {"key": "riskScore", "label": "风险分"},
            {"key": "riskReason", "label": "风险原因"},
            {"key": "message", "label": "日志内容"},
        ],
        "rows": top_rows,
    }


def _score_system_log_risk(row: Mapping[str, Any], query_params: Mapping[str, Any]) -> dict[str, Any]:
    level = str(row.get("level") or row.get("severity") or "").strip().lower()
    message = str(row.get("message") or row.get("content") or row.get("text") or "")
    lowered = message.lower()
    score = 0
    reasons: list[str] = []
    level_scores = {
        "critical": 95,
        "fatal": 92,
        "error": 82,
        "err": 78,
        "warning": 58,
        "warn": 58,
    }
    if level in level_scores:
        score = max(score, level_scores[level])
        reasons.append(f"级别 {level.upper()}")

    keyword_scores = {
        "高危": 92,
        "严重": 86,
        "攻击": 90,
        "注入": 90,
        "漏洞": 88,
        "异常": 72,
        "失败": 68,
        "错误": 74,
        "超时": 70,
        "死锁": 84,
        "崩溃": 88,
        "critical": 95,
        "fatal": 92,
        "panic": 90,
        "exception": 78,
        "timeout": 70,
        "failed": 68,
        "failure": 68,
        "oom": 86,
        "deadlock": 84,
        "attack": 90,
        "inject": 90,
    }
    for keyword, keyword_score in keyword_scores.items():
        if keyword.lower() in lowered or keyword in message:
            score = max(score, keyword_score)
            reasons.append(keyword)

    risk_keywords = query_params.get("riskKeywords")
    if isinstance(risk_keywords, list):
        for keyword in risk_keywords:
            normalized = str(keyword or "").strip()
            if normalized and (normalized.lower() in lowered or normalized in message):
                score = max(score, 76)
                reasons.append(normalized)

    if score < 55:
        return {"riskScore": 0, "riskLevel": "normal", "riskReason": ""}
    if score >= 88:
        risk_level = "critical"
    elif score >= 72:
        risk_level = "high"
    else:
        risk_level = "medium"
    deduped_reasons = []
    for reason in reasons:
        if reason and reason not in deduped_reasons:
            deduped_reasons.append(reason)
    return {
        "riskScore": score,
        "riskLevel": risk_level,
        "riskReason": " / ".join(deduped_reasons[:4]) or "风险日志",
    }


def _query_real_alarms(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.working_secrets import ensure_working_secrets_loaded

    ensure_working_secrets_loaded()
    from qwenpaw.extensions.integrations.portal_real_alarms import query_portal_real_alarms

    limit = max(1, min(200, _safe_int(query_params.get("limit"), 100)))
    lookback_minutes = (
        max(1, min(24 * 60, _safe_int(query_params.get("lookbackMinutes"), 15)))
        if "lookbackMinutes" in query_params
        else None
    )
    alarm_status = str(
        query_params.get("alarmStatus") or query_params.get("alarmstatus") or "",
    ).strip()
    payload = query_portal_real_alarms(
        limit=limit,
        lookback_minutes=lookback_minutes,
        alarm_status=alarm_status or None,
    )
    rows = list(payload.get("items") or [])
    columns = _columns_for_capability_fields("real-alarms", query_params.get("fields"))
    trend = (
        f"最近 {lookback_minutes} 分钟活动告警"
        if lookback_minutes is not None
        else "当前活动告警"
    )
    return {
        "source": "portal-real-alarm-api",
        "sourceStatus": "live" if rows else "empty",
        "lookbackMinutes": lookback_minutes,
        "total": int(payload.get("total") or len(rows)),
        "value": int(payload.get("total") or len(rows)),
        "unit": "起",
        "trend": trend,
        "columns": columns,
        "rows": rows[:limit],
    }


def _query_cmdb_resources(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.portal_monitoring_overview import query_asset_overview

    envelope = query_asset_overview()
    source_status = _envelope_source_status(envelope)
    data = envelope.get("data") if isinstance(envelope, dict) else None
    message = str(envelope.get("msg") or "接口不可用") if isinstance(envelope, dict) else "接口不可用"
    rows = _build_metric_rows(data)
    columns = _columns_for_capability_fields("cmdb-resources", query_params.get("fields"))
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
        "columns": columns,
        "rows": rows,
        "raw": data,
    }


def _query_workorders(query_params: Mapping[str, Any]) -> dict[str, Any]:
    from qwenpaw.extensions.integrations.order_workflow import (
        ORDER_SOURCE,
        query_order_workorders,
    )

    limit = max(1, min(100, _safe_int(query_params.get("limit"), 20)))
    time_range = str(query_params.get("timeRange") or "today")
    columns = _columns_for_capability_fields("workorders", query_params.get("fields"))
    payload = query_order_workorders(limit=limit, time_range=time_range)
    provider_source = str(payload.get("source") or "")
    if provider_source != "live":
        return {
            "source": ORDER_SOURCE,
            "sourceStatus": "unavailable",
            "timeRange": time_range,
            "total": 0,
            "value": 0,
            "unit": "单",
            "trend": "传统工单系统未返回实时数据",
            "message": "工单能力未返回实时来源，已阻断 mock/sample 数据展示。",
            "columns": columns,
            "rows": [],
        }
    rows = list(payload.get("items") or [])
    total = int(payload.get("total") or len(rows))
    return {
        "source": ORDER_SOURCE,
        "sourceStatus": "live" if rows else "empty",
        "timeRange": time_range,
        "total": total,
        "value": total,
        "unit": "单",
        "trend": "今日工单" if time_range == "today" else "工单查询结果",
        "stats": copy.deepcopy(payload.get("stats") or {}),
        "columns": columns,
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


def _build_capability_gap_data(query_params: Mapping[str, Any]) -> dict[str, Any]:
    requested_data = str(query_params.get("requestedData") or "未接入数据").strip()
    reason = str(query_params.get("reason") or "当前没有可复用的真实取数能力").strip()
    suggested_skill = str(query_params.get("suggestedSkillName") or "--").strip() or "--"
    suggested_api = str(query_params.get("suggestedApi") or "--").strip() or "--"
    required_inputs = query_params.get("requiredInputs")
    validation_plan = str(
        query_params.get("validationPlan")
        or "接入真实接口后以 sourceStatus=live 的响应作为展示依据。",
    ).strip()
    rows = [
        {"name": "数据对象", "value": requested_data},
        {"name": "缺口原因", "value": reason},
        {"name": "建议 skill", "value": suggested_skill},
        {"name": "建议接口", "value": suggested_api},
        {
            "name": "所需输入",
            "value": "、".join(str(item) for item in required_inputs)
            if isinstance(required_inputs, list)
            else str(required_inputs or "数据源地址、鉴权方式、查询参数、返回字段映射"),
        },
        {"name": "校验方式", "value": validation_plan},
    ]
    return {
        "source": "ai-capability-planning",
        "sourceStatus": "unavailable",
        "message": "当前没有可复用的真实数据能力，已生成接入方案，未展示模拟数据。",
        "columns": [
            {"key": "name", "label": "事项"},
            {"key": "value", "label": "方案"},
        ],
        "rows": rows,
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


def _coerce_field_values(raw_fields: Any) -> list[str]:
    if isinstance(raw_fields, str):
        values = re.split(r"[,，、\s]+", raw_fields)
    elif isinstance(raw_fields, list):
        values = [str(item) for item in raw_fields]
    else:
        values = []
    normalized: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _resolve_capability_field_key(capability_id: str, value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    lowered = candidate.lower()
    for field in _CAPABILITY_FIELD_DEFINITIONS.get(capability_id, []):
        key = str(field.get("key") or "")
        label = str(field.get("label") or "")
        aliases = [str(item) for item in field.get("aliases", []) if str(item).strip()]
        if lowered == key.lower() or candidate == label:
            return key
        if any(lowered == alias.lower() or candidate == alias for alias in aliases):
            return key
    return ""


def _normalize_capability_fields(
    capability_id: str,
    raw_fields: Any,
    *,
    fallback: list[str] | None = None,
) -> list[str]:
    normalized: list[str] = []
    for value in _coerce_field_values(raw_fields):
        key = _resolve_capability_field_key(capability_id, value)
        if key and key not in normalized:
            normalized.append(key)
    if normalized:
        return normalized
    allowed_keys = {
        str(field.get("key") or "")
        for field in _CAPABILITY_FIELD_DEFINITIONS.get(capability_id, [])
    }
    return [field for field in list(fallback or []) if field in allowed_keys]


def _default_capability_fields(capability_id: str) -> list[str]:
    return list(_DEFAULT_CAPABILITY_FIELDS.get(capability_id, []))


def _columns_for_capability_fields(capability_id: str, raw_fields: Any) -> list[dict[str, str]]:
    field_keys = _normalize_capability_fields(
        capability_id,
        raw_fields,
        fallback=_default_capability_fields(capability_id),
    )
    columns: list[dict[str, str]] = []
    for key in field_keys:
        for field in _CAPABILITY_FIELD_DEFINITIONS.get(capability_id, []):
            if str(field.get("key") or "") == key:
                columns.append({"key": key, "label": str(field.get("label") or key)})
                break
    return columns


def _component_current_fields(component: Mapping[str, Any]) -> list[str]:
    capability_id = str(component.get("capabilityId") or component.get("pluginId") or "")
    query_fields = _normalize_capability_fields(
        capability_id,
        _component_query_params(component).get("fields"),
        fallback=[],
    )
    if query_fields:
        return query_fields

    data = component.get("data") if isinstance(component.get("data"), dict) else {}
    columns = data.get("columns") if isinstance(data, dict) else []
    column_keys = [
        str(column.get("key") or "")
        for column in columns
        if isinstance(column, dict) and str(column.get("key") or "").strip()
    ]
    data_fields = _normalize_capability_fields(capability_id, column_keys, fallback=[])
    if data_fields:
        return data_fields
    return _default_capability_fields(capability_id)


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
        "skillName": str(plugin.get("skillName") or ""),
    }


def _rebuild_data_bindings(
    *,
    components: list[Any],
    previous_bindings: Any,
) -> list[dict[str, Any]]:
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
        binding = _build_binding(component)
        previous_id = previous_by_component_id.get(str(component.get("id") or ""))
        if previous_id:
            binding["id"] = previous_id
        bindings.append(binding)
    return bindings


def _extract_capability_gaps(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for component in components:
        if str(component.get("pluginId") or component.get("capabilityId") or "") != "capability-gap":
            continue
        query_params = _component_query_params(component)
        gaps.append(
            {
                "componentId": str(component.get("id") or ""),
                "requestedData": str(query_params.get("requestedData") or component.get("title") or ""),
                "reason": str(query_params.get("reason") or ""),
                "suggestedSkillName": str(query_params.get("suggestedSkillName") or ""),
                "suggestedApi": str(query_params.get("suggestedApi") or ""),
            },
        )
    return gaps


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
    instruction: str = "",
) -> dict[str, Any]:
    allowed_component_ids = {
        str(item.get("id") or "")
        for item in screen.get("components", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    operations: list[dict[str, Any]] = []
    raw_operations = plan.get("operations")
    add_component_count = 0
    for raw_operation in raw_operations if isinstance(raw_operations, list) else []:
        if not isinstance(raw_operation, dict):
            continue
        operation_type = str(raw_operation.get("type") or "").strip()
        if operation_type == "addComponent":
            normalized = _normalize_add_component_operation(
                raw_operation,
                screen=screen,
                instruction=instruction,
                add_component_count=add_component_count,
            )
            if normalized:
                add_component_count += 1
        else:
            normalized = _normalize_patch_operation(
                operation_type=operation_type,
                operation=raw_operation,
                allowed_component_ids=allowed_component_ids,
                selected_component_id=selected_component_id,
            )
        if normalized:
            operations.append(normalized)
    operations = _ensure_semantic_patch_operations(
        operations=operations,
        screen=screen,
        selected_component_id=selected_component_id,
        instruction=instruction,
    )
    summary = str(plan.get("summary") or "").strip()
    if _summary_mentions_unsupported_layout(summary) and any(
        operation.get("type") == "setComponentLayout"
        for operation in operations
    ):
        summary = "已根据修改要求调整组件布局"
    if not summary and operations:
        summary = "已根据修改要求调整大屏配置"
    return {
        "summary": summary,
        "operations": operations,
    }


def _ensure_semantic_patch_operations(
    *,
    operations: list[dict[str, Any]],
    screen: Mapping[str, Any],
    selected_component_id: str,
    instruction: str,
) -> list[dict[str, Any]]:
    text = str(instruction or "").strip()
    if not text:
        return operations

    components = [
        item
        for item in screen.get("components", [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    if selected_component_id:
        candidates = [
            component
            for component in components
            if str(component.get("id") or "") == selected_component_id
        ]
    else:
        candidates = components

    semantic_operations: list[dict[str, Any]] = []
    if _instruction_mentions_add_component(text) and not _operations_mention_add_component(operations):
        add_operation = _build_semantic_add_component_operation(
            screen=screen,
            instruction=text,
            add_component_count=0,
        )
        if add_operation:
            semantic_operations.append(add_operation)
    if _instruction_mentions_field_change(text):
        mode = _infer_field_patch_mode(text)
        for component in candidates:
            component_id = str(component.get("id") or "")
            capability_id = str(component.get("capabilityId") or component.get("pluginId") or "")
            fields = _extract_requested_fields_from_instruction(text, capability_id)
            if not fields or _component_patch_mentions_fields(operations, component_id):
                continue
            semantic_operations.append(
                {
                    "type": "setComponentFields",
                    "componentIds": [component_id],
                    "mode": mode,
                    "fields": fields,
                },
            )
    if _instruction_mentions_latest_non_empty_logs(text):
        for component in candidates:
            component_id = str(component.get("id") or "")
            capability_id = str(component.get("capabilityId") or component.get("pluginId") or "")
            if capability_id != "system-logs" or _component_patch_mentions_log_time_strategy(
                [*operations, *semantic_operations],
                component_id,
            ):
                continue
            semantic_operations.append(
                {
                    "type": "setComponentQueryParams",
                    "componentIds": [component_id],
                    "queryParams": {
                        "searchStrategy": "latest_non_empty",
                        "timeMode": "latest_non_empty",
                        "maxLookbackDays": _infer_latest_non_empty_max_days(text),
                    },
                },
            )
    if _instruction_mentions_layout_change(text):
        for component in candidates:
            component_id = str(component.get("id") or "")
            if _component_patch_mentions_layout([*operations, *semantic_operations], component_id):
                continue
            layout_operation = _infer_layout_alignment_operation(
                component=component,
                components=components,
                instruction=text,
            )
            if layout_operation:
                semantic_operations.append(layout_operation)
    return [*operations, *semantic_operations]


def _operations_mention_add_component(operations: list[dict[str, Any]]) -> bool:
    return any(operation.get("type") == "addComponent" for operation in operations)


def _instruction_mentions_add_component(instruction: str) -> bool:
    text = str(instruction or "")
    if any(term in text for term in ("模块", "组件", "区域", "卡片", "图表", "面板", "新模块")):
        return any(term in text for term in ("新增", "增加", "加入", "添加", "追加", "加一个", "加个", "补一个", "新"))
    return any(
        term in text
        for term in ("新增一个", "增加一个", "加入一个", "添加一个", "追加一个", "加一个", "加个", "补一个")
    )


def _build_semantic_add_component_operation(
    *,
    screen: Mapping[str, Any],
    instruction: str,
    add_component_count: int,
) -> dict[str, Any]:
    capability_ids = _extract_semantic_capability_ids(instruction)
    capability_id = capability_ids[0] if capability_ids else ""
    if not capability_id:
        return {}
    title = _semantic_component_title(instruction, capability_id)
    visual_type = "table"
    query_params: dict[str, Any] = {}
    visual_config = {"palette": "industrial", "emphasis": "standard"}
    if capability_id == "system-logs" and _text_requests_log_risk_analysis(instruction):
        visual_type = "risk-pulse"
        title = "系统日志高危情况分析"
        query_params = {
            "lookbackMinutes": _extract_lookback_minutes(instruction),
            "limit": 100,
            "analysisMode": "risk_summary",
        }
        visual_config = {"palette": "warm", "emphasis": "strong"}
    elif capability_id == "real-alarms" and _text_requests_current_alarm(instruction):
        visual_type = "status-stream"
        query_params = {"limit": 100}
        visual_config = {"palette": "warm", "emphasis": "strong"}
    component = {
        "title": title,
        "description": instruction[:220],
        "capabilityId": capability_id,
        "visualType": visual_type,
        "queryParams": query_params,
        "layoutPosition": _next_append_layout_position(screen.get("components")),
        "visualConfig": visual_config,
    }
    return _normalize_add_component_operation(
        {"type": "addComponent", "component": component},
        screen=screen,
        instruction=instruction,
        add_component_count=add_component_count,
    )


def _semantic_component_title(instruction: str, capability_id: str) -> str:
    if capability_id == "system-logs":
        return "系统日志分析"
    if capability_id == "real-alarms":
        return "实时告警"
    if capability_id == "workorders":
        return "工单信息"
    if capability_id == "cmdb-resources":
        return "CMDB 资源信息"
    return str(_plugin_by_id(capability_id).get("name") or instruction or "新增模块")[:80]


def _summary_mentions_unsupported_layout(summary: str) -> bool:
    text = str(summary or "")
    if not any(term in text for term in ("不支持", "无法", "不能")):
        return False
    return any(term in text for term in ("布局", "尺寸", "长度", "宽度", "高度", "位置", "平齐", "对齐"))


def _instruction_mentions_layout_change(instruction: str) -> bool:
    text = str(instruction or "")
    if not any(term in text for term in ("对齐", "平齐", "尺寸", "大小", "长度", "宽度", "高度", "位置", "拉长", "缩短")):
        return False
    return any(term in text for term in ("左侧", "右侧", "上方", "下方", "组件", "模块", "这个", "选中"))


def _component_patch_mentions_layout(
    operations: list[dict[str, Any]],
    component_id: str,
) -> bool:
    for operation in operations:
        component_ids = operation.get("componentIds")
        if not isinstance(component_ids, list) or component_id not in component_ids:
            continue
        if operation.get("type") == "setComponentLayout":
            return True
    return False


def _infer_layout_alignment_operation(
    *,
    component: Mapping[str, Any],
    components: list[Mapping[str, Any]],
    instruction: str,
) -> dict[str, Any]:
    component_id = str(component.get("id") or "")
    current_position = _component_layout_position(component)
    reference = _find_layout_reference_component(
        component=component,
        components=components,
        instruction=instruction,
    )
    if not reference:
        return {}

    reference_position = _component_layout_position(reference)
    layout_patch: dict[str, int] = {}
    if any(term in instruction for term in ("对齐", "平齐", "高度", "长度", "尺寸", "大小")):
        layout_patch["y"] = reference_position.get("y", current_position.get("y", 0))
        layout_patch["h"] = reference_position.get("h", current_position.get("h", 1))
    if any(term in instruction for term in ("宽度", "尺寸", "大小")):
        layout_patch["w"] = reference_position.get("w", current_position.get("w", 1))
    if not layout_patch:
        return {}
    return {
        "type": "setComponentLayout",
        "componentIds": [component_id],
        "layoutPosition": layout_patch,
    }


def _find_layout_reference_component(
    *,
    component: Mapping[str, Any],
    components: list[Mapping[str, Any]],
    instruction: str,
) -> Mapping[str, Any] | None:
    component_id = str(component.get("id") or "")
    current = _component_layout_position(component)
    candidates = [
        item
        for item in components
        if isinstance(item, dict) and str(item.get("id") or "") != component_id
    ]
    if not candidates:
        return None

    if "左侧" in instruction or current.get("x", 0) > 0:
        left_candidates = [
            item
            for item in candidates
            if _component_layout_position(item).get("x", 0) < current.get("x", 0)
        ]
        if left_candidates:
            return sorted(
                left_candidates,
                key=lambda item: (
                    abs(_component_layout_position(item).get("y", 0) - current.get("y", 0)),
                    current.get("x", 0) - _component_layout_position(item).get("x", 0),
                ),
            )[0]
    return sorted(
        candidates,
        key=lambda item: (
            abs(_component_layout_position(item).get("y", 0) - current.get("y", 0)),
            abs(_component_layout_position(item).get("x", 0) - current.get("x", 0)),
        ),
    )[0]


def _instruction_mentions_field_change(instruction: str) -> bool:
    return any(
        term in instruction
        for term in (
            "字段",
            "列",
            "返回",
            "显示",
            "展示",
            "补充",
            "增加",
            "新增",
            "加上",
            "去掉",
            "删除",
            "移除",
            "隐藏",
            "不要",
        )
    )


def _infer_field_patch_mode(instruction: str) -> str:
    if any(term in instruction for term in ("删除", "移除", "去掉", "隐藏", "不要")):
        return "remove"
    if any(term in instruction for term in ("只显示", "仅显示", "替换为", "改成这些字段")):
        return "replace"
    return "add"


def _instruction_mentions_latest_non_empty_logs(instruction: str) -> bool:
    text = str(instruction or "")
    if not any(term in text for term in ("日志", "log", "logs")):
        return False
    return any(
        term in text
        for term in (
            "最后一次",
            "最近有",
            "有日志",
            "有数据",
            "查到",
            "查询到",
            "不为空",
            "非空",
            "空结果",
            "历史",
        )
    )


def _infer_latest_non_empty_max_days(instruction: str) -> int:
    text = str(instruction or "")
    day_match = re.search(r"(\d{1,3})\s*天", text)
    if day_match:
        return max(1, min(365, int(day_match.group(1))))
    month_match = re.search(r"(\d{1,2})\s*月", text)
    if month_match:
        return 90
    return 45


def _extract_requested_fields_from_instruction(instruction: str, capability_id: str) -> list[str]:
    text = str(instruction or "")
    lowered = text.lower()
    fields: list[str] = []
    for field in _CAPABILITY_FIELD_DEFINITIONS.get(capability_id, []):
        key = str(field.get("key") or "")
        label = str(field.get("label") or "")
        aliases = [str(item) for item in field.get("aliases", []) if str(item).strip()]
        candidates = [key, label, *aliases]
        if any(candidate and (candidate in text or candidate.lower() in lowered) for candidate in candidates):
            if key and key not in fields:
                fields.append(key)
    return fields


def _component_patch_mentions_fields(
    operations: list[dict[str, Any]],
    component_id: str,
) -> bool:
    for operation in operations:
        component_ids = operation.get("componentIds")
        if not isinstance(component_ids, list) or component_id not in component_ids:
            continue
        if operation.get("type") == "setComponentFields":
            return True
        if operation.get("type") == "setComponentQueryParams":
            query_params = operation.get("queryParams")
            if isinstance(query_params, dict) and "fields" in query_params:
                return True
    return False


def _component_patch_mentions_log_time_strategy(
    operations: list[dict[str, Any]],
    component_id: str,
) -> bool:
    for operation in operations:
        component_ids = operation.get("componentIds")
        if not isinstance(component_ids, list) or component_id not in component_ids:
            continue
        if operation.get("type") != "setComponentQueryParams":
            continue
        query_params = operation.get("queryParams")
        if not isinstance(query_params, dict):
            continue
        if any(
            key in query_params
            for key in (
                "searchStrategy",
                "search_strategy",
                "timeMode",
                "time_mode",
                "fromTime",
                "from_time",
                "toTime",
                "to_time",
            )
        ):
            return True
    return False


def _normalize_add_component_operation(
    operation: Mapping[str, Any],
    *,
    screen: Mapping[str, Any],
    instruction: str,
    add_component_count: int,
) -> dict[str, Any]:
    raw_component = operation.get("component")
    component = dict(raw_component) if isinstance(raw_component, dict) else {}
    for source_key, target_key in (
        ("title", "title"),
        ("description", "description"),
        ("capabilityId", "capabilityId"),
        ("pluginId", "capabilityId"),
        ("visualType", "visualType"),
        ("componentType", "visualType"),
        ("type", "visualType"),
        ("queryParams", "queryParams"),
        ("layoutPosition", "layoutPosition"),
        ("visualConfig", "visualConfig"),
        ("visualSpec", "visualSpec"),
    ):
        if source_key in operation and target_key not in component:
            component[target_key] = copy.deepcopy(operation.get(source_key))
    if "layoutPosition" not in component:
        component["layoutPosition"] = _next_append_layout_position(screen.get("components"))
    normalized_component = _normalize_plan_component(
        component,
        index=len(screen.get("components") if isinstance(screen.get("components"), list) else []) + add_component_count,
        inferred_lookback_minutes=_extract_lookback_minutes(instruction),
        prompt=instruction,
    )
    if not normalized_component:
        return {}
    return {"type": "addComponent", "component": normalized_component}


def _next_append_layout_position(components: Any) -> dict[str, int]:
    max_bottom = 0
    if isinstance(components, list):
        for component in components:
            if not isinstance(component, dict):
                continue
            position = _component_layout_position(component)
            max_bottom = max(max_bottom, position.get("y", 0) + position.get("h", 1))
    return {"x": 0, "y": max_bottom, "w": 12, "h": 4}


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
    if operation_type == "setComponentLayout":
        layout_position = _coerce_layout_position_patch(operation)
        if not layout_position or not component_ids:
            return {}
        return {
            "type": operation_type,
            "componentIds": component_ids,
            "layoutPosition": layout_position,
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
    if operation_type == "setComponentFields":
        fields = _coerce_field_values(
            operation.get("fields")
            if "fields" in operation
            else operation.get("fieldKeys"),
        )
        if not fields or not component_ids:
            return {}
        mode = str(operation.get("mode") or "add").strip()
        return {
            "type": operation_type,
            "componentIds": component_ids,
            "mode": mode if mode in {"add", "replace", "remove"} else "add",
            "fields": fields,
        }
    return {}


def _coerce_layout_position_patch(operation: Mapping[str, Any]) -> dict[str, int]:
    raw_position = operation.get("layoutPosition")
    if not isinstance(raw_position, dict):
        raw_position = {
            key: operation.get(key)
            for key in ("x", "y", "w", "h")
            if key in operation
        }
    layout_position: dict[str, int] = {}
    for key in ("x", "y", "w", "h"):
        if key not in raw_position:
            continue
        if key in {"x", "y"}:
            layout_position[key] = max(0, _safe_int(raw_position.get(key), 0))
        elif key == "w":
            layout_position[key] = max(1, min(12, _safe_int(raw_position.get(key), 1)))
        else:
            layout_position[key] = max(1, min(8, _safe_int(raw_position.get(key), 1)))
    return layout_position


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


async def _apply_patch_plan(
    *,
    screen: dict[str, Any],
    plan: Mapping[str, Any],
    instruction: str = "",
) -> str:
    components = screen.get("components")
    if not isinstance(components, list):
        return ""

    rehydrate_component_ids: set[str] = set()
    for operation in plan.get("operations", []) if isinstance(plan.get("operations"), list) else []:
        if not isinstance(operation, dict):
            continue
        operation_type = operation.get("type")
        if operation_type == "addComponent":
            component = operation.get("component")
            if isinstance(component, dict):
                components.append(
                    await _hydrate_component_with_data(
                        component,
                        instruction=instruction,
                    ),
                )
            continue
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
            component_id = str(component.get("id") or "")
            if component_id not in target_ids:
                continue
            components[index] = _apply_component_operation(component, operation)
            if operation_type in {"setComponentQueryParams", "setComponentFields"}:
                rehydrate_component_ids.add(component_id)

    if rehydrate_component_ids:
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                continue
            if str(component.get("id") or "") in rehydrate_component_ids:
                components[index] = await _hydrate_component_with_data(
                    component,
                    instruction=instruction,
                )

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
    elif operation_type == "setComponentLayout":
        layout_position = operation.get("layoutPosition")
        if isinstance(layout_position, dict):
            current_position = _component_layout_position(next_component)
            next_position = {**current_position, **copy.deepcopy(layout_position)}
            x = max(0, min(11, _safe_int(next_position.get("x"), current_position["x"])))
            w = max(1, min(12 - x, _safe_int(next_position.get("w"), current_position["w"])))
            next_component["layoutPosition"] = {
                "x": x,
                "y": max(0, _safe_int(next_position.get("y"), current_position["y"])),
                "w": w,
                "h": max(1, min(8, _safe_int(next_position.get("h"), current_position["h"]))),
            }
    elif operation_type == "setComponentTitle":
        title = str(operation.get("title") or "").strip()
        if title:
            next_component["title"] = title
    elif operation_type == "setComponentQueryParams":
        query_params = _component_query_params(next_component)
        patch_params = operation.get("queryParams")
        if isinstance(patch_params, dict):
            query_params.update(copy.deepcopy(patch_params))
            capability_id = str(
                next_component.get("capabilityId") or next_component.get("pluginId") or "",
            )
            if "fields" in query_params:
                fields = _normalize_capability_fields(
                    capability_id,
                    query_params.get("fields"),
                    fallback=[],
                )
                if fields:
                    query_params["fields"] = fields
                else:
                    query_params.pop("fields", None)
            next_component["queryParams"] = query_params
    elif operation_type == "setComponentFields":
        capability_id = str(next_component.get("capabilityId") or next_component.get("pluginId") or "")
        requested_fields = _normalize_capability_fields(
            capability_id,
            operation.get("fields"),
            fallback=[],
        )
        if requested_fields:
            query_params = _component_query_params(next_component)
            current_component_type = str(next_component.get("type") or "")
            current_fields = (
                _default_capability_fields(capability_id)
                if current_component_type != "table"
                else _component_current_fields(next_component)
            )
            mode = str(operation.get("mode") or "add").strip()
            if mode == "replace":
                next_fields = requested_fields
            elif mode == "remove":
                next_fields = [field for field in current_fields if field not in requested_fields]
            else:
                next_fields = list(current_fields)
                for field in requested_fields:
                    if field not in next_fields:
                        next_fields.append(field)
            query_params["fields"] = next_fields or _default_capability_fields(capability_id)
            next_component["queryParams"] = query_params
            if current_component_type != "table":
                next_component["type"] = "table"
    return next_component


def _component_visual_config(component: Mapping[str, Any]) -> dict[str, Any]:
    visual_config = component.get("visualConfig")
    return dict(visual_config) if isinstance(visual_config, dict) else {}


def _component_query_params(component: Mapping[str, Any]) -> dict[str, Any]:
    query_params = component.get("queryParams")
    return dict(query_params) if isinstance(query_params, dict) else {}


def _component_layout_position(component: Mapping[str, Any]) -> dict[str, int]:
    layout_position = component.get("layoutPosition")
    raw = layout_position if isinstance(layout_position, dict) else {}
    x = max(0, min(11, _safe_int(raw.get("x"), 0)))
    w = max(1, min(12 - x, _safe_int(raw.get("w"), 1)))
    return {
        "x": x,
        "y": max(0, _safe_int(raw.get("y"), 0)),
        "w": w,
        "h": max(1, min(8, _safe_int(raw.get("h"), 1))),
    }


def _validate_screen(screen: Mapping[str, Any]) -> None:
    if not str(screen.get("id") or "").strip():
        raise ValueError("screen.id 不能为空")
    if not str(screen.get("name") or "").strip():
        raise ValueError("screen.name 不能为空")
    components = screen.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("screen.components 不能为空")
