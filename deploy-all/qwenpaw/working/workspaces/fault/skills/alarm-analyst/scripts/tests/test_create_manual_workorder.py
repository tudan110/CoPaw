import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests


SCRIPT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SCRIPT_DIR / "create_manual_workorder.py"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WORKORDER_MODULE = _load_module("alarm_manual_workorder_test", SCRIPT_PATH)


def test_build_workorder_payload_marks_ai_created_and_keeps_suggestions():
    args = SimpleNamespace(
        chat_id="chat-1",
        res_id="3094",
        metric_type="mysql",
        alarm_id="alarm-001",
        alarm_title="数据库锁异常",
        visible_content="数据库锁异常（db_mysql_001 10.43.150.186）",
        device_name="db_mysql_001",
        manage_ip="10.43.150.186",
        asset_id="db_mysql_001",
        level="critical",
        status="active",
        event_time="2026-04-20 15:00:00",
        analysis_summary="AI 已完成根因分析，自动创建人工处置工单",
        root_cause="疑似 MySQL 锁等待 / 长事务 / 死锁",
        suggestion=["排查长事务", "检查阻塞链"],
        suggestions_json='["检查阻塞链", "确认是否存在热点更新"]',
        ticket_title="",
        ticket_priority="P1",
        ticket_category="database-lock",
        ticket_source="portal-fault-disposal-ai",
        ticket_external_system="manual-workorder",
    )

    payload = WORKORDER_MODULE.build_workorder_payload(args)

    assert payload["chatId"] == "chat-1"
    assert payload["alarm"]["alarmId"] == "alarm-001"
    assert payload["alarm"]["title"] == "数据库锁异常（AI创建）"
    assert payload["ticket"]["source"] == "portal-fault-disposal-ai"
    assert payload["ticket"]["title"].startswith("AI创建")
    assert payload["analysis"]["suggestions"] == [
        "排查长事务",
        "检查阻塞链",
        "确认是否存在热点更新",
    ]


def test_build_workorder_payload_normalizes_prefixed_ai_alarm_title_to_suffix():
    args = SimpleNamespace(
        chat_id="chat-1",
        res_id="3094",
        metric_type="mysql",
        alarm_id="alarm-001",
        alarm_title="AI创建 · 数据库锁异常",
        visible_content="数据库锁异常（db_mysql_001 10.43.150.186）",
        device_name="db_mysql_001",
        manage_ip="10.43.150.186",
        asset_id="db_mysql_001",
        level="critical",
        status="active",
        event_time="2026-04-20 15:00:00",
        analysis_summary="AI 已完成根因分析，自动创建人工处置工单",
        root_cause="疑似 MySQL 锁等待 / 长事务 / 死锁",
        suggestion=["排查长事务"],
        suggestions_json="",
        ticket_title="",
        ticket_priority="P1",
        ticket_category="database-lock",
        ticket_source="portal-fault-disposal-ai",
        ticket_external_system="manual-workorder",
    )

    payload = WORKORDER_MODULE.build_workorder_payload(args)

    assert payload["alarm"]["alarmId"] == "alarm-001"
    assert payload["alarm"]["title"] == "数据库锁异常（AI创建）"


def test_build_workorder_payload_keeps_single_ai_alarm_title_suffix():
    args = SimpleNamespace(
        chat_id="chat-1",
        res_id="3094",
        metric_type="mysql",
        alarm_id="alarm-001",
        alarm_title="数据库锁异常（AI创建）",
        visible_content="数据库锁异常（db_mysql_001 10.43.150.186）",
        device_name="db_mysql_001",
        manage_ip="10.43.150.186",
        asset_id="db_mysql_001",
        level="critical",
        status="active",
        event_time="2026-04-20 15:00:00",
        analysis_summary="AI 已完成根因分析，自动创建人工处置工单",
        root_cause="疑似 MySQL 锁等待 / 长事务 / 死锁",
        suggestion=["排查长事务"],
        suggestions_json="",
        ticket_title="",
        ticket_priority="P1",
        ticket_category="database-lock",
        ticket_source="portal-fault-disposal-ai",
        ticket_external_system="manual-workorder",
    )

    payload = WORKORDER_MODULE.build_workorder_payload(args)

    assert payload["alarm"]["title"] == "数据库锁异常（AI创建）"


def test_build_workorder_payload_requires_suggestions():
    args = SimpleNamespace(
        chat_id="chat-1",
        res_id="3094",
        metric_type="mysql",
        alarm_id="",
        alarm_title="数据库锁异常",
        visible_content="",
        device_name="",
        manage_ip="",
        asset_id="",
        level="",
        status="active",
        event_time="",
        analysis_summary="",
        root_cause="",
        suggestion=[],
        suggestions_json="",
        ticket_title="",
        ticket_priority="P1",
        ticket_category="database-lock",
        ticket_source="portal-fault-disposal-ai",
        ticket_external_system="manual-workorder",
    )

    with pytest.raises(ValueError, match="至少提供一条处置建议"):
        WORKORDER_MODULE.build_workorder_payload(args)


def test_build_workorder_payload_requires_alarm_id():
    args = SimpleNamespace(
        chat_id="chat-1",
        res_id="3094",
        metric_type="mysql",
        alarm_id="",
        alarm_title="数据库锁异常",
        visible_content="",
        device_name="",
        manage_ip="",
        asset_id="",
        level="",
        status="active",
        event_time="",
        analysis_summary="",
        root_cause="",
        suggestion=["排查长事务"],
        suggestions_json="",
        ticket_title="",
        ticket_priority="P1",
        ticket_category="database-lock",
        ticket_source="portal-fault-disposal-ai",
        ticket_external_system="manual-workorder",
    )

    with pytest.raises(ValueError, match="必须提供告警流水号"):
        WORKORDER_MODULE.build_workorder_payload(args)


@patch.dict(
    "os.environ",
    {
        "INOE_API_BASE_URL": "http://example.com",
        "INOE_API_TOKEN": "token-123",
        "ORDER_CREATE_NOTIFY_PUSH_URL": "",
        "ORDER_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL": "",
        "ORDER_CREATE_NOTIFY_DINGTALK_SECRET": "",
        "ORDER_CREATE_NOTIFY_FEISHU_WEBHOOK_URL": "",
        "ORDER_CREATE_NOTIFY_FEISHU_SECRET": "",
        "ORDER_CREATE_NOTIFY_MENTION_ALL": "false",
    },
    clear=False,
)
def test_create_manual_workorder_posts_expected_request():
    payload = {
        "chatId": "chat-1",
        "resId": "3094",
        "metricType": "mysql",
        "alarm": {"alarmId": "alarm-001", "title": "AI创建 · 数据库锁异常"},
        "analysis": {"summary": "AI 已完成根因分析，自动创建人工处置工单", "suggestions": ["排查长事务"]},
        "ticket": {"title": "AI创建 · 数据库锁异常人工处置", "source": "portal-fault-disposal-ai"},
    }
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 200,
        "msg": None,
        "data": {"procInsId": "proc-1", "taskId": "task-1"},
    }

    with patch.object(WORKORDER_MODULE.requests, "post", return_value=response) as mock_post:
        result = WORKORDER_MODULE.create_manual_workorder(payload, timeout_seconds=12)

    assert result["data"]["procInsId"] == "proc-1"
    kwargs = mock_post.call_args.kwargs
    assert kwargs["json"] == payload
    assert kwargs["timeout"] == 12
    assert kwargs["headers"]["Authorization"] == "token-123"
    assert kwargs["headers"]["Content-Type"] == "application/json;charset=utf-8"
    assert kwargs["headers"]["SerialNo"]
    assert result["notification"]["status"] == "skipped"
    assert result["notification"]["reason"] == "webhook_not_configured"


@patch.dict(
    "os.environ",
    {
        "ORDER_CREATE_NOTIFY_PUSH_URL": "http://notify.example.com/push",
        "ORDER_CREATE_NOTIFY_MENTION_ALL": "true",
    },
    clear=False,
)
def test_app_notification_payload_mentions_all_when_enabled():
    context = WORKORDER_MODULE._build_notification_context(
        {
            "resId": "3094",
            "alarm": {
                "title": "数据库锁异常（AI创建）",
                "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
                "deviceName": "db_mysql_001",
                "manageIp": "10.43.150.186",
                "level": "critical",
            },
            "analysis": {
                "summary": "AI 已完成根因分析，自动创建人工处置工单",
                "rootCause": "疑似长事务",
                "suggestions": ["排查长事务", "检查阻塞链"],
            },
            "ticket": {"title": "AI创建 · 数据库锁异常人工处置"},
        },
        {"data": {"taskId": "task-1", "procInsId": "proc-1"}},
    )

    payload = WORKORDER_MODULE._build_app_notify_payload(context)

    assert payload["type"] == "text"
    assert payload["title"] == "AI创建处置工单"
    assert "AI创建处置工单" in payload["content"]
    assert "根因方向：疑似长事务" in payload["content"]
    assert "处置建议：排查长事务；检查阻塞链" in payload["content"]
    assert "**" not in payload["content"]
    assert ">" not in payload["content"]


@patch.dict(
    "os.environ",
    {
        "ORDER_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=test",
        "ORDER_CREATE_NOTIFY_DINGTALK_KEYWORD": "工单",
        "ORDER_CREATE_NOTIFY_MENTION_ALL": "true",
    },
    clear=False,
)
def test_dingtalk_notification_payload_mentions_all_when_enabled():
    context = WORKORDER_MODULE._build_notification_context(
        {
            "resId": "3094",
            "alarm": {
                "title": "数据库锁异常（AI创建）",
                "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
                "deviceName": "db_mysql_001",
                "manageIp": "10.43.150.186",
                "level": "critical",
            },
            "analysis": {
                "summary": "AI 已完成根因分析，自动创建人工处置工单",
                "rootCause": "疑似长事务",
                "suggestions": ["排查长事务"],
            },
            "ticket": {"title": "AI创建 · 数据库锁异常人工处置"},
        },
        {"data": {"taskId": "task-1", "procInsId": "proc-1"}},
    )

    payload = WORKORDER_MODULE._build_dingtalk_notify_payload(context)

    assert payload["msgtype"] == "markdown"
    assert payload["at"]["isAtAll"] is True
    assert payload["markdown"]["text"].startswith("工单\n")
    assert "- **taskId**：task-1" in payload["markdown"]["text"]


@patch.dict(
    "os.environ",
    {
        "ORDER_CREATE_NOTIFY_DINGTALK_SECRET": "SEC-secret",
    },
    clear=False,
)
def test_dingtalk_signed_webhook_url_appends_timestamp_and_sign():
    with patch.object(WORKORDER_MODULE.time, "time", return_value=1700000000.0):
        url = WORKORDER_MODULE._build_dingtalk_signed_webhook_url(
            "https://oapi.dingtalk.com/robot/send?access_token=test"
        )

    query = parse_qs(urlparse(url).query)
    assert query["access_token"][0] == "test"
    assert query["timestamp"][0] == "1700000000000"
    assert query["sign"][0]


@patch.dict(
    "os.environ",
    {
        "ORDER_CREATE_NOTIFY_FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        "ORDER_CREATE_NOTIFY_FEISHU_SECRET": "feishu-secret",
        "ORDER_CREATE_NOTIFY_MENTION_ALL": "true",
    },
    clear=False,
)
def test_feishu_notification_payload_appends_timestamp_and_sign():
    context = WORKORDER_MODULE._build_notification_context(
        {
            "resId": "3094",
            "alarm": {
                "title": "数据库锁异常（AI创建）",
                "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
                "deviceName": "db_mysql_001",
                "manageIp": "10.43.150.186",
                "level": "critical",
            },
            "analysis": {
                "summary": "AI 已完成根因分析，自动创建人工处置工单",
                "rootCause": "疑似长事务",
                "suggestions": ["排查长事务"],
            },
            "ticket": {"title": "AI创建 · 数据库锁异常人工处置"},
        },
        {"data": {"taskId": "task-1", "procInsId": "proc-1"}},
    )

    with patch.object(WORKORDER_MODULE.time, "time", return_value=1700000000.0):
        payload = WORKORDER_MODULE._build_feishu_notify_payload(context)

    assert payload["msg_type"] == "interactive"
    assert payload["timestamp"] == "1700000000"
    assert payload["sign"]
    assert payload["card"]["header"]["title"]["content"] == "AI创建处置工单 — db_mysql_001"
    assert payload["card"]["elements"][0]["text"]["content"] == "<at id=all></at>"
    assert payload["card"]["elements"][1]["fields"][0]["text"]["content"] == "**告警标题**\nAI创建 · 数据库锁异常人工处置"


@patch.dict(
    "os.environ",
    {
        "INOE_API_BASE_URL": "http://example.com",
        "INOE_API_TOKEN": "token-123",
        "ORDER_CREATE_NOTIFY_PUSH_URL": "http://notify.example.com/push",
        "ORDER_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL": "",
        "ORDER_CREATE_NOTIFY_DINGTALK_SECRET": "",
        "ORDER_CREATE_NOTIFY_FEISHU_WEBHOOK_URL": "",
        "ORDER_CREATE_NOTIFY_FEISHU_SECRET": "",
    },
    clear=False,
)
def test_create_manual_workorder_notification_failure_does_not_break_create():
    payload = {
        "chatId": "chat-1",
        "resId": "3094",
        "metricType": "mysql",
        "alarm": {"alarmId": "alarm-001", "title": "AI创建 · 数据库锁异常"},
        "analysis": {
            "summary": "AI 已完成根因分析，自动创建人工处置工单",
            "rootCause": "疑似长事务",
            "suggestions": ["排查长事务"],
        },
        "ticket": {"title": "AI创建 · 数据库锁异常人工处置", "source": "portal-fault-disposal-ai"},
    }
    workorder_response = Mock()
    workorder_response.raise_for_status.return_value = None
    workorder_response.json.return_value = {
        "code": 200,
        "msg": None,
        "data": {"procInsId": "proc-1", "taskId": "task-1"},
    }

    with patch.object(
        WORKORDER_MODULE.requests,
        "post",
        side_effect=[workorder_response, requests.RequestException("notify down")],
    ):
        result = WORKORDER_MODULE.create_manual_workorder(payload, timeout_seconds=12)

    assert result["data"]["taskId"] == "task-1"
    assert result["notification"]["status"] == "failed"
    assert "notify down" in result["notification"]["reason"]


@patch.dict(
    "os.environ",
    {
        "INOE_API_BASE_URL": "http://example.com",
        "INOE_API_TOKEN": "token-123",
        "ORDER_CREATE_NOTIFY_PUSH_URL": "http://notify.example.com/push",
        "ORDER_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=test",
        "ORDER_CREATE_NOTIFY_FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        "ORDER_CREATE_NOTIFY_MENTION_ALL": "true",
    },
    clear=False,
)
def test_create_manual_workorder_supports_multi_channel_success():
    payload = {
        "chatId": "chat-1",
        "resId": "3094",
        "metricType": "mysql",
        "alarm": {
            "alarmId": "alarm-001",
            "title": "AI创建 · 数据库锁异常",
            "deviceName": "db_mysql_001",
            "manageIp": "10.43.150.186",
            "level": "critical",
        },
        "analysis": {
            "summary": "AI 已完成根因分析，自动创建人工处置工单",
            "rootCause": "疑似长事务",
            "suggestions": ["排查长事务"],
        },
        "ticket": {"title": "AI创建 · 数据库锁异常人工处置", "source": "portal-fault-disposal-ai"},
    }

    class MockResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    with patch.object(
        WORKORDER_MODULE.requests,
        "post",
        side_effect=[
            MockResponse({"code": 200, "msg": None, "data": {"procInsId": "proc-1", "taskId": "task-1"}}),
            MockResponse({"ok": True, "code": 200}),
            MockResponse({"errcode": 0, "errmsg": "ok"}),
            MockResponse({"StatusCode": 0, "StatusMessage": "success", "code": 0}),
        ],
    ):
        result = WORKORDER_MODULE.create_manual_workorder(payload)

    assert result["notification"]["status"] == "sent"
    assert len(result["notification"]["channels"]) == 3


def test_format_markdown_result_contains_ai_marker():
    markdown = WORKORDER_MODULE.format_markdown_result(
        {
            "resId": "3094",
            "alarm": {"alarmId": "alarm-001", "title": "AI创建 · 数据库锁异常"},
            "analysis": {
                "summary": "AI 已完成根因分析，自动创建人工处置工单",
                "rootCause": "疑似 MySQL 锁等待 / 长事务 / 死锁",
                "suggestions": ["排查长事务"],
            },
            "ticket": {"title": "AI创建 · 数据库锁异常人工处置", "source": "portal-fault-disposal-ai"},
        },
        {
            "data": {"procInsId": "proc-1", "taskId": "task-1"},
            "notification": {
                "status": "sent",
                "channels": [
                    {"channel": "app", "status": "sent"},
                    {"channel": "dingtalk", "status": "sent"},
                    {"channel": "feishu", "status": "sent"},
                ],
            },
        },
    )

    assert "AI 创建处置工单结果" in markdown
    assert "alarm-001" in markdown
    assert "portal-fault-disposal-ai" in markdown
    assert "排查长事务" in markdown
    assert "通知状态：**✅ 已成功推送**" in markdown
