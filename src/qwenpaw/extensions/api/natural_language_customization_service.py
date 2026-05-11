from __future__ import annotations

import json
import re
import uuid
from typing import Any

from qwenpaw.exceptions import ProviderError
from qwenpaw.extensions.api.natural_language_customization_models import (
    NlCustomizationPreviewRequest,
    NlCustomizationPreviewResponse,
)
from qwenpaw.extensions.natural_language_customization_registry import (
    list_published_customizations,
    publish_customization,
)

CONFIGURE_DEFAULT_LLM_MESSAGE = (
    "未配置默认大模型，请先到“模型配置”里设置默认 LLM 后再生成结构化预览。"
)

_ALLOWED_SCENARIO_TYPES = {
    "inspection",
    "alert-analysis",
    "workorder",
    "portal-dashboard",
    "generic",
}
_ALLOWED_TRIGGER_TYPES = {"schedule", "event", "manual"}
_ALLOWED_APPROVAL_MODES = {"none", "manual", "dual"}

_TEMPLATE_CATALOG: dict[str, dict[str, Any]] = {
    "inspection": {
        "templateId": "inspection-template",
        "templateName": "巡检能力模板",
        "templateKind": "skill-template",
        "skillId": "inspection-analyst",
        "confidence": 0.92,
    },
    "alert-analysis": {
        "templateId": "alert-analysis-template",
        "templateName": "告警分析模板",
        "templateKind": "skill-template",
        "skillId": "alarm-analysis",
        "confidence": 0.9,
    },
    "workorder": {
        "templateId": "workorder-template",
        "templateName": "工单调度模板",
        "templateKind": "skill-template",
        "skillId": "workorder-dispatch",
        "confidence": 0.88,
    },
    "portal-dashboard": {
        "templateId": "portal-dashboard-template",
        "templateName": "门户展示模板",
        "templateKind": "portal-template",
        "skillId": "",
        "confidence": 0.84,
    },
    "generic": {
        "templateId": "generic-template",
        "templateName": "通用定制模板",
        "templateKind": "bundle-template",
        "skillId": "",
        "confidence": 0.6,
    },
}


async def build_nl_customization_preview(
    request: NlCustomizationPreviewRequest,
) -> NlCustomizationPreviewResponse:
    prompt = str(request.prompt or "").strip()
    if not prompt:
        raise ValueError("prompt 不能为空")

    intent, parser_warnings = await _extract_intent(prompt)
    matched_template = _match_template(intent)
    title = str(request.title or "").strip() or _build_default_title(intent)
    bundle = _build_bundle(title=title, prompt=prompt, intent=intent, matched_template=matched_template)
    warnings = _unique_items([*parser_warnings, *_build_warnings(intent, matched_template)])
    missing_inputs = _build_missing_inputs(intent)

    return NlCustomizationPreviewResponse(
        previewId=f"nl-preview-{uuid.uuid4().hex[:10]}",
        title=title,
        prompt=prompt,
        intent=intent,
        matchedTemplate=matched_template,
        bundle=bundle,
        summaryMarkdown=_build_summary_markdown(
            title=title,
            prompt=prompt,
            intent=intent,
            matched_template=matched_template,
            bundle=bundle,
            warnings=warnings,
        ),
        warnings=warnings,
        missingInputs=missing_inputs,
    )


def publish_nl_customization(
    *,
    preview: NlCustomizationPreviewResponse,
    requested_by: str = "portal",
    title: str = "",
) -> dict[str, Any]:
    return publish_customization(
        preview=preview.model_dump(mode="json"),
        requested_by=requested_by,
        title_override=title,
    )


def list_nl_customization_versions(*, limit: int = 20) -> list[dict[str, Any]]:
    return list_published_customizations(limit=limit)


async def _extract_intent(prompt: str) -> tuple[dict[str, Any], list[str]]:
    rule_intent = _extract_rule_intent(prompt)
    llm_intent, warnings = await _extract_intent_with_llm(prompt, rule_intent)
    return llm_intent, warnings


def _extract_rule_intent(prompt: str) -> dict[str, Any]:
    normalized = prompt.lower()
    scenario_type = _detect_scenario_type(prompt, normalized)
    trigger_type, trigger_label, schedule_cron = _detect_trigger(prompt)
    target_type = _detect_target_type(prompt, normalized)
    target_name = _detect_target_name(prompt, target_type)
    actions = _detect_actions(prompt, normalized)
    display_targets = _detect_display_targets(prompt)
    roles = _detect_roles(prompt)
    restrictions = _detect_restrictions(prompt, normalized)
    approval_mode = _detect_approval_mode(prompt, restrictions)
    confidence = _estimate_confidence(
        scenario_type=scenario_type,
        target_type=target_type,
        trigger_type=trigger_type,
        actions=actions,
    )

    return {
        "scenarioType": scenario_type,
        "targetType": target_type,
        "targetName": target_name,
        "triggerType": trigger_type,
        "triggerLabel": trigger_label,
        "scheduleCron": schedule_cron,
        "actions": actions,
        "displayTargets": display_targets,
        "roles": roles,
        "restrictions": restrictions,
        "approvalMode": approval_mode,
        "confidence": confidence,
    }


async def _extract_intent_with_llm(
    prompt: str,
    fallback_intent: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    from qwenpaw.agents.model_factory import create_model_and_formatter

    messages = [
        {
            "role": "system",
            "content": (
                "你是企业级自然语言定制需求解析器。"
                "你的任务是把用户的中文需求解析成严格 JSON，"
                "不要输出任何解释、Markdown、代码块包裹或额外文本。"
                "JSON 字段固定为："
                "scenarioType, targetType, targetName, triggerType, triggerLabel, "
                "scheduleCron, actions, displayTargets, roles, restrictions, "
                "approvalMode, confidence。"
                "其中 scenarioType 只能是 inspection、alert-analysis、workorder、"
                "portal-dashboard、generic 之一；"
                "triggerType 只能是 schedule、event、manual 之一；"
                "approvalMode 只能是 none、manual、dual 之一；"
                "actions、displayTargets、roles、restrictions 必须是字符串数组；"
                "confidence 必须是 0 到 1 之间的小数。"
                "如果某个字段无法确认，请给空字符串、空数组或合理低置信度，"
                "不要编造不存在的系统名、角色或动作。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请解析下面的客户需求并输出 JSON：\n{prompt}\n\n"
                "输出示例："
                '{"scenarioType":"inspection","targetType":"Oracle","targetName":"Oracle",'
                '"triggerType":"schedule","triggerLabel":"每天 08:00","scheduleCron":"0 8 * * *",'
                '"actions":["analyze","ticket"],"displayTargets":["assistant-entry"],'
                '"roles":["运维"],"restrictions":["禁止自动变更"],'
                '"approvalMode":"manual","confidence":0.92}'
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

    parsed_payload = _parse_llm_json_payload(response_text)
    if not isinstance(parsed_payload, dict):
        return fallback_intent, ["默认大模型返回内容未完全结构化，已按规则补齐解析结果。"]
    return _normalize_llm_intent(parsed_payload, fallback_intent), []


def _map_provider_error(exc: ProviderError) -> ValueError:
    message = _extract_exception_message(exc)
    if "No active model configured" in message:
        return ValueError(CONFIGURE_DEFAULT_LLM_MESSAGE)
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


def _parse_llm_json_payload(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    candidate = fenced_match.group(1) if fenced_match else text
    if not fenced_match and "{" in text and "}" in text:
        candidate = text[text.find("{") : text.rfind("}") + 1]

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_llm_intent(
    payload: dict[str, Any],
    fallback_intent: dict[str, Any],
) -> dict[str, Any]:
    scenario_type = _normalize_choice(
        payload.get("scenarioType"),
        _ALLOWED_SCENARIO_TYPES,
        str(fallback_intent.get("scenarioType") or "generic"),
    )
    trigger_type = _normalize_choice(
        payload.get("triggerType"),
        _ALLOWED_TRIGGER_TYPES,
        str(fallback_intent.get("triggerType") or "manual"),
    )
    schedule_cron = ""
    if trigger_type == "schedule":
        schedule_cron = _normalize_text(payload.get("scheduleCron")) or str(
            fallback_intent.get("scheduleCron") or "",
        )

    target_type = _normalize_text(payload.get("targetType")) or str(
        fallback_intent.get("targetType") or "",
    )
    target_name = _normalize_text(payload.get("targetName")) or str(
        fallback_intent.get("targetName") or target_type or "",
    )

    return {
        "scenarioType": scenario_type,
        "targetType": target_type,
        "targetName": target_name,
        "triggerType": trigger_type,
        "triggerLabel": _normalize_text(payload.get("triggerLabel"))
        or str(fallback_intent.get("triggerLabel") or ""),
        "scheduleCron": schedule_cron,
        "actions": _normalize_string_list(payload.get("actions"))
        or list(fallback_intent.get("actions") or ["configure"]),
        "displayTargets": _normalize_string_list(payload.get("displayTargets"))
        or list(fallback_intent.get("displayTargets") or ["assistant-entry"]),
        "roles": _normalize_string_list(payload.get("roles"))
        or list(fallback_intent.get("roles") or ["运维"]),
        "restrictions": _normalize_string_list(payload.get("restrictions"))
        or list(fallback_intent.get("restrictions") or []),
        "approvalMode": _normalize_choice(
            payload.get("approvalMode"),
            _ALLOWED_APPROVAL_MODES,
            str(fallback_intent.get("approvalMode") or "none"),
        ),
        "confidence": _normalize_confidence(
            payload.get("confidence"),
            float(fallback_intent.get("confidence") or 0.45),
        ),
    }


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    candidate = _normalize_text(value)
    return candidate if candidate in allowed else default


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[，,、\n]+", value)
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        return []
    return _unique_items([item for item in items if item])


def _normalize_confidence(value: Any, default: float) -> float:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return round(default, 2)
    return round(min(max(candidate, 0.0), 1.0), 2)


def _extract_exception_message(exc: Exception) -> str:
    for attr in ("message", "detail"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(exc).strip() or exc.__class__.__name__


def _unique_items(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _detect_scenario_type(prompt: str, normalized: str) -> str:
    if any(keyword in prompt for keyword in ("巡检", "检查")):
        return "inspection"
    if any(keyword in prompt for keyword in ("首页", "卡片", "菜单", "报表")):
        return "portal-dashboard"
    if "工单" in prompt and not any(keyword in prompt for keyword in ("告警", "报警")):
        return "workorder"
    if any(keyword in prompt for keyword in ("告警", "报警", "root cause", "rca", "分析")):
        return "alert-analysis"
    if "dashboard" in normalized:
        return "portal-dashboard"
    return "generic"


def _detect_trigger(prompt: str) -> tuple[str, str, str]:
    schedule_match = re.search(
        r"(每天|每日)(早上|上午|中午|下午|晚上)?\s*(\d{1,2})(?:\s*[:点时]\s*(\d{1,2}))?",
        prompt,
    )
    if schedule_match:
        meridiem = schedule_match.group(2) or ""
        hour = int(schedule_match.group(3))
        minute = int(schedule_match.group(4) or "0")
        if meridiem in {"下午", "晚上"} and hour < 12:
            hour += 12
        cron = f"{minute} {hour} * * *"
        label = f"每天 {hour:02d}:{minute:02d}"
        return "schedule", label, cron

    if any(keyword in prompt for keyword in ("收到", "触发", "P1", "告警", "报警")):
        return "event", "事件触发", ""

    return "manual", "手动触发", ""


def _detect_target_type(prompt: str, normalized: str) -> str:
    candidates = (
        ("Oracle", ("oracle", "Oracle")),
        ("MySQL", ("mysql", "MySQL")),
        ("Linux", ("linux", "Linux")),
        ("CMDB", ("cmdb", "CMDB")),
        ("ITSM", ("itsm", "ITSM")),
        ("首页", ("首页", "dashboard")),
    )
    for label, keywords in candidates:
        if any(keyword in prompt or keyword in normalized for keyword in keywords):
            return label
    return ""


def _detect_target_name(prompt: str, target_type: str) -> str:
    if target_type:
        return target_type
    if "待处理工单" in prompt:
        return "待处理工单"
    if "P1" in prompt:
        return "P1 告警"
    return ""


def _detect_actions(prompt: str, normalized: str) -> list[str]:
    actions: list[str] = []
    if any(keyword in prompt for keyword in ("巡检", "检查", "分析", "查询")):
        actions.append("analyze")
    if any(keyword in prompt for keyword in ("通知", "企业微信", "短信")):
        actions.append("notify")
    if any(keyword in prompt for keyword in ("工单", "建单", "派单")):
        actions.append("ticket")
    if any(keyword in prompt for keyword in ("首页", "卡片", "菜单", "报表")):
        actions.append("render")
    if "approve" in normalized or "审批" in prompt:
        actions.append("approve")
    if not actions:
        actions.append("configure")
    return list(dict.fromkeys(actions))


def _detect_display_targets(prompt: str) -> list[str]:
    targets: list[str] = []
    if "首页" in prompt:
        targets.append("portal-home")
    if "卡片" in prompt:
        targets.append("portal-card")
    if "菜单" in prompt:
        targets.append("portal-menu")
    if not targets:
        targets.append("assistant-entry")
    return targets


def _detect_roles(prompt: str) -> list[str]:
    roles: list[str] = []
    if "领导" in prompt:
        roles.append("领导")
    if any(keyword in prompt for keyword in ("运维", "DBA", "管理员")):
        roles.append("运维")
    if not roles:
        roles.append("运维")
    return roles


def _detect_restrictions(prompt: str, normalized: str) -> list[str]:
    restrictions: list[str] = []
    if any(keyword in prompt for keyword in ("不能自动变更", "禁止自动变更", "不能自动执行变更")):
        restrictions.append("禁止自动变更")
    if any(keyword in prompt for keyword in ("不能自动执行", "默认禁止自动执行", "不能自动重启")):
        restrictions.append("禁止自动执行高风险动作")
    if "只读" in prompt or "readonly" in normalized:
        restrictions.append("仅允许只读操作")
    return restrictions


def _detect_approval_mode(prompt: str, restrictions: list[str]) -> str:
    if "双人审批" in prompt:
        return "dual"
    if "审批" in prompt or restrictions:
        return "manual"
    return "none"


def _estimate_confidence(
    *,
    scenario_type: str,
    target_type: str,
    trigger_type: str,
    actions: list[str],
) -> float:
    score = 0.45
    if scenario_type != "generic":
        score += 0.2
    if target_type:
        score += 0.15
    if trigger_type != "manual":
        score += 0.1
    if actions:
        score += 0.1
    return round(min(score, 0.98), 2)


def _match_template(intent: dict[str, Any]) -> dict[str, Any]:
    scenario_type = str(intent.get("scenarioType") or "generic")
    template = dict(_TEMPLATE_CATALOG.get(scenario_type, _TEMPLATE_CATALOG["generic"]))
    reasons = [f"识别到场景类型：{scenario_type}"]
    target_type = str(intent.get("targetType") or "")
    if target_type:
        reasons.append(f"识别到目标对象：{target_type}")
    if intent.get("triggerType") == "schedule":
        reasons.append("识别到定时触发需求")
    template["reasons"] = reasons
    return template


def _build_default_title(intent: dict[str, Any]) -> str:
    scenario_type = intent.get("scenarioType")
    target_name = str(intent.get("targetName") or intent.get("targetType") or "").strip()
    if scenario_type == "inspection":
        return f"{target_name or '通用'}巡检助手"
    if scenario_type == "alert-analysis":
        return f"{target_name or '告警'}分析流程"
    if scenario_type == "workorder":
        return f"{target_name or '工单'}调度流程"
    if scenario_type == "portal-dashboard":
        return f"{target_name or '首页'}展示定制"
    return "自然语言定制方案"


def _build_bundle(
    *,
    title: str,
    prompt: str,
    intent: dict[str, Any],
    matched_template: dict[str, Any],
) -> dict[str, Any]:
    allow_production_change = not any(
        "禁止自动变更" in restriction or "禁止自动执行高风险动作" in restriction
        for restriction in intent.get("restrictions") or []
    )
    allow_write = "ticket" in (intent.get("actions") or []) or allow_production_change
    approval_mode = str(intent.get("approvalMode") or "none")
    template_kind = str(matched_template.get("templateKind") or "")
    display_targets = intent.get("displayTargets") or ["assistant-entry"]
    target_type = str(intent.get("targetType") or "")
    target_name = str(intent.get("targetName") or target_type or "通用")

    return {
        "agent": {
            "name": title,
            "description": f"由自然语言定制生成，面向 {target_name} 场景。",
            "scenarioType": intent.get("scenarioType"),
            "sourcePrompt": prompt,
        },
        "skillBinding": {
            "skillId": str(matched_template.get("skillId") or ""),
            "templateKind": template_kind,
            "parameters": {
                "targetType": target_type,
                "targetName": target_name,
                "actions": intent.get("actions") or [],
                "roles": intent.get("roles") or [],
            },
        },
        "scheduler": {
            "enabled": intent.get("triggerType") == "schedule",
            "triggerType": intent.get("triggerType"),
            "label": intent.get("triggerLabel"),
            "cron": intent.get("scheduleCron"),
        },
        "portal": {
            "menuTitle": title,
            "cardTitle": f"{target_name}结果",
            "displayTargets": display_targets,
            "roles": intent.get("roles") or [],
        },
        "policies": {
            "allowWrite": allow_write,
            "allowProductionChange": allow_production_change,
            "approvalMode": approval_mode,
            "approvalRequired": approval_mode != "none",
            "restrictions": intent.get("restrictions") or [],
        },
        "documentation": {
            "acceptanceChecklist": [
                "确认结构化意图与客户描述一致",
                "确认模板匹配正确",
                "确认权限与审批边界",
                "确认发布后可回滚",
            ],
        },
    }


def _build_warnings(intent: dict[str, Any], matched_template: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not intent.get("targetType"):
        warnings.append("未识别到明确目标对象，已生成通用草案。")
    if intent.get("scenarioType") == "generic":
        warnings.append("未命中明确模板，当前使用通用定制模板。")
    if matched_template.get("templateKind") == "portal-template" and "render" not in (
        intent.get("actions") or []
    ):
        warnings.append("门户展示模板缺少明确展示动作，建议补充页面展示要求。")
    return warnings


def _build_missing_inputs(intent: dict[str, Any]) -> list[str]:
    missing_inputs: list[str] = []
    if intent.get("scenarioType") == "inspection" and intent.get("triggerType") != "schedule":
        missing_inputs.append("建议补充巡检执行频率")
    if "notify" in (intent.get("actions") or []) and not any(
        keyword in (intent.get("targetType") or "")
        for keyword in ("企业微信", "短信", "邮件")
    ):
        missing_inputs.append("建议补充通知渠道")
    if not intent.get("targetType"):
        missing_inputs.append("建议补充目标系统或对象")
    return missing_inputs


def _build_summary_markdown(
    *,
    title: str,
    prompt: str,
    intent: dict[str, Any],
    matched_template: dict[str, Any],
    bundle: dict[str, Any],
    warnings: list[str],
) -> str:
    scheduler = bundle.get("scheduler") if isinstance(bundle.get("scheduler"), dict) else {}
    policies = bundle.get("policies") if isinstance(bundle.get("policies"), dict) else {}
    actions = "、".join(intent.get("actions") or []) or "configure"
    warnings_block = "\n".join(f"- {item}" for item in warnings) if warnings else "- 无"
    return (
        f"# {title}\n\n"
        f"## 原始需求\n\n"
        f"> {prompt}\n\n"
        f"## 结构化意图\n\n"
        f"- 场景类型：{intent.get('scenarioType') or 'generic'}\n"
        f"- 目标对象：{intent.get('targetType') or '未识别'}\n"
        f"- 触发方式：{intent.get('triggerLabel') or '手动触发'}\n"
        f"- 动作：{actions}\n"
        f"- 审批模式：{intent.get('approvalMode') or 'none'}\n\n"
        f"## 模板匹配\n\n"
        f"- 模板：{matched_template.get('templateName') or '通用模板'}\n"
        f"- Skill：{matched_template.get('skillId') or '无'}\n"
        f"- Cron：{scheduler.get('cron') or '无'}\n"
        f"- 允许生产变更：{'是' if policies.get('allowProductionChange') else '否'}\n\n"
        f"## 风险提示\n\n"
        f"{warnings_block}\n"
    )
