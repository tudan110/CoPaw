# -*- coding: utf-8 -*-
"""L1 intent layer: natural language -> typed ``ScreenPlan``.

Ported from the legacy monolith with the structured-output strategy
from ``llm.py``:

- semantic fast-path (simple data queries / explicit log-risk asks)
  builds a plan without calling the LLM at all;
- the LLM path validates against ``ScreenPlan`` with bounded repair;
- exhausted repairs degrade to the keyword-guardrail plan, honestly
  marked ``degraded=True``;
- keyword guardrails keep capability routing consistent (e.g. a
  component titled 工单 can only bind ``workorders``) regardless of
  what capabilityId the model claimed.
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from typing import Any, Mapping

from qwenpaw.extensions.ai_big_screen.capabilities import (
    get_descriptor,
    list_capability_metadata,
)
from qwenpaw.extensions.ai_big_screen.capabilities.fields import safe_int
from qwenpaw.extensions.ai_big_screen.llm import (
    ModelCallable,
    create_pipeline_model,
    structured_call,
)
from qwenpaw.extensions.ai_big_screen.sanitizer import (
    ALLOWED_EMPHASIS,
    ALLOWED_PALETTES,
    sanitize_component_style,
    sanitize_visual_spec,
)
from qwenpaw.extensions.ai_big_screen.schemas import (
    PlanComponent,
    ScreenPlan,
    parse_screen_plan,
)

DEFAULT_SCREEN_NAME = "AI 实时运维大屏"

# ALLOWED_PALETTES / ALLOWED_EMPHASIS are now canonical in ``sanitizer`` and
# re-exported here for backward-compatible imports (e.g. ``patch``).
ALLOWED_COMPONENT_TYPES = {
    # Legacy types still rendered via the adapter.
    "metric-card",
    "line-chart",
    "bar-chart",
    "table",
    "topology",
    "text",
    "risk-pulse",
    "status-stream",
    # D-max palette.
    "metric-kpi",
    "flip-number",
    "liquid-ball",
    "area-chart",
    "donut",
    "gauge",
    "radar",
    "heatmap",
    "graph",
    "map-fly",
    "alarm-stream",
    "top-n",
    "funnel",
    "timeline",
    "bar3d",
    # Generative: declarative blueprint of controlled atoms (P2b).
    "composed",
}

_FALLBACK_POSITIONS = [
    {"x": 0, "y": 0, "w": 6, "h": 4},
    {"x": 6, "y": 0, "w": 6, "h": 4},
    {"x": 0, "y": 4, "w": 4, "h": 3},
    {"x": 4, "y": 4, "w": 4, "h": 3},
    {"x": 8, "y": 4, "w": 4, "h": 3},
    {"x": 0, "y": 7, "w": 12, "h": 4},
]

_SEMANTIC_CAPABILITY_CHECKS = [
    ("system-logs", ("日志", "log", "logs")),
    ("real-alarms", ("告警", "报警", "alarm", "alarms")),
    ("workorders", ("工单", "workorder", "ticket", "tickets")),
    ("cmdb-resources", ("cmdb", "资源", "资产", "resource", "asset")),
    ("topology-impact", ("拓扑", "链路", "影响范围", "topology")),
]


def _capability_meta(capability_id: str) -> dict[str, Any]:
    descriptor = get_descriptor(capability_id)
    if descriptor is None:
        return {}
    return copy.deepcopy(descriptor.metadata)


# ---------------------------------------------------------------------------
# prompt heuristics (ported)
# ---------------------------------------------------------------------------


def extract_semantic_capability_ids(prompt: str) -> list[str]:
    normalized = str(prompt or "").lower()
    matches: list[tuple[int, int, str]] = []
    for capability_id, terms in _SEMANTIC_CAPABILITY_CHECKS:
        positions = [
            normalized.find(term.lower())
            for term in terms
            if normalized.find(term.lower()) >= 0
        ]
        if positions:
            matches.append((min(positions), len(matches), capability_id))
    matches.sort(key=lambda item: (item[0], item[1]))
    capability_ids: list[str] = []
    for _, _, capability_id in matches:
        if capability_id not in capability_ids:
            capability_ids.append(capability_id)
    return capability_ids


def prompt_is_simple_data_query(prompt: str) -> bool:
    text = str(prompt or "")
    if not any(term in text for term in ("查询", "查看", "看一下", "展示", "显示")):
        return False
    expansion_terms = (
        "分析",
        "风险",
        "高危",
        "危险",
        "动态",
        "渲染",
        "趋势",
        "排行",
        "排名",
        "top",
        "Top",
        "对比",
        "统计图",
        "多个",
        "分别",
    )
    return not any(term in text for term in expansion_terms)


def text_requests_log_risk_analysis(text: str) -> bool:
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


def _should_use_log_risk_fast_path(prompt: str) -> bool:
    text = str(prompt or "")
    if not text_requests_log_risk_analysis(text):
        return False
    return any(term in text for term in ("分析", "高危", "危险", "动态", "突出", "有哪些"))


_REQUEST_SPLIT_RE = re.compile(r"[,，、;；]|和|以及|还有|还要|另外|顺便")
_CLAUSE_NOISE_RE = re.compile(
    r"查询|查看|看一下|看下|展示|显示|最近|当前|实时|今日|本周|本月|"
    r"分钟|小时|天|的|了|一下|帮我|生成|大屏|"
    # analysis-intent words modify a known capability (e.g. "分析日志高危
    # 情况") — they are not standalone data objects, so they count as
    # noise when deciding whether a clause is an uncovered new request.
    r"分析|风险|高危|危险|严重|异常|故障|错误|失败|超时|攻击|"
    r"动态|突出|渲染|情况|监控|根因|趋势|走势|变化|对比|比较|"
    r"同比|环比|统计|汇总|排行|排名|关联|影响",
)


def _clause_has_substance(clause: str) -> bool:
    """A clause carries a real data request if, after stripping query
    verbs / time words / fillers, a meaningful noun still remains."""
    stripped = _CLAUSE_NOISE_RE.sub("", clause)
    stripped = re.sub(r"[\d\s]", "", stripped)
    return len(stripped) >= 2


def _has_uncovered_request(prompt: str) -> bool:
    """True if a multi-clause prompt has a substantive clause matching no
    known capability (e.g. "查询系统日志，南京天气"). Such prompts must go
    to the LLM, which turns the unknown ask into an honest capability-gap
    instead of the keyword fast-path silently dropping it."""
    clauses = [
        c.strip()
        for c in _REQUEST_SPLIT_RE.split(str(prompt or ""))
        if c.strip()
    ]
    if len(clauses) <= 1:
        return False
    for clause in clauses:
        if extract_semantic_capability_ids(clause):
            continue
        if _clause_has_substance(clause):
            return True
    return False


def should_use_semantic_fast_path(prompt: str) -> bool:
    capability_ids = extract_semantic_capability_ids(prompt)
    if not capability_ids:
        return False
    if _has_uncovered_request(prompt):
        return False
    return prompt_is_simple_data_query(
        prompt,
    ) or _should_use_log_risk_fast_path(
        prompt,
    )


def extract_lookback_minutes(prompt: str) -> int:
    normalized = str(prompt or "")
    minute_match = re.search(r"(\d{1,4})\s*分钟", normalized)
    if minute_match:
        return max(1, min(24 * 60, int(minute_match.group(1))))
    hour_match = re.search(r"(\d{1,3})\s*(?:小时|钟头)", normalized)
    if hour_match:
        return max(1, min(24 * 60, int(hour_match.group(1)) * 60))
    return 15


def capability_time_window_applies(prompt: str, capability_id: str) -> bool:
    if capability_id == "system-logs":
        return True
    if capability_id != "real-alarms":
        return False
    text = str(prompt or "")
    time_matches = list(
        re.finditer(r"\d{1,4}\s*分钟|\d{1,3}\s*(?:小时|钟头)", text),
    )
    if not time_matches:
        return False
    alarm_matches = list(
        re.finditer(r"告警|报警|alarm|alarms", text, flags=re.I),
    )
    if not alarm_matches:
        return False
    for alarm_match in alarm_matches:
        prefix = text[max(0, alarm_match.start() - 8) : alarm_match.start()]
        if "当前" in prefix or "活动" in prefix or "实时" in prefix:
            continue
        if any(
            time_match.start() <= alarm_match.start()
            for time_match in time_matches
        ):
            return True
    return False


def _text_requests_current_alarm(text: str) -> bool:
    normalized = str(text or "")
    if not re.search(r"告警|报警|alarm|alarms", normalized, flags=re.I):
        return False
    current_terms = r"当前|目前|现在|现有|实时|活动|有哪些|共有|总数|全部|所有"
    alarm_terms = r"告警|报警|alarm|alarms"
    return bool(
        re.search(
            rf"(?:{current_terms}).{{0,18}}(?:{alarm_terms})",
            normalized,
            flags=re.I,
        )
        or re.search(
            rf"(?:{alarm_terms}).{{0,18}}(?:{current_terms})",
            normalized,
            flags=re.I,
        ),
    )


def _text_requests_workorder_stream_visual(text: str) -> bool:
    normalized = str(text or "")
    lowered = normalized.lower()
    if not any(term in normalized for term in ("工单", "待办")) and not any(
        term in lowered for term in ("workorder", "ticket", "tickets")
    ):
        return False
    return any(
        term in normalized for term in ("流转", "动态", "时间线", "状态流", "轮播")
    ) or any(term in lowered for term in ("stream", "timeline", "dynamic"))


# ---------------------------------------------------------------------------
# normalization (ported)
# ---------------------------------------------------------------------------


def _normalize_palette(value: Any) -> str:
    palette = str(value or "").strip()
    return palette if palette in ALLOWED_PALETTES else ""


def normalize_theme(raw_theme: Any) -> dict[str, Any]:
    theme = raw_theme if isinstance(raw_theme, dict) else {}
    palette = _normalize_palette(theme.get("palette")) or "industrial"
    return {
        "mode": "dark",
        "palette": palette,
        "density": str(theme.get("density") or "dashboard").strip()
        or "dashboard",
    }


def normalize_layout(raw_layout: Any) -> dict[str, Any]:
    layout = raw_layout if isinstance(raw_layout, dict) else {}
    return {
        "type": "grid",
        "columns": 12,
        "rowHeight": max(64, min(120, safe_int(layout.get("rowHeight"), 84))),
    }


def normalize_layout_position(raw_position: Any, index: int) -> dict[str, int]:
    position = raw_position if isinstance(raw_position, dict) else {}
    fallback = _FALLBACK_POSITIONS[index % len(_FALLBACK_POSITIONS)]
    x = max(0, min(11, safe_int(position.get("x"), fallback["x"])))
    w = max(1, min(12 - x, safe_int(position.get("w"), fallback["w"])))
    return {
        "x": x,
        "y": max(0, safe_int(position.get("y"), fallback["y"])),
        "w": w,
        "h": max(1, min(8, safe_int(position.get("h"), fallback["h"]))),
    }


def _normalize_visual_config(raw_visual_config: Any) -> dict[str, str]:
    visual_config = (
        raw_visual_config if isinstance(raw_visual_config, dict) else {}
    )
    palette = _normalize_palette(visual_config.get("palette")) or "industrial"
    emphasis = str(visual_config.get("emphasis") or "standard").strip()
    return {
        "palette": palette,
        "emphasis": emphasis if emphasis in ALLOWED_EMPHASIS else "standard",
    }


def _default_style_for_type(component_type: str) -> dict[str, Any]:
    """Born-visible ``visualSpec.style`` defaults when the LLM omits one.

    Topology / relationship graphs render tiny + faint by default (few
    nodes → small box, 20%-opacity links); give them a larger size and
    brighter lines/labels so they are legible out of the box. Still fully
    editable afterwards via ``setComponentStyle``.
    """
    if component_type in {"graph", "topology"}:
        return {
            "sizeScale": 1.3,
            "lineOpacity": 75,
            "labelBrightness": 25,
            "emphasis": "strong",
        }
    return {}


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
    if capability_id == "real-alarms":
        source = component or {}
        query_text = " ".join(
            (
                str(prompt or ""),
                str(source.get("title") or ""),
                str(source.get("description") or ""),
            ),
        )
        if not capability_time_window_applies(
            query_text,
            "real-alarms",
        ) and _text_requests_current_alarm(query_text):
            _remove_real_alarm_builtin_filters(query_params)
    if "lookbackMinutes" in query_params:
        query_params["lookbackMinutes"] = max(
            1,
            min(
                24 * 60,
                safe_int(
                    query_params.get("lookbackMinutes"),
                    inferred_lookback_minutes,
                ),
            ),
        )
    if inferred_lookback_minutes and capability_id == "system-logs":
        query_params["lookbackMinutes"] = inferred_lookback_minutes
    if "limit" in query_params:
        query_params["limit"] = max(
            1,
            min(200, safe_int(query_params.get("limit"), 50)),
        )
    return query_params


def default_log_risk_visual_spec() -> dict[str, Any]:
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
            {
                "field": "riskScore",
                "operator": ">=",
                "value": 88,
                "tone": "critical",
            },
            {
                "field": "riskScore",
                "operator": ">=",
                "value": 72,
                "tone": "high",
            },
        ],
        "layers": [
            {"type": "score", "source": "rows"},
            {"type": "list", "source": "rows", "limit": 5},
        ],
    }


def default_status_stream_visual_spec() -> dict[str, Any]:
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
            {
                "field": "level",
                "operator": "contains",
                "value": "critical",
                "tone": "critical",
            },
            {
                "field": "level",
                "operator": "contains",
                "value": "urgent",
                "tone": "high",
            },
        ],
        "layers": [
            {"type": "stream", "source": "rows", "limit": 8},
        ],
    }


def _infer_component_capability_id(
    component: Mapping[str, Any],
    *,
    keys: tuple[str, ...] = ("title", "description", "name", "summary"),
) -> str:
    text = " ".join(str(component.get(key) or "") for key in keys).strip()
    if not text:
        return ""
    lowered = text.lower()
    scores: dict[str, int] = {}
    if any(
        term in text for term in ("工单", "待办", "待处理", "流程", "派单", "处置单")
    ) or any(
        term in lowered
        for term in ("workorder", "work order", "ticket", "tickets")
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
    if (
        any(term in text for term in ("拓扑", "链路", "影响范围"))
        or "topology" in lowered
    ):
        scores["topology-impact"] = 6
    if not scores:
        return ""
    return max(scores.items(), key=lambda item: item[1])[0]


def _resolve_component_capability_id(
    *,
    raw_capability_id: str,
    component: Mapping[str, Any],
) -> str:
    # Dynamic capabilities — operator connectors (proxy:<id>) and
    # skill-backed (skill:<ws>:<skill>) — are explicit choices; keep
    # them verbatim so a title keyword can't hijack them onto a static
    # built-in.
    if raw_capability_id.startswith(("proxy:", "skill:")) and _capability_meta(
        raw_capability_id,
    ):
        return raw_capability_id
    if raw_capability_id and not _capability_meta(raw_capability_id):
        return raw_capability_id
    if raw_capability_id:
        title_inferred = _infer_component_capability_id(
            component,
            keys=("title", "name", "summary"),
        )
        if title_inferred:
            return title_inferred
        return raw_capability_id
    inferred = _infer_component_capability_id(component)
    if inferred:
        return inferred
    return raw_capability_id


def build_capability_gap_component(
    *,
    index: int,
    requested_data: str,
    reason: str,
    query_params: Mapping[str, Any],
    layout_position: Any | None = None,
    visual_config: Any | None = None,
) -> PlanComponent:
    capability = _capability_meta("capability-gap")
    title = (requested_data or "待接入数据能力").strip()[:80]
    merged_query_params = copy.deepcopy(capability.get("inputSchema") or {})
    merged_query_params.update(copy.deepcopy(dict(query_params)))
    merged_query_params["requestedData"] = title
    merged_query_params["reason"] = reason
    if not merged_query_params.get("validationPlan"):
        merged_query_params[
            "validationPlan"
        ] = "接入真实接口后以 sourceStatus=live 的响应作为展示依据。"
    if not merged_query_params.get("requiredInputs"):
        merged_query_params["requiredInputs"] = [
            "数据源地址",
            "鉴权方式",
            "查询参数",
            "返回字段映射",
        ]
    raw_component = {
        "title": f"待接入：{title}",
        "description": (f"{reason}。AI 已保留取数方案位置，" "接入真实能力前不展示模拟数据。"),
        "capabilityId": "capability-gap",
        "visualType": "table",
        "queryParams": merged_query_params,
        "layoutPosition": layout_position
        or normalize_layout_position({}, index),
        "visualConfig": visual_config
        or {"palette": "cool", "emphasis": "standard"},
    }
    return normalize_plan_component(
        raw_component,
        index=index,
        inferred_lookback_minutes=15,
    )


def normalize_plan_component(
    component: Mapping[str, Any],
    *,
    index: int,
    inferred_lookback_minutes: int,
    prompt: str = "",
) -> PlanComponent:
    """Normalize one raw plan component into a typed ``PlanComponent``.

    Applies capability resolution (keyword guardrails win over the
    model's claimed capabilityId), visual-type whitelisting, query-param
    bounds, and visualSpec sanitization.
    """
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
    capability = _capability_meta(capability_id)
    if not capability:
        return build_capability_gap_component(
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
                "originalQueryParams": copy.deepcopy(
                    component.get("queryParams") or {},
                ),
            },
            layout_position=component.get("layoutPosition"),
            visual_config=component.get("visualConfig"),
        )

    supported_visuals = [
        str(item)
        for item in capability.get("supportedVisuals", [])
        if str(item) in ALLOWED_COMPONENT_TYPES
    ]
    requested_type = str(
        component.get("visualType") or component.get("type") or "",
    ).strip()
    component_type = (
        requested_type if requested_type in supported_visuals else ""
    )
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
    visual_spec = sanitize_visual_spec(component.get("visualSpec"))
    explicit_log_risk = (
        capability_id == "system-logs"
        and text_requests_log_risk_analysis(prompt)
    )
    if (
        capability_id == "system-logs"
        and component_type == "risk-pulse"
        and not explicit_log_risk
    ):
        component_type = "table"
        if str(query_params.get("analysisMode") or "") == "risk_summary":
            query_params["analysisMode"] = ""
        if visual_spec.get("kind") == "risk-field":
            visual_spec = {}
    if explicit_log_risk:
        component_type = "risk-pulse"
        query_params["analysisMode"] = "risk_summary"
        query_params.setdefault("limit", 100)
        visual_config["palette"] = "warm"
        visual_config["emphasis"] = "strong"
        if not visual_spec:
            visual_spec = default_log_risk_visual_spec()
    elif capability_id == "real-alarms" and component_type == "status-stream":
        if not visual_spec:
            visual_spec = default_status_stream_visual_spec()

    if not (isinstance(visual_spec, dict) and visual_spec.get("style")):
        default_style = _default_style_for_type(component_type)
        if default_style:
            visual_spec = {
                **(visual_spec if isinstance(visual_spec, dict) else {}),
                "style": sanitize_component_style(default_style),
            }

    return PlanComponent(
        id=f"component-{index + 1}-{uuid.uuid4().hex[:6]}",
        type=component_type,
        title=(
            str(component.get("title") or "").strip()
            or str(capability.get("name") or capability_id)
        )[:80],
        description=(
            str(component.get("description") or "").strip()
            or str(capability.get("description") or "")
        )[:220],
        capability_id=capability_id,
        query_params=query_params,
        visual_config=visual_config,
        visual_spec=visual_spec,
        layout_position=normalize_layout_position(
            component.get("layoutPosition"),
            index,
        ),
    )


def build_semantic_component(
    *,
    capability_id: str,
    index: int,
    inferred_lookback_minutes: int,
    force_lookback: bool = False,
    prompt: str = "",
) -> PlanComponent | None:
    capability = _capability_meta(capability_id)
    if not capability:
        return None
    visual_type = (capability.get("supportedVisuals") or ["table"])[0]
    uses_time_window = capability_id == "system-logs" or (
        capability_id == "real-alarms" and force_lookback
    )
    title_prefix = (
        f"{inferred_lookback_minutes}分钟"
        if inferred_lookback_minutes and uses_time_window
        else ""
    )
    raw_component: dict[str, Any] = {
        "title": f"{title_prefix}{capability.get('name') or capability_id}",
        "description": capability.get("description") or "",
        "capabilityId": capability_id,
        "visualType": visual_type,
        "queryParams": copy.deepcopy(capability.get("inputSchema") or {}),
        "layoutPosition": normalize_layout_position({}, index),
        "visualConfig": {"palette": "industrial", "emphasis": "standard"},
    }
    if inferred_lookback_minutes and uses_time_window:
        raw_component["queryParams"][
            "lookbackMinutes"
        ] = inferred_lookback_minutes
    if capability_id == "system-logs" and text_requests_log_risk_analysis(
        prompt,
    ):
        raw_component["title"] = "系统日志高危情况分析"
        raw_component["visualType"] = "risk-pulse"
        raw_component["queryParams"]["analysisMode"] = "risk_summary"
        raw_component["queryParams"]["limit"] = 100
        raw_component["visualConfig"] = {
            "palette": "warm",
            "emphasis": "strong",
        }
        raw_component["visualSpec"] = default_log_risk_visual_spec()
    return normalize_plan_component(
        raw_component,
        index=index,
        inferred_lookback_minutes=inferred_lookback_minutes,
        prompt=prompt,
    )


def _ensure_semantic_capabilities(
    *,
    prompt: str,
    components: list[PlanComponent],
    inferred_lookback_minutes: int,
) -> list[PlanComponent]:
    present = {component.capability_id for component in components}
    next_components = list(components)
    for capability_id in extract_semantic_capability_ids(prompt):
        if capability_id in present:
            continue
        appended = build_semantic_component(
            capability_id=capability_id,
            index=len(next_components),
            inferred_lookback_minutes=inferred_lookback_minutes,
            force_lookback=capability_time_window_applies(
                prompt,
                capability_id,
            ),
            prompt=prompt,
        )
        if appended is not None:
            next_components.append(appended)
            present.add(capability_id)
    return next_components


def _dedupe_simple_query_components(
    *,
    prompt: str,
    components: list[PlanComponent],
) -> list[PlanComponent]:
    if not prompt_is_simple_data_query(prompt):
        return components
    semantic_ids = set(extract_semantic_capability_ids(prompt))
    if not semantic_ids:
        return components
    seen: set[str] = set()
    deduped: list[PlanComponent] = []
    for component in components:
        if component.capability_id in semantic_ids:
            if component.capability_id in seen:
                continue
            seen.add(component.capability_id)
        deduped.append(component)
    return deduped


# ---------------------------------------------------------------------------
# plan building
# ---------------------------------------------------------------------------


def build_guardrail_plan(
    *,
    prompt: str,
    title: str,
    degraded: bool = False,
) -> ScreenPlan:
    """Keyword-routed minimal viable plan (fast path + degraded fallback)."""
    inferred_lookback_minutes = extract_lookback_minutes(prompt)
    components: list[PlanComponent] = []
    for capability_id in extract_semantic_capability_ids(prompt):
        component = build_semantic_component(
            capability_id=capability_id,
            index=len(components),
            inferred_lookback_minutes=inferred_lookback_minutes,
            force_lookback=capability_time_window_applies(
                prompt,
                capability_id,
            ),
            prompt=prompt,
        )
        if component is not None:
            components.append(component)
    if not components:
        components = [
            build_capability_gap_component(
                index=0,
                requested_data=prompt,
                reason="未匹配到可真实查询的已接入数据能力",
                query_params={},
            ),
        ]
    capability_names = [
        str(_capability_meta(component.capability_id).get("name") or "")
        for component in components
    ]
    capability_label = (
        "、".join(name for name in capability_names if name) or "数据能力"
    )
    requested_title = str(title or "").strip()
    return ScreenPlan(
        name=requested_title or DEFAULT_SCREEN_NAME,
        description=f"按数据意图查询：{prompt}",
        summary=f"已按数据意图生成 {capability_label} 查询组件。",
        theme=normalize_theme({}),
        layout=normalize_layout({}),
        components=components,
        degraded=degraded,
    )


def _normalize_llm_plan(
    plan: ScreenPlan,
    *,
    prompt: str,
    title: str,
) -> ScreenPlan:
    inferred_lookback_minutes = extract_lookback_minutes(prompt)
    components = [
        normalize_plan_component(
            component.model_dump(by_alias=True),
            index=index,
            inferred_lookback_minutes=inferred_lookback_minutes,
            prompt=prompt,
        )
        for index, component in enumerate(plan.components)
    ]
    components = _ensure_semantic_capabilities(
        prompt=prompt,
        components=components,
        inferred_lookback_minutes=inferred_lookback_minutes,
    )
    components = _dedupe_simple_query_components(
        prompt=prompt,
        components=components,
    )
    if not components:
        components = [
            build_capability_gap_component(
                index=0,
                requested_data=prompt,
                reason="未匹配到可真实查询的已接入数据能力",
                query_params={},
            ),
        ]
    requested_title = str(title or "").strip()
    return ScreenPlan(
        name=requested_title or plan.name.strip() or DEFAULT_SCREEN_NAME,
        description=plan.description.strip(),
        summary=plan.summary.strip(),
        theme=normalize_theme(plan.theme),
        layout=normalize_layout(plan.layout),
        components=components,
        degraded=plan.degraded,
    )


def _build_intent_messages(prompt: str, title: str) -> list[dict[str, str]]:
    capabilities = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "domain": str(item.get("domain") or ""),
            "description": str(item.get("description") or ""),
            "inputSchema": copy.deepcopy(item.get("inputSchema") or {}),
            "supportedVisuals": copy.deepcopy(
                item.get("supportedVisuals") or [],
            ),
            "dataSource": str(item.get("dataSource") or ""),
            "skillName": str(item.get("skillName") or ""),
        }
        for item in list_capability_metadata()
    ]
    system_prompt = (
        "你是面向运维场景的 AI 大屏产品设计师和数据需求分析师。"
        "你必须先理解用户语义中真正需要的数据，再从给定 dataCapabilities 中选择能力。"
        "同一句话出现多个数据对象时必须全部覆盖，例如日志和告警要生成两个独立数据需求。"
        "同一个 capabilityId 的数据可以从不同视角拆成多个互补组件"
        '（例如告警可同时做"总数翻牌 + 分级占比环图 + 滚动告警流 + 趋势曲线"），'
        "只要每个组件呈现不同侧面、不是简单重复——这样大屏更丰富；简单单值查询保持一个组件即可。"
        "组件标题、描述、capabilityId 必须语义一致：工单只能使用 workorders，"
        "告警只能使用 real-alarms，日志只能使用 system-logs。"
        "你需要创造性设计版式、标题、描述、视觉调性和组件组合，"
        "但不得输出前端源码、SQL、脚本或未授权接口。"
        "创造性不得改变用户请求的数据意图；用户没有要求分析、风险、高危、动态突出时，"
        "系统日志只能按普通日志查询展示，"
        "不要使用 risk-pulse、risk-field 或 queryParams.analysisMode=risk_summary。"
        "对于天气、汇率、新闻、百科等公开互联网实时信息，"
        "使用 web-live-data 能力，queryParams.query 用一句话写明要查什么"
        "（如“南京天气”“美元兑人民币汇率”），数据会真实联网检索并标注来源。"
        "只有当用户需要的是内部系统/业务数据、且没有可真实查询的已接入能力时，"
        "才使用 capability-gap，"
        "在 queryParams 中写明 requestedData、reason、suggestedSkillName、"
        "suggestedApi、requiredInputs、validationPlan，"
        "不得用已有能力或样例数据伪装。"
        "只输出严格 JSON，不要输出 Markdown、解释或代码块。"
        "JSON 字段固定为：name, description, theme, layout, components, summary。"
        "theme.palette 只能是 professional、industrial、aurora、mono、"
        "warm、cool、executive。"
        "components 是数组；每项必须包含 title, description, capabilityId, visualType, "
        "queryParams, layoutPosition。capabilityId 必须来自 dataCapabilities。"
        "visualType 从以下大屏组件库中按数据特征挑最贴切、最有视觉冲击力的，不要清一色用 table："
        "数字指标=metric-kpi / flip-number(大数翻牌) / gauge(达成率仪表) / "
        "liquid-ball(百分比水球)；"
        "趋势对比=line-chart / area-chart / bar-chart / donut(占比) / "
        "radar(多维评估) / heatmap(时段热力)；"
        "列表与流=alarm-stream(滚动告警流) / top-n(TOP排行) / "
        "timeline(时间线) / funnel(漏斗收敛)；"
        "关系地理=graph(依赖拓扑) / map-fly(全国分布飞线)；风险=risk-pulse。"
        "兼容旧类型 table、topology、status-stream、metric-card、text 仍可用。"
        "如果用户要求分析系统日志高危/风险/危险情况并动态突出，"
        "系统日志组件优先使用 visualType=risk-pulse，"
        "queryParams.analysisMode=risk_summary。"
        "components 每项可以包含 visualSpec 安全视觉规格；"
        "visualSpec.kind 只能是 risk-field、signal-stream、timeline、"
        "heatmap-matrix、metric-cluster，"
        "motion 只能是 none、pulse、scan、flow、stagger；"
        "bindings 用于声明字段绑定，键名取自数据列："
        "name/value(指标与排行)、x/y(图表横纵轴)、unit/prefix(数值单位前缀)、"
        "time/message/tone(流与时间线)、title/severity/status/group 等，"
        "highlightRules 用于声明条件高亮，layers 用于声明 "
        "score/list/stream/timeline/matrix/metrics 等层。"
        "不要输出 HTML、CSS、JS、URL 或代码。queryParams 只写普通 JSON 参数。"
        "用 visualSpec.composition 表达组件重要度："
        "primary(核心，最大) / secondary(次要) / supporting(辅助)；"
        "新版大屏据此自动排版铺满整屏。layoutPosition 仍用 12 列网格 "
        "x,y,w,h，但仅作兜底、不必追求精确。"
        "用 visualSpec.style 控制组件外观，让大屏更好看、更可读："
        "sizeScale 0.5-2.0(放大/缩小，关系拓扑/graph 建议 1.3 以上避免太小)、"
        "palette(同 theme.palette 取值，覆盖单个组件配色)、"
        "accentColor(强调主色，颜色名或 #十六进制)、"
        "lineOpacity 0-100(图表线条/区域不透明度，关系拓扑建议 70 以上避免太暗)、"
        "labelBrightness -100 到 100(文字提亮/压暗)、emphasis standard|strong。"
        "关系拓扑/graph 默认偏小偏暗，务必配 style 让它够大够亮。"
        "尽量生成 4-8 个主次分明、类型多样的组件，让大屏丰富炫酷而不单薄。"
        "【汇总必配明细】凡是工单/告警/日志这类列表型数据，"
        "汇总数字（flip-number/metric-card）必须配一个同能力的明细组件"
        "（table 或 alarm-stream），只给一个孤零零的大数字是不合格的；"
        "用户点名查询的每个对象至少 1-2 个组件。"
        "【即时创作】当成品组件不足以表达数据时，"
        "用 visualType=composed 自由创作：在 visualSpec.blueprint 里声明版式，"
        "blueprint={layout, gap?, cells:[{span?, element}]}；"
        "layout 只能是 rows、columns、grid、overlay、radial，"
        "gap 只能是 s、m、l，span 1-4，cells 最多 12 个。"
        "element.kind 只能是："
        "value(大数字，bind{value,unit,label,prefix}，style plain/flip/glow，"
        "size m/l/xl)、"
        "chart(图表，chart line/area/bar/donut/gauge/radar/heatmap，"
        "bind{x,y,name,value})、"
        "list(列表，style stream/rank/plain，"
        "bind{title,message,time,tone,value,name}，limit≤20)、"
        "badge(状态徽章，text 静态文本或 bind{text}，tone)、"
        "label(静态说明文字 text)、"
        "progress(进度，style bar/ring/liquid，bind{value,max})、"
        "sparkline(迷你趋势线，bind{x,y})、"
        "group(嵌套一层子版式，含 layout 和 cells)。"
        "bind 的值一律写数据列名/指标名，渲染器据此绑定真实数据。"
        "web-live-data 组件的可绑定键固定为：value，以及天气场景的 "
        "temperature/condition/feelsLike/humidity/wind/location、"
        "汇率场景的 rate；不要为它自造其他键名。"
        "天气数据还自带 rows（列 date/desc/max/min，未来三日预报）和 "
        "series（逐小时气温），天气 composed 卡应该用满：大数字气温 + "
        "状态徽章 + sparkline 逐时趋势 + 预报 list，不要只放一个数字留白。"
        "鼓励把每屏最重要的 1-2 个组件用 composed 创作出与众不同的版式"
        "（例如：翻牌大数 + 迷你趋势 + 状态徽章的组合卡，"
        "或环图叠加中心数值再配滚动列表），不要与成品组件简单重复。"
    )
    output_example = {
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
                "title": "实时告警总数",
                "description": "最近 15 分钟活动告警计数。",
                "capabilityId": "real-alarms",
                "visualType": "flip-number",
                "queryParams": {"lookbackMinutes": 15, "limit": 200},
                "visualSpec": {
                    "composition": "primary",
                    "bindings": {"value": "total", "unit": "条"},
                    "style": {
                        "sizeScale": 1.2,
                        "emphasis": "strong",
                        "accentColor": "#22d3ee",
                    },
                },
                "layoutPosition": {"x": 0, "y": 0, "w": 4, "h": 2},
            },
            {
                "title": "告警分级占比",
                "description": "按严重级别统计的告警占比。",
                "capabilityId": "real-alarms",
                "visualType": "donut",
                "queryParams": {"lookbackMinutes": 15, "limit": 200},
                "visualSpec": {
                    "composition": "secondary",
                    "bindings": {"name": "level", "value": "count"},
                },
                "layoutPosition": {"x": 4, "y": 0, "w": 4, "h": 4},
            },
            {
                "title": "实时告警流",
                "description": "最近活动告警滚动列表。",
                "capabilityId": "real-alarms",
                "visualType": "alarm-stream",
                "queryParams": {"lookbackMinutes": 15, "limit": 80},
                "visualSpec": {
                    "composition": "supporting",
                    "bindings": {
                        "message": "title",
                        "time": "eventTime",
                        "tone": "level",
                    },
                },
                "layoutPosition": {"x": 8, "y": 0, "w": 4, "h": 4},
            },
            {
                "title": "15分钟系统日志",
                "description": "最近 15 分钟智观日志接入的业务/应用/系统日志。",
                "capabilityId": "system-logs",
                "visualType": "table",
                "queryParams": {
                    "lookbackMinutes": 15,
                    "limit": 50,
                    "query": "",
                },
                "visualSpec": {"composition": "supporting"},
                "layoutPosition": {"x": 0, "y": 2, "w": 4, "h": 2},
            },
            {
                "title": "告警态势核心舱",
                "description": "翻牌总数 + 趋势 + 实时流的即时创作组合。",
                "capabilityId": "real-alarms",
                "visualType": "composed",
                "queryParams": {"lookbackMinutes": 60, "limit": 200},
                "visualSpec": {
                    "composition": "primary",
                    "blueprint": {
                        "layout": "columns",
                        "gap": "m",
                        "cells": [
                            {
                                "span": 1,
                                "element": {
                                    "kind": "group",
                                    "layout": "rows",
                                    "cells": [
                                        {
                                            "element": {
                                                "kind": "value",
                                                "style": "flip",
                                                "size": "xl",
                                                "bind": {
                                                    "value": "total",
                                                    "unit": "条",
                                                    "label": "活动告警",
                                                },
                                            },
                                        },
                                        {
                                            "element": {
                                                "kind": "badge",
                                                "text": "实时监控中",
                                                "tone": "cool",
                                            },
                                        },
                                    ],
                                },
                            },
                            {
                                "span": 2,
                                "element": {
                                    "kind": "chart",
                                    "chart": "area",
                                    "bind": {"x": "eventTime", "y": "value"},
                                },
                            },
                            {
                                "span": 1,
                                "element": {
                                    "kind": "list",
                                    "style": "stream",
                                    "limit": 6,
                                    "bind": {
                                        "title": "title",
                                        "time": "eventTime",
                                        "tone": "level",
                                    },
                                },
                            },
                        ],
                    },
                },
                "layoutPosition": {"x": 4, "y": 2, "w": 8, "h": 4},
            },
        ],
        "summary": "告警从总数、分级、实时流三个视角展开，并覆盖系统日志需求。",
    }
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "prompt": prompt,
                    "titleOverride": title,
                    "dataCapabilities": capabilities,
                    "outputExample": output_example,
                },
                ensure_ascii=False,
            ),
        },
    ]


async def build_screen_plan(
    prompt: str,
    title: str = "",
    *,
    model: ModelCallable | None = None,
    max_repair: int = 2,
    timeout: float = 120.0,
) -> ScreenPlan:
    """L1 entry point: NL prompt -> normalized typed ``ScreenPlan``."""
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        raise ValueError("prompt 不能为空")
    requested_title = str(title or "").strip()

    if should_use_semantic_fast_path(normalized_prompt):
        return build_guardrail_plan(
            prompt=normalized_prompt,
            title=requested_title,
        )

    active_model = model if model is not None else create_pipeline_model()
    result = await structured_call(
        active_model,
        _build_intent_messages(normalized_prompt, requested_title),
        parser=parse_screen_plan,
        max_repair=max_repair,
        timeout=timeout,
        fallback=lambda: build_guardrail_plan(
            prompt=normalized_prompt,
            title=requested_title,
            degraded=True,
        ),
    )
    if result.degraded:
        return result.value
    return _normalize_llm_plan(
        result.value,
        prompt=normalized_prompt,
        title=requested_title,
    )
