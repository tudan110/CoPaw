# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen import telemetry


@pytest.fixture(name="db_path")
def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "ai_big_screen" / "ai_big_screen.sqlite3"


def _event(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "draft",
        "success": True,
        "degraded": False,
        "durationMs": 1200,
        "screenId": "screen-x",
        "promptChars": 24,
        "llmAttempts": 1,
        "stages": {"意图解析": 400, "取数": 600, "视觉编排": 150},
        "capabilityStatuses": {"real-alarms": "live", "workorders": "live"},
        "componentTypes": ["flip-number", "donut", "alarm-stream"],
        "error": "",
    }
    payload.update(overrides)
    return payload


class TestRecordAndSummarize:
    def test_roundtrip_and_rates(self, db_path: Path) -> None:
        telemetry.record_generation(_event(), path=db_path)
        telemetry.record_generation(
            _event(degraded=True, durationMs=3000),
            path=db_path,
        )
        telemetry.record_generation(
            _event(
                success=False,
                durationMs=500,
                error="boom",
                capabilityStatuses={"real-alarms": "failed"},
            ),
            path=db_path,
        )
        summary = telemetry.summarize(path=db_path)
        assert summary["total"] == 3
        assert summary["successRate"] == pytest.approx(2 / 3)
        assert summary["degradedRate"] == pytest.approx(1 / 3)
        assert summary["avgDurationMs"] == pytest.approx(
            (1200 + 3000 + 500) / 3,
        )
        failure_rates = summary["capabilityFailureRates"]
        assert failure_rates["real-alarms"] == pytest.approx(1 / 3)
        assert failure_rates["workorders"] == pytest.approx(0.0)
        assert summary["kinds"]["draft"] == 3

    def test_window_limit(self, db_path: Path) -> None:
        for index in range(10):
            telemetry.record_generation(
                _event(success=index % 2 == 0),
                path=db_path,
            )
        summary = telemetry.summarize(limit=4, path=db_path)
        assert summary["total"] == 4

    def test_empty_db_summary(self, db_path: Path) -> None:
        summary = telemetry.summarize(path=db_path)
        assert summary["total"] == 0
        assert summary["successRate"] == 0.0

    def test_record_never_raises(self) -> None:
        # unwritable path → swallowed, generation must not break
        telemetry.record_generation(
            _event(),
            path=Path("Z:/no/such/dir/x.sqlite3"),
        )


class TestPipelineIntegration:
    async def test_draft_pipeline_records_metrics(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db_path: Path,
    ) -> None:
        from qwenpaw.extensions.ai_big_screen import store
        from qwenpaw.extensions.ai_big_screen.pipeline import (
            run_draft_pipeline,
        )
        from qwenpaw.extensions.integrations import order_workflow

        monkeypatch.setattr(store, "DEFAULT_DB_PATH", db_path)
        monkeypatch.setattr(
            store,
            "DEFAULT_REGISTRY_PATH",
            db_path.parent / "registry.json",
        )
        monkeypatch.setattr(store, "_DEFAULT_MIGRATION_DONE", True)
        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: {
                "source": "live",
                "total": 1,
                "items": [{"id": "wo-1", "title": "x"}],
            },
        )

        class ForbiddenModel:
            async def __call__(self, _messages: Any) -> Any:
                raise AssertionError("fast-path must not call LLM")

        await run_draft_pipeline(
            prompt="查询今日工单",
            model=ForbiddenModel(),
        )
        summary = telemetry.summarize(path=db_path)
        assert summary["total"] == 1
        assert summary["successRate"] == 1.0
        assert summary["kinds"]["draft"] == 1
        events = telemetry.recent_events(limit=1, path=db_path)
        event = events[0]
        assert event["capabilityStatuses"]["workorders"] == "live"
        assert event["componentTypes"]
        assert event["durationMs"] >= 0
        assert "取数" in event["stages"]
