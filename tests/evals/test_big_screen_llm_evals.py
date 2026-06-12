# -*- coding: utf-8 -*-
"""Nightly real-LLM grading of the big-screen golden set (p1).

Runs the full draft pipeline (real LLM, real integrations — honest
``failed`` statuses are acceptable) over ``GOLDEN_CASES`` and asserts
a pass-rate floor. Costs real model calls, so it is double-gated:
``QWENPAW_RUN_LLM_EVALS=1`` must be set AND a default model must be
configured; otherwise the test skips.
"""
from __future__ import annotations

import json
import os

import pytest

from qwenpaw.extensions.ai_big_screen.evals import GOLDEN_CASES, run_evals
from qwenpaw.extensions.ai_big_screen.llm import create_pipeline_model

pytestmark = [pytest.mark.p1, pytest.mark.slow]

#: starting quality floor; T5 records the measured baseline and the
#: floor should only ever move up.
PASS_RATE_FLOOR = 0.6


def _llm_evals_enabled() -> bool:
    return os.environ.get("QWENPAW_RUN_LLM_EVALS", "").strip() in {
        "1",
        "true",
        "on",
    }


async def test_golden_set_pass_rate_floor() -> None:
    if not _llm_evals_enabled():
        pytest.skip("set QWENPAW_RUN_LLM_EVALS=1 to run real-LLM evals")
    try:
        create_pipeline_model()
    except ValueError as exc:
        pytest.skip(f"no usable default LLM: {exc}")

    summary = await run_evals(GOLDEN_CASES)
    # keep the full verdict in the nightly log for baseline tracking
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    failed = [r for r in summary["results"] if not r["passed"]]
    assert summary["passRate"] >= PASS_RATE_FLOOR, (
        f"golden pass rate {summary['passRate']:.2f} below floor"
        f" {PASS_RATE_FLOOR}: {json.dumps(failed, ensure_ascii=False)}"
    )
