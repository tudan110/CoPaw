# -*- coding: utf-8 -*-
"""Contract tests for the AI-backed system situation summary."""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_build_system_summary_uses_live_facts_and_model_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    cmdb_calls = 0

    def query_cmdb_summary() -> dict:
        nonlocal cmdb_calls
        cmdb_calls += 1
        return {"code": 200, "data": {"total_ci_count": 128}}

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_cmdb_summary",
        query_cmdb_summary,
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 130}},
    )
    monkeypatch.setattr(
        service.portal_real_alarms,
        "query_portal_real_alarms",
        lambda **_kwargs: {
            "total": 3,
            "source": "live",
            "items": [
                {
                    "alarmId": "a-1",
                    "title": "MySQL 锁异常",
                    "level": "critical",
                    "levelName": "紧急",
                    "deviceName": "mysql-01",
                    "resId": "ci-01",
                    "eventTime": "2026-07-16 08:00:00",
                },
                {
                    "alarmId": "a-2",
                    "title": "MySQL 锁异常",
                    "level": "urgent",
                    "levelName": "严重",
                    "deviceName": "mysql-01",
                    "resId": "ci-01",
                    "eventTime": "2026-07-16 08:05:00",
                },
                {
                    "alarmId": "a-3",
                    "title": "Redis 内存碎片率异常",
                    "level": "warning",
                    "levelName": "普通",
                    "deviceName": "redis-01",
                    "resId": "ci-02",
                    "eventTime": "2026-07-16 09:00:00",
                },
            ],
        },
    )

    async def fake_model(_messages):
        return json.dumps(
            {
                "riskLevel": "critical",
                "summary": "当前风险集中在数据库锁异常，建议优先处理 mysql-01。",
                "issueKeys": ["MySQL 锁异常", "Redis 内存碎片率异常"],
                "targetKey": "ci-01",
                "recommendationReason": "紧急告警数量最多且持续时间最长。",
            },
        )

    result = await service.build_system_summary(model=fake_model)

    assert result["modelStatus"] == "live"
    assert cmdb_calls == 0
    assert result["facts"]["assetTotal"] == 130
    assert result["facts"]["activeAlarmTotal"] == 3
    assert result["facts"]["severity"] == {
        "urgent": 1,
        "severe": 1,
        "normal": 1,
        "warning": 0,
    }
    assert [item["issue"] for item in result["topIssues"]] == [
        "MySQL 锁异常",
        "Redis 内存碎片率异常",
    ]
    assert result["recommendations"][0]["target"] == "mysql-01"
    assert result["recommendations"][0]["priority"] == "P0"
    assert result["sources"]["assets"]["status"] == "live"
    assert result["sources"]["assets"]["source"] == "asset-overview"
    assert result["sources"]["alarms"]["complete"] is True


@pytest.mark.asyncio
async def test_build_system_summary_does_not_fall_back_to_cmdb_asset_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_cmdb_summary",
        lambda: {"code": 200, "data": {"total_ci_count": 8}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 500, "msg": "unavailable", "data": None},
    )
    monkeypatch.setattr(
        service.portal_real_alarms,
        "query_portal_real_alarms",
        lambda **_kwargs: {
            "total": 1,
            "source": "live",
            "items": [
                {
                    "alarmId": "a-1",
                    "title": "系统内存使用率过高",
                    "level": "urgent",
                    "levelName": "严重",
                    "deviceName": "host-01",
                    "resId": "ci-host-01",
                },
            ],
        },
    )

    async def unavailable_model(_messages):
        raise RuntimeError("provider unavailable")

    result = await service.build_system_summary(model=unavailable_model)

    assert result["modelStatus"] == "degraded"
    assert result["facts"]["assetTotal"] is None
    assert "资产数量暂不可得" in result["summary"]
    assert result["sources"]["assets"]["status"] == "failed"
    assert result["topIssues"][0]["issue"] == "系统内存使用率过高"
    assert result["recommendations"][0]["target"] == "host-01"


@pytest.mark.asyncio
async def test_build_system_summary_marks_partial_when_alarm_sample_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_cmdb_summary",
        lambda: {"code": 200, "data": {"total_ci_count": 3}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 3}},
    )
    monkeypatch.setattr(
        service.portal_real_alarms,
        "query_portal_real_alarms",
        lambda **_kwargs: {
            "total": 201,
            "source": "live",
            "items": [
                {
                    "alarmId": "a-1",
                    "title": "MySQL 锁异常",
                    "levelName": "紧急",
                    "deviceName": "mysql-01",
                    "resId": "ci-01",
                },
            ],
        },
    )

    result = await service.build_system_summary(
        model=lambda _messages: (_ for _ in ()).throw(RuntimeError("down")),
    )

    assert result["status"] == "partial"
    assert result["facts"]["activeAlarmTotal"] == 201
    assert result["facts"]["analysisComplete"] is False
    assert result["sources"]["alarms"]["complete"] is False
    assert "样本" in result["sources"]["alarms"]["message"]


@pytest.mark.asyncio
async def test_build_system_summary_never_relabels_alarm_failure_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_cmdb_summary",
        lambda: {"code": 200, "data": {"total_ci_count": 12}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 12}},
    )

    def raise_alarm_backend(**_kwargs):
        raise ConnectionError("alarm backend down")

    monkeypatch.setattr(
        service.portal_real_alarms,
        "query_portal_real_alarms",
        raise_alarm_backend,
    )

    result = await service.build_system_summary()

    assert result["status"] == "partial"
    assert result["riskLevel"] == "unknown"
    assert result["facts"]["activeAlarmTotal"] is None
    assert "暂不可得" in result["summary"]
    assert result["sources"]["alarms"]["status"] == "failed"


def test_system_summary_endpoint_is_mounted_and_read_only(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from qwenpaw.extensions.api import system_summary_api
    from qwenpaw.extensions.api import portal_backend

    async def fake_build_system_summary(*, fresh: bool = False):
        assert fresh is True
        return {
            "generatedAt": "2026-07-16T10:00:00+08:00",
            "dataAsOf": "2026-07-16T10:00:00+08:00",
            "status": "live",
            "summary": "摘要",
            "riskLevel": "low",
            "facts": {"assetTotal": 0, "activeAlarmTotal": 0, "severity": {}},
            "topIssues": [],
            "recommendations": [],
            "sources": {},
            "modelStatus": "live",
        }

    monkeypatch.setattr(
        system_summary_api,
        "build_system_summary",
        fake_build_system_summary,
    )

    response = TestClient(portal_backend.app).get(
        "/api/portal/ai/system-summary?fresh=true",
    )

    assert response.status_code == 200
    assert response.json() == {"summary": "摘要"}


def test_system_summary_endpoint_is_explicitly_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.requests import Request

    from qwenpaw.app import auth

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "has_registered_users", lambda: True)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/portal/ai/system-summary",
            "headers": [],
            "query_string": b"",
            "client": ("10.0.0.8", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
        },
    )

    assert auth.AuthMiddleware._should_skip_auth(request) is True
