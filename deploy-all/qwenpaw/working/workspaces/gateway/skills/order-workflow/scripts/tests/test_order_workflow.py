#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import json
from pathlib import Path
import sys
import tempfile
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


# Sample payloads mirror the inoe-ferry 工单接口文档 examples.
TODO_ROW = {
    "id": 123,
    "title": "数据库锁异常人工处置",
    "priority": 3,
    "process": 15,
    "classify": 1,
    "is_end": 0,
    "creator": 1,
    "create_time": "2026-06-18 10:13:21",
    "update_time": "2026-06-18 10:25:09",
    "current_state": "recv1",
    "process_name": "故障处置",
    "principals": "张三",
    "state_name": "处理节点",
}

PROCESS_STRUCTURE_DETAIL = {
    "code": 200,
    "data": {
        "process": {"id": 15, "name": "故障处置"},
        "nodes": [
            {"id": "start1", "clazz": "start", "label": "开始", "sort": 0},
            {"id": "recv1", "clazz": "receiveTask", "label": "处理节点", "sort": 1},
            {"id": "end1", "clazz": "end", "label": "结束", "sort": 2},
        ],
        "edges": [
            {"source": "start1", "target": "recv1", "sort": 0},
            {"source": "recv1", "target": "end1", "sort": 1},
        ],
        "circulationHistory": [
            {
                "id": 1,
                "work_order": 123,
                "circulation": "新建",
                "processor": "张三",
                "processor_id": 1,
                "status": 2,
            }
        ],
        "workOrder": {
            "id": 123,
            "title": "数据库锁异常人工处置",
            "priority": 3,
            "current_state": "recv1",
            "principals": "李四",
        },
        "tpls": [
            {
                "name": "故障处置表单",
                "form_structure": {
                    "list": [
                        {
                            "__vModel__": "deviceName",
                            "__config__": {"label": "设备名称"},
                        }
                    ],
                    "config": {},
                },
                "form_data": {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                },
            }
        ],
        "userAuthority": True,
    },
    "msg": "数据获取成功",
}


def _list_envelope(rows, *, total=None, page=1, per_page=10):
    return {
        "code": 200,
        "data": {
            "total_count": len(rows) if total is None else total,
            "total_page": 1,
            "page": page,
            "per_page": per_page,
            "data": rows,
        },
        "msg": "",
    }


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

    def test_build_list_params_uses_ferry_query_keys(self) -> None:
        params = OrderWorkflowClient._build_list_params(
            classify=OrderWorkflowClient.CLASSIFY_FINISHED,
            page=2,
            per_page=20,
            begin_time="2026-06-01 00:00:00",
            end_time="2026-06-30 23:59:59",
            title="数据库",
        )
        self.assertEqual(
            params,
            {
                "classify": 5,
                "page": 2,
                "per_page": 20,
                "title": "数据库",
                "startTime": "2026-06-01 00:00:00",
                "endTime": "2026-06-30 23:59:59",
            },
        )

    def test_require_ok_raises_on_business_failure(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            OrderWorkflowClient._require_ok(
                {"code": 500, "msg": "获取流程失败！", "data": None}
            )
        self.assertIn("获取流程失败", str(ctx.exception))

    def test_require_ok_passes_on_success(self) -> None:
        # Should not raise.
        OrderWorkflowClient._require_ok({"code": 200, "data": {}, "msg": ""})

    def test_require_ok_raises_on_missing_business_code(self) -> None:
        # A JSON body without a ferry business code (e.g. a misconfigured
        # gateway answering 200 {"msg": ""}) must fail loudly instead of
        # being normalized into an empty result list downstream.
        with self.assertRaises(RuntimeError) as ctx:
            OrderWorkflowClient._require_ok(
                {"msg": ""},
                "http://gateway.example:30080/ferry",
            )
        self.assertIn("未返回业务码", str(ctx.exception))
        self.assertIn("http://gateway.example:30080/ferry", str(ctx.exception))

    def test_normalize_list_payload_maps_paginator_result(self) -> None:
        normalized = OrderWorkflowClient._normalize_list_payload(
            _list_envelope([TODO_ROW], total=26, page=1, per_page=10)
        )
        self.assertEqual(normalized["total"], 26)
        self.assertEqual(normalized["pageNum"], 1)
        self.assertEqual(normalized["pageSize"], 10)
        self.assertEqual([row["id"] for row in normalized["rows"]], [123])

    def test_stats_markdown_renders_counts_with_ferry_semantics(self) -> None:
        markdown = format_stats_markdown(
            {
                "code": 200,
                "data": {
                    "todoCount": 5,
                    "inProgressCount": 12,
                    "finishedCount": 30,
                },
            }
        )
        self.assertIn("待处理：**5**", markdown)
        self.assertIn("进行中：**12**", markdown)
        self.assertIn("已完成：**30**", markdown)

    def test_todo_list_markdown_renders_ferry_columns(self) -> None:
        markdown = format_list_markdown(
            {"total": 1, "rows": [TODO_ROW]},
            title="待办工单",
        )
        self.assertIn("预览第 1 页 1 条", markdown)
        self.assertIn(
            "| 序号 | 工单号 | 流程号 | 标题 | 流程 | 当前节点 | 处理人 | 优先级 | 创建时间 |",
            markdown,
        )
        self.assertIn(
            "| 1 | 123 | 15 | 数据库锁异常人工处置 | 故障处置 | 处理节点 | 张三 | P1 | 2026-06-18 10:13:21 |",
            markdown,
        )
        self.assertNotIn("portal-visualization", markdown)

    def test_finished_list_markdown_renders_state_and_times(self) -> None:
        finished_row = dict(TODO_ROW, is_end=1)
        markdown = format_list_markdown(
            {"total": 1, "rows": [finished_row]},
            title="已办工单",
        )
        self.assertIn(
            "| 序号 | 工单号 | 流程号 | 标题 | 流程 | 状态 | 处理人 | 创建时间 | 更新时间 |",
            markdown,
        )
        self.assertIn(
            "| 1 | 123 | 15 | 数据库锁异常人工处置 | 故障处置 | 已结束 | 张三 | 2026-06-18 10:13:21 | 2026-06-18 10:25:09 |",
            markdown,
        )
        self.assertNotIn("portal-visualization", markdown)

    def test_list_markdown_uses_global_index_for_later_pages(self) -> None:
        row = dict(TODO_ROW, id=131)
        markdown = format_list_markdown(
            {"total": 31, "pageNum": 2, "pageSize": 10, "rows": [row]},
            title="待办工单",
        )
        self.assertIn("| 11 | 131 | 15 |", markdown)

    def test_detail_markdown_maps_process_structure(self) -> None:
        markdown = format_detail_markdown(PROCESS_STRUCTURE_DETAIL)
        self.assertIn("## 工单详情", markdown)
        self.assertIn("流程名称：**故障处置**", markdown)
        self.assertIn("工单标题：**数据库锁异常人工处置**", markdown)
        self.assertIn("当前节点：**处理节点**", markdown)
        self.assertIn("### 表单信息预览", markdown)
        self.assertIn("设备名称", markdown)
        self.assertIn("db_mysql_001", markdown)
        self.assertIn("### 流转记录", markdown)
        self.assertIn("1. `新建`", markdown)
        self.assertIn("### 流程跟踪", markdown)
        self.assertIn(
            "开始（已完成） -> 处理节点（处理中） -> 结束（未到达）",
            markdown,
        )
        self.assertNotIn("portal-visualization", markdown)

    def test_detail_markdown_emits_portal_order_detail_block(self) -> None:
        markdown = format_detail_markdown(PROCESS_STRUCTURE_DETAIL)
        start = markdown.index("```portal-order-detail")
        block = markdown[start:].split("```", 2)[1]
        payload = json.loads(block.replace("portal-order-detail", "", 1).strip())
        self.assertEqual(payload["processName"], "故障处置")
        tabs = payload["tabs"]
        self.assertTrue(tabs["form"]["sections"])
        self.assertEqual(tabs["records"]["records"][0]["nodeLabel"], "新建")
        self.assertEqual(tabs["records"]["records"][0]["status"], "finished")
        statuses = {node["id"]: node["status"] for node in tabs["tracking"]["nodes"]}
        self.assertEqual(statuses["recv1"], "active")
        self.assertEqual(statuses["start1"], "finished")
        self.assertEqual(statuses["end1"], "pending")

    def test_fetch_all_workorders_aggregates_pages(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(base_url="http://example.com", authorization="token")
        )
        with mock.patch.object(
            client,
            "_request",
            side_effect=[
                _list_envelope(
                    [{"id": 1}, {"id": 2}], total=3, page=1, per_page=2
                ),
                _list_envelope([{"id": 3}], total=3, page=2, per_page=2),
            ],
        ) as request_mock:
            payload = client.list_todo_workorders(page_size=2, fetch_all=True)
        self.assertEqual([row["id"] for row in payload["rows"]], [1, 2, 3])
        self.assertTrue(payload["fetchedAll"])
        self.assertEqual(request_mock.call_count, 2)

    def test_config_falls_back_to_inoe_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "INOE_API_BASE_URL": "http://82.156.83.38:30080",
                "INOE_API_TOKEN": "inoe-token",
            },
            clear=True,
        ):
            config = OrderWorkflowConfig.from_env()
        self.assertEqual(config.base_url, "http://82.156.83.38:30080")
        self.assertEqual(config.authorization, "inoe-token")

    def test_normalize_create_payload_maps_template_fields(self) -> None:
        payload = OrderWorkflowClient._normalize_create_payload(
            {
                "alarmSeq": "test001",
                "alarmTitle": "端口down告警",
                "neName": "HW-hs318",
                "neIp": "192.168.1.32",
                "vendor": "华为",
                "neTime": "现在",
                "alarmSeverity": "P2",
            }
        )
        alarm = payload["alarm"]
        self.assertEqual(alarm["alarmSeq"], "test001")
        self.assertEqual(alarm["alarmTitle"], "端口down告警")
        self.assertEqual(alarm["neName"], "HW-hs318")
        self.assertEqual(alarm["neIp"], "192.168.1.32")
        self.assertEqual(alarm["vendor"], "华为")
        self.assertEqual(alarm["alarmSeverity"], "主要")
        self.assertEqual(alarm["isClear"], "活跃告警")
        self.assertTrue(alarm["neTime"])
        self.assertEqual(alarm["sendTim"], alarm["neTime"])
        self.assertEqual(payload["ticket"]["priority"], "P2")
        self.assertEqual(payload["ticket"]["title"], "端口down告警")
        self.assertTrue(alarm["alarmId"].startswith("alarm-"))
        # 用户没给处置建议 → suggestions 不乱塞，留空
        self.assertEqual(payload["analysis"]["suggestions"], [])

    def test_normalize_create_payload_accepts_old_aliases(self) -> None:
        payload = OrderWorkflowClient._normalize_create_payload(
            {
                "deviceName": "db1",
                "manageIp": "10.0.0.9",
                "title": "数据库锁异常",
                "level": "critical",
                "suggestions": "需人工排查长事务",
            }
        )
        alarm = payload["alarm"]
        self.assertEqual(alarm["neName"], "db1")
        self.assertEqual(alarm["neIp"], "10.0.0.9")
        self.assertEqual(alarm["alarmTitle"], "数据库锁异常")
        self.assertEqual(alarm["alarmSeverity"], "严重")
        self.assertEqual(payload["ticket"]["priority"], "P1")
        self.assertEqual(payload["analysis"]["suggestions"], ["需人工排查长事务"])

    def test_normalize_create_payload_requires_device(self) -> None:
        with self.assertRaises(RuntimeError):
            OrderWorkflowClient._normalize_create_payload({"alarmTitle": "x"})

    def test_create_disposal_workorder_raises_on_business_failure(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(base_url="http://example.com", authorization="token")
        )
        with mock.patch.object(
            client,
            "_request",
            return_value={"code": 500, "msg": "获取流程失败！", "data": None},
        ):
            with self.assertRaises(RuntimeError) as ctx:
                client.create_disposal_workorder(
                    {"alarmTitle": "x", "neName": "d1"}
                )
        self.assertIn("获取流程失败", str(ctx.exception))

    def test_create_markdown_renders_workorder_ids(self) -> None:
        markdown = format_create_markdown(
            {
                "data": {"workOrderId": 124, "processId": 16},
                "notification": {
                    "status": "sent",
                    "channels": [{"channel": "app", "status": "sent"}],
                },
            }
        )
        self.assertIn("`工单号`: `124`", markdown)
        self.assertIn("`流程`: `16`", markdown)
        self.assertIn("通知推送：**应用已发送**", markdown)

    def test_create_notification_context_uses_workorder_ids(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
                create_notify_push_url="http://notify.example.com/push",
            )
        )
        context = client._build_create_notify_context(
            response_payload={"data": {"workOrderId": "wo-1", "processId": "p-1"}},
            request_payload=OrderWorkflowClient._normalize_create_payload(
                {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
                }
            ),
        )
        payload = client._build_create_notify_payload(context)
        self.assertIn("工单号：wo-1", payload["content"])
        self.assertIn("流程：p-1", payload["content"])

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
            return_value={
                "code": 200,
                "data": {"workOrderId": "wo-1", "processId": "p-1"},
            },
        ), mock.patch.object(
            client,
            "_post_json",
            side_effect=RuntimeError("notify down"),
        ):
            payload = client.create_disposal_workorder(
                {
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
                }
            )
        self.assertEqual(payload["data"]["workOrderId"], "wo-1")
        self.assertEqual(payload["notification"]["status"], "failed")
        self.assertIn("notify down", payload["notification"]["reason"])


if __name__ == "__main__":
    unittest.main()
