# -*- coding: utf-8 -*-
"""Tests for portal employee runtime status aggregation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.extensions.api import portal_backend


class _FakeChatManager:
    def __init__(self, chats: list[ChatSpec]) -> None:
        self._chats = chats

    async def list_chats(self) -> list[ChatSpec]:
        return self._chats


class _FakeTaskTracker:
    def __init__(self, active_tasks: list[str]) -> None:
        self._active_tasks = active_tasks

    async def list_active_tasks(self) -> list[str]:
        return self._active_tasks


class _FakeManager:
    def __init__(self, workspaces: dict[str, object]) -> None:
        self._workspaces = workspaces
        self.agents = workspaces

    async def get_agent(self, agent_id: str):
        workspace = self._workspaces.get(agent_id)
        if workspace is None:
            raise ValueError(f"Agent '{agent_id}' not found")
        return workspace


def _make_request(manager: _FakeManager):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        )
    )


def test_platform_ai_model_settings_api_is_separate_from_agent_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: list[dict[str, object]] = []
    monkeypatch.setattr(
        portal_backend.platform_ai_model_settings_store,
        "build_settings_payload",
        lambda: {
            "providerId": "ctyun",
            "modelId": "GLM-5.1",
            "usesGlobalDefault": False,
        },
    )
    monkeypatch.setattr(
        portal_backend.platform_ai_model_settings_store,
        "apply_settings_update",
        lambda body: stored.append(body),
    )

    client = TestClient(portal_backend.app)
    assert client.get("/api/portal/platform-ai-model-settings").json()[
        "modelId"
    ] == "GLM-5.1"
    assert client.put(
        "/api/portal/platform-ai-model-settings",
        json={"providerId": "ctyun", "modelId": "GLM-5.1"},
    ).status_code == 200
    assert stored == [{"providerId": "ctyun", "modelId": "GLM-5.1"}]


@pytest.fixture(autouse=True)
def _reset_portal_alarm_runtime_state() -> None:
    refresh_task = portal_backend.PORTAL_REAL_ALARM_REFRESH_TASK
    if refresh_task is not None and not refresh_task.done():
        refresh_task.cancel()
    alert_task = portal_backend.PORTAL_STATUS_ALERT_COUNT_REFRESH_TASK
    if alert_task is not None and not alert_task.done():
        alert_task.cancel()

    portal_backend.PORTAL_REAL_ALARM_REFRESH_TASK = None
    portal_backend.PORTAL_REAL_ALARM_REFRESH_LIMIT = 0
    portal_backend.PORTAL_REAL_ALARM_DEGRADED_UNTIL_MONOTONIC = 0.0
    portal_backend.PORTAL_REAL_ALARM_PAYLOAD_CACHE.update(
        {"payload": None, "limit": 0, "updated_at": 0.0}
    )
    portal_backend.PORTAL_STATUS_ALERT_COUNT_REFRESH_TASK = None
    portal_backend.PORTAL_STATUS_ALERT_COUNT_CACHE.update(
        {"value": 0, "updated_at": 0.0}
    )


@pytest.mark.asyncio
async def test_collect_portal_employee_statuses_uses_runtime_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    query_chat = ChatSpec(
        id="query-chat-1",
        name="CPU 使用率分析",
        session_id="console:default",
        user_id="default",
        channel="console",
        updated_at=now,
    )
    fault_chat = ChatSpec(
        id="fault-chat-1",
        name="端口 down 定位",
        session_id="console:default",
        user_id="default",
        channel="console",
        updated_at=now,
    )

    query_workspace = SimpleNamespace(
        chat_manager=_FakeChatManager([query_chat]),
        task_tracker=_FakeTaskTracker(["query-chat-1"]),
    )
    fault_workspace = SimpleNamespace(
        chat_manager=_FakeChatManager([fault_chat]),
        task_tracker=_FakeTaskTracker([]),
    )
    manager = _FakeManager(
        {
            "query": query_workspace,
            "fault": fault_workspace,
        }
    )

    monkeypatch.setattr(
        portal_backend,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "query": SimpleNamespace(enabled=True),
                    "fault": SimpleNamespace(enabled=True),
                }
            )
        ),
    )
    monkeypatch.setattr(
        portal_backend,
        "_query_visible_portal_real_alarms",
        lambda _limit: {"total": 2, "items": [{"id": "alarm-1"}, {"id": "alarm-2"}], "source": "live"},
    )

    statuses = await portal_backend.collect_portal_employee_statuses(
        _make_request(manager),
        employee_ids=("query", "fault", "resource"),
    )
    by_id = {item["employeeId"]: item for item in statuses}

    assert by_id["query"]["available"] is True
    assert by_id["query"]["employeeName"] == "数据分析专家"
    assert by_id["query"]["status"] == "running"
    assert by_id["query"]["urgent"] is False
    assert by_id["query"]["currentJob"] == "正在处理 1 个对话任务"
    assert by_id["query"]["latestSessionTitle"] == "CPU 使用率分析"

    assert by_id["fault"]["available"] is True
    assert by_id["fault"]["employeeName"] == "故障分析专家"
    assert by_id["fault"]["status"] == "idle"
    assert by_id["fault"]["urgent"] is True
    assert by_id["fault"]["alertCount"] == 2
    assert by_id["fault"]["workStatus"] == "紧急任务"

    assert by_id["resource"]["available"] is False
    assert by_id["resource"]["employeeName"] == "资产管理专员"
    assert by_id["resource"]["status"] == "idle"
    assert by_id["resource"]["currentJob"] == "暂无对话"


@pytest.mark.asyncio
async def test_refresh_fault_alert_count_cache_prefers_live_visible_alarm_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(portal_backend.PORTAL_STATUS_ALERT_COUNT_CACHE, "value", 16)
    monkeypatch.setitem(portal_backend.PORTAL_STATUS_ALERT_COUNT_CACHE, "updated_at", 123.0)
    monkeypatch.setattr(
        portal_backend,
        "_query_visible_portal_real_alarms",
        lambda _limit: {"total": 3, "items": [{"id": "alarm-1"}, {"id": "alarm-2"}, {"id": "alarm-3"}]},
    )

    count = await portal_backend._refresh_fault_alert_count_cache()

    assert count == 3
    assert portal_backend.PORTAL_STATUS_ALERT_COUNT_CACHE["value"] == 3


@pytest.mark.asyncio
async def test_get_employee_alert_count_returns_cached_value_while_refresh_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_task = asyncio.get_running_loop().create_future()
    monkeypatch.setitem(portal_backend.PORTAL_STATUS_ALERT_COUNT_CACHE, "value", 7)
    monkeypatch.setitem(portal_backend.PORTAL_STATUS_ALERT_COUNT_CACHE, "updated_at", 1.0)
    monkeypatch.setattr(
        portal_backend,
        "_ensure_fault_alert_count_refresh",
        lambda: refresh_task,
    )

    count = await portal_backend._get_employee_alert_count("fault")

    assert count == 7


def test_build_portal_employee_status_payload_prefers_recent_session_for_idle() -> None:
    payload = portal_backend._build_portal_employee_status_payload(
        "knowledge",
        available=True,
        total_chat_count=3,
        active_task_count=0,
        active_chat_count=0,
        alert_count=0,
        latest_session_title="Oracle 死锁方案",
        updated_at="2026-01-02T03:04:05+00:00",
    )

    assert payload["status"] == "idle"
    assert payload["employeeName"] == "知识库助手"
    assert payload["urgent"] is False
    assert payload["workStatus"] == "待机"
    assert payload["currentJob"] == "最近会话：Oracle 死锁方案"


def test_alarm_analyst_diagnose_route_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend,
        "run_alarm_analyst_diagnose",
        lambda payload: {
            "session": {
                "sessionId": payload["sessionId"],
                "scene": "alarm_analyst_rca",
            },
            "result": {
                "summary": "已定位为数据库死锁导致 CMDB 新增失败",
                "rootCause": {"type": "数据库异常"},
                "steps": [{"id": "database-analysis", "status": "success"}],
                "logEntries": [{"stage": "database-analysis", "summary": "锁等待命中"}],
            },
        },
    )

    response = client.post(
        "/api/portal/alarm-analyst/diagnose",
        json={
            "sessionId": "fault-scenario-1",
            "employeeId": "fault",
            "content": "CMDB 添加失败，怀疑 mysql 死锁",
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["rootCause"]["type"] == "数据库异常"


def test_alarm_analyst_diagnose_route_persists_history_with_unique_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"alarm-analyst-1": []}

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)
    monkeypatch.setattr(
        portal_backend,
        "run_alarm_analyst_diagnose",
        lambda payload: {
            "session": {
                "sessionId": payload["sessionId"],
                "scene": "alarm_analyst_rca",
            },
            "result": {
                "summary": "存在拓扑伴随告警扩散。",
                "rootCause": {"type": "数据库异常", "object": "db_mysql_001"},
                "steps": [{"id": "related-alarms-recent", "status": "partial"}],
                "logEntries": [{"stage": "related-alarms", "summary": "recent 失败资源: 5002"}],
            },
        },
    )

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)

    payload = {
        "sessionId": "alarm-analyst-1",
        "employeeId": "fault",
        "content": "数据库锁异常\nCI ID：3094\n告警时间：2026-04-20 18:39:19",
    }

    first_response = client.post("/api/portal/alarm-analyst/diagnose", json=payload)
    second_response = client.post("/api/portal/alarm-analyst/diagnose", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(history_store["alarm-analyst-1"]) == 4

    message_ids = [message["id"] for message in history_store["alarm-analyst-1"]]
    assert len(message_ids) == len(set(message_ids))
    assert history_store["alarm-analyst-1"][-1]["faultScenarioResult"]["steps"][0]["status"] == "partial"


def test_alarm_analyst_diagnose_route_shapes_partial_result_for_history_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"alarm-analyst-1": []}

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)
    monkeypatch.setattr(
        portal_backend,
        "run_alarm_analyst_diagnose",
        lambda payload: {
            "session": {
                "sessionId": payload["sessionId"],
                "scene": "alarm_analyst_rca",
            },
            "result": {
                "summary": "部分完成",
            },
        },
    )

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)

    response = client.post(
        "/api/portal/alarm-analyst/diagnose",
        json={
            "sessionId": "alarm-analyst-1",
            "employeeId": "fault",
            "content": "数据库锁异常\nCI ID：3094\n告警时间：2026-04-20 18:39:19",
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["steps"] == []
    assert response.json()["result"]["logEntries"] == []
    assert history_store["alarm-analyst-1"][-1]["faultScenarioResult"]["steps"] == []
    assert history_store["alarm-analyst-1"][-1]["faultScenarioResult"]["logEntries"] == []


def test_alarm_analyst_cards_route_persists_and_lists_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    card_store: dict[str, dict[str, dict[str, dict]]] = {"fault-session-1": {}}
    db_store: dict[str, dict[str, dict]] = {}

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)

    async def fake_load_cards(_request, *, session_id: str, user_id: str = "default") -> dict:
        return dict(card_store.get(session_id, {}))

    async def fake_save_cards(
        _request,
        *,
        session_id: str,
        records: dict[str, dict[str, dict]],
        user_id: str = "default",
    ) -> None:
        card_store[session_id] = dict(records)

    monkeypatch.setattr(
        portal_backend,
        "_load_portal_alarm_analyst_cards",
        fake_load_cards,
    )
    monkeypatch.setattr(
        portal_backend,
        "_save_portal_alarm_analyst_cards",
        fake_save_cards,
    )
    monkeypatch.setattr(
        portal_backend,
        "_load_cards_for_chat_from_db",
        lambda chat_id: dict(db_store.get(chat_id, {})),
    )

    def fake_save_card_to_db(*, chat_id: str, message_id: str, card: dict, session_id: str = "") -> None:
        db_store.setdefault(chat_id, {})[message_id] = dict(card)

    monkeypatch.setattr(
        portal_backend,
        "_save_card_to_db",
        fake_save_card_to_db,
    )

    create_response = client.post(
        "/api/portal/alarm-analyst/cards",
        json={
            "sessionId": "fault-session-1",
            "chatId": "chat-1",
            "messageId": "assistant-1",
            "employeeId": "fault",
            "reportMarkdown": (
                "🔴 数据库锁异常 — 完整故障分析报告\n"
                "## 根因分析结论\n"
                "- 根资源 MySQL（CI ID 3094）出现锁等待放大\n"
                "## 影响范围\n"
                "- 受影响应用：CMDB\n"
                "## 处置建议\n"
                "- P0：终止异常慢 SQL 会话\n"
            ),
            "processBlocks": [
                {
                    "kind": "tool",
                    "toolName": "read_file",
                    "outputContent": (
                        "```json\n"
                        "{\"series\":[{\"type\":\"graph\",\"data\":[{\"id\":\"3094\",\"name\":\"MySQL\"}],"
                        "\"links\":[{\"source\":\"3094\",\"target\":\"3092\"}]}]}\n"
                        "```"
                    ),
                }
            ],
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["matched"] is True
    assert db_store["chat-1"]["assistant-1"]["summary"]["title"] == "数据库锁异常"
    assert "chat-1" in card_store["fault-session-1"]
    assert "assistant-1" in card_store["fault-session-1"]["chat-1"]

    list_response = client.get(
        "/api/portal/alarm-analyst/cards/chat-1",
        params={"sessionId": "fault-session-1"},
    )

    assert list_response.status_code == 200
    assert len(list_response.json()["cards"]) == 1
    assert list_response.json()["cards"][0]["source"]["messageId"] == "assistant-1"
    assert list_response.json()["cards"][0]["topology"]["nodes"][0]["id"] == "3094"


def test_alarm_analyst_cards_route_returns_unmatched_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    card_store: dict[str, dict[str, dict[str, dict]]] = {"fault-session-1": {}}
    db_store: dict[str, dict[str, dict]] = {}

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)

    async def fake_load_cards(_request, *, session_id: str, user_id: str = "default") -> dict:
        return dict(card_store.get(session_id, {}))

    async def fake_save_cards(
        _request,
        *,
        session_id: str,
        records: dict[str, dict[str, dict]],
        user_id: str = "default",
    ) -> None:
        card_store[session_id] = dict(records)

    monkeypatch.setattr(
        portal_backend,
        "_load_portal_alarm_analyst_cards",
        fake_load_cards,
    )
    monkeypatch.setattr(
        portal_backend,
        "_save_portal_alarm_analyst_cards",
        fake_save_cards,
    )
    monkeypatch.setattr(
        portal_backend,
        "_load_cards_for_chat_from_db",
        lambda chat_id: dict(db_store.get(chat_id, {})),
    )
    monkeypatch.setattr(
        portal_backend,
        "_save_card_to_db",
        lambda **_kwargs: db_store.setdefault("called", {}),
    )

    response = client.post(
        "/api/portal/alarm-analyst/cards",
        json={
            "sessionId": "fault-session-1",
            "chatId": "chat-1",
            "messageId": "assistant-2",
            "employeeId": "fault",
            "reportMarkdown": "这是普通回复，没有结构化 RCA 段落。",
            "processBlocks": [],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"matched": False, "card": None}
    assert card_store["fault-session-1"] == {}
    assert db_store == {}


def test_list_alarm_analyst_cards_reads_db_without_runtime_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    if hasattr(portal_backend.app.state, "multi_agent_manager"):
        delattr(portal_backend.app.state, "multi_agent_manager")

    monkeypatch.setattr(
        portal_backend,
        "_load_cards_for_chat_from_db",
        lambda _chat_id: {
            "assistant-1": {
                "type": "alarm-analyst-card",
                "version": "v1",
                "source": {
                    "chatId": "chat-1",
                    "messageId": "assistant-1",
                    "skillName": "alarm-analyst",
                    "contentHash": "hash-1",
                },
                "summary": {
                    "title": "数据库锁异常",
                    "conclusion": "MySQL 锁等待放大",
                },
                "rootCause": {"reason": "MySQL 锁等待放大"},
                "impact": {"affectedApplications": [], "affectedResources": []},
                "topology": {"nodes": [], "edges": []},
                "recommendations": [],
                "evidence": [],
                "workorderProposal": {
                    "proposalId": "proposal-1",
                    "idempotencyKey": "proposal-1",
                    "enabled": True,
                    "title": "数据库锁异常",
                    "summary": "建议创建故障工单",
                    "alarmId": "COM_2079409043571912704",
                    "suggestions": ["先止血后修复"],
                    "expiresInSeconds": 10,
                },
                "workorderStatus": {"state": "idle"},
                "rawReportMarkdown": "报告正文",
            }
        },
    )

    response = client.get(
        "/api/portal/alarm-analyst/cards/chat-1",
        params={"sessionId": "portal-fault-alarm-COM_2079409043571912704"},
    )

    assert response.status_code == 200
    assert len(response.json()["cards"]) == 1
    assert response.json()["cards"][0]["source"]["messageId"] == "assistant-1"



def test_list_alarm_analyst_cards_returns_backfilled_card_without_runtime_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    if hasattr(portal_backend.app.state, "multi_agent_manager"):
        delattr(portal_backend.app.state, "multi_agent_manager")

    backfilled_card = portal_backend.AlarmAnalystCard.model_validate(
        {
            "type": "alarm-analyst-card",
            "version": "v1",
            "source": {
                "chatId": "chat-1",
                "messageId": "assistant-backfilled",
                "skillName": "alarm-analyst",
                "contentHash": "hash-backfilled",
            },
            "summary": {
                "title": "系统平均负载过高",
                "conclusion": "误告警，阈值规则逻辑配置错误",
            },
            "rootCause": {"reason": "误告警，阈值规则逻辑配置错误"},
            "impact": {"affectedApplications": [], "affectedResources": []},
            "topology": {"nodes": [], "edges": []},
            "recommendations": [],
            "evidence": [],
            "workorderProposal": {
                "proposalId": "proposal-backfilled",
                "idempotencyKey": "proposal-backfilled",
                "enabled": True,
                "title": "系统平均负载过高",
                "summary": "建议创建故障工单",
                "alarmId": "COM_2079409043571912704",
                "suggestions": ["检查阈值规则"],
                "expiresInSeconds": 10,
            },
            "workorderStatus": {"state": "idle"},
            "rawReportMarkdown": "报告正文",
        }
    )
    mirrored: list[tuple[str, str, str]] = []

    monkeypatch.setattr(portal_backend, "_load_cards_for_chat_from_db", lambda _chat_id: {})

    async def fake_backfill(*, request, session_id: str, chat_id: str, employee_id: str):
        assert session_id == "portal-fault-alarm-COM_2079409043571912704"
        assert chat_id == "chat-1"
        assert employee_id == "fault"
        return backfilled_card

    async def fake_mirror(_request, *, session_id: str, chat_id: str, message_id: str, card):
        mirrored.append((session_id, chat_id, message_id))
        assert card.source.message_id == "assistant-backfilled"

    monkeypatch.setattr(
        portal_backend,
        "_try_persist_alarm_analyst_card_from_agent_context",
        fake_backfill,
    )
    monkeypatch.setattr(
        portal_backend,
        "_mirror_alarm_analyst_card_to_session_state",
        fake_mirror,
    )

    response = client.get(
        "/api/portal/alarm-analyst/cards/chat-1",
        params={"sessionId": "portal-fault-alarm-COM_2079409043571912704"},
    )

    assert response.status_code == 200
    assert response.json()["cards"][0]["summary"]["title"] == "系统平均负载过高"
    assert mirrored == [
        (
            "portal-fault-alarm-COM_2079409043571912704",
            "chat-1",
            "assistant-backfilled",
        )
    ]



def test_alarm_analyst_cards_route_reuses_existing_db_card_for_alarm_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    card_store: dict[str, dict[str, dict[str, dict]]] = {"portal-fault-alarm-abc": {}}
    existing_card = {
        "type": "alarm-analyst-card",
        "version": "v1",
        "source": {
            "chatId": "chat-1",
            "messageId": "assistant-1",
            "skillName": "alarm-analyst",
            "contentHash": "hash-1",
        },
        "summary": {
            "title": "数据库锁异常",
            "conclusion": "MySQL 锁等待放大",
        },
        "rootCause": {"reason": "MySQL 锁等待放大"},
        "impact": {"affectedApplications": [], "affectedResources": []},
        "topology": {"nodes": [], "edges": []},
        "recommendations": [],
        "evidence": [],
        "workorderProposal": {
            "proposalId": "proposal-1",
            "idempotencyKey": "proposal-1",
            "enabled": True,
            "title": "数据库锁异常",
            "summary": "建议创建故障工单",
            "alarmId": "abc",
            "suggestions": ["先止血后修复"],
            "expiresInSeconds": 10,
        },
        "workorderStatus": {"state": "idle"},
        "rawReportMarkdown": "已存在报告正文",
    }
    db_store = {"chat-1": {"assistant-1": existing_card}}
    save_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)

    async def fake_load_cards(_request, *, session_id: str, user_id: str = "default") -> dict:
        return dict(card_store.get(session_id, {}))

    async def fake_save_cards(
        _request,
        *,
        session_id: str,
        records: dict[str, dict[str, dict]],
        user_id: str = "default",
    ) -> None:
        card_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_alarm_analyst_cards", fake_load_cards)
    monkeypatch.setattr(portal_backend, "_save_portal_alarm_analyst_cards", fake_save_cards)
    monkeypatch.setattr(
        portal_backend,
        "_load_cards_for_chat_from_db",
        lambda chat_id: dict(db_store.get(chat_id, {})),
    )

    def fake_save_card_to_db(*, chat_id: str, message_id: str, card: dict, session_id: str = "") -> None:
        save_calls.append((chat_id, message_id))
        db_store.setdefault(chat_id, {})[message_id] = dict(card)

    monkeypatch.setattr(portal_backend, "_save_card_to_db", fake_save_card_to_db)

    response = client.post(
        "/api/portal/alarm-analyst/cards",
        json={
            "sessionId": "portal-fault-alarm-abc",
            "chatId": "chat-1",
            "messageId": "assistant-1",
            "employeeId": "fault",
            "reportMarkdown": "这是一次失败的兜底重试文本，不应该覆盖已落库卡片。",
            "processBlocks": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["card"]["summary"]["title"] == "数据库锁异常"
    assert save_calls == []
    assert card_store["portal-fault-alarm-abc"]["chat-1"]["assistant-1"]["summary"]["title"] == "数据库锁异常"


def test_alarm_analyst_cards_route_returns_existing_card_for_same_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    card_store: dict[str, dict[str, dict[str, dict]]] = {"portal-fault-alarm-abc": {}}
    existing_card = {
        "type": "alarm-analyst-card",
        "version": "v1",
        "source": {
            "chatId": "chat-1",
            "messageId": "assistant-1",
            "skillName": "alarm-analyst",
            "contentHash": "hash-1",
        },
        "summary": {
            "title": "数据库锁异常",
            "conclusion": "MySQL 锁等待放大",
        },
        "rootCause": {"reason": "MySQL 锁等待放大"},
        "impact": {"affectedApplications": [], "affectedResources": []},
        "topology": {"nodes": [], "edges": []},
        "recommendations": [],
        "evidence": [],
        "workorderProposal": {
            "proposalId": "proposal-1",
            "idempotencyKey": "proposal-1",
            "enabled": True,
            "title": "数据库锁异常",
            "summary": "建议创建故障工单",
            "alarmId": "abc",
            "suggestions": ["先止血后修复"],
            "expiresInSeconds": 10,
        },
        "workorderStatus": {"state": "idle"},
        "rawReportMarkdown": "已存在报告正文",
    }
    db_store = {"chat-1": {"assistant-1": existing_card}}
    save_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)

    async def fake_load_cards(_request, *, session_id: str, user_id: str = "default") -> dict:
        return dict(card_store.get(session_id, {}))

    async def fake_save_cards(
        _request,
        *,
        session_id: str,
        records: dict[str, dict[str, dict]],
        user_id: str = "default",
    ) -> None:
        card_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_alarm_analyst_cards", fake_load_cards)
    monkeypatch.setattr(portal_backend, "_save_portal_alarm_analyst_cards", fake_save_cards)
    monkeypatch.setattr(
        portal_backend,
        "_load_cards_for_chat_from_db",
        lambda chat_id: dict(db_store.get(chat_id, {})),
    )

    def fake_save_card_to_db(*, chat_id: str, message_id: str, card: dict, session_id: str = "") -> None:
        save_calls.append((chat_id, message_id))
        db_store.setdefault(chat_id, {})[message_id] = dict(card)

    monkeypatch.setattr(portal_backend, "_save_card_to_db", fake_save_card_to_db)

    response = client.post(
        "/api/portal/alarm-analyst/cards",
        json={
            "sessionId": "portal-fault-alarm-abc",
            "chatId": "chat-1",
            "messageId": "assistant-1",
            "employeeId": "fault",
            "reportMarkdown": "这是一次失败的兜底重试文本，不应该覆盖已落库卡片。",
            "processBlocks": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["card"]["summary"]["title"] == "数据库锁异常"
    assert save_calls == []
    assert card_store["portal-fault-alarm-abc"]["chat-1"]["assistant-1"]["summary"]["title"] == "数据库锁异常"


def test_alarm_analyst_cards_route_reuses_existing_card_for_same_chat_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    card_store: dict[str, dict[str, dict[str, dict]]] = {"portal-fault-alarm-abc": {}}
    existing_card = {
        "type": "alarm-analyst-card",
        "version": "v1",
        "source": {
            "chatId": "chat-1",
            "messageId": "assistant-1",
            "skillName": "alarm-analyst",
            "contentHash": "hash-1",
        },
        "summary": {
            "title": "数据库锁异常",
            "conclusion": "MySQL 锁等待放大",
        },
        "rootCause": {"reason": "MySQL 锁等待放大"},
        "impact": {"affectedApplications": [], "affectedResources": []},
        "topology": {"nodes": [], "edges": []},
        "recommendations": [],
        "evidence": [],
        "workorderProposal": {
            "proposalId": "proposal-1",
            "idempotencyKey": "proposal-1",
            "enabled": True,
            "title": "数据库锁异常",
            "summary": "建议创建故障工单",
            "alarmId": "abc",
            "suggestions": ["先止血后修复"],
            "expiresInSeconds": 10,
        },
        "workorderStatus": {"state": "idle"},
        "rawReportMarkdown": (
            "## 告警分析报告：数据库锁异常\n"
            "## 告警基础信息\n"
            "- 告警时间：2026-07-28 10:00:00\n"
            "## 根因判断\n"
            "- MySQL 锁等待放大，导致写入链路受阻。\n"
            "## 影响范围\n"
            "- 受影响应用：CMDB\n"
            "## 处置建议\n"
            "- P0：终止异常慢 SQL 会话。\n"
            "## 📊 总结\n"
            "- 置信度：86%"
        ),
    }
    db_store = {"chat-1": {"assistant-1": existing_card}}
    save_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)

    async def fake_load_cards(_request, *, session_id: str, user_id: str = "default") -> dict:
        return dict(card_store.get(session_id, {}))

    async def fake_save_cards(
        _request,
        *,
        session_id: str,
        records: dict[str, dict[str, dict]],
        user_id: str = "default",
    ) -> None:
        card_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_alarm_analyst_cards", fake_load_cards)
    monkeypatch.setattr(portal_backend, "_save_portal_alarm_analyst_cards", fake_save_cards)
    monkeypatch.setattr(
        portal_backend,
        "_load_cards_for_chat_from_db",
        lambda chat_id: dict(db_store.get(chat_id, {})),
    )

    def fake_save_card_to_db(*, chat_id: str, message_id: str, card: dict, session_id: str = "") -> None:
        save_calls.append((chat_id, message_id))
        db_store.setdefault(chat_id, {})[message_id] = dict(card)

    monkeypatch.setattr(portal_backend, "_save_card_to_db", fake_save_card_to_db)

    response = client.post(
        "/api/portal/alarm-analyst/cards",
        json={
            "sessionId": "portal-fault-alarm-abc",
            "chatId": "chat-1",
            "messageId": "assistant-2",
            "employeeId": "fault",
            "reportMarkdown": existing_card["rawReportMarkdown"],
            "processBlocks": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["card"]["source"]["messageId"] == "assistant-1"
    assert response.json()["card"]["workorderProposal"]["proposalId"] == "proposal-1"
    assert save_calls == []


def test_alarm_analyst_cards_route_allows_alarm_session_fallback_for_report_like_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    card_store: dict[str, dict[str, dict[str, dict]]] = {"portal-fault-alarm-abc": {}}
    db_store: dict[str, dict[str, dict]] = {}
    registry_calls: list[dict[str, object]] = []

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)

    async def fake_load_cards(_request, *, session_id: str, user_id: str = "default") -> dict:
        return dict(card_store.get(session_id, {}))

    async def fake_save_cards(
        _request,
        *,
        session_id: str,
        records: dict[str, dict[str, dict]],
        user_id: str = "default",
    ) -> None:
        card_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_alarm_analyst_cards", fake_load_cards)
    monkeypatch.setattr(portal_backend, "_save_portal_alarm_analyst_cards", fake_save_cards)
    monkeypatch.setattr(portal_backend, "_load_cards_for_chat_from_db", lambda chat_id: dict(db_store.get(chat_id, {})))

    def fake_save_card_to_db(*, chat_id: str, message_id: str, card: dict, session_id: str = "") -> None:
        db_store.setdefault(chat_id, {})[message_id] = dict(card)

    monkeypatch.setattr(portal_backend, "_save_card_to_db", fake_save_card_to_db)
    monkeypatch.setattr(
        portal_backend,
        "_persist_analysis_result_to_registry",
        lambda **kwargs: registry_calls.append(dict(kwargs)),
    )

    response = client.post(
        "/api/portal/alarm-analyst/cards",
        json={
            "sessionId": "portal-fault-alarm-abc",
            "chatId": "chat-1",
            "messageId": "assistant-2",
            "employeeId": "fault",
            "reportMarkdown": (
                "## 告警分析报告：数据库锁异常\n"
                "## 根因判断\n"
                "- MySQL 锁等待放大，导致写入链路受阻。\n"
                "## 影响范围\n"
                "- 受影响应用：CMDB\n"
                "## 处置建议\n"
                "- P0：终止异常慢 SQL 会话。\n"
            ),
            "processBlocks": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert db_store["chat-1"]["assistant-2"]["summary"]["title"] == "数据库锁异常"
    assert registry_calls == [
        {
            "session_id": "portal-fault-alarm-abc",
            "card": db_store["chat-1"]["assistant-2"],
            "chat_id": "chat-1",
        }
    ]


def test_alarm_analyst_workorders_route_returns_existing_created_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    card_payload = {
        "type": "alarm-analyst-card",
        "version": "v1",
        "source": {
            "chatId": "chat-1",
            "messageId": "assistant-1",
            "skillName": "alarm-analyst",
            "contentHash": "hash-1",
        },
        "summary": {
            "title": "数据库锁异常",
            "conclusion": "MySQL 锁等待放大",
        },
        "rootCause": {"reason": "MySQL 锁等待放大"},
        "impact": {"affectedApplications": [], "affectedResources": []},
        "topology": {"nodes": [], "edges": []},
        "recommendations": [],
        "evidence": [],
        "workorderProposal": {
            "proposalId": "proposal-1",
            "idempotencyKey": "proposal-1",
            "enabled": True,
            "title": "数据库锁异常",
            "summary": "建议创建故障工单",
            "alarmId": "alarm-1",
            "suggestions": ["先止血后修复"],
            "expiresInSeconds": 10,
        },
        "workorderStatus": {
            "state": "created",
            "workorderId": "wo-1",
            "processId": "proc-1",
        },
        "rawReportMarkdown": "报告正文",
    }

    monkeypatch.setattr(
        portal_backend,
        "_find_alarm_analyst_card_by_proposal",
        lambda **_kwargs: (
            portal_backend.AlarmAnalystCard.model_validate(card_payload),
            "assistant-1",
        ),
    )

    response = client.post(
        "/api/portal/alarm-analyst/workorders",
        json={
            "proposalId": "proposal-1",
            "messageId": "assistant-1",
            "chatId": "chat-1",
            "alarmId": "alarm-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "already_exists"
    assert body["workorderId"] == "wo-1"
    assert body["workorderStatus"]["processId"] == "proc-1"



def test_alarm_analyst_workorders_route_uses_original_alarm_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    saved_cards: list[dict[str, object]] = []
    registry_updates: list[dict[str, object]] = []
    create_payloads: list[dict[str, object]] = []

    card_payload = {
        "type": "alarm-analyst-card",
        "version": "v1",
        "source": {
            "chatId": "chat-1",
            "messageId": "assistant-2",
            "skillName": "alarm-analyst",
            "contentHash": "hash-2",
        },
        "summary": {
            "title": "报告推送成功。现在整理完整分析报告给用户。",
            "conclusion": "疑似数据库锁等待",
            "severity": "critical",
        },
        "rootCause": {"reason": "锁等待放大"},
        "impact": {"affectedApplications": [], "affectedResources": []},
        "topology": {"nodes": [], "edges": []},
        "recommendations": [],
        "evidence": [],
        "workorderProposal": {
            "proposalId": "proposal-2",
            "idempotencyKey": "proposal-2",
            "enabled": True,
            "title": "报告推送成功。现在整理完整分析报告给用户。",
            "summary": "建议创建故障工单",
            "alarmId": "alarm-2",
            "deviceName": "db_mysql_001",
            "manageIp": "10.43.150.186",
            "eventTime": "2026-07-21 16:42:32",
            "severity": "critical",
            "suggestions": ["先止血后修复"],
            "expiresInSeconds": 10,
        },
        "rawReportMarkdown": "报告正文",
    }

    monkeypatch.setattr(
        portal_backend,
        "_find_alarm_analyst_card_by_proposal",
        lambda **_kwargs: (
            portal_backend.AlarmAnalystCard.model_validate(card_payload),
            "assistant-2",
        ),
    )
    monkeypatch.setattr(
        portal_backend,
        "get_alarm_record",
        lambda alarm_id: {
            "alarmId": alarm_id,
            "id": alarm_id,
            "title": "系统平均负载过高",
            "deviceName": "db_mysql_001",
            "manageIp": "10.43.150.186",
            "eventTime": "2026-07-21 16:42:32",
            "level": "critical",
            "status": "active",
            "resId": "3094",
            "visibleContent": "系统平均负载过高（db_mysql_001 10.43.150.186）",
            "additionalText": "原始报文：load average 15m 持续超过阈值",
            "alarmLocation": "db_mysql_001 / 10.43.150.186",
        },
    )
    monkeypatch.setattr(
        portal_backend,
        "create_order_disposal_workorder",
        lambda payload: create_payloads.append(payload) or {
            "code": 200,
            "data": {"workOrderId": "wo-2", "processId": "proc-2"},
        },
    )
    monkeypatch.setattr(
        portal_backend,
        "_save_card_to_db",
        lambda **kwargs: saved_cards.append(kwargs),
    )
    monkeypatch.setattr(
        portal_backend,
        "_update_portal_real_alarm_registry_safe",
        lambda **kwargs: registry_updates.append(kwargs) or {},
    )

    response = client.post(
        "/api/portal/alarm-analyst/workorders",
        json={
            "proposalId": "proposal-2",
            "messageId": "assistant-2",
            "chatId": "chat-1",
            "alarmId": "alarm-2",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["workorderId"] == "wo-2"
    assert create_payloads[0]["alarm"]["alarmId"] == "alarm-2"
    assert create_payloads[0]["alarm"]["alarmSeq"] == "alarm-2"
    assert create_payloads[0]["alarm"]["alarmTitle"] == "系统平均负载过高"
    assert (
        create_payloads[0]["alarm"]["additionalText"]
        == "原始报文：load average 15m 持续超过阈值"
    )
    assert create_payloads[0]["alarm"]["alarmLocation"] == "db_mysql_001 / 10.43.150.186"
    assert create_payloads[0]["ticket"]["title"] == "报告推送成功。现在整理完整分析报告给用户。"
    assert saved_cards[0]["message_id"] == "assistant-2"
    assert registry_updates[0]["status"] == "manual_pending"



def test_real_alarms_route_returns_backend_payload(monkeypatch) -> None:
    client = TestClient(portal_backend.app)
    received: dict[str, int] = {}

    monkeypatch.setattr(
        portal_backend,
        "query_portal_real_alarms",
        lambda limit: received.setdefault("limit", limit) and {
            "total": 1,
            "items": [
                {
                    "id": "mock-deadlock-1",
                    "alarmId": "mock-deadlock-1",
                    "resId": "3094",
                    "title": "数据库锁异常",
                    "level": "critical",
                    "status": "active",
                    "eventTime": "2026-04-15 19:20:00",
                    "timeLabel": "2026-04-15 19:20:00",
                    "deviceName": "MySQL",
                    "manageIp": "10.43.150.186",
                    "employeeId": "fault",
                    "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
                    "visibleContent": "数据库锁异常（MySQL 10.43.150.186）",
                }
            ],
            "source": "live",
        },
    )
    monkeypatch.setattr(portal_backend, "filter_visible_alarms", lambda payload: payload)

    response = client.get("/api/portal/real-alarms?limit=8")

    assert response.status_code == 200
    assert received["limit"] == 24
    assert response.json()["source"] == "live"
    assert response.json()["items"][0]["employeeId"] == "fault"
    assert response.json()["items"][0]["resId"] == "3094"




def test_real_alarm_register_route_persists_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    update_calls: list[dict[str, object]] = []

    def fake_update_alarm_record(**kwargs):
        update_calls.append(kwargs)
        return {
            "alarmId": kwargs["alarm_id"],
            "sessionId": kwargs.get("session_id", ""),
            "status": kwargs.get("status", ""),
        }

    monkeypatch.setattr(
        portal_backend,
        "update_alarm_record",
        fake_update_alarm_record,
    )

    response = client.post(
        "/api/portal/alarm-registry/register",
        json={
            "alarmId": "alarm-1",
            "sessionId": "portal-fault-alarm-alarm-1",
            "title": "数据库锁异常",
            "additionalText": "原始报文：lock wait timeout",
            "alarmLocation": "db_mysql_001 / 10.43.150.186",
            "status": "analyzing",
            "source": "manual-bell",
        },
    )

    assert response.status_code == 200
    assert update_calls[0]["session_id"] == "portal-fault-alarm-alarm-1"
    assert update_calls[0]["alarm"]["additionalText"] == "原始报文：lock wait timeout"
    assert update_calls[0]["alarm"]["alarmLocation"] == "db_mysql_001 / 10.43.150.186"
    assert response.json()["record"]["sessionId"] == "portal-fault-alarm-alarm-1"



def test_stream_done_status_update_uses_session_id_when_chat_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        portal_backend,
        "_try_persist_analysis_result_from_stream",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        portal_backend,
        "_update_portal_real_alarm_registry_safe",
        lambda **kwargs: update_calls.append(kwargs) or {},
    )

    class DummyStream:
        async def aclose(self) -> None:
            return None

        def __aiter__(self):
            async def _gen():
                if False:
                    yield ""
            return _gen()

    class DummyTaskTracker:
        def stream_from_queue(self, _queue, _chat_id):
            return DummyStream()

    asyncio.run(
        portal_backend._drain_portal_real_alarm_stream(
            DummyTaskTracker(),
            object(),
            "",
            "portal-fault-alarm-abc",
        ),
    )

    assert update_calls[0]["session_id"] == "portal-fault-alarm-abc"
    assert update_calls[0]["status"] == "analyzed"



def test_stream_persistence_uses_unified_alarm_card_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        portal_backend,
        "_collect_sse_report_messages",
        lambda _chunks: [
            ("assistant-1", "普通结束语"),
            (
                "assistant-2",
                "## 告警分析报告：数据库锁异常\n"
                "## 根因判断\n"
                "- MySQL 锁等待放大。\n"
                "## 影响范围\n"
                "- 受影响应用：CMDB\n"
                "## 处置建议\n"
                "- P0：终止异常慢 SQL 会话。\n",
            ),
        ],
    )

    def fake_persist(**kwargs):
        persisted_calls.append(kwargs)
        return (kwargs["message_id"] == "assistant-2", None, False)

    monkeypatch.setattr(
        portal_backend,
        "_persist_alarm_analyst_card_from_report",
        fake_persist,
    )

    portal_backend._try_persist_analysis_result_from_stream(
        chunks=["ignored"],
        chat_id="chat-1",
        session_id="portal-fault-alarm-abc",
    )

    assert [call["message_id"] for call in persisted_calls] == ["assistant-2"]
    assert persisted_calls[0]["session_id"] == "portal-fault-alarm-abc"
    assert persisted_calls[0]["employee_id"] == "fault"



def test_list_alarm_analyst_cards_enriches_missing_proposal_fields_from_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend.app.state,
        "multi_agent_manager",
        object(),
        raising=False,
    )
    monkeypatch.setattr(
        portal_backend,
        "_load_cards_for_chat_from_db",
        lambda _chat_id: {
            "assistant-1": {
                "type": "alarm-analyst-card",
                "version": "v1",
                "source": {
                    "chatId": "chat-1",
                    "messageId": "assistant-1",
                    "skillName": "alarm-analyst",
                    "contentHash": "hash-1",
                },
                "summary": {
                    "title": "项目 | 值",
                    "conclusion": "系统平均负载超过阈值（如 >80）才应告警",
                },
                "rootCause": {
                    "reason": "系统平均负载超过阈值（如 >80）才应告警",
                },
                "impact": {"affectedApplications": [], "affectedResources": []},
                "topology": {"nodes": [], "edges": []},
                "recommendations": [],
                "evidence": [],
                "workorderProposal": {
                    "proposalId": "proposal-1",
                    "idempotencyKey": "proposal-1",
                    "enabled": True,
                    "title": "项目 | 值",
                    "summary": "建议创建故障工单",
                    "alarmId": "portal-abc",
                    "suggestions": ["检查规则配置"],
                    "expiresInSeconds": 10,
                },
                "workorderStatus": {"state": "idle"},
                "rawReportMarkdown": "报告正文",
            }
        },
    )
    monkeypatch.setattr(
        portal_backend,
        "get_alarm_record",
        lambda alarm_id: {
            "alarmId": alarm_id,
            "title": "系统平均负载过高",
            "deviceName": "172.28.75.4",
            "manageIp": "172.28.75.4",
            "eventTime": "2026-07-21 16:42:32",
            "level": "严重",
            "resId": "3094",
        },
    )

    response = client.get(
        "/api/portal/alarm-analyst/cards/chat-1",
        params={"sessionId": "portal-fault-alarm-abc"},
    )

    assert response.status_code == 200
    card = response.json()["cards"][0]
    assert card["workorderProposal"]["title"] == "系统平均负载过高"
    assert card["workorderProposal"]["deviceName"] == "172.28.75.4"
    assert card["workorderProposal"]["manageIp"] == "172.28.75.4"



def test_real_alarms_route_does_not_start_sessions_on_list_when_runtime_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    payload = {
        "total": 1,
        "items": [
            {
                "id": "alarm-1",
                "alarmId": "alarm-1",
                "resId": "3094",
                "title": "数据库锁异常",
                "level": "critical",
                "status": "active",
                "eventTime": "2026-04-15 19:20:00",
                "timeLabel": "2026-04-15 19:20:00",
                "deviceName": "MySQL",
                "manageIp": "10.43.150.186",
                "employeeId": "fault",
                "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
                "visibleContent": "数据库锁异常（MySQL 10.43.150.186）",
            }
        ],
        "source": "live",
    }
    called: dict[str, object] = {}

    monkeypatch.setattr(
        portal_backend,
        "_query_visible_portal_real_alarms",
        lambda limit: payload,
    )

    async def fake_ensure(request, alarms_payload):
        called["request"] = request
        called["payload"] = alarms_payload

    monkeypatch.setattr(
        portal_backend,
        "_ensure_portal_real_alarm_sessions",
        fake_ensure,
    )

    response = client.get("/api/portal/real-alarms?limit=8")

    assert response.status_code == 200
    assert called == {}


def test_real_alarms_trigger_sessions_route_starts_sessions_when_runtime_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)

    payload = {
        "total": 1,
        "items": [
            {
                "id": "alarm-1",
                "alarmId": "alarm-1",
                "resId": "3094",
                "title": "数据库锁异常",
                "level": "critical",
                "status": "active",
                "eventTime": "2026-04-15 19:20:00",
                "timeLabel": "2026-04-15 19:20:00",
                "deviceName": "MySQL",
                "manageIp": "10.43.150.186",
                "employeeId": "fault",
                "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
                "visibleContent": "数据库锁异常（MySQL 10.43.150.186）",
            }
        ],
        "source": "live",
    }
    called: dict[str, object] = {}

    monkeypatch.setattr(portal_backend, "_query_visible_portal_real_alarms", lambda limit: payload)

    async def fake_ensure(request, alarms_payload, *, takeover_source: str = "manual-trigger"):
        called["request"] = request
        called["payload"] = alarms_payload
        called["takeover_source"] = takeover_source
        return {
            "total": 1,
            "eligible": 1,
            "created": 1,
            "started": 1,
            "skipped": 0,
            "sessions": ["portal-fault-alarm-alarm-1"],
        }

    monkeypatch.setattr(portal_backend, "_ensure_portal_real_alarm_sessions", fake_ensure)

    response = client.post("/api/portal/real-alarms/trigger-sessions?limit=8")

    assert response.status_code == 200
    assert called["payload"] == payload
    assert called["takeover_source"] == "manual-trigger"
    assert response.json()["started"] == 1
    assert response.json()["alarmSource"] == "live"


def test_build_portal_real_alarm_payload_uses_runtime_text_content() -> None:
    payload = portal_backend._build_portal_real_alarm_payload(  # pylint: disable=protected-access
        "portal-fault-alarm-alarm-1",
        {
            "id": "alarm-1",
            "alarmId": "alarm-1",
            "resId": "3094",
            "title": "数据库锁异常",
            "eventTime": "2026-04-15 19:20:00",
            "deviceName": "MySQL",
            "manageIp": "10.43.150.186",
            "visibleContent": "数据库锁异常（MySQL 10.43.150.186）",
        },
    )

    assert payload["content_parts"][0].type == "text"
    assert "告警流水号：alarm-1" in payload["content_parts"][0].text


def test_inspection_trigger_sessions_route_starts_session_when_runtime_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)
    called: dict[str, object] = {}

    async def fake_ensure(request, *, inspection_object: str, session_id: str = ""):
        called["request"] = request
        called["inspection_object"] = inspection_object
        called["session_id"] = session_id
        return {
            "inspectionObject": inspection_object,
            "sessionId": "portal-inspection-target-db",
            "created": 1,
            "started": 1,
            "skipped": 0,
            "chatId": "chat-1",
        }

    monkeypatch.setattr(portal_backend, "_ensure_portal_inspection_session", fake_ensure)

    response = client.post(
        "/api/portal/inspection/trigger-sessions",
        json={"inspectionObject": "数据库"},
    )

    assert response.status_code == 200
    assert called["inspection_object"] == "数据库"
    assert response.json()["started"] == 1
    assert response.json()["sessionId"] == "portal-inspection-target-db"


def test_build_portal_inspection_payload_uses_runtime_text_content() -> None:
    payload = portal_backend._build_portal_inspection_payload(  # pylint: disable=protected-access
        "portal-inspection-target-db",
        "数据库",
    )

    assert payload["content_parts"][0].type == "text"
    assert "请帮我巡检一下数据库" in payload["content_parts"][0].text


def test_real_alarms_route_returns_fallback_payload_when_backend_query_fails(
    monkeypatch,
) -> None:
    client = TestClient(portal_backend.app)

    def _raise(limit: int) -> dict:
        raise RuntimeError("unexpected backend failure")

    monkeypatch.setattr(portal_backend, "_query_visible_portal_real_alarms", _raise)
    monkeypatch.setattr(
        portal_backend,
        "_load_visible_portal_real_alarm_fallback_payload",
        lambda limit: {"total": 0, "items": [], "source": "live"},
    )

    response = client.get("/api/portal/real-alarms?limit=8")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": [], "source": "live"}


def test_real_alarms_route_keeps_alarm_workorders_route_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend,
        "query_alarm_workorders",
        lambda limit: {"total": 2, "items": [{"id": "wo-1"}], "source": "mock"},
    )
    monkeypatch.setattr(
        portal_backend,
        "_query_visible_portal_real_alarms",
        lambda limit: {"total": 1, "items": [{"id": "alarm-1"}], "source": "live"},
    )

    workorders_response = client.get("/api/portal/alarm-workorders?limit=5")
    real_alarms_response = client.get("/api/portal/real-alarms?limit=5")

    assert workorders_response.status_code == 200
    assert real_alarms_response.status_code == 200
    assert workorders_response.json()["total"] == 2
    assert real_alarms_response.json()["total"] == 1


@pytest.mark.asyncio
async def test_auto_takeover_once_uses_auto_poll_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_app = SimpleNamespace(state=SimpleNamespace(multi_agent_manager=object()))
    payload = {
        "total": 1,
        "items": [
            {
                "id": "alarm-1",
                "alarmId": "alarm-1",
                "resId": "3094",
                "title": "数据库锁异常",
                "level": "critical",
                "status": "active",
                "eventTime": "2026-04-15 19:20:00",
                "timeLabel": "2026-04-15 19:20:00",
                "deviceName": "MySQL",
                "manageIp": "10.43.150.186",
                "employeeId": "fault",
                "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
                "visibleContent": "数据库锁异常（MySQL 10.43.150.186）",
            }
        ],
        "source": "live",
    }
    called: dict[str, object] = {}

    monkeypatch.setattr(
        portal_backend,
        "_get_portal_auto_takeover_runtime_app",
        lambda: runtime_app,
    )

    async def fake_build(limit, trigger_body, *, allow_stale: bool = True):
        return payload

    monkeypatch.setattr(
        portal_backend,
        "_build_portal_real_alarm_trigger_payload",
        fake_build,
    )

    async def fake_ensure(request, alarms_payload, *, takeover_source: str = "manual-trigger"):
        called["request_app"] = request.app
        called["payload"] = alarms_payload
        called["takeover_source"] = takeover_source
        return {
            "total": 1,
            "eligible": 1,
            "created": 1,
            "started": 1,
            "skipped": 0,
            "sessions": ["portal-fault-alarm-alarm-1"],
        }

    monkeypatch.setattr(portal_backend, "_ensure_portal_real_alarm_sessions", fake_ensure)

    summary = await portal_backend._run_portal_real_alarm_auto_takeover_once()  # pylint: disable=protected-access

    assert called["request_app"] is runtime_app
    assert called["payload"] == payload
    assert called["takeover_source"] == "auto-poll"
    assert summary["started"] == 1
    assert summary["alarmSource"] == "live"


@pytest.mark.asyncio
async def test_auto_takeover_once_skips_non_live_alarm_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_app = SimpleNamespace(state=SimpleNamespace(multi_agent_manager=object()))
    called: dict[str, object] = {}

    monkeypatch.setattr(
        portal_backend,
        "_get_portal_auto_takeover_runtime_app",
        lambda: runtime_app,
    )

    async def fake_build(limit, trigger_body, *, allow_stale: bool = True):
        return {"total": 2, "items": [{"id": "alarm-1"}], "source": "stale"}

    async def fake_ensure(request, alarms_payload, *, takeover_source: str = "manual-trigger"):
        called["request"] = request
        called["payload"] = alarms_payload
        return {"started": 1}

    monkeypatch.setattr(
        portal_backend,
        "_build_portal_real_alarm_trigger_payload",
        fake_build,
    )
    monkeypatch.setattr(portal_backend, "_ensure_portal_real_alarm_sessions", fake_ensure)

    summary = await portal_backend._run_portal_real_alarm_auto_takeover_once()  # pylint: disable=protected-access

    assert summary["ok"] is False
    assert summary["reason"] == "alarm-source-unavailable"
    assert summary["alarmSource"] == "stale"
    assert summary["started"] == 0
    assert called == {}


def test_fault_disposal_history_normalizes_fault_scenario_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return [
            {
                "id": "agent-1",
                "type": "agent",
                "content": "部分完成",
                "faultScenarioResult": {
                    "summary": "部分完成",
                },
            }
        ]

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)

    response = client.get("/api/portal/fault-disposal/history/fault-scenario-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["faultScenarioResult"]["steps"] == []
    assert payload["messages"][0]["faultScenarioResult"]["logEntries"] == []


def test_fault_disposal_history_preserves_unknown_message_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return [
            {
                "id": "agent-1",
                "type": "agent",
                "content": "部分完成",
                "customField": {"source": "persisted"},
                "extraFlag": True,
                "faultScenarioResult": {
                    "summary": "部分完成",
                },
            }
        ]

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)

    response = client.get("/api/portal/fault-disposal/history/fault-scenario-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["customField"] == {"source": "persisted"}
    assert payload["messages"][0]["extraFlag"] is True
    assert payload["messages"][0]["faultScenarioResult"]["steps"] == []


def test_manual_workorder_dispatch_route_persists_record_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"chat-1": []}
    workorder_store: dict[str, dict[str, dict]] = {"chat-1": {}}
    registry_updates: list[dict[str, object]] = []

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    async def fake_load_workorders(_request, *, session_id: str, user_id: str = "default") -> dict[str, dict]:
        return dict(workorder_store.get(session_id, {}))

    async def fake_save_workorders(
        _request,
        *,
        session_id: str,
        records: dict[str, dict],
        user_id: str = "default",
    ) -> None:
        workorder_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)
    monkeypatch.setattr(portal_backend, "_load_portal_manual_workorders", fake_load_workorders)
    monkeypatch.setattr(portal_backend, "_save_portal_manual_workorders", fake_save_workorders)
    monkeypatch.setattr(
        portal_backend,
        "_update_portal_real_alarm_registry_safe",
        lambda **kwargs: registry_updates.append(dict(kwargs)),
    )

    response = client.post(
        "/api/portal/fault-disposal/manual-workorders/dispatch",
        json={
            "chatId": "chat-1",
            "resId": "3094",
            "metricType": "mysql",
            "alarm": {
                "title": "数据库锁异常",
                "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
                "deviceName": "db_mysql_001",
                "manageIp": "10.43.150.186",
            },
            "analysis": {
                "summary": "AI 无法直接止血，转人工处理",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending_manual"
    assert payload["dispatchRequest"]["chatId"] == "chat-1"
    assert payload["dispatchRequest"]["resId"] == "3094"
    assert payload["dispatchRequest"]["context"]["callback_url"].endswith(
        "/api/portal/fault-disposal/manual-workorders/notify-closed"
    )
    assert workorder_store["chat-1"]["3094"]["status"] == "pending_manual"
    assert history_store["chat-1"][-1]["manualWorkorder"]["resId"] == "3094"
    assert registry_updates[-1]["status"] == "manual_pending"
    assert registry_updates[-1]["chat_id"] == "chat-1"
    assert registry_updates[-1]["res_id"] == "3094"


def test_manual_workorder_close_notification_updates_history_and_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"chat-1": []}
    workorder_store: dict[str, dict[str, dict]] = {
        "chat-1": {
            "3094": {
                "chatId": "chat-1",
                "resId": "3094",
                "metricType": "mysql",
                "status": "pending_manual",
                "workorder": {"title": "数据库锁异常"},
            }
        }
    }
    registry_updates: list[dict[str, object]] = []

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    async def fake_load_workorders(_request, *, session_id: str, user_id: str = "default") -> dict[str, dict]:
        return dict(workorder_store.get(session_id, {}))

    async def fake_save_workorders(
        _request,
        *,
        session_id: str,
        records: dict[str, dict],
        user_id: str = "default",
    ) -> None:
        workorder_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)
    monkeypatch.setattr(portal_backend, "_load_portal_manual_workorders", fake_load_workorders)
    monkeypatch.setattr(portal_backend, "_save_portal_manual_workorders", fake_save_workorders)
    monkeypatch.setattr(
        portal_backend,
        "_update_portal_real_alarm_registry_safe",
        lambda **kwargs: registry_updates.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        portal_backend,
        "_run_alarm_metric_verification",
        lambda *, metric_type, res_id, max_metrics=5: {
            "definitions": {"source": "live"},
            "selectedMetrics": [
                {"code": "mysql_global_status_innodb_row_lock_time", "name": "InnoDB 总锁等待时长"}
            ],
            "metricDataResults": [
                {
                    "metricCode": "mysql_global_status_innodb_row_lock_time",
                    "latestValue": "0",
                    "avgValue": "0",
                    "source": "live",
                }
            ],
        },
    )

    response = client.post(
        "/api/portal/fault-disposal/manual-workorders/notify-closed",
        json={
            "chatId": "chat-1",
            "resId": "3094",
            "workorder": {
                "workorderNo": "WO-001",
                "status": "resolved",
                "handler": "alice",
            },
            "processing": {
                "summary": "已释放阻塞事务",
                "details": "人工终止长事务后恢复写入",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "recovered"
    assert payload["manualWorkorder"]["status"] == "manual_recovered"
    assert payload["verification"]["summary"] == "最新关键指标未见锁等待/慢 SQL 类异常，可初步判定已恢复"
    assert history_store["chat-1"][-1]["recoveryVerification"]["status"] == "recovered"
    assert registry_updates[-1]["status"] == "manual_recovered"
    assert registry_updates[-1]["verification_status"] == "recovered"


def test_manual_workorder_close_notification_returns_404_when_record_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    async def fake_load_workorders(_request, *, session_id: str, user_id: str = "default") -> dict[str, dict]:
        return {}

    monkeypatch.setattr(portal_backend, "_load_portal_manual_workorders", fake_load_workorders)

    response = client.post(
        "/api/portal/fault-disposal/manual-workorders/notify-closed",
        json={
            "chatId": "missing-chat",
            "resId": "3094",
            "processing": {"summary": "done"},
        },
    )

    assert response.status_code == 404
    assert "manual workorder not found" in response.json()["detail"]
