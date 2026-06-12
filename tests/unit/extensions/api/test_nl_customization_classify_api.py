# -*- coding: utf-8 -*-
"""轻应用入口分类端点（/nl-customization/classify）测试。

刻意不 mock 模型工厂：classify 必须是纯规则路径，
任何对 LLM 的调用都会因无可用模型而暴露。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.extensions.api.natural_language_customization_api import (
    router as nl_customization_router,
)


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(nl_customization_router, prefix="/api/portal")
    return TestClient(app)


def _classify(client: TestClient, prompt: str) -> dict:
    response = client.post(
        "/api/portal/nl-customization/classify",
        json={"prompt": prompt},
    )
    assert response.status_code == 200
    return response.json()


def test_classify_report_prompt_recommends_page() -> None:
    client = _make_client()
    payload = _classify(client, "做一个本周告警 TOP10 报表")

    assert payload["recommendedKind"] == "page"
    assert payload["scenarioType"] == "portal-dashboard"


def test_classify_page_keyword_overrides_task_scenario() -> None:
    client = _make_client()
    payload = _classify(client, "做一个展示告警趋势图页面")

    assert payload["recommendedKind"] == "page"


def test_classify_dashboard_keyword_recommends_page() -> None:
    client = _make_client()
    payload = _classify(client, "给我一个 ops dashboard")

    assert payload["recommendedKind"] == "page"


def test_classify_inspection_prompt_recommends_task() -> None:
    client = _make_client()
    payload = _classify(client, "每天 8 点对 Oracle 做巡检并通知我")

    assert payload["recommendedKind"] == "task"
    assert payload["scenarioType"] == "inspection"
    assert payload["triggerType"] == "schedule"


def test_classify_alert_prompt_recommends_task() -> None:
    client = _make_client()
    payload = _classify(client, "出现告警时自动分析根因")

    assert payload["recommendedKind"] == "task"


def test_classify_empty_prompt_returns_400() -> None:
    client = _make_client()
    response = client.post(
        "/api/portal/nl-customization/classify",
        json={"prompt": "   "},
    )

    assert response.status_code == 400
    assert "prompt 不能为空" in response.json()["detail"]
