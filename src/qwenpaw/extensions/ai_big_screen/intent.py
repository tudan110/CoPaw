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

#: hard cap for the screen banner title — kept identical to the patch
#: ``setScreenTitle`` op so draft-time and edit-time titles clamp the same way
#: (``patch`` imports this constant instead of defining its own).
MAX_SCREEN_TITLE_LENGTH = 60

#: banner-friendly truncation for the heuristic fallback (LLM screenTitle and
#: explicit overrides are only bounded by ``MAX_SCREEN_TITLE_LENGTH``).
_HEURISTIC_TITLE_LENGTH = 20

#: framing verbs / 大屏-type nouns stripped from a prompt to recover a title.
#: Longest-first so "监控大屏" is removed before "大屏", "做一个" before "做".
_SCREEN_TITLE_STOP_TERMS = tuple(
    sorted(
        (
            "帮我",
            "麻烦",
            "请",
            "给我",
            "做一个",
            "做个",
            "制作",
            "生成",
            "创建",
            "搭建",
            "搭个",
            "建一个",
            "构建",
            "做",
            "查询一下",
            "查询",
            "查一下",
            "查看",
            "查",
            "看一下",
            "看看",
            "展示",
            "显示",
            "呈现",
            "可视化大屏",
            "数据大屏",
            "监控大屏",
            "实时大屏",
            "态势大屏",
            "大屏",
            "看板",
            "仪表盘",
            "驾驶舱",
            "面板",
        ),
        key=len,
        reverse=True,
    )
)


_DECLINE_TITLE_RE = re.compile(
    r"不要(?:加|带|生成|显示)?(?:大屏)?(?:主)?标题"
    r"|不(?:需|用)要?(?:大屏)?(?:主)?标题"
    r"|无(?:主)?标题"
    r"|别(?:加|带|生成|放)(?:大屏)?(?:主)?标题"
    r"|去掉(?:大屏)?(?:主)?标题",
)


def prompt_declines_title(prompt: str) -> bool:
    """User explicitly asked for a title-less screen in the draft prompt.

    The auto-title fallback (T-015) must yield to an explicit "不要标题" —
    auto-generation is a convenience, never something the user can't
    decline at generation time.
    """
    return bool(_DECLINE_TITLE_RE.search(str(prompt or "")))


def derive_screen_title(prompt: str, title: str = "") -> str:
    """Heuristic banner title for paths without an LLM ``screenTitle``.

    An explicit override wins; otherwise framing verbs (查询/生成/…) and
    大屏-type nouns are stripped from the prompt and the remainder truncated
    to a banner-friendly length, falling back to :data:`DEFAULT_SCREEN_NAME`
    when nothing meaningful survives. Always clamped to
    :data:`MAX_SCREEN_TITLE_LENGTH`.
    """
    override = str(title or "").strip()
    if override:
        return override[:MAX_SCREEN_TITLE_LENGTH]
    text = str(prompt or "").strip()
    for term in _SCREEN_TITLE_STOP_TERMS:
        text = text.replace(term, "")
    text = re.sub(r"[\s,，。;；:：!！?？、~～]+", "", text)
    text = text.strip(" 的和与及关于对于")
    if not text:
        return DEFAULT_SCREEN_NAME
    return text[:_HEURISTIC_TITLE_LENGTH]


def clamp_screen_title(title: str) -> str:
    """Clamp any banner title to :data:`MAX_SCREEN_TITLE_LENGTH`."""
    return str(title or "").strip()[:MAX_SCREEN_TITLE_LENGTH]


# A capability-gap placeholder is titled ``待接入：<name>`` to warn that no
# real source is wired yet. Both the fullwidth (：) and halfwidth (:) colon
# variants are tolerated so an upstream/hand-authored title still reconciles.
GAP_TITLE_PREFIXES = ("待接入：", "待接入:")

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

#: Colloquial / Chinese names for component types, as an LLM (or a user
#: instruction echoed by one) actually writes them. Keys are lowercase.
COMPONENT_TYPE_ALIASES: dict[str, str] = {
    "柱状图": "bar-chart",
    "柱图": "bar-chart",
    "条形图": "bar-chart",
    "bar": "bar-chart",
    "column": "bar-chart",
    "折线图": "line-chart",
    "曲线图": "line-chart",
    "趋势图": "line-chart",
    "line": "line-chart",
    "面积图": "area-chart",
    "area": "area-chart",
    "饼图": "donut",
    "环形图": "donut",
    "圆环图": "donut",
    "占比图": "donut",
    "pie": "donut",
    "表格": "table",
    "列表": "table",
    "明细表": "table",
    "指标卡": "metric-kpi",
    "数字卡": "metric-kpi",
    "kpi": "metric-kpi",
    "metric": "metric-kpi",
    "翻牌器": "flip-number",
    "数字翻牌": "flip-number",
    "仪表盘": "gauge",
    "仪表图": "gauge",
    "雷达图": "radar",
    "热力图": "heatmap",
    "拓扑图": "graph",
    "拓扑": "graph",
    "关系图": "graph",
    "时间线": "timeline",
    "时间轴": "timeline",
    "漏斗图": "funnel",
    "漏斗": "funnel",
    "水球图": "liquid-ball",
    "水球": "liquid-ball",
    "排行榜": "top-n",
    "排名": "top-n",
    "topn": "top-n",
    "告警流": "alarm-stream",
    "文本": "text",
    "文字": "text",
    "3d柱状图": "bar3d",
}


#: Screen-level composition patterns the renderer implements
#: deterministically — the planner picks one per screen so the macro
#: layout is a design decision, not a side effect of box packing.
ALLOWED_SCREEN_PATTERNS = (
    "focus-left",
    "focus-right",
    "kpi-top",
    "balanced",
)

_COMPONENT_ROLES = ("hero", "support", "context")


def normalize_screen_pattern(raw: Any) -> str:
    """Canonical screen pattern for ``raw``, or ``""`` when unrecognized."""
    text = str(raw or "").strip().lower()
    return text if text in ALLOWED_SCREEN_PATTERNS else ""


def normalize_component_role(raw: Any) -> str:
    """Canonical composition role, tolerating common synonyms."""
    text = str(raw or "").strip().lower()
    if text in _COMPONENT_ROLES:
        return text
    return {
        "primary": "hero",
        "main": "hero",
        "focus": "hero",
        "主角": "hero",
        "主视觉": "hero",
        "secondary": "support",
        "辅助": "support",
        "supporting": "context",
        "背景": "context",
    }.get(text, "")


def _enforce_single_hero(components: list[PlanComponent]) -> None:
    """Demote every hero after the first — the pattern needs ONE focus."""
    seen_hero = False
    for component in components:
        if component.role != "hero":
            continue
        if seen_hero:
            component.role = "support"
        seen_hero = True


_SMALL_PATTERN_TYPES = {
    "metric-kpi",
    "metric-card",
    "flip-number",
    "gauge",
    "liquid-ball",
}


def default_screen_pattern(components: list[PlanComponent]) -> str:
    """Heuristic pattern when the planner didn't pick one.

    A designated hero wants a focus composition; a cluster of small
    numeric panels reads best as a KPI strip; everything else keeps the
    balanced auto layout (zero change to legacy behaviour).
    """
    if any(component.role == "hero" for component in components):
        return "focus-left"
    small = sum(
        1 for c in components if c.type in _SMALL_PATTERN_TYPES
    )
    if small >= 3 and small < len(components):
        return "kpi-top"
    return "balanced"


def normalize_component_type(raw: Any) -> str:
    """Canonical widget type for ``raw``, or ``""`` when unrecognized.

    Accepts canonical ids as-is (any case) and the colloquial names in
    :data:`COMPONENT_TYPE_ALIASES` — an instruction like "换成柱状图"
    must be executable without the model knowing internal type ids.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    if text in ALLOWED_COMPONENT_TYPES:
        return text
    lowered = text.lower()
    if lowered in ALLOWED_COMPONENT_TYPES:
        return lowered
    alias = COMPONENT_TYPE_ALIASES.get(lowered, "")
    if alias:
        return alias
    # "应用列表/服务清单/告警明细"这类叫法都是表格 — 后缀规则兜住
    # 全部组合，别让一个具体名词卡死用户的换型指令。
    if text.endswith(("列表", "清单", "明细")):
        return "table"
    return ""

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
    (
        "self-monitor-overview",
        ("自监控", "self-monitor", "自身健康", "系统健康"),
    ),
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
    if not any(
        term in text for term in ("查询", "查看", "看一下", "展示", "显示")
    ):
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
    return any(
        term in text
        for term in ("分析", "高危", "危险", "动态", "突出", "有哪些")
    )


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
        term in normalized
        for term in ("流转", "动态", "时间线", "状态流", "轮播")
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
        term in text
        for term in ("工单", "待办", "待处理", "流程", "派单", "处置单")
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
    # Public web data — lowest score so an internal keyword always wins a
    # collision (e.g. "资讯中心告警" stays real-alarms); only a pure public
    # ask like "南京天气" routes here.
    if _text_is_web_live(text):
        scores["web-live-data"] = 4
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
        # Unknown claimed capability. Public web data (天气/汇率/新闻) has a real
        # capability — route it there instead of an honest-gap placeholder;
        # unknown *internal* data still gaps (no faking).
        if (
            _infer_component_capability_id(
                component,
                keys=("title", "name", "summary", "description"),
            )
            == "web-live-data"
        ):
            return "web-live-data"
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
        merged_query_params["validationPlan"] = (
            "接入真实接口后以 sourceStatus=live 的响应作为展示依据。"
        )
    if not merged_query_params.get("requiredInputs"):
        merged_query_params["requiredInputs"] = [
            "数据源地址",
            "鉴权方式",
            "查询参数",
            "返回字段映射",
        ]
    raw_component = {
        "title": f"{GAP_TITLE_PREFIXES[0]}{title}",
        "description": (
            f"{reason}。AI 已保留取数方案位置，"
            "接入真实能力前不展示模拟数据。"
        ),
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


def reconcile_gap_title(component: Any) -> bool:
    """Drop the ``待接入：`` prefix once a gap component's data goes live.

    A capability-gap placeholder is titled ``待接入：<name>`` to warn that no
    real source is wired yet. Once a refetch returns ``sourceStatus=live`` the
    warning is a lie — the source *is* connected — so strip the prefix (only
    the prefix; the rest of the title is preserved verbatim). Any non-live
    status (gap/failed/empty) keeps the warning untouched. Call this right
    after a component's ``data`` is replaced by a fresh fetch. Returns True
    iff the title actually changed.
    """
    if not isinstance(component, dict):
        return False
    data = component.get("data")
    if not isinstance(data, dict):
        return False
    if str(data.get("sourceStatus") or "").strip().lower() != "live":
        return False
    title = str(component.get("title") or "")
    for prefix in GAP_TITLE_PREFIXES:
        if title.startswith(prefix):
            component["title"] = title[len(prefix) :]
            return True
    return False


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
    # web-live-data needs a query; backfill from the title if the model
    # routed here (e.g. inferred from "南京天气") without one.
    if (
        capability_id == "web-live-data"
        and not str(
            query_params.get("query") or "",
        ).strip()
    ):
        query_params["query"] = (
            str(component.get("title") or "").strip() or prompt
        )[:60]
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
        role=normalize_component_role(component.get("role")),
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


_WEB_LIVE_CN_TERMS = (
    "天气",
    "气温",
    "汇率",
    "外汇",
    "新闻",
    "资讯",
    "百科",
)
_WEB_LIVE_EN_TERMS = ("weather", "forecast", "exchange rate", "news")
_WEB_QUERY_LEADING_RE = re.compile(
    r"^(?:查询|查看|看一下|看下|显示|展示|搜索|帮我|给我|我想|想|要|再|并|顺便|的)+",
)

#: Leading authoring/framing verbs on a clause ("同时写一个…", "帮我做个…")
#: stripped for a clean gap-card title. Order-agnostic prefix chain.
_CLAUSE_FRAMING_RE = re.compile(
    r"^(?:同时|另外|还要|还想|顺便|再|并|而且|以及|和|帮我|给我|我想|想|要|"
    r"请|麻烦)*"
    r"(?:写|做|生成|制作|创建|搭建|构建|画|列|来|整|弄|给)?"
    r"(?:一个|一张|一份|一条|个|张|份|下|点)?",
)


def _clean_gap_title(clause: str) -> str:
    """Trim leading framing verbs so a gap card reads as the thing asked
    for ("元素周期表") not the whole instruction ("同时写一个元素周期表")."""
    cleaned = _CLAUSE_FRAMING_RE.sub("", str(clause or "").strip()).strip()
    return cleaned or str(clause or "").strip()


def _text_is_web_live(text: str) -> bool:
    """True if free text is a public-web ask (天气/汇率/新闻…)."""
    lowered = text.lower()
    return any(term in text for term in _WEB_LIVE_CN_TERMS) or any(
        term in lowered for term in _WEB_LIVE_EN_TERMS
    )


def extract_web_live_requests(prompt: str) -> list[str]:
    """Public-web clauses (天气/汇率/新闻…) → cleaned query strings.

    The keyword guardrail only knows internal capabilities, so a degraded
    plan used to silently drop public-data asks (the confirmed cause of
    "weather not showing"). This surfaces them so the guardrail can build a
    real ``web-live-data`` component instead of dropping them.
    """
    out: list[str] = []
    for clause in _REQUEST_SPLIT_RE.split(str(prompt or "")):
        clause = clause.strip()
        if not clause or not _text_is_web_live(clause):
            continue
        query = _WEB_QUERY_LEADING_RE.sub("", clause).strip()[:60]
        if query and query not in out:
            out.append(query)
    return out


def build_web_live_component(
    *,
    query: str,
    index: int,
) -> PlanComponent | None:
    """A real ``web-live-data`` component for a public-web query.

    Rendered as a ``table`` so it is non-blank for every kind: weather →
    3-day forecast, fx → currency rates, web/news → search results (each
    ships columns+rows). The generative composed card is the LLM path's job.
    """
    capability = _capability_meta("web-live-data")
    if not capability:
        return None
    normalized_query = str(query or "").strip()[:60]
    raw_component: dict[str, Any] = {
        "title": normalized_query or "实时公开数据",
        "description": capability.get("description") or "",
        "capabilityId": "web-live-data",
        "visualType": "table",
        "queryParams": {"query": normalized_query, "kind": "auto"},
        "layoutPosition": normalize_layout_position({}, index),
        "visualConfig": {"palette": "cool", "emphasis": "standard"},
    }
    return normalize_plan_component(
        raw_component,
        index=index,
        inferred_lookback_minutes=15,
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


def _shared_bigram(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` share a contiguous 2-char content segment."""
    a_clean = re.sub(r"[\s\d，。、；：,.;:!？?！~～]", "", a)
    b_clean = re.sub(r"[\s\d，。、；：,.;:!？?！~～]", "", b)
    if len(a_clean) < 2 or len(b_clean) < 2:
        return False
    bigrams = {a_clean[i : i + 2] for i in range(len(a_clean) - 1)}
    return any(b_clean[i : i + 2] in bigrams for i in range(len(b_clean) - 1))


def _clause_covered_by_authored(
    clause: str,
    components: list[PlanComponent],
) -> bool:
    """A clause the planner routed to the authored-content channel IS
    covered — coverage there has no capability keyword to match, so the
    clause-completeness fallback would misfire an honest-gap card next to
    a perfectly good authored component ("同时写一个99乘法表" gapping
    while 九九乘法表 renders right above it). Text-overlap check is
    deliberately scoped to authored components only, so the T-007
    protection for ops/data clauses stays intact.
    """
    stripped = _CLAUSE_NOISE_RE.sub("", str(clause or ""))
    if not stripped.strip():
        return False
    for component in components:
        if component.capability_id != "ai-authored-content":
            continue
        component_text = f"{component.title} {component.description}"
        if _shared_bigram(stripped, component_text):
            return True
    return False


def _fill_uncovered_clauses(
    components: list[PlanComponent],
    *,
    prompt: str,
    degraded: bool = False,
) -> list[PlanComponent]:
    """Patch any substantive clause left unrepresented by ``components``.

    General on purpose — not a per-topic keyword whitelist. Reuses the
    same clause split + noise-stripping already used by
    ``_has_uncovered_request`` to decide fast-path routing, but applies it
    *after* a plan (guardrail or LLM) is built: any clause with real
    content that matches no known capability is either a genuine
    public-web ask (→ a real ``web-live-data`` component, still fetchable)
    or something we truly can't serve (→ an honest ``capability-gap``).
    Weather was one example that used to vanish silently; this closes the
    same hole for any other topic (an internal system name, a vendor API,
    whatever the user happens to ask for next).
    """
    clauses = [
        c.strip()
        for c in _REQUEST_SPLIT_RE.split(str(prompt or ""))
        if c.strip()
    ]
    if len(clauses) <= 1:
        return components
    present = {component.capability_id for component in components}
    out = list(components)
    seen_web_queries: set[str] = set()
    for clause in clauses:
        if extract_semantic_capability_ids(clause):
            continue
        if not _clause_has_substance(clause):
            continue
        if _clause_covered_by_authored(clause, out):
            continue
        if _text_is_web_live(clause):
            if "web-live-data" in present:
                continue
            query = _WEB_QUERY_LEADING_RE.sub("", clause).strip()[:60]
            if not query or query in seen_web_queries:
                continue
            seen_web_queries.add(query)
            appended = build_web_live_component(query=query, index=len(out))
            if appended is not None:
                out.append(appended)
                present.add("web-live-data")
            continue
        if "capability-gap" in present:
            continue
        # Strip framing verbs ("同时写一个…") from the card title; keep the
        # verbatim clause in queryParams for context.
        cleaned = _clean_gap_title(clause)
        if degraded:
            # Honest about the actual situation: the AI planning pass
            # failed (timeout/ratelimit), so authorable content could not
            # be created THIS time — a retry likely succeeds. Without
            # this, a transient failure reads as a permanent missing
            # integration.
            reason = (
                "本次 AI 规划未完成(超时/限流降级)。若该内容可由 AI 直接"
                "生成(表格/知识类)，点击重新生成即可；若需接入内部系统"
                "数据，再按下方方案接入。"
            )
        else:
            reason = "该数据需求未匹配到已接入能力，也非公开互联网可查信息"
        out.append(
            build_capability_gap_component(
                index=len(out),
                requested_data=cleaned,
                reason=reason,
                query_params={"originalClause": clause},
            )
        )
        present.add("capability-gap")
    return out


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
    # Public-web asks (天气/汇率/新闻…) the keyword router doesn't cover — build
    # a real web-live-data component so the degraded path stops dropping them.
    for query in extract_web_live_requests(prompt):
        component = build_web_live_component(
            query=query,
            index=len(components),
        )
        if component is not None:
            components.append(component)
    components = _fill_uncovered_clauses(
        components,
        prompt=prompt,
        degraded=degraded,
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
        screen_title=(
            ""
            if prompt_declines_title(prompt) and not requested_title
            else derive_screen_title(prompt, requested_title)
        ),
        layout_pattern=default_screen_pattern(components),
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
    components = _fill_uncovered_clauses(components, prompt=prompt)
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
    # Banner title priority: explicit override → planner's in-band screenTitle
    # → heuristic recovered from the prompt. Clamped like setScreenTitle.
    if prompt_declines_title(prompt) and not requested_title:
        screen_title = ""
    else:
        screen_title = clamp_screen_title(
            requested_title
            or plan.screen_title.strip()
            or derive_screen_title(prompt, requested_title),
        )
    _enforce_single_hero(components)
    layout_pattern = normalize_screen_pattern(
        plan.layout_pattern,
    ) or default_screen_pattern(components)
    return ScreenPlan(
        name=requested_title or plan.name.strip() or DEFAULT_SCREEN_NAME,
        screen_title=screen_title,
        layout_pattern=layout_pattern,
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
        "JSON 字段固定为：name, screenTitle, layoutPattern, description, "
        "theme, layout, components, summary。"
        "当用户需求是可计算/静态知识/示例类内容(如乘法表、对照表、"
        "口诀、公式或概念说明)，使用 capabilityId=ai-authored-content，"
        "并把你生成的完整内容内联到该组件 queryParams.content："
        "{columns:[{key,label}...], rows:[{...}...]}(表格类)或 "
        "{text: 说明文字}(文本类)或 {metrics:{名:值}}(数值类)——"
        "内容必须完整可用，不要留空让后端去取(它不会访问任何外部源)。"
        "内容行数较多(超过50行)时只保留最关键的3-4列以控制体积，"
        "但行数必须完整——绝不截断行数或用省略号代替。"
        "这类内容不要路由到 web-live-data 检索。"
        "ai-authored-content 绝不可用于告警/工单/CMDB/资源/日志/监控等"
        "运维数据：运维数据必须绑定真实数据能力，"
        "没有对应能力时用 capability-gap 诚实标注，严禁编造。"
        "screenTitle 是渲染在大屏顶部的主标题：一句话概括本屏主题，"

        "紧扣用户需求、不含'查询/生成/大屏'等动词，≤20 字（如'15分钟告警态势'）。"
        "layoutPattern 是整屏构图，只能是：focus-left(左侧主视觉+右侧信息栏，"
        "适合有明确核心指标/趋势的需求)、focus-right(镜像)、"
        "kpi-top(顶部一排关键数字+下方内容区，适合多个小指标+明细)、"
        "balanced(均衡网格，内容彼此平级时用)。"
        "构图要服务需求语义：谁最重要就让谁当主视觉，不要千篇一律。"
        "components 每项可带 role 字段：hero(全屏唯一视觉主角，"
        "数据最核心/最动态的那个组件)、support(次级)、context(状态/辅助类)；"
        "focus 构图必须恰好一个 hero。"
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
        "screenTitle": "15分钟运行态势",
        "layoutPattern": "focus-left",
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
                "role": "hero",
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
    timeout: float = 300.0,
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
        plan = result.value
        plan.last_error = result.last_error
        return plan
    return _normalize_llm_plan(
        result.value,
        prompt=normalized_prompt,
        title=requested_title,
    )
