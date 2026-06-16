# -*- coding: utf-8 -*-
from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.extensions.api.alarm_analyst_service as alarm_analyst_service
from qwenpaw.extensions.api.alarm_analyst_service import (
    _fault_skill_root,
    _build_alarm_analyst_result,
    parse_alarm_dispatch_context,
    run_alarm_analyst_diagnose,
)


def test_alarm_analyst_service_fault_skill_root_prefers_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_FAULT_SKILL_ROOT", "/configured/fault-skills")

    assert _fault_skill_root() == Path("/configured/fault-skills")


def test_parse_alarm_dispatch_context_extracts_res_id_and_event_time() -> None:
    context = parse_alarm_dispatch_context(
        "数据库锁异常（db_mysql_001 10.43.150.186）\n资源 ID（CI ID）：3094\n告警时间：2026-04-20 18:39:19",
    )

    assert context["res_id"] == "3094"
    assert context["event_time"] == "2026-04-20 18:39:19"
    assert context["manage_ip"] == "10.43.150.186"


def test_parse_alarm_dispatch_context_accepts_res_id_label_variants() -> None:
    context = parse_alarm_dispatch_context(
        "数据库锁异常\nCI ID：3094\n告警时间：2026-04-20 18:39:19",
    )

    assert context["res_id"] == "3094"
    assert context["event_time"] == "2026-04-20 18:39:19"


def test_parse_alarm_dispatch_context_extracts_app_keyword() -> None:
    context = parse_alarm_dispatch_context("计费应用插入数据失败")

    assert context["app_keyword"] == "计费"


def test_parse_alarm_dispatch_context_infers_cmdb_as_application_keyword() -> (
    None
):
    context = parse_alarm_dispatch_context("cmdb 应用插入数据失败")

    assert context["app_keyword"] == "cmdb"


def test_build_alarm_analyst_result_maps_partial_execution_to_steps_and_logs() -> (
    None
):
    result = _build_alarm_analyst_result(
        {
            "topology": {
                "resourceCount": 2,
                "resourceIds": ["3094", "5002"],
                "rootResource": {
                    "resId": "3094",
                    "ciType": "mysql",
                    "ciTypeAlias": "MySQL",
                    "name": "db_mysql_001",
                },
            },
            "relatedAlarms": {
                "recent": {
                    "total": 2,
                },
                "previous": {
                    "total": 1,
                },
                "comparison": {
                    "deltaTotal": 1,
                },
            },
            "metricAnalysis": {
                "metricType": "mysql",
                "metricDataResults": [],
                "selectedMetrics": ["m1", "m2"],
            },
            "findings": ["存在拓扑伴随告警扩散。"],
            "execution": {
                "status": "partial",
                "rootResource": {
                    "resolved": True,
                    "resId": "3094",
                    "ciType": "mysql",
                },
                "metrics": {
                    "metricTypeResolved": True,
                    "selectedCount": 2,
                    "queriedCount": 0,
                    "failedCount": 2,
                    "skippedReason": "",
                },
                "topology": {
                    "resourceIdsExpected": 2,
                    "resourceIdsCollected": 2,
                    "resourceIds": ["3094", "5002"],
                },
                "relatedAlarmsRecent": {
                    "expectedQueries": 2,
                    "attemptedQueries": 2,
                    "successIds": ["3094"],
                    "failedIds": ["5002"],
                },
                "relatedAlarmsPrevious": {
                    "expectedQueries": 2,
                    "attemptedQueries": 2,
                    "successIds": ["3094", "5002"],
                    "failedIds": [],
                },
            },
        },
        {"res_id": "3094"},
    )

    steps = {item["id"]: item["status"] for item in result["steps"]}
    assert steps["root-resource"] == "success"
    assert steps["cmdb-topology"] == "success"
    assert steps["related-alarms-recent"] == "partial"
    assert steps["related-alarms-compare"] == "success"
    assert steps["metric-analysis"] == "partial"
    assert "5002" in result["logEntries"][2]["summary"]
    assert "失败 2 个" in result["logEntries"][3]["summary"]


def test_build_alarm_analyst_result_blocks_steps_when_execution_is_blocked() -> (
    None
):
    result = _build_alarm_analyst_result(
        {
            "topology": {
                "resourceCount": 0,
                "resourceIds": [],
                "rootResource": {
                    "resId": "3094",
                    "ciType": "",
                    "ciTypeAlias": "",
                    "name": "db_unknown_001",
                },
            },
            "relatedAlarms": {
                "recent": {"total": 0},
                "previous": {"total": 0},
                "comparison": {"deltaTotal": 0},
            },
            "metricAnalysis": {
                "metricType": "",
                "metricDataResults": [],
                "selectedMetrics": [],
            },
            "findings": [],
            "execution": {
                "status": "blocked",
                "rootResource": {
                    "resolved": False,
                    "resId": "3094",
                    "ciType": "",
                },
                "metrics": {
                    "metricTypeResolved": False,
                    "selectedCount": 0,
                    "queriedCount": 0,
                    "failedCount": 0,
                    "skippedReason": "missing_root_ci_type",
                },
                "topology": {
                    "resourceIdsExpected": 0,
                    "resourceIdsCollected": 0,
                    "resourceIds": [],
                },
                "relatedAlarmsRecent": {
                    "expectedQueries": 0,
                    "attemptedQueries": 0,
                    "successIds": [],
                    "failedIds": [],
                },
                "relatedAlarmsPrevious": {
                    "expectedQueries": 0,
                    "attemptedQueries": 0,
                    "successIds": [],
                    "failedIds": [],
                },
            },
        },
        {"res_id": "3094"},
    )

    steps = {item["id"]: item["status"] for item in result["steps"]}
    assert steps["root-resource"] == "blocked"
    assert steps["cmdb-topology"] == "blocked"
    assert steps["metric-analysis"] == "blocked"
    assert "missing_root_ci_type" in result["logEntries"][3]["summary"]


def test_run_alarm_analyst_diagnose_requires_session_id() -> None:
    with pytest.raises(ValueError, match="sessionId is required"):
        run_alarm_analyst_diagnose({})


def test_run_alarm_analyst_diagnose_returns_partial_result_when_res_id_and_app_keyword_missing() -> (
    None
):
    payload = run_alarm_analyst_diagnose(
        {
            "sessionId": "alarm-analyst-1",
            "content": "应用插入数据失败",
        },
    )

    assert payload["session"]["scene"] == "alarm_analyst_rca"
    assert "请补充应用名或资源 ID" in payload["result"]["summary"]
    assert payload["result"]["steps"][1]["status"] == "blocked"


def test_run_alarm_analyst_diagnose_uses_application_driven_path_when_app_keyword_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.api.alarm_analyst_service._run_alarm_analyst_context_from_application",
        lambda payload, dispatch_context: {
            "summary": "已匹配应用拓扑并继续执行 RCA。",
            "rootCause": {"type": "mysql", "object": "billing-mysql"},
            "steps": [{"id": "match-application", "status": "success"}],
            "logEntries": [
                {"stage": "application-topology", "summary": "已获取应用拓扑"},
            ],
            "actions": [],
        },
    )

    payload = run_alarm_analyst_diagnose(
        {
            "sessionId": "alarm-analyst-2",
            "content": "cmdb 应用插入数据失败",
        },
    )

    assert payload["session"]["scene"] == "alarm_analyst_rca"
    assert "应用拓扑" in payload["result"]["summary"]
    assert payload["result"]["steps"][0]["status"] == "success"


def test_run_alarm_analyst_context_from_application_selects_single_matching_project_and_root_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_find_project = SimpleNamespace(
        _project_summary=lambda item: {
            "id": item["_id"],
            "name": item["project_name"],
        },
        _project_name=lambda item: item["project_name"],
        _match_projects=lambda projects, keyword: (projects, "exact"),
    )
    fake_app_topology = SimpleNamespace(
        _fetch_relations=lambda client, project_id: [
            {
                "_id": 3094,
                "ci_type": "mysql",
                "name": "cmdb-mysql",
                "manage_ip": "10.43.150.186",
            },
            {"_id": 5002, "ci_type": "docker", "name": "cmdb-pod"},
        ],
        _build_tree=lambda project, relation_rows: {
            "name": project["project_name"],
            "children": relation_rows,
        },
        _build_option=lambda tree, title: {
            "title": title,
            "series": [{"data": [tree]}],
        },
    )

    monkeypatch.setattr(
        alarm_analyst_service,
        "_load_zgops_modules",
        lambda: (fake_find_project, fake_app_topology),
    )
    monkeypatch.setattr(
        alarm_analyst_service,
        "_load_zgops_client",
        lambda _find_project: SimpleNamespace(
            list_projects=lambda: [{"_id": 1001, "project_name": "cmdb"}],
        ),
    )
    monkeypatch.setattr(
        alarm_analyst_service,
        "_run_alarm_analyst_context",
        lambda payload: {
            "summary": "已完成告警拓扑、关联告警和指标的联合分析。",
            "rootCause": {"type": "mysql", "object": "cmdb-mysql"},
            "steps": [],
            "logEntries": [],
            "actions": [],
        },
    )

    result = alarm_analyst_service._run_alarm_analyst_context_from_application(
        {"content": "cmdb 应用插入数据失败"},
        {
            "app_keyword": "cmdb",
            "device_name": "",
            "manage_ip": "",
            "alarm_title": "",
            "event_time": "",
            "res_id": "",
        },
    )

    assert "application-topology" in result["logEntries"][0]["stage"]
    assert any(
        action["type"] == "alarm-analyst-application-topology"
        for action in result["actions"]
    )
