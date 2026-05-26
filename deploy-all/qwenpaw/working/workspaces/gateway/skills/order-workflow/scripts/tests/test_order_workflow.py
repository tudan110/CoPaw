#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlparse
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[2]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from runtime.client import OrderWorkflowClient, OrderWorkflowConfig
from runtime.formatters import (
    format_create_markdown,
    format_detail_markdown,
    format_list_markdown,
    format_stats_markdown,
)


class OrderWorkflowTests(unittest.TestCase):
    def test_order_workflow_config_prefers_workspace_notification_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_file = Path(tmp_dir) / "extensions" / "notifications" / "settings.json"
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            settings_file.write_text(
                json.dumps(
                    {
                        "notification_channels": {
                            "order_workflow": {
                                "push_url": "http://settings.example.com/push",
                                "dingtalk_webhook_url": "",
                                "dingtalk_secret": "",
                                "feishu_webhook_url": "",
                                "feishu_secret": "",
                                "timeout_seconds": 17,
                                "mention_all": False,
                            }
                        }
                    }
                ),
                "utf-8",
            )

            with mock.patch.dict(
                "os.environ",
                {
                    "QWENPAW_WORKING_DIR": tmp_dir,
                    "ORDER_CREATE_NOTIFY_PUSH_URL": "http://env.example.com/push",
                    "ORDER_CREATE_NOTIFY_TIMEOUT_SECONDS": "8",
                    "ORDER_CREATE_NOTIFY_MENTION_ALL": "true",
                },
                clear=False,
            ):
                config = OrderWorkflowConfig.from_env()

        self.assertEqual(config.create_notify_push_url, "http://settings.example.com/push")
        self.assertEqual(config.create_notify_timeout_seconds, 17)
        self.assertFalse(config.create_notify_mention_all)

    def test_build_list_params_uses_documented_query_keys(self) -> None:
        params = OrderWorkflowClient._build_list_params(
            page_num=2,
            page_size=20,
            begin_time="2026-04-23 00:00:00",
            end_time="2026-04-23 23:59:59",
        )
        self.assertEqual(
            params,
            {
                "pageNum": 2,
                "pageSize": 20,
                "params.beginTime": "2026-04-23 00:00:00",
                "params.endTime": "2026-04-23 23:59:59",
            },
        )

    def test_stats_markdown_renders_counts(self) -> None:
        markdown = format_stats_markdown(
            {
                "code": 200,
                "data": {
                    "inProgressCount": 3,
                    "finishedCount": 4,
                    "todoCount": 5,
                },
            }
        )
        self.assertIn("待处理：**3**", markdown)
        self.assertIn("已完成：**4**", markdown)
        self.assertIn("进行中：**5**", markdown)

    def test_list_markdown_renders_core_columns(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 1,
                "rows": [
                    {
                        "taskId": "task-1",
                        "procInsId": "proc-1",
                        "procDefName": "故障处置工单",
                        "procDefVersion": 7,
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:10:07",
                        "procVars": {
                            "title": "数据库锁异常",
                            "processStatus": "running",
                        },
                    }
                ],
            },
            title="待办工单",
        )
        self.assertIn("预览第 1 页 1 条", markdown)
        self.assertIn("| 序号 | 任务编号 | 流程实例ID | 流程名称 | 任务节点 | 流程版本 | 流程发起人 | 接收时间 |", markdown)
        self.assertIn("故障处置工单", markdown)
        self.assertIn("v7", markdown)
        self.assertIn("| 1 | task-1 | proc-1 | 故障处置工单 | 人工处置 | v7 | xiaok | 2026-04-23 10:10:07 |", markdown)
        self.assertIn("查看第 3 条", markdown)
        self.assertNotIn("### 完整编号", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_finished_list_markdown_renders_page_columns(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 1,
                "rows": [
                    {
                        "taskId": "task-2",
                        "procInsId": "proc-2",
                        "procDefName": "故障处置工单",
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:25:37",
                        "finishTime": "2026-04-23 11:56:31",
                        "duration": "1小时30分54秒",
                    }
                ],
            },
            title="已办工单",
        )
        self.assertIn("| 序号 | 任务编号 | 流程实例ID | 流程名称 | 任务节点 | 流程发起人 | 接收时间 | 审批时间 | 耗时 |", markdown)
        self.assertIn("2026-04-23 11:56:31", markdown)
        self.assertIn("1小时30分54秒", markdown)
        self.assertIn("| 1 | task-2 | proc-2 | 故障处置工单 | 人工处置 | xiaok | 2026-04-23 10:25:37 | 2026-04-23 11:56:31 | 1小时30分54秒 |", markdown)
        self.assertNotIn("### 完整编号", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_list_markdown_never_emits_portal_visualization(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 1,
                "rows": [
                    {
                        "taskId": "task-3",
                        "procInsId": "proc-3",
                        "procDefName": "故障处置工单",
                        "procDefVersion": 7,
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:10:07",
                    }
                ],
            },
            title="待办工单",
            lightweight=False,
        )
        self.assertIn("| 1 | task-3 | proc-3 | 故障处置工单 | 人工处置 | v7 | xiaok | 2026-04-23 10:10:07 |", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_list_markdown_uses_global_index_for_later_pages(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 31,
                "pageNum": 2,
                "pageSize": 10,
                "rows": [
                    {
                        "taskId": "task-11",
                        "procInsId": "proc-11",
                        "procDefName": "故障处置工单",
                        "procDefVersion": 7,
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:10:07",
                    }
                ],
            },
            title="待办工单",
        )
        self.assertIn("| 11 | task-11 | proc-11 | 故障处置工单 | 人工处置 | v7 | xiaok | 2026-04-23 10:10:07 |", markdown)

    def test_detail_markdown_renders_light_preview(self) -> None:
        long_alarm_text = (
            "设备id:18，判断关系为：or，采集结果[ping_percent_packet_loss]=100.0，"
            "阈值范围[70, +∞)，满足条件=true"
        )
        markdown = format_detail_markdown(
            {
                "data": {
                    "bpmnXml": """
<bpmn2:definitions>
  <bpmn2:process id="Process_1" name="故障处置工单">
    <bpmn2:startEvent id="StartEvent_1" name="开始"></bpmn2:startEvent>
    <bpmn2:userTask id="Activity_1" name="人工办理"></bpmn2:userTask>
    <bpmn2:endEvent id="Event_1" name="结束"></bpmn2:endEvent>
    <bpmn2:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Activity_1" />
    <bpmn2:sequenceFlow id="Flow_2" sourceRef="Activity_1" targetRef="Event_1" />
  </bpmn2:process>
</bpmn2:definitions>
                    """,
                    "flowViewer": {
                        "finishedTaskSet": ["StartEvent_1"],
                        "unfinishedTaskSet": ["Activity_1"],
                    },
                    "processFormList": [
                        {
                            "title": "告警列表",
                            "formData": {
                                "alarmTitle": "云包异常",
                                "additionalText": long_alarm_text,
                                "deviceName": "DKCZZ-HUAWEI-DCLEAF-1",
                                "manageIp": "172.27.34.15",
                            },
                            "formModel": {
                                "widgetList": [
                                    {
                                        "type": "input",
                                        "formItemFlag": True,
                                        "options": {"name": "alarmTitle", "label": "告警标题"},
                                    },
                                    {
                                        "type": "textarea",
                                        "formItemFlag": True,
                                        "options": {"name": "additionalText", "label": "告警原始报文"},
                                    },
                                ]
                            },
                        }
                    ],
                    "historyProcNodeList": [
                        {
                            "activityId": "StartEvent_1",
                            "activityName": "开始",
                            "activityType": "startEvent",
                            "assigneeName": "xiaok",
                            "createTime": "2026-04-16 19:20:04",
                            "endTime": "2026-04-16 19:20:04",
                            "duration": "0秒",
                        },
                        {
                            "activityId": "Activity_1",
                            "activityName": "人工办理",
                            "activityType": "userTask",
                            "assigneeName": "xiaok",
                            "createTime": "2026-04-16 19:20:04",
                            "commentList": [{"fullMessage": "已接单"}],
                        },
                    ],
                }
            }
        )
        self.assertIn("### 表单信息预览", markdown)
        self.assertIn("| 字段 | 内容 |", markdown)
        self.assertIn(long_alarm_text, markdown)
        self.assertNotIn("满足条件=tru...", markdown)
        self.assertIn("### 流转记录", markdown)
        self.assertIn("1. `开始`", markdown)
        self.assertIn("2. `人工办理`", markdown)
        self.assertIn("### 流程跟踪", markdown)
        self.assertIn("开始（已完成） -> 人工办理（处理中） -> 结束（未到达）", markdown)
        self.assertIn("查看完整表单信息", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_detail_markdown_full_still_uses_markdown_only(self) -> None:
        markdown = format_detail_markdown(
            {
                "data": {
                    "processFormList": [
                        {
                            "title": "告警列表",
                            "formData": {"alarmTitle": "云包异常", "manageIp": "172.27.34.15"},
                            "formModel": {
                                "widgetList": [
                                    {
                                        "type": "input",
                                        "formItemFlag": True,
                                        "options": {"name": "alarmTitle", "label": "告警标题"},
                                    },
                                    {
                                        "type": "input",
                                        "formItemFlag": True,
                                        "options": {"name": "manageIp", "label": "设备IP"},
                                    },
                                ]
                            },
                        }
                    ],
                    "historyProcNodeList": [
                        {
                            "activityId": "StartEvent_1",
                            "activityName": "开始",
                            "activityType": "startEvent",
                            "assigneeName": "xiaok",
                            "createTime": "2026-04-16 19:20:04",
                            "endTime": "2026-04-16 19:20:04",
                            "duration": "0秒",
                        }
                    ],
                    "bpmnXml": "",
                    "flowViewer": {},
                }
            },
            lightweight=False,
        )
        self.assertIn("### 表单信息", markdown)
        self.assertIn("### 流转记录", markdown)
        self.assertIn("### 流程跟踪", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_fetch_all_workorders_aggregates_pages(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
            )
        )
        with mock.patch.object(
            client,
            "_request",
            side_effect=[
                {
                    "total": 3,
                    "rows": [
                        {"taskId": "task-1"},
                        {"taskId": "task-2"},
                    ],
                },
                {
                    "total": 3,
                    "rows": [
                        {"taskId": "task-3"},
                    ],
                },
            ],
        ) as request_mock:
            payload = client.list_todo_workorders(page_size=2, fetch_all=True)
        self.assertEqual([row["taskId"] for row in payload["rows"]], ["task-1", "task-2", "task-3"])
        self.assertTrue(payload["fetchedAll"])
        self.assertEqual(request_mock.call_count, 2)

    def test_detail_resolves_proc_ins_id_when_task_id_was_reused(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
            )
        )
        with mock.patch.object(
            client,
            "_request",
            side_effect=[
                {
                    "total": 1,
                    "rows": [
                        {
                            "taskId": "task-1",
                            "procInsId": "proc-real",
                        }
                    ],
                },
                {"data": {"processName": "故障处置工单"}},
            ],
        ) as request_mock:
            payload = client.get_workorder_detail(
                proc_ins_id="task-1",
                task_id="task-1",
            )

        self.assertEqual(payload["data"]["processName"], "故障处置工单")
        detail_call = request_mock.call_args_list[-1]
        self.assertEqual(detail_call.kwargs["params"]["procInsId"], "proc-real")
        self.assertEqual(detail_call.kwargs["params"]["taskId"], "task-1")

    def test_client_uses_default_route_base_url(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://192.168.130.51:30081",
                authorization="token",
            )
        )
        self.assertEqual(client.config.base_url, "http://192.168.130.51:30081")

    def test_config_falls_back_to_inoe_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "INOE_API_BASE_URL": "http://192.168.130.51:30080",
                "INOE_API_TOKEN": "inoe-token",
            },
            clear=True,
        ):
            config = OrderWorkflowConfig.from_env()
        self.assertEqual(config.base_url, "http://192.168.130.51:30080")
        self.assertEqual(config.authorization, "inoe-token")

    def test_normalize_create_payload_accepts_lightweight_form_fields(self) -> None:
        payload = OrderWorkflowClient._normalize_create_payload(
            {
                "deviceName": "db_mysql_001",
                "manageIp": "10.43.150.186",
                "assetId": "3094",
                "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
            }
        )
        self.assertEqual(payload["resId"], "3094")
        self.assertEqual(payload["alarm"]["deviceName"], "db_mysql_001")
        self.assertEqual(payload["alarm"]["manageIp"], "10.43.150.186")
        self.assertEqual(payload["alarm"]["assetId"], "3094")
        self.assertTrue(payload["chatId"])
        self.assertTrue(payload["alarm"]["alarmId"].startswith("alarm-"))
        self.assertIn("数据库锁异常", payload["alarm"]["title"])
        self.assertIn("人工排查", payload["analysis"]["summary"])
        self.assertGreaterEqual(len(payload["analysis"]["suggestions"]), 1)

    def test_normalize_create_payload_preserves_nested_fields(self) -> None:
        payload = OrderWorkflowClient._normalize_create_payload(
            {
                "chatId": "chat-1",
                "resId": "res-1",
                "metricType": "mysql",
                "alarm": {
                    "alarmId": "alarm-1",
                    "title": "数据库锁异常",
                    "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "assetId": "3094",
                    "level": "critical",
                    "status": "active",
                    "eventTime": "2026-04-23 20:00:00",
                },
                "analysis": {
                    "summary": "AI 无法直接止血，转人工处理",
                    "rootCause": "疑似长事务",
                    "suggestions": ["排查长事务", "检查阻塞链"],
                },
                "ticket": {
                    "title": "数据库锁异常人工处置",
                    "priority": "P1",
                    "category": "database-lock",
                    "source": "portal-fault-disposal",
                    "externalSystem": "manual-workorder",
                },
            }
        )
        self.assertEqual(payload["chatId"], "chat-1")
        self.assertEqual(payload["resId"], "res-1")
        self.assertEqual(payload["metricType"], "mysql")
        self.assertEqual(payload["alarm"]["alarmId"], "alarm-1")
        self.assertEqual(payload["alarm"]["eventTime"], "2026-04-23 20:00:00")
        self.assertEqual(payload["analysis"]["rootCause"], "疑似长事务")
        self.assertEqual(payload["analysis"]["suggestions"], ["排查长事务", "检查阻塞链"])
        self.assertEqual(payload["ticket"]["priority"], "P1")

    def test_create_notification_payload_mentions_all_when_enabled(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
                create_notify_push_url="http://notify.example.com/push",
                create_notify_mention_all=True,
            )
        )
        context = client._build_create_notify_context(
            response_payload={"data": {"taskId": "task-1", "procInsId": "proc-1"}},
            request_payload=OrderWorkflowClient._normalize_create_payload(
                {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
                }
            ),
        )
        payload = client._build_create_notify_payload(context)
        self.assertEqual(payload["type"], "text")
        self.assertEqual(payload["title"], "工单创建通知")
        self.assertIn("摘要：", payload["content"])
        self.assertIn("设备：db_mysql_001 / 10.43.150.186", payload["content"])
        self.assertIn("taskId：task-1", payload["content"])
        self.assertIn("procInsId：proc-1", payload["content"])

    def test_dingtalk_notification_payload_mentions_all_when_enabled(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
                create_notify_dingtalk_webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
                create_notify_mention_all=True,
            )
        )
        context = client._build_create_notify_context(
            response_payload={"data": {"taskId": "task-1", "procInsId": "proc-1"}},
            request_payload=OrderWorkflowClient._normalize_create_payload(
                {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
                }
            ),
        )
        payload = client._build_dingtalk_create_notify_payload(context)
        self.assertEqual(payload["msgtype"], "text")
        self.assertTrue(payload["at"]["isAtAll"])
        self.assertTrue(payload["text"]["content"].startswith("【工单创建通知】"))
        self.assertIn("摘要：", payload["text"]["content"])
        self.assertIn("taskId：task-1", payload["text"]["content"])

    def test_dingtalk_signed_webhook_url_appends_timestamp_and_sign(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
                create_notify_dingtalk_webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
                create_notify_dingtalk_secret="SEC-secret",
            )
        )
        with mock.patch("runtime.client.time.time", return_value=1700000000.0):
            url = client._build_dingtalk_signed_webhook_url(
                "https://oapi.dingtalk.com/robot/send?access_token=test"
            )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["access_token"][0], "test")
        self.assertEqual(query["timestamp"][0], "1700000000000")
        self.assertTrue(query["sign"][0])

    def test_feishu_notification_payload_appends_timestamp_and_sign(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
                create_notify_feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
                create_notify_feishu_secret="feishu-secret",
                create_notify_mention_all=True,
            )
        )
        context = client._build_create_notify_context(
            response_payload={"data": {"taskId": "task-1", "procInsId": "proc-1"}},
            request_payload=OrderWorkflowClient._normalize_create_payload(
                {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
                }
            ),
        )
        with mock.patch("runtime.client.time.time", return_value=1700000000.0):
            payload = client._build_feishu_create_notify_payload(context)
        self.assertEqual(payload["msg_type"], "text")
        self.assertEqual(payload["timestamp"], "1700000000")
        self.assertTrue(payload["sign"])
        self.assertIn('<at user_id="all">所有人</at>', payload["content"]["text"])
        self.assertIn("摘要：", payload["content"]["text"])

    def test_create_notification_failure_does_not_break_create(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
                create_notify_push_url="http://notify.example.com/push",
            )
        )
        with mock.patch.object(
            client,
            "_request",
            return_value={"code": 200, "data": {"taskId": "task-1", "procInsId": "proc-1"}},
        ), mock.patch(
            "runtime.client.requests.post",
            side_effect=RuntimeError("notify down"),
        ):
            payload = client.create_disposal_workorder(
                {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
                }
            )
        self.assertEqual(payload["data"]["taskId"], "task-1")
        self.assertEqual(payload["notification"]["status"], "failed")
        self.assertIn("notify down", payload["notification"]["reason"])

    def test_create_notification_supports_multi_channel_success(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
                create_notify_push_url="http://notify.example.com/push",
                create_notify_dingtalk_webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
                create_notify_feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
                create_notify_mention_all=True,
            )
        )

        class MockResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        with mock.patch.object(
            client,
            "_request",
            return_value={"code": 200, "data": {"taskId": "task-1", "procInsId": "proc-1"}},
        ), mock.patch(
            "runtime.client.requests.post",
            side_effect=[
                MockResponse({"ok": True, "code": 200}),
                MockResponse({"errcode": 0, "errmsg": "ok"}),
                MockResponse({"StatusCode": 0, "StatusMessage": "success", "code": 0}),
            ],
        ):
            payload = client.create_disposal_workorder(
                {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
                }
            )
        self.assertEqual(payload["notification"]["status"], "sent")
        self.assertEqual(len(payload["notification"]["channels"]), 3)

    def test_create_markdown_renders_notification_status(self) -> None:
        markdown = format_create_markdown(
            {
                "data": {"procInsId": "proc-1", "taskId": "task-1"},
                "notification": {"status": "sent", "channels": [{"channel": "app", "status": "sent"}, {"channel": "dingtalk", "status": "sent"}, {"channel": "feishu", "status": "sent"}]},
            }
        )
        self.assertIn("通知推送：**应用、钉钉、飞书已发送**", markdown)


if __name__ == "__main__":
    unittest.main()
