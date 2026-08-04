# -*- coding: utf-8 -*-
"""Contract tests for the AI-backed system situation summary."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _stub_active_alarm_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep summary tests offline unless a case explicitly supplies active alarms."""
    from qwenpaw.extensions.api import system_summary_service as service

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_active_alarm_history",
        lambda **_kwargs: {"code": 200, "total": 0, "rows": []},
        raising=False,
    )


def test_urgent_top_candidates_deduplicate_and_prioritize_active_latest() -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    alarms = [
        {"title": "重复紧急告警", "alarmseverity": "1", "alarmStatus": "0", "eventLastTime": "2026-07-21 09:00:00", "deviceName": "redis-01", "resId": "r1"},
        {"title": "重复紧急告警", "alarmseverity": "1", "alarmStatus": "1", "eventLastTime": "2026-07-21 10:00:00", "deviceName": "redis-01", "resId": "r1"},
        {"title": "紧急B", "alarmseverity": "1", "alarmStatus": "1", "eventLastTime": "2026-07-21 11:00:00", "deviceName": "mysql-01", "resId": "r2"},
        {"title": "紧急C", "alarmseverity": "1", "alarmStatus": "1", "eventLastTime": "2026-07-21 08:00:00", "deviceName": "vm-01", "resId": "r3"},
        {"title": "紧急D", "alarmseverity": "1", "alarmStatus": "1", "eventLastTime": "2026-07-21 07:00:00", "deviceName": "es-01", "resId": "r4"},
        {"title": "紧急E", "alarmseverity": "1", "alarmStatus": "0", "eventLastTime": "2026-07-21 12:00:00", "deviceName": "kafka-01", "resId": "r5"},
        {"title": "严重告警", "alarmseverity": "2", "alarmStatus": "1", "eventLastTime": "2026-07-21 13:00:00", "deviceName": "redis-02", "resId": "r6"},
    ]

    issues, targets = service._urgent_alarm_candidates(alarms)

    assert [item["issue"] for item in issues] == [
        "紧急B",
        "重复紧急告警",
        "紧急C",
        "紧急D",
        "紧急E",
    ]
    assert [item["resources"] for item in issues] == [
        ["mysql-01"],
        ["redis-01"],
        ["vm-01"],
        ["es-01"],
        ["kafka-01"],
    ]
    assert targets[0]["target"] == "mysql-01"


def test_top_alarm_candidates_fall_back_from_urgent_to_severe() -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    alarms = [
        {
            "title": "Redis内存碎片率异常",
            "alarmseverity": "2",
            "alarmStatus": "1",
            "eventLastTime": "2026-07-22 10:00:00",
            "deviceName": "redis-01",
            "manageIp": "10.2.0.15",
            "resId": "redis-01-id",
        },
        {
            "title": "系统内存使用率过高",
            "alarmseverity": "3",
            "alarmStatus": "1",
            "eventLastTime": "2026-07-22 10:01:00",
            "deviceName": "vm-01",
            "resId": "vm-01-id",
        },
    ]

    severity, issues, targets = service._top_alarm_candidates(alarms)

    assert severity == "severe"
    assert [item["issue"] for item in issues] == ["Redis内存碎片率异常"]
    assert targets[0]["target"] == "redis-01"


def test_fallback_summary_declares_normal_when_no_alarm_exists() -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    decision = service._fallback_decision(
        {
            "assetTotal": 12,
            "activeAlarmTotal": 0,
            "severity": {"urgent": 0, "severe": 0, "normal": 0, "warning": 0},
            "issueCandidates": [],
            "targetCandidates": [],
            "alarmsAvailable": True,
        },
    )

    assert "系统运行正常" in decision["summary"]
    assert "TOP" not in decision["summary"]


def test_model_decision_requires_ip_for_selected_urgent_resource() -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    facts = {
        "issueCandidates": [
            {
                "key": "系统内存使用率过高::8341",
                "issue": "系统内存使用率过高",
                "resources": ["天翼智观部署虚机"],
                "resourceName": "天翼智观部署虚机",
                "manageIp": "10.2.0.15",
            },
        ],
        "targetCandidates": [
            {
                "key": "8341",
                "target": "天翼智观部署虚机",
                "manageIp": "10.2.0.15",
            },
        ],
    }
    response = json.dumps(
        {
            "riskLevel": "critical",
            "summary": "TOP1紧急告警：系统内存使用率过高（天翼智观部署虚机）。建议优先处理天翼智观部署虚机。",
            "issueKeys": ["系统内存使用率过高::8341"],
            "targetKey": "8341",
            "recommendationReason": "紧急告警。",
        },
    )

    with pytest.raises(ValueError, match="IP"):
        service._parse_model_decision_for_facts(response, facts)

    fallback = service._fallback_decision(
        {
            **facts,
            "assetTotal": 12,
            "activeAlarmTotal": 1,
            "severity": {"urgent": 1},
            "alarmsAvailable": True,
        },
    )
    assert "10.2.0.15" in fallback["summary"]


def test_active_alarm_health_treats_query_failure_as_normal() -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    health_status, source = service._collect_active_alarm_health(
        ConnectionError("active alarm backend down"),
    )

    assert health_status == "normal"
    assert source["status"] == "failed"


@pytest.mark.asyncio
async def test_system_summary_exposes_safe_html_and_active_alarm_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.extensions.api import system_summary_service as service

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 12}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        lambda **_kwargs: {"code": 200, "data": {"1": 1, "2": 2, "3": 0, "4": 0}},
    )
    history = {
        "code": 200,
        "total": 1,
        "rows": [
            {
                "alarmtitle": "系统内存使用率过高",
                "alarmseverity": "1",
                "devName": "vm-01",
                "devId": "vm-01-id",
                "manageIp": "10.2.0.15",
            },
        ],
    }
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        lambda **_kwargs: history,
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_active_alarm_history",
        lambda **_kwargs: history,
        raising=False,
    )

    async def model(_messages):
        return json.dumps(
            {
                "riskLevel": "critical",
                "summary": (
                    "当前共纳管12个资产对象，当天累计3条告警（紧急1、严重2）。"
                    "TOP1紧急告警：系统内存使用率过高（vm-01，10.2.0.15）。"
                    "建议优先处理vm-01（10.2.0.15）。<script>alert(1)</script>"
                ),
                "issueKeys": ["系统内存使用率过高::vm-01-id"],
                "targetKey": "vm-01-id",
                "recommendationReason": "紧急告警。",
            },
        )

    result = await service.build_system_summary(model=model)

    assert result["healthStatus"] == "abnormal"
    assert '<span style="color: #c00018; font-weight: 700;">紧急1</span>' in result["summaryHtml"]
    assert '<span style="color: #f57c00; font-weight: 700;">严重2</span>' in result["summaryHtml"]
    assert (
        '<span style="font-weight: 700;">系统内存使用率过高</span>'
        in result["summaryHtml"]
    )
    assert "</span>（vm-01，10.2.0.15）。建议优先处理" in result["summaryHtml"]
    assert (
        '建议优先处理<span style="color: #d4001a; font-weight: 700;">vm-01</span>'
        in result["summaryHtml"]
    )
    assert "class=\"ai-" not in result["summaryHtml"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result["summaryHtml"]


@pytest.mark.asyncio
async def test_system_summary_uses_the_standalone_platform_model_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A platform selection wins without inheriting an Agent model."""
    from qwenpaw.config.config import ModelSlotConfig
    from qwenpaw.extensions.api import system_summary_service as service

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 12}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        lambda **_kwargs: {"code": 200, "data": {"1": 0, "2": 0, "3": 0, "4": 0}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        lambda **_kwargs: {"code": 200, "total": 0, "rows": []},
    )
    selected_slot = ModelSlotConfig(provider_id="ctyun", model="GLM-5.1")
    monkeypatch.setattr(
        service.platform_ai_model_settings_store,
        "get_model_slot",
        lambda: selected_slot,
    )
    received: list[ModelSlotConfig | None] = []

    async def model(_messages):
        return json.dumps(
            {
                "riskLevel": "low",
                "summary": "当前共纳管12个资产对象，当天暂未发现告警，系统运行正常。",
                "issueKeys": [],
                "targetKey": "",
                "recommendationReason": "",
            },
        )

    def create_selected_model(
        slot: ModelSlotConfig | None,
        *,
        use_global_default: bool,
    ):
        assert use_global_default is True
        received.append(slot)
        return model

    monkeypatch.setattr(service, "create_pipeline_model", create_selected_model)

    await service.build_system_summary()

    assert received == [selected_slot]


@pytest.mark.asyncio
async def test_system_summary_uses_dashboard_alarm_sources_with_one_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counts and issue rows come from the same page-backed time snapshot."""
    from qwenpaw.extensions.api import system_summary_service as service

    calls: dict[str, object] = {}
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 12}},
    )

    def query_severity(*, now):
        calls["severity_now"] = now
        return {"code": 200, "data": {"1": 5, "2": 13, "3": 60, "4": 12}}

    def query_alarm_list(*, now, limit):
        calls["list_now"] = now
        calls["list_limit"] = limit
        return {
            "code": 200,
            "total": 2,
            "rows": [
                {
                    "alarmtitle": "MySQL锁异常",
                    "alarmseverity": "1",
                    "devName": "mysql-01",
                    "devId": "mysql-01-id",
                },
                {
                    "alarmtitle": "Redis内存碎片率异常",
                    "alarmseverity": "2",
                    "devName": "redis-01",
                    "devId": "redis-01-id",
                },
            ],
        }

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        query_severity,
        raising=False,
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        query_alarm_list,
        raising=False,
    )
    async def model(_messages):
        return json.dumps(
            {
                "riskLevel": "critical",
                "summary": (
                    "当前共纳管12个资产对象，当天累计90条告警（紧急5、严重13）。"
                    "TOP1紧急告警：MySQL锁异常（mysql-01），"
                    "建议优先处理mysql-01。"
                ),
                "issueKeys": ["MySQL锁异常::mysql-01-id"],
                "targetKey": "mysql-01-id",
                "recommendationReason": "紧急告警关联核心数据库。",
            },
        )

    result = await service.build_system_summary(model=model)

    assert result["facts"]["activeAlarmTotal"] == 90
    assert result["facts"]["severity"] == {
        "urgent": 5,
        "severe": 13,
        "normal": 60,
        "warning": 12,
    }
    assert calls["severity_now"] == calls["list_now"]
    assert calls["list_limit"] == 1000
    assert "portal_real_alarms" not in vars(service)


@pytest.mark.asyncio
async def test_system_summary_uses_same_day_alarm_history_for_top_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOP issues are aggregated from the dashboard's historical rows, not live alarms."""
    from qwenpaw.extensions.api import system_summary_service as service

    calls: dict[str, object] = {}
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 12}},
    )

    def query_severity(*, now):
        calls["severity_now"] = now
        return {"code": 200, "data": {"1": 1, "2": 2, "3": 1, "4": 0}}

    def query_history(*, now, limit):
        calls["history_now"] = now
        calls["history_limit"] = limit
        return {
            "code": 200,
            "total": 4,
            "rows": [
                {
                    "alarmtitle": "Redis每秒操作次数越限",
                    "alarmseverity": "2",
                    "alarmstatus": "0",
                    "devName": "redis-01",
                    "devId": "redis-01-id",
                },
                {
                    "alarmtitle": "Redis每秒操作次数越限",
                    "alarmseverity": "2",
                    "alarmstatus": "1",
                    "devName": "redis-01",
                    "devId": "redis-01-id",
                },
                {
                    "alarmtitle": "系统内存使用率过高",
                    "alarmseverity": "1",
                    "alarmstatus": "0",
                    "devName": "vm-01",
                    "devId": "vm-01-id",
                },
                {
                    "alarmtitle": "块设备写速率过高",
                    "alarmseverity": "3",
                    "alarmstatus": "0",
                    "devName": "vm-01",
                    "devId": "vm-01-id",
                },
            ],
        }

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        query_severity,
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        query_history,
        raising=False,
    )
    observed_messages: list[dict[str, str]] = []

    async def model(messages):
        observed_messages.extend(messages)
        return json.dumps(
            {
                "riskLevel": "critical",
                "summary": (
                    "当前共纳管12个资产对象，当天累计4条告警（紧急1、严重2）。"
                    "TOP1紧急告警：系统内存使用率过高（vm-01），"
                    "建议优先处理vm-01。"
                ),
                "issueKeys": ["系统内存使用率过高::vm-01-id"],
                "targetKey": "vm-01-id",
                "recommendationReason": "紧急告警影响虚拟机。",
            },
        )

    result = await service.build_system_summary(model=model)

    assert result["facts"]["activeAlarmTotal"] == 4
    assert [item["issue"] for item in result["topIssues"]] == ["系统内存使用率过高"]
    assert calls["severity_now"] == calls["history_now"]
    assert calls["history_limit"] == 1000
    assert "当天累计" in observed_messages[0]["content"]


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
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        lambda **_kwargs: {"code": 200, "data": {"1": 1, "2": 1, "3": 1, "4": 0}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        lambda **_kwargs: {
            "code": 200,
            "total": 3,
            "rows": [
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
                "issueKeys": ["MySQL 锁异常::ci-01"],
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
    assert [item["issue"] for item in result["topIssues"]] == ["MySQL 锁异常"]
    assert result["recommendations"][0]["target"] == "mysql-01"
    assert result["recommendations"][0]["priority"] == "P0"
    assert result["sources"]["assets"]["status"] == "live"
    assert result["sources"]["assets"]["source"] == "asset-overview"
    assert result["sources"]["alarms"]["complete"] is True


@pytest.mark.asyncio
async def test_system_summary_uses_model_narrative_with_fact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model, rather than a fixed backend template, writes the narrative."""
    from qwenpaw.extensions.api import system_summary_service as service

    observed_query: dict[str, object] = {}
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 12}},
    )

    def query_alarm_list(**kwargs):
        observed_query.update(kwargs)
        return {
            "code": 200,
            "total": 6,
            "rows": [
                {"title": "MySQL锁异常", "levelName": "紧急", "deviceName": "mysql-01", "resId": "mysql"},
                {"title": "MySQL锁异常", "levelName": "紧急", "deviceName": "mysql-01", "resId": "mysql"},
                {"title": "Redis内存碎片率异常", "levelName": "严重", "deviceName": "redis-01", "resId": "redis"},
                {"title": "Redis内存碎片率异常", "levelName": "严重", "deviceName": "redis-01", "resId": "redis"},
                {"title": "系统内存使用率过高", "levelName": "普通", "deviceName": "vm-01", "resId": "vm"},
                {"title": "磁盘使用率过高", "levelName": "预警", "deviceName": "es-01", "resId": "es"},
            ],
        }

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        lambda **_kwargs: {"code": 200, "data": {"1": 2, "2": 2, "3": 1, "4": 1}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        query_alarm_list,
    )

    observed_messages: list[dict[str, str]] = []
    generated_summary = (
        "模型生成结论：当前共纳管12个资产对象，当天累计6条告警（紧急2、严重2），"
        "TOP1紧急告警：MySQL锁异常（mysql-01），建议优先处理mysql-01。"
    )

    async def narrative_model(messages):
        observed_messages.extend(messages)
        return json.dumps(
            {
                "riskLevel": "high",
                "summary": generated_summary,
                "issueKeys": ["MySQL锁异常::mysql"],
                "targetKey": "mysql",
                "recommendationReason": "紧急告警聚集。",
            },
        )

    result = await service.build_system_summary(model=narrative_model)

    assert observed_query["limit"] == 1000
    assert result["summary"] == generated_summary
    assert "TOP3至TOP5" in observed_messages[0]["content"]
    assert "mysql-01" in observed_messages[1]["content"]


@pytest.mark.asyncio
async def test_system_summary_repairs_internal_resource_id_in_model_narrative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public narrative must name the resource, not expose its internal ID."""
    from qwenpaw.extensions.api import system_summary_service as service

    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_asset_overview",
        lambda: {"code": 200, "data": {"totalResources": 12}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        lambda **_kwargs: {"code": 200, "data": {"1": 1, "2": 0, "3": 0, "4": 0}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        lambda **_kwargs: {
            "code": 200,
            "total": 1,
            "rows": [
                {
                    "title": "系统内存使用率过高",
                    "levelName": "紧急",
                    "deviceName": "天翼智观部署虚机",
                    "resId": "8341",
                },
            ],
        },
    )

    calls: list[list[dict[str, str]]] = []
    invalid_summary = (
        "当前共纳管12个资产对象，1条未恢复告警（紧急1、严重0）。"
        "TOP1问题集中在系统内存使用率过高，受影响资源为天翼智观部署虚机。"
        "建议优先处理8341对应资源。"
    )
    corrected_summary = (
        "当前共纳管12个资产对象，1条未恢复告警（紧急1、严重0）。"
        "TOP1问题集中在系统内存使用率过高，受影响资源为天翼智观部署虚机。"
        "建议优先处理天翼智观部署虚机。"
    )

    async def model(messages):
        calls.append(messages)
        summary = invalid_summary if len(calls) == 1 else corrected_summary
        return json.dumps(
            {
                "riskLevel": "critical",
                "summary": summary,
                "issueKeys": ["系统内存使用率过高::8341"],
                "targetKey": "8341",
                "recommendationReason": "紧急告警。",
            },
        )

    result = await service.build_system_summary(model=model)

    assert result["summary"] == corrected_summary
    assert len(calls) == 2
    assert "禁止展示内部 ID" in calls[1][-1]["content"]


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
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        lambda **_kwargs: {"code": 200, "data": {"1": 0, "2": 1, "3": 0, "4": 0}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        lambda **_kwargs: {
            "code": 200,
            "total": 1,
            "rows": [
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
    assert [item["issue"] for item in result["topIssues"]] == [
        "系统内存使用率过高",
    ]
    assert result["recommendations"][0]["target"] == "host-01"
    assert "TOP1严重告警" in result["summary"]


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
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        lambda **_kwargs: {"code": 200, "data": {"1": 201, "2": 0, "3": 0, "4": 0}},
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
        lambda **_kwargs: {
            "code": 200,
            "total": 201,
            "rows": [
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
        service.portal_monitoring_overview,
        "query_dashboard_alarm_severity",
        raise_alarm_backend,
    )
    monkeypatch.setattr(
        service.portal_monitoring_overview,
        "query_dashboard_alarm_history",
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
            "summaryHtml": "摘要",
            "healthStatus": "normal",
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
    assert response.json() == {
        "summary": "摘要",
        "summaryHtml": "摘要",
        "healthStatus": "normal",
    }


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
