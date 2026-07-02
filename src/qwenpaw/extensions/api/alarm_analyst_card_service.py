from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from qwenpaw.extensions.api.alarm_analyst_card_models import (
    AlarmAnalystCard,
    AlarmAnalystCardEvidence,
    AlarmAnalystCardImpact,
    AlarmAnalystCardImpactEntity,
    AlarmAnalystCardProcessBlock,
    AlarmAnalystCardRecommendation,
    AlarmAnalystCardRootCause,
    AlarmAnalystCardRootCauseCandidate,
    AlarmAnalystCardSource,
    AlarmAnalystCardSummary,
    AlarmAnalystCardTopology,
)

SECTION_HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)
BULLET_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)(.+?)\s*$", re.MULTILINE)
RESOURCE_ID_RE = re.compile(
    r"(?:资源\s*ID(?:（CI\s*ID）|\(CI\s*ID\))?|CI\s*ID|res[_\s-]*id)[:：]?\s*([0-9]+)",
    re.IGNORECASE,
)
RESOURCE_ID_FALLBACK_RE = re.compile(r"(?:根资源|资源)\D{0,8}([0-9]{3,})")
ROOT_RESOURCE_RE = re.compile(
    r"(?:根资源|根因对象|根因资源|根资源为)[:：]?\s*([A-Za-z0-9_.\-\u4e00-\u9fa5]+)"
)
APPLICATION_VALUE_RE = re.compile(r"^(?:受影响应用|影响应用|应用)\s*[:：]\s*(.+)$")
RESOURCE_VALUE_RE = re.compile(r"^(?:受影响资源|影响资源|资源|CI\s*ID)\s*[:：]\s*(.+)$", re.IGNORECASE)
SECTION_ONLY_APPLICATIONS = {"受影响应用", "影响应用", "应用"}
SECTION_ONLY_RESOURCES = {"受影响资源", "影响资源", "资源", "ciid", "ci id"}
ENTITY_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-()（）/\u4e00-\u9fa5\s]{1,32}$")
SEVERITY_KEYWORDS = (
    ("critical", ("p0", "严重", "critical", "高危", "紧急")),
    ("major", ("p1", "major", "高", "重要")),
    ("minor", ("p2", "minor", "一般", "低")),
)
PORTAL_ALARM_ANALYST_CARD_MARKER = "# PORTAL ALARM ANALYST CARD MODE"


def is_alarm_analyst_card_candidate(
    *,
    employee_id: str,
    report_markdown: str,
    process_blocks: Iterable[dict[str, Any] | AlarmAnalystCardProcessBlock],
) -> bool:
    if str(employee_id or "").strip() != "fault":
        return False

    raw_report_text = str(report_markdown or "").strip()
    report_text = _unwrap_portal_alarm_analyst_card_content(raw_report_text)
    if len(report_text) < 20:
        return False

    if _matches_portal_alarm_analyst_protocol(raw_report_text, report_text):
        return True

    marker_count = sum(
        1
        for marker in (
            "完整故障分析报告",
            "根因分析结论",
            "根因结论",
            "处置建议",
            "影响范围",
            "证据摘要",
        )
        if marker in report_text
    )
    has_recommendation_hint = "建议" in report_text
    has_topology_signal = bool(_extract_topology_payload(process_blocks)[0])
    return marker_count >= 2 and (has_recommendation_hint or has_topology_signal)


def _matches_portal_alarm_analyst_protocol(raw_report_text: str, report_text: str) -> bool:
    if PORTAL_ALARM_ANALYST_CARD_MARKER not in raw_report_text:
        return False
    if "\n---\n" not in raw_report_text:
        return False
    if not report_text.lstrip().startswith("## 告警分析报告"):
        return False
    return all(
        marker in report_text
        for marker in (
            "告警分析报告",
            "告警基础信息",
            "根因判断",
            "影响范围",
            "处置建议",
            "总结",
        )
    )


def build_alarm_analyst_card(
    *,
    chat_id: str,
    message_id: str,
    employee_id: str,
    report_markdown: str,
    process_blocks: Iterable[dict[str, Any] | AlarmAnalystCardProcessBlock],
) -> AlarmAnalystCard:
    if str(employee_id or "").strip() != "fault":
        raise ValueError("alarm analyst cards are only supported for employee_id='fault'")

    raw_report_text = str(report_markdown or "").strip()
    report_text = _unwrap_portal_alarm_analyst_card_content(raw_report_text)
    root_section = _extract_named_section(
        report_text,
        ("根因判断", "根因分析结论", "根因结论", "根因分析", "根因"),
    )
    summary_section = _extract_named_section(report_text, ("总结",))
    impact_section = _extract_named_section(report_text, ("影响范围", "影响分析", "影响面"))
    recommendation_section = _extract_named_section(report_text, ("处置建议", "建议动作", "修复建议", "处置方案"))
    evidence_section = _extract_named_section(report_text, ("证据摘要", "关键证据", "证据", "分析依据"))

    title = _extract_title(report_text)
    conclusion = (
        _first_meaningful_item(root_section)
        or _first_meaningful_item(summary_section)
        or _first_meaningful_item(report_text)
    )
    resource_id = _extract_resource_id(root_section) or _extract_resource_id(report_text)
    resource_name = _extract_root_resource_name(root_section) or _extract_root_resource_name(report_text)
    severity = _detect_severity(report_text)
    confidence, status = _detect_confidence_and_status(root_section or report_text)
    applications, resources, blast_radius_text = _extract_impact_entities(impact_section or report_text)
    nodes, edges = _extract_topology_payload(process_blocks)
    highlighted_node_ids = [item for item in (resource_id, resource_name) if item]
    recommendations = _extract_recommendations(recommendation_section or report_text)
    evidence = _extract_evidence(
        evidence_section=evidence_section,
        conclusion=conclusion,
        blast_radius_text=blast_radius_text,
        topology_nodes=nodes,
        topology_edges=edges,
    )

    return AlarmAnalystCard(
        source=AlarmAnalystCardSource(
            chat_id=str(chat_id or "").strip(),
            message_id=str(message_id or "").strip(),
            content_hash=_build_content_hash(report_text),
        ),
        summary=AlarmAnalystCardSummary(
            title=title,
            conclusion=conclusion,
            severity=severity,
            confidence=confidence,
            status=status,
        ),
        root_cause=AlarmAnalystCardRootCause(
            resource_id=resource_id or None,
            resource_name=resource_name or None,
            ci_id=resource_id or None,
            reason=conclusion,
            candidates=_extract_root_cause_candidates(
                root_section or report_text,
            ),
        ),
        impact=AlarmAnalystCardImpact(
            affected_applications=applications,
            affected_resources=resources,
            blast_radius_text=blast_radius_text or None,
        ),
        topology=AlarmAnalystCardTopology(
            nodes=nodes,
            edges=edges,
            highlighted_node_ids=highlighted_node_ids,
        ),
        recommendations=recommendations,
        evidence=evidence,
        raw_report_markdown=raw_report_text,
    )


def _extract_title(report_markdown: str) -> str:
    heading_match = re.search(
        r"^##+\s*.*?告警分析报告[：:]\s*(.+?)\s*$",
        str(report_markdown or ""),
        flags=re.MULTILINE,
    )
    if heading_match:
        return _sanitize_inline_text(heading_match.group(1)) or "故障根因分析"

    # Try extracting "故障性质" from 📊 总结 section as a structured title
    summary_section = _extract_named_section(report_markdown, ("总结",))
    if summary_section:
        fault_nature = _extract_labeled_value(
            summary_section,
            ("故障性质", "根因方向", "根因结论"),
        )
        if fault_nature and not _is_ai_thinking_text(fault_nature):
            return fault_nature

    for line in str(report_markdown or "").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        text = re.sub(r"^[\W_]+", "", text)
        text = re.split(r"\s+[—-]\s+", text, maxsplit=1)[0].strip()
        if text and not _is_ai_thinking_text(text):
            return text
    return "故障根因分析"


def _unwrap_portal_alarm_analyst_card_content(report_markdown: str) -> str:
    normalized = str(report_markdown or "").replace("\r\n", "\n")
    if (
        PORTAL_ALARM_ANALYST_CARD_MARKER in normalized
        and "\n---\n" in normalized
    ):
        segments = normalized.split("\n---\n")
        marker_index = next(
            (index for index, segment in enumerate(segments) if PORTAL_ALARM_ANALYST_CARD_MARKER in segment),
            -1,
        )
        if marker_index != -1:
            fallback = ""
            collected: list[str] = []
            for segment in segments[marker_index + 1 :]:
                candidate = segment.strip()
                if not candidate:
                    continue
                if not fallback:
                    fallback = candidate
                starts_with_heading = bool(re.match(r"^##+\s+", candidate))
                if not collected:
                    if re.search(r"^##+\s*.*?告警分析报告", candidate, flags=re.MULTILINE):
                        collected.append(candidate)
                    continue
                if not starts_with_heading:
                    break
                collected.append(candidate)
            if collected:
                return "\n\n---\n\n".join(collected)
            if fallback:
                return fallback
    return normalized.strip()


def _extract_named_section(report_markdown: str, names: tuple[str, ...]) -> str:
    if not report_markdown:
        return ""

    headings = list(SECTION_HEADING_RE.finditer(report_markdown))
    if not headings:
        return ""

    normalized_names = {_normalize_heading(name) for name in names}
    for index, heading in enumerate(headings):
        heading_normalized = _normalize_heading(heading.group(1))
        if not any(name in heading_normalized for name in normalized_names):
            continue
        current_level = len(heading.group(0)) - len(heading.group(0).lstrip("#"))
        start = heading.end()
        end = len(report_markdown)
        for next_heading in headings[index + 1 :]:
            next_level = len(next_heading.group(0)) - len(next_heading.group(0).lstrip("#"))
            if next_level <= current_level:
                end = next_heading.start()
                break
        return report_markdown[start:end].strip()
    return ""


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


CANDIDATE_HEADING_RE = re.compile(
    r"^(?:#{2,6}\s*|\*\*)候选根因",
    re.MULTILINE,
)
MAX_ROOT_CAUSE_CANDIDATES = 5
_CANDIDATE_COLUMN_ALIASES = {
    "rank": ("排名", "序号", "top"),
    "reason": ("候选根因", "根因描述", "根因方向", "根因"),
    "resource_name": ("关联资源", "根因资源", "资源", "对象"),
    "confidence": ("置信度",),
    "evidence": ("关键证据", "证据", "依据"),
}


def _extract_root_cause_candidates(
    text: str,
) -> list[AlarmAnalystCardRootCauseCandidate]:
    """Parse the "候选根因" Top-N table from the report.

    Best-effort by design: tolerate column reordering via header-name
    matching, skip malformed rows, and return [] when the model did not
    emit the optional subsection — never fail the card build.
    """
    source = str(text or "")
    heading_match = CANDIDATE_HEADING_RE.search(source)
    if heading_match is None:
        return []
    tail = source[heading_match.end():]
    next_heading = re.search(r"^#{1,6}\s", tail, re.MULTILINE)
    if next_heading is not None:
        tail = tail[: next_heading.start()]

    table_lines = [
        line.strip()
        for line in tail.splitlines()
        if line.strip().startswith("|")
    ]
    if len(table_lines) < 2:
        return []

    def _split_row(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    header_cells = [
        _normalize_heading(cell) for cell in _split_row(table_lines[0])
    ]
    column_index: dict[str, int] = {}
    for field, aliases in _CANDIDATE_COLUMN_ALIASES.items():
        for index, cell in enumerate(header_cells):
            if any(alias in cell for alias in aliases):
                column_index[field] = index
                break
    if "reason" not in column_index:
        return []

    def _cell(cells: list[str], field: str) -> str:
        index = column_index.get(field)
        if index is None or index >= len(cells):
            return ""
        return _sanitize_inline_text(cells[index])

    candidates: list[AlarmAnalystCardRootCauseCandidate] = []
    for line in table_lines[1:]:
        cells = _split_row(line)
        if all(re.fullmatch(r":?-{2,}:?", cell or "-") for cell in cells):
            continue  # markdown separator row
        reason = _cell(cells, "reason")
        if not reason:
            continue
        rank_text = _cell(cells, "rank")
        rank_match = re.search(r"\d+", rank_text)
        rank = (
            int(rank_match.group(0))
            if rank_match
            else len(candidates) + 1
        )
        candidates.append(
            AlarmAnalystCardRootCauseCandidate(
                rank=rank,
                reason=reason,
                resource_name=_cell(cells, "resource_name") or None,
                confidence=_cell(cells, "confidence"),
                evidence=_cell(cells, "evidence") or None,
            )
        )
        if len(candidates) >= MAX_ROOT_CAUSE_CANDIDATES:
            break
    return candidates


TABLE_KV_RE = re.compile(
    r"^\s*\|\s*\**([^|*]{1,30}?)\**\s*\|\s*\**(.+?)\**\s*\|?\s*$",
    re.MULTILINE,
)


_TABLE_HEADER_VALUES = {
    "结论", "内容", "值", "value", "说明", "描述", "备注",
    "步骤", "项目", "维度", "字段", "指标", "当前值",
}


def _first_meaningful_item(text: str) -> str:
    bullets = [
        _sanitize_inline_text(item)
        for item in BULLET_LINE_RE.findall(str(text or ""))
        if _sanitize_inline_text(item)
        and not _is_ai_thinking_text(_sanitize_inline_text(item))
        and _sanitize_inline_text(item) not in _GENERIC_FILLER_VALUES
    ]
    if bullets:
        return bullets[0]

    for line in str(text or "").splitlines():
        if re.match(r"^\s*#{1,6}\s", line):
            continue
        if "|" in line:
            continue
        cleaned = _sanitize_inline_text(line)
        if (
            cleaned
            and not cleaned.startswith("#")
            and not _is_ai_thinking_text(cleaned)
            and cleaned not in _GENERIC_FILLER_VALUES
        ):
            return cleaned

    # Try table rows: | label | value |
    for match in TABLE_KV_RE.finditer(str(text or "")):
        label = _sanitize_inline_text(match.group(1))
        value = _sanitize_inline_text(match.group(2))
        if (
            label and value
            and len(value) > 3
            and not re.match(r"^[-:]+$", label)
            and label not in _TABLE_HEADER_VALUES
            and value not in _TABLE_HEADER_VALUES
            and not _is_ai_thinking_text(value)
            and value not in _GENERIC_FILLER_VALUES
        ):
            return value

    return "已完成故障根因分析。"


def _extract_resource_id(text: str) -> str:
    labeled = _extract_labeled_value(
        text,
        ("资源 ID（CI ID）", "资源 ID(CI ID)", "资源ID（CI ID）", "资源 ID", "CI ID", "resId"),
    )
    if labeled:
        digits = re.search(r"[0-9]{3,}", labeled)
        if digits:
            return digits.group(0)
    match = RESOURCE_ID_RE.search(str(text or ""))
    if match:
        return match.group(1)
    fallback_match = RESOURCE_ID_FALLBACK_RE.search(str(text or ""))
    return fallback_match.group(1) if fallback_match else ""


_RESOURCE_NAME_REJECT_VALUES = {
    "ci id", "ciid", "ci_id", "ci", "resid", "res_id", "res id",
    "资源id", "资源 id", "无", "未知", "n/a", "-", "--", "未配置",
}

_GENERIC_FILLER_VALUES = {
    "已完成故障根因分析。",
    "已完成故障根因分析",
    "已完成根因分析。",
    "已完成根因分析",
    "分析完成。",
    "分析完成",
}

_AI_THINKING_RE = re.compile(
    r"^("
    r"我来分析|我先|先读取|先加载|先并行|先查|先执行|"
    r"好的[，,]|好的。|现在按|现在开始|现在继续|"
    r"技能文档已|文档已读取|文档已加载|"
    r"让我|让我们|"
    r"资源确认为|资源确认完毕|"
    r"很好[！!]|"
    r"接下来|下一步|"
    r"📋\s*Step|"
    r"\d+\.\s*(?:查|读取|确认|执行)|"
    r"拓扑关系中|指标值返回|"
    r"关键发现|数据完整|数据非常|"
    r"现在推送|分析报告已"
    r")",
    re.UNICODE,
)


def _is_ai_thinking_text(text: str) -> bool:
    cleaned = re.sub(r"^[\W_]+", "", str(text or "").strip())
    if not cleaned:
        return False
    return bool(_AI_THINKING_RE.match(cleaned))


def _extract_root_resource_name(text: str) -> str:
    labeled = _extract_labeled_value(
        text,
        ("设备名称", "资源名称", "根因资源", "根资源", "实例", "资产编号"),
    )
    if labeled and labeled.lower().strip() not in _RESOURCE_NAME_REJECT_VALUES:
        return labeled
    match = ROOT_RESOURCE_RE.search(str(text or ""))
    if match:
        value = match.group(1).strip()
        if value.lower() not in _RESOURCE_NAME_REJECT_VALUES:
            return value
    return ""


def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str:
    normalized = str(text or "")
    for label in labels:
        escaped = re.escape(label)
        table_pattern = re.compile(
            rf"\|\s*(?:\*\*)?{escaped}(?:\*\*)?\s*\|\s*([^|\n]+?)\s*\|",
            re.IGNORECASE,
        )
        line_pattern = re.compile(
            rf"(?:^|\n)\s*(?:[-*•]\s*)?{escaped}\s*[：:]\s*([^\n]+)",
            re.IGNORECASE,
        )
        match = table_pattern.search(normalized) or line_pattern.search(normalized)
        if match:
            value = _sanitize_inline_text(match.group(1))
            if value:
                return value
    return ""


def _detect_severity(text: str) -> str | None:
    normalized = str(text or "").lower()
    for label, keywords in SEVERITY_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return label
    return None


def _detect_confidence_and_status(text: str) -> tuple[str, str]:
    normalized = str(text or "")
    if not normalized.strip():
        return "low", "unknown"
    if any(keyword in normalized for keyword in ("疑似", "可能", "待确认", "怀疑")):
        return "medium", "suspected"
    return "high", "identified"


def _extract_impact_entities(
    text: str,
) -> tuple[list[AlarmAnalystCardImpactEntity], list[AlarmAnalystCardImpactEntity], str]:
    applications: list[AlarmAnalystCardImpactEntity] = []
    resources: list[AlarmAnalystCardImpactEntity] = []
    blast_radius_text = ""
    current_group: str | None = None

    for line in str(text or "").splitlines():
        raw_cleaned = str(line or "").strip()
        cleaned = _sanitize_inline_text(raw_cleaned)
        if not cleaned:
            continue
        normalized_label = _normalize_heading(cleaned)
        application_match = APPLICATION_VALUE_RE.match(cleaned)
        resource_match = RESOURCE_VALUE_RE.match(cleaned)

        if normalized_label in {_normalize_heading(value) for value in SECTION_ONLY_APPLICATIONS}:
            current_group = "application"
            continue
        if normalized_label in {_normalize_heading(value) for value in SECTION_ONLY_RESOURCES}:
            current_group = "resource"
            continue
        if raw_cleaned.startswith("#"):
            current_group = None
            continue

        if application_match:
            current_group = "application"
            applications.extend(_build_impact_entities(application_match.group(1), kind="application"))
            continue
        if resource_match:
            current_group = "resource"
            resources.extend(_build_impact_entities(resource_match.group(1), kind="resource"))
            continue

        if current_group == "application":
            matched_entities = _build_impact_entities(cleaned, kind="application")
            if matched_entities:
                applications.extend(matched_entities)
                continue
        elif current_group == "resource":
            matched_entities = _build_impact_entities(cleaned, kind="resource")
            if matched_entities:
                resources.extend(matched_entities)
                continue

        if not blast_radius_text and _is_readable_summary_line(raw_cleaned, cleaned):
            blast_radius_text = cleaned[:120]

    deduped_applications = _dedupe_entities(applications)
    deduped_resources = _dedupe_entities(resources)
    summarized_blast_radius = _summarize_blast_radius(deduped_applications, deduped_resources)
    if summarized_blast_radius and (
        not blast_radius_text or not re.match(r"^(影响|波及|涉及)", blast_radius_text)
    ):
        blast_radius_text = summarized_blast_radius
    return deduped_applications, deduped_resources, blast_radius_text


def _split_named_values(line: str) -> list[str]:
    tail = re.split(r"[:：]", line, maxsplit=1)
    value_text = tail[1] if len(tail) > 1 else line
    values = [
        _sanitize_inline_text(item)
        for item in re.split(r"[、,，/；;]+", value_text)
        if _sanitize_inline_text(item)
    ]
    return values


def _dedupe_entities(
    entities: Iterable[AlarmAnalystCardImpactEntity],
) -> list[AlarmAnalystCardImpactEntity]:
    deduped: list[AlarmAnalystCardImpactEntity] = []
    seen: set[tuple[str | None, str]] = set()
    for entity in entities:
        key = (entity.id, entity.name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)
    return deduped


def _extract_recommendations(text: str) -> list[AlarmAnalystCardRecommendation]:
    recommendations: list[AlarmAnalystCardRecommendation] = []
    items = BULLET_LINE_RE.findall(str(text or ""))

    for index, item in enumerate(items):
        content = _sanitize_inline_text(item)
        if not content:
            continue
        priority = _detect_priority(content, fallback=index)
        title = _extract_brief_title(content, fallback=f"建议 {index + 1}")
        recommendations.append(
            AlarmAnalystCardRecommendation(
                title=title,
                priority=priority,
                description=content,
                risk=_extract_risk(content),
                action_type=_detect_action_type(content),
            )
        )

    return recommendations


def _detect_priority(text: str, fallback: int = 0) -> str:
    match = re.search(r"\b(P[0-2])\b", str(text or ""), flags=re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return "p0" if fallback == 0 else "p1" if fallback == 1 else "p2"


def _extract_risk(text: str) -> str | None:
    match = re.search(r"(?:风险|risk)[:：]?\s*([^。；;\n]+)", str(text or ""), flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _detect_action_type(text: str) -> str:
    normalized = str(text or "").lower()
    if any(keyword in normalized for keyword in ("脚本", "sql", "命令", "执行")):
        return "script"
    if any(keyword in normalized for keyword in ("观察", "监控", "收敛", "确认恢复")):
        return "observe"
    return "manual"


def _extract_evidence(
    *,
    evidence_section: str,
    conclusion: str,
    blast_radius_text: str,
    topology_nodes: list[dict[str, Any]],
    topology_edges: list[dict[str, Any]],
) -> list[AlarmAnalystCardEvidence]:
    evidence: list[AlarmAnalystCardEvidence] = []

    for item in BULLET_LINE_RE.findall(str(evidence_section or "")):
        cleaned = _sanitize_inline_text(item)
        if not cleaned:
            continue
        evidence.append(
            AlarmAnalystCardEvidence(
                kind=_detect_evidence_kind(cleaned),
                title=_extract_brief_title(cleaned, fallback="关键证据"),
                summary=cleaned,
            )
        )

    if not evidence and conclusion and conclusion not in _GENERIC_FILLER_VALUES:
        evidence.append(
            AlarmAnalystCardEvidence(
                kind="alarm",
                title="根因结论",
                summary=conclusion,
            )
        )
    if not evidence and blast_radius_text:
        evidence.append(
            AlarmAnalystCardEvidence(
                kind="cmdb",
                title="影响范围",
                summary=blast_radius_text,
            )
        )
    if topology_nodes or topology_edges:
        evidence.append(
            AlarmAnalystCardEvidence(
                kind="tool",
                title="拓扑分析",
                summary=f"识别 {len(topology_nodes)} 个节点、{len(topology_edges)} 条关系。",
            )
        )

    return evidence[:4]


def _detect_evidence_kind(text: str) -> str:
    normalized = str(text or "").lower()
    if "告警" in normalized:
        return "alarm"
    if "指标" in normalized or "metric" in normalized:
        return "metric"
    if "拓扑" in normalized or "cmdb" in normalized:
        return "cmdb"
    return "tool"


def _extract_topology_payload(
    process_blocks: Iterable[dict[str, Any] | AlarmAnalystCardProcessBlock],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    for block in process_blocks or []:
        output_content = _get_block_value(block, "output_content", "outputContent") or ""
        for payload in _iter_json_payloads(output_content):
            series_list = payload.get("series")
            if not isinstance(series_list, list):
                continue
            for series in series_list:
                if not isinstance(series, dict):
                    continue
                series_type = str(series.get("type") or "").lower()
                if series_type == "tree":
                    nodes, edges = _flatten_tree_series(series)
                    if nodes:
                        return nodes, edges
                    continue
                if series_type != "graph":
                    continue
                nodes = series.get("data") if isinstance(series.get("data"), list) else []
                edges = series.get("links") if isinstance(series.get("links"), list) else []
                return list(nodes), list(edges)
    return [], []


def _flatten_tree_series(
    series: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flatten an echarts `series.type='tree'` payload into flat nodes/edges.

    `alarm-analyst` is instructed to prefer `type='tree'` for topology, but
    the rest of the card pipeline (evidence detection, structured chart,
    highlighting) works on flat graph-style nodes/edges — so tree data is
    converted here rather than requiring a second representation upstream.
    """
    roots = series.get("data")
    if not isinstance(roots, list):
        return [], []

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _walk(node: Any, path: str, parent_id: str | None) -> None:
        if not isinstance(node, dict):
            return
        name = str(node.get("name") or "").strip()
        raw_id = node.get("id")
        node_id = str(raw_id).strip() if isinstance(raw_id, (str, int)) and str(raw_id).strip() else path
        if node_id in seen_ids:
            node_id = f"{node_id}#{len(nodes)}"
        seen_ids.add(node_id)
        nodes.append({"id": node_id, "name": name or node_id})
        if parent_id is not None:
            edges.append({"source": parent_id, "target": node_id})

        children = node.get("children")
        if isinstance(children, list):
            for index, child in enumerate(children):
                child_name = child.get("name") if isinstance(child, dict) else index
                _walk(child, f"{path}/{index}:{child_name}", node_id)

    for root_index, root in enumerate(roots):
        root_name = root.get("name") if isinstance(root, dict) else root_index
        _walk(root, f"root{root_index}:{root_name}", None)

    return nodes, edges


def _iter_json_payloads(text: str) -> Iterable[dict[str, Any]]:
    stripped = str(text or "").strip()
    if not stripped:
        return []

    candidates = []
    candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", stripped, flags=re.IGNORECASE))
    candidates.append(stripped)

    payloads: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def _get_block_value(
    block: dict[str, Any] | AlarmAnalystCardProcessBlock,
    *keys: str,
) -> Any:
    if isinstance(block, AlarmAnalystCardProcessBlock):
        for key in keys:
            if hasattr(block, key):
                return getattr(block, key)
        return None
    if isinstance(block, dict):
        for key in keys:
            if key in block:
                return block.get(key)
    return None


def _build_content_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()[:16]


def _sanitize_inline_text(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+|\d+[、)]\s+)?", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("`", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" |：:-")


def _build_impact_entities(value_text: str, *, kind: str) -> list[AlarmAnalystCardImpactEntity]:
    entities: list[AlarmAnalystCardImpactEntity] = []
    for value in _split_named_values(value_text):
        entity_name = _sanitize_entity_name(value)
        if not entity_name:
            continue
        entities.append(
            AlarmAnalystCardImpactEntity(
                id=entity_name if kind == "resource" and entity_name.isdigit() else None,
                name=entity_name,
            )
        )
    return entities


def _sanitize_entity_name(value: str) -> str:
    cleaned = _sanitize_inline_text(value)
    if not cleaned or len(cleaned) > 32:
        return ""
    if "|" in str(value or ""):
        return ""
    if len(cleaned.split()) > 4:
        return ""
    if not ENTITY_NAME_RE.fullmatch(cleaned):
        return ""
    if re.search(r"(查询|拓扑|告警|窗口|任务|变更|链路|写入|恢复|确认)", cleaned) and len(cleaned) > 12:
        return ""
    return cleaned


def _is_readable_summary_line(raw_line: str, cleaned_line: str) -> bool:
    if not cleaned_line or len(cleaned_line) > 120:
        return False
    if "|" in str(raw_line or ""):
        return False
    if "完整故障分析报告" in cleaned_line or "告警分析报告" in cleaned_line:
        return False
    if _is_ai_thinking_text(cleaned_line):
        return False
    if cleaned_line in _GENERIC_FILLER_VALUES:
        return False
    if APPLICATION_VALUE_RE.match(cleaned_line) or RESOURCE_VALUE_RE.match(cleaned_line):
        return False
    if re.search(r"(query|拓扑|确认|链路|写入|调用)", cleaned_line, flags=re.IGNORECASE):
        return False
    normalized = _normalize_heading(cleaned_line)
    if normalized in {_normalize_heading(value) for value in SECTION_ONLY_APPLICATIONS | SECTION_ONLY_RESOURCES}:
        return False
    return True


def _summarize_blast_radius(
    applications: list[AlarmAnalystCardImpactEntity],
    resources: list[AlarmAnalystCardImpactEntity],
) -> str:
    parts: list[str] = []
    if applications:
        parts.append(f"{len(applications)} 个应用")
    if resources:
        parts.append(f"{len(resources)} 个资源")
    return f"影响 {('、'.join(parts))}" if parts else ""


def _extract_brief_title(text: str, *, fallback: str) -> str:
    content = re.sub(r"^(P[0-2])[:：\s-]*", "", str(text or ""), flags=re.IGNORECASE).strip()
    content = _sanitize_inline_text(content)
    title = re.split(r"\s*(?:→|->|=>|；|;|。)\s*", content, maxsplit=1)[0].strip()
    return (title[:32] or fallback).strip()


# ---------------------------------------------------------------------------
# Summary-table label aliases (mirrors frontend SUMMARY_LABEL_ALIASES)
# ---------------------------------------------------------------------------
_SUMMARY_LABEL_ALIASES: dict[str, str] = {
    "影响面": "影响范围",
    "根因结论": "根因方向",
    "优先建议": "优先动作",
    "关键问题": "关键提醒",
    "关联告警查询": "关联资源告警查询状态",
    "关联告警": "关联资源告警查询状态",
    "关联资源告警查询": "关联资源告警查询状态",
    "关联资源告警": "关联资源告警查询状态",
}

_SUMMARY_DISPLAY_LABELS = [
    "置信度",
    "故障性质",
    "根因方向",
    "影响范围",
    "优先动作",
    "关联资源告警查询状态",
    "关键提醒",
]


def extract_display_fields(card_dict: dict[str, Any]) -> dict[str, Any]:
    """Extract the display-ready fields from a card dict.

    Mirrors the frontend card display: parses the 📊 总结 section
    and structured card fields, returns English-keyed dict matching
    what the UI shows.
    """
    raw_md = str(card_dict.get("rawReportMarkdown") or "")
    summary_section = _extract_named_section(raw_md, ("总结",))

    # Parse label:value pairs from bullets and table rows
    rows_by_label: dict[str, str] = {}
    if summary_section:
        for line in summary_section.splitlines():
            label = ""
            value = ""

            # Try table row: | **label** | value |
            table_match = TABLE_KV_RE.match(line)
            if table_match:
                label = _sanitize_inline_text(table_match.group(1)).strip()
                value = _sanitize_inline_text(table_match.group(2)).strip()
            else:
                # Try bullet: - label：value
                bullet_match = re.match(
                    r"^\s*[-*•]\s*\**([^：:]{1,24}?)\**\s*[：:]\s*(.+)$", line
                )
                if bullet_match:
                    label = _sanitize_inline_text(bullet_match.group(1)).strip()
                    value = _sanitize_inline_text(bullet_match.group(2)).strip()

            if not label or not value:
                continue
            if re.match(r"^[-:]+$", label) or re.match(r"^[-:]+$", value):
                continue

            # Normalize alias
            normalized_label = _SUMMARY_LABEL_ALIASES.get(label, label)
            if normalized_label not in rows_by_label:
                rows_by_label[normalized_label] = value

    # Build the display result with English keys
    summary = card_dict.get("summary") or {}
    root_cause = card_dict.get("rootCause") or {}

    # Title: prefer report heading, fallback to summary.title
    title_match = re.search(
        r"^##+\s*.*?告警分析报告[：:]\s*(.+?)\s*$", raw_md, re.MULTILINE
    )
    title = (
        _sanitize_inline_text(title_match.group(1))
        if title_match
        else _sanitize_inline_text(summary.get("title") or "")
    ) or "故障根因分析"

    resource_name = _sanitize_inline_text(root_cause.get("resourceName") or "")
    fault_nature = rows_by_label.get("故障性质", "")
    root_cause_direction = rows_by_label.get("根因方向", "")
    confidence = rows_by_label.get("置信度", "")

    # Fallback to structured card fields
    if not fault_nature:
        fault_nature = _sanitize_inline_text(summary.get("conclusion") or "")
    if not root_cause_direction:
        root_cause_direction = _sanitize_inline_text(root_cause.get("reason") or "")
    if not confidence:
        raw_conf = summary.get("confidence") or ""
        if raw_conf in ("high", "高"):
            confidence = "90%"
        elif raw_conf in ("medium", "中"):
            confidence = "70%"
        elif raw_conf in ("low", "低"):
            confidence = "50%"

    result: dict[str, Any] = {
        "title": title,
        "anchorObject": resource_name,
        "faultNature": fault_nature,
        "rootCauseDirection": root_cause_direction,
        "impactScope": rows_by_label.get("影响范围", ""),
        "priorityAction": rows_by_label.get("优先动作", ""),
        "relatedAlarmQueryStatus": rows_by_label.get("关联资源告警查询状态", ""),
        "keyReminder": rows_by_label.get("关键提醒", ""),
        "confidence": confidence,
        "rootCauseType": fault_nature,
        "rootCauseObject": resource_name,
        "faultReason": root_cause_direction,
    }

    # Remove empty values
    return {k: v for k, v in result.items() if v}
