# -*- coding: utf-8 -*-
"""Mock smoke for the golden eval harness (real-LLM grading is p1)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen import evals
from qwenpaw.extensions.ai_big_screen.evals import (
    EvalCase,
    run_evals,
    score_screen,
)


def _component(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "comp-1",
        "type": "table",
        "capabilityId": "workorders",
        "data": {"sourceStatus": "live", "rows": [{"id": "wo-1"}]},
    }
    payload.update(overrides)
    return payload


def _screen(components: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": "screen-1", "name": "工单屏", "components": components}


CASE = EvalCase(
    case_id="case-x",
    prompt="查询今日工单",
    expect_capabilities=frozenset({"workorders"}),
    forbid_capabilities=frozenset({"real-alarms"}),
)


class TestScorer:
    def test_good_screen_passes(self) -> None:
        result = score_screen(CASE, _screen([_component()]))
        assert result == {
            "caseId": "case-x",
            "passed": True,
            "reasons": [],
        }

    def test_missing_capability_fails(self) -> None:
        screen = _screen([_component(capabilityId="system-logs")])
        result = score_screen(CASE, screen)
        assert not result["passed"]
        assert any("缺少期望能力" in r for r in result["reasons"])

    def test_forbidden_capability_fails(self) -> None:
        screen = _screen(
            [
                _component(),
                _component(id="comp-2", capabilityId="real-alarms"),
            ],
        )
        result = score_screen(CASE, screen)
        assert not result["passed"]
        assert any("禁止能力" in r for r in result["reasons"])

    def test_dishonest_source_status_fails(self) -> None:
        screen = _screen(
            [_component(data={"sourceStatus": "mock", "rows": []})],
        )
        result = score_screen(CASE, screen)
        assert not result["passed"]
        assert any("不诚实" in r for r in result["reasons"])

    def test_missing_status_fails(self) -> None:
        screen = _screen([_component(data={"rows": []})])
        result = score_screen(CASE, screen)
        assert not result["passed"]

    def test_component_count_and_diversity(self) -> None:
        case = EvalCase(
            case_id="diverse",
            prompt="x",
            min_components=2,
            min_distinct_types=2,
        )
        screen = _screen([_component()])
        result = score_screen(case, screen)
        joined = "\n".join(result["reasons"])
        assert "组件数" in joined
        assert "多样性" in joined

    def test_require_composed(self) -> None:
        case = EvalCase(case_id="gen", prompt="x", require_composed=True)
        result = score_screen(case, _screen([_component()]))
        assert any("composed" in r for r in result["reasons"])

    def test_honest_failed_status_still_passes(self) -> None:
        # honest failure is acceptable structure — never a fake number
        screen = _screen(
            [_component(data={"sourceStatus": "failed", "rows": []})],
        )
        result = score_screen(CASE, screen)
        assert result["passed"]


class TestHarnessSmoke:
    async def test_fast_path_case_passes_end_to_end(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from qwenpaw.extensions.ai_big_screen import store
        from qwenpaw.extensions.ai_big_screen.capabilities import (
            descriptors,
        )

        monkeypatch.setattr(
            store,
            "DEFAULT_DB_PATH",
            tmp_path / "ai_big_screen.sqlite3",
        )
        monkeypatch.setattr(store, "_DEFAULT_MIGRATION_DONE", True)
        monkeypatch.setitem(
            descriptors.FETCHERS,
            "workorders",
            lambda _params: {
                "sourceStatus": "live",
                "rows": [{"id": "wo-1", "title": "磁盘工单"}],
                "stats": {"todo": 1},
            },
        )

        class ForbiddenModel:
            async def __call__(self, _messages: Any) -> Any:
                raise AssertionError("fast-path eval must not call LLM")

        fast_cases = [
            case
            for case in evals.GOLDEN_CASES
            if case.case_id == "workorders-today"
        ]
        assert fast_cases, "golden set must keep a fast-path case"
        summary = await run_evals(fast_cases, model=ForbiddenModel())
        assert summary["total"] == 1
        assert summary["passRate"] == 1.0
        assert summary["results"][0]["reasons"] == []

    async def test_pipeline_crash_counts_as_failed_case(self) -> None:
        case = EvalCase(case_id="empty", prompt="   ")
        summary = await run_evals([case])
        assert summary["passed"] == 0
        assert summary["passRate"] == 0.0
        assert any(
            "pipeline 异常" in r for r in summary["results"][0]["reasons"]
        )

    def test_golden_set_is_well_formed(self) -> None:
        ids = [case.case_id for case in evals.GOLDEN_CASES]
        assert len(ids) == len(set(ids))
        for case in evals.GOLDEN_CASES:
            assert case.prompt.strip()
            assert case.min_components >= 1
