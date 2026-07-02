# -*- coding: utf-8 -*-
"""Golden-prompt eval harness (M2): grade generation quality.

Each :class:`EvalCase` pins what a correct screen for a prompt must
look like *structurally* — capability routing, component coverage,
type diversity, honest source statuses — never the data values
themselves (data comes from live systems and changes). The scorer is
pure and deterministic: the same screen always gets the same verdict
with machine-readable reasons. Intelligence quality is then a number:
run the real pipeline over :data:`GOLDEN_CASES` (p1 nightly, real
LLM) and read the aggregated pass rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qwenpaw.extensions.ai_big_screen.llm import ModelCallable
from qwenpaw.extensions.ai_big_screen.pipeline import run_draft_pipeline

#: the honest source statuses a rendered component may carry; anything
#: else (or a missing status) means fabricated/unaccounted data.
ALLOWED_SOURCE_STATUSES = frozenset({"live", "empty", "failed", "gap"})


@dataclass(frozen=True)
class EvalCase:
    """One golden prompt plus its structural acceptance criteria."""

    case_id: str
    prompt: str
    #: capability ids that must all appear on the screen
    expect_capabilities: frozenset[str] = frozenset()
    #: capability ids that must NOT appear (wrong-routing detector)
    forbid_capabilities: frozenset[str] = frozenset()
    min_components: int = 1
    min_distinct_types: int = 1
    require_composed: bool = False


GOLDEN_CASES: tuple[EvalCase, ...] = (
    # deterministic fast-path: simple data query must route to the
    # workorder capability and nothing alarm/log shaped
    EvalCase(
        case_id="workorders-today",
        prompt="查询今日工单",
        expect_capabilities=frozenset({"workorders"}),
        forbid_capabilities=frozenset({"real-alarms", "system-logs"}),
    ),
    # LLM path: analysis intent over alarms
    EvalCase(
        case_id="alarms-distribution",
        prompt="分析当前告警分布和高危风险",
        expect_capabilities=frozenset({"real-alarms"}),
        forbid_capabilities=frozenset({"workorders"}),
    ),
    # LLM path: mixed prompt — half catalog capability, half open-web
    # retrieval; the weather clause must not be silently dropped
    EvalCase(
        case_id="logs-and-weather",
        prompt="查询15分钟系统日志，南京天气",
        expect_capabilities=frozenset({"system-logs", "web-live-data"}),
        min_components=2,
    ),
    # LLM path: mixed prompt with a fabricated internal-system ask that
    # is neither a catalog capability nor a public-web query. Proves the
    # completeness patch (_fill_uncovered_clauses) is general, not a
    # weather-specific keyword list: the unmatched clause must surface
    # as an honest capability-gap, never vanish silently, while the
    # matched clause still routes correctly.
    EvalCase(
        case_id="workorders-and-invented-source",
        prompt="查询今日工单，以及库存管理系统的库存周转率",
        expect_capabilities=frozenset({"workorders", "capability-gap"}),
        min_components=2,
    ),
    # LLM path: nothing in the catalog covers stock prices — the
    # honest answers are open-web retrieval or an explicit gap, never
    # a data-bearing wrong route
    EvalCase(
        case_id="stock-fallback",
        prompt="展示阿里巴巴最新股价走势",
        forbid_capabilities=frozenset(
            {"workorders", "real-alarms", "system-logs", "cmdb-resources"},
        ),
    ),
    # LLM path: broad cockpit ask must produce a multi-capability,
    # visually diverse screen
    EvalCase(
        case_id="executive-cockpit",
        prompt="做一个领导驾驶舱，展示核心指标、告警态势和工单总览",
        expect_capabilities=frozenset({"real-alarms", "workorders"}),
        min_components=3,
        min_distinct_types=2,
    ),
)


def _component_capability_id(component: Mapping[str, Any]) -> str:
    return str(
        component.get("capabilityId") or component.get("pluginId") or "",
    )


def score_screen(
    case: EvalCase,
    screen: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministically grade one screen against one golden case."""
    reasons: list[str] = []
    components = [
        component
        for component in (screen.get("components") or [])
        if isinstance(component, Mapping)
    ]

    if len(components) < case.min_components:
        reasons.append(
            f"组件数 {len(components)} < 下限 {case.min_components}",
        )

    used = {_component_capability_id(component) for component in components}
    used.discard("")
    missing = case.expect_capabilities - used
    if missing:
        reasons.append(f"缺少期望能力: {sorted(missing)} (实际 {sorted(used)})")
    forbidden = case.forbid_capabilities & used
    if forbidden:
        reasons.append(f"出现禁止能力(错误路由): {sorted(forbidden)}")

    types = [str(component.get("type") or "") for component in components]
    if len(set(types)) < case.min_distinct_types:
        reasons.append(
            f"组件类型多样性 {len(set(types))} < 下限"
            f" {case.min_distinct_types} (实际 {sorted(set(types))})",
        )
    if case.require_composed and "composed" not in types:
        reasons.append("期望至少一个 composed 即时创作组件")

    for component in components:
        data = component.get("data")
        status = (
            str(data.get("sourceStatus") or "")
            if isinstance(data, Mapping)
            else ""
        )
        if status not in ALLOWED_SOURCE_STATUSES:
            reasons.append(
                f"组件 {component.get('id')} 状态不诚实:" f" sourceStatus={status!r}",
            )

    if not str(screen.get("name") or "").strip():
        reasons.append("大屏缺少标题")

    return {
        "caseId": case.case_id,
        "passed": not reasons,
        "reasons": reasons,
    }


async def run_case(
    case: EvalCase,
    *,
    model: ModelCallable | None = None,
) -> dict[str, Any]:
    """Run the real pipeline for one case and grade the result."""
    try:
        screen = await run_draft_pipeline(prompt=case.prompt, model=model)
    except Exception as exc:  # a crashed pipeline is a failed case
        return {
            "caseId": case.case_id,
            "passed": False,
            "reasons": [f"pipeline 异常: {exc}"],
        }
    return score_screen(case, screen)


async def run_evals(
    cases: Sequence[EvalCase] = GOLDEN_CASES,
    *,
    model: ModelCallable | None = None,
) -> dict[str, Any]:
    """Run the golden set sequentially and aggregate the pass rate.

    Sequential on purpose: deterministic ordering and no thundering
    herd against the real LLM/integrations during nightly runs.
    """
    results = [await run_case(case, model=model) for case in cases]
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    return {
        "total": total,
        "passed": passed,
        "passRate": passed / total if total else 0.0,
        "results": results,
    }
