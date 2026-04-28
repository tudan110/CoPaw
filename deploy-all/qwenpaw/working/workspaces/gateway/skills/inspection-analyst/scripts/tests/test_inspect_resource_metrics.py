import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_DIR = Path(__file__).resolve().parents[1]
INSPECTION_MODULE = _load_module(
    "inspection_metric_test_module",
    SCRIPT_DIR / "inspect_resource_metrics.py",
)


def test_fetch_all_metric_definitions_paginates_and_dedupes():
    responses = [
        {
            "source": "live",
            "url": "http://example/api",
            "request": {"pageNum": 1},
            "fallbackReason": None,
            "metrics": [
                {"code": "m1", "name": "指标1", "unit": ""},
                {"code": "m2", "name": "指标2", "unit": "%"},
            ],
        },
        {
            "source": "live",
            "url": "http://example/api",
            "request": {"pageNum": 2},
            "fallbackReason": None,
            "metrics": [
                {"code": "m2", "name": "指标2", "unit": "%"},
                {"code": "m3", "name": "指标3", "unit": "ms"},
            ],
        },
        {
            "source": "live",
            "url": "http://example/api",
            "request": {"pageNum": 3},
            "fallbackReason": None,
            "metrics": [],
        },
    ]

    with patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "fetch_metric_definitions",
        side_effect=responses,
    ) as mocked_fetch:
        result = INSPECTION_MODULE.fetch_all_metric_definitions(
            metric_type="mysql",
            page_size=2,
        )

    assert mocked_fetch.call_count == 3
    assert result["metricsTotal"] == 3
    assert [item["code"] for item in result["metrics"]] == ["m1", "m2", "m3"]


def test_fetch_metric_data_batch_uses_all_metric_codes_in_one_request():
    recorded_payloads = []

    def _fake_post_json_with_fallback(*, url, headers, json_payload, timeout_seconds):
        recorded_payloads.append(
            {
                "url": url,
                "headers": headers,
                "json_payload": json_payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return (
            {
                "code": 200,
                "msg": "ok",
                "data": [
                    {
                        "resId": "3094",
                        "processData": {
                            "m1Min": "1",
                            "m1Avg": "2",
                            "m1Max": "3",
                            "m2Min": "4",
                            "m2Avg": "5",
                            "m2Max": "6",
                        },
                        "originalDatas": [
                            {"formatTime": "2026-04-24 10:00:00", "m1": "2", "m2": "5"}
                        ],
                    }
                ],
            },
            "requests",
        )

    with patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "_normalize_base_url",
        return_value="http://example.test",
    ), patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "_get_token",
        return_value="token",
    ), patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "_post_json_with_fallback",
        side_effect=_fake_post_json_with_fallback,
    ):
        result = INSPECTION_MODULE.fetch_metric_data_batch(
            res_id="3094",
            metric_definitions=[
                {"code": "m1", "name": "指标1", "unit": ""},
                {"code": "m2", "name": "指标2", "unit": "%"},
            ],
        )

    assert recorded_payloads[0]["json_payload"]["queryKeys"] == ["m1", "m2"]
    assert result["metricResults"][0]["latestValue"] == "2"
    assert result["metricResults"][1]["latestValue"] == "5"


def test_render_markdown_contains_metric_table():
    markdown = INSPECTION_MODULE.render_markdown(
        {
            "inspectionObject": "数据库",
            "resourceName": "db_mysql_001",
            "resId": "3094",
            "metricType": "mysql",
            "definitions": {
                "metricsTotal": 2,
                "source": "live",
                "fallbackReason": None,
            },
            "metricDataBatch": {
                "source": "live",
                "fallbackReason": None,
                "metricResults": [
                    {
                        "metricName": "活跃线程数",
                        "metricCode": "threads_running",
                        "latestValue": "12",
                        "sampleTime": "2026-04-24 10:00:00",
                        "minValue": "10",
                        "avgValue": "11",
                        "maxValue": "12",
                        "unit": "",
                        "source": "live",
                    }
                ],
            },
            "notification": {
                "status": "sent",
                "channels": [{"channel": "app", "status": "sent"}],
            },
        }
    )

    assert "PORTAL INSPECTION CARD MODE" in markdown
    assert "## 巡检结果" in markdown
    assert "## 基本信息" in markdown
    assert "db_mysql_001" in markdown
    assert "threads_running" in markdown
    assert "| 巡检时间 | 2026-04-24 10:00:00 |" in markdown
    assert "| 状态 | 正常 |" in markdown
    assert "通知状态" in markdown
    assert "应用已发送" in markdown


def test_inspect_resource_metrics_triggers_notification_by_default():
    with patch.object(
        INSPECTION_MODULE,
        "fetch_all_metric_definitions",
        return_value={
            "metricsTotal": 1,
            "source": "live",
            "metrics": [{"code": "m1", "name": "指标1", "unit": ""}],
        },
    ), patch.object(
        INSPECTION_MODULE,
        "fetch_metric_data_batch",
        return_value={
            "source": "live",
            "metricResults": [
                {
                    "metricName": "指标1",
                    "metricCode": "m1",
                    "latestValue": "1",
                    "sampleTime": "2026-04-24 10:00:00",
                    "minValue": "1",
                    "avgValue": "1",
                    "maxValue": "1",
                    "unit": "",
                    "source": "live",
                }
            ],
        },
    ), patch.object(
        INSPECTION_MODULE,
        "_notify_inspection_result",
        return_value={"status": "sent", "channels": [{"channel": "app", "status": "sent"}]},
    ) as mocked_notify:
        result = INSPECTION_MODULE.inspect_resource_metrics(
            metric_type="mysql",
            res_id="3094",
            inspection_object="数据库",
            resource_name="db_mysql_001",
        )

    mocked_notify.assert_called_once()
    assert result["notification"]["status"] == "sent"


def test_inspect_resource_metrics_can_skip_notification():
    with patch.object(
        INSPECTION_MODULE,
        "fetch_all_metric_definitions",
        return_value={
            "metricsTotal": 1,
            "source": "live",
            "metrics": [{"code": "m1", "name": "指标1", "unit": ""}],
        },
    ), patch.object(
        INSPECTION_MODULE,
        "fetch_metric_data_batch",
        return_value={
            "source": "live",
            "metricResults": [],
        },
    ), patch.object(
        INSPECTION_MODULE,
        "_notify_inspection_result",
    ) as mocked_notify:
        result = INSPECTION_MODULE.inspect_resource_metrics(
            metric_type="mysql",
            res_id="3094",
            notify=False,
        )

    mocked_notify.assert_not_called()
    assert result["notification"]["reason"] == "notify_disabled"


@patch.dict(
    "os.environ",
    {
        "INSPECTION_NOTIFY_WEBHOOK_URL": "http://notify.example.com/webhook",
        "INSPECTION_NOTIFY_MENTION_ALL": "true",
    },
    clear=False,
)
def test_app_notification_payload_uses_plain_text_content():
    payload = INSPECTION_MODULE._build_app_notify_payload(
        {
            "inspection_object": "核心数据库",
            "resource_name": "db_mysql_001",
            "res_id": "3094",
            "metric_type": "mysql",
            "metrics_total": "12",
            "definition_source": "live",
            "data_source": "live",
            "metric_preview": "活跃线程数=12；连接数=80",
            "metric_results": [
                {
                    "metricName": "活跃线程数",
                    "metricCode": "mysql_active_threads",
                    "latestValue": "12",
                    "unit": "%",
                }
            ],
            "inspection_status": "正常",
            "inspection_time": "2026-04-24 10:00:00",
            "inspection_conclusion": "各项指标均在正常范围，资源运行健康。",
            "created_at": "2026-04-24 10:00:00",
        }
    )

    assert payload["type"] == "text"
    assert payload["textMsg"]["isMentioned"] is True
    assert payload["textMsg"]["mentionType"] == 1
    assert "AI巡检结果" in payload["textMsg"]["content"]
    assert "- 巡检对象：核心数据库" in payload["textMsg"]["content"]
    assert "- 整体状态：正常" in payload["textMsg"]["content"]
    assert "活跃线程数（mysql_active_threads）：12" in payload["textMsg"]["content"]
    assert "活跃线程数（mysql_active_threads）：12%" not in payload["textMsg"]["content"]
    assert "巡检结论" in payload["textMsg"]["content"]
    assert "**" not in payload["textMsg"]["content"]
    assert ">" not in payload["textMsg"]["content"]


@patch.dict(
    "os.environ",
    {
        "INSPECTION_NOTIFY_DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=test",
        "INSPECTION_NOTIFY_DINGTALK_KEYWORD": "巡检",
        "INSPECTION_NOTIFY_MENTION_ALL": "true",
    },
    clear=False,
)
def test_dingtalk_notification_payload_uses_markdown_message():
    payload = INSPECTION_MODULE._build_dingtalk_notify_payload(
        {
            "inspection_object": "核心数据库",
            "resource_name": "db_mysql_001",
            "res_id": "3094",
            "metric_type": "mysql",
            "metrics_total": "12",
            "definition_source": "live",
            "data_source": "live",
            "metric_preview": "活跃线程数=12；连接数=80",
            "metric_results": [
                {
                    "metricName": "活跃线程数",
                    "metricCode": "mysql_active_threads",
                    "latestValue": "12",
                    "unit": "%",
                }
            ],
            "inspection_status": "正常",
            "inspection_time": "2026-04-24 10:00:00",
            "inspection_conclusion": "各项指标均在正常范围，资源运行健康。",
            "created_at": "2026-04-24 10:00:00",
        }
    )

    assert payload["msgtype"] == "markdown"
    assert payload["at"]["isAtAll"] is True
    assert payload["markdown"]["text"].startswith("巡检\n")
    assert "- **巡检对象**：核心数据库" in payload["markdown"]["text"]
    assert "- **整体状态**：正常" in payload["markdown"]["text"]
    assert "活跃线程数（mysql_active_threads）：12" in payload["markdown"]["text"]
    assert "活跃线程数（mysql_active_threads）：12%" not in payload["markdown"]["text"]
    assert "**巡检结论**" in payload["markdown"]["text"]


@patch.dict(
    "os.environ",
    {
        "INSPECTION_NOTIFY_FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        "INSPECTION_NOTIFY_FEISHU_SECRET": "feishu-secret",
        "INSPECTION_NOTIFY_MENTION_ALL": "true",
    },
    clear=False,
)
def test_feishu_notification_payload_uses_table_card_and_sign():
    with patch.object(INSPECTION_MODULE.time, "time", return_value=1700000000.0):
        payload = INSPECTION_MODULE._build_feishu_notify_payload(
            {
                "inspection_object": "核心数据库",
                "resource_name": "db_mysql_001",
                "res_id": "3094",
                "metric_type": "mysql",
                "metrics_total": "12",
                "definition_source": "live",
                "data_source": "live",
                "metric_preview": "活跃线程数=12；连接数=80",
                "metric_results": [
                    {
                        "metricName": "活跃线程数",
                        "metricCode": "mysql_active_threads",
                        "latestValue": "12",
                        "unit": "",
                    },
                    {
                        "metricName": "CPU 使用率",
                        "metricCode": "mysql_cpu_usage",
                        "latestValue": "42.5",
                        "unit": "%",
                    },
                ],
                "inspection_status": "正常",
                "inspection_time": "2026-04-24 10:00:00",
                "inspection_conclusion": "各项指标均在正常范围，资源运行健康。",
                "created_at": "2026-04-24 10:00:00",
            }
        )

    assert payload["msg_type"] == "interactive"
    assert payload["timestamp"] == "1700000000"
    assert payload["sign"]
    assert payload["card"]["header"]["template"] == "green"
    assert payload["card"]["header"]["title"]["content"] == "AI巡检报告 — db_mysql_001"
    assert payload["card"]["elements"][0]["text"]["content"] == "<at id=all></at>"
    assert payload["card"]["elements"][1]["fields"][0]["text"]["content"] == "**巡检对象**\n核心数据库"
    detail_heading = next(
        element
        for element in payload["card"]["elements"]
        if element.get("tag") == "div"
        and element.get("text", {}).get("content") == "**指标值明细**"
    )
    assert detail_heading["text"]["content"] == "**指标值明细**"
    table_element = next(
        element
        for element in payload["card"]["elements"]
        if element.get("tag") == "table"
    )
    assert table_element["columns"][0]["display_name"] == "指标名"
    assert table_element["rows"][0]["metric_name"] == "活跃线程数"
    assert table_element["rows"][1]["latest_value"] == "42.5"
    conclusion_element = next(
        element
        for element in payload["card"]["elements"]
        if element.get("tag") == "div"
        and "巡检结论" in element.get("text", {}).get("content", "")
    )
    assert "各项指标均在正常范围" in conclusion_element["text"]["content"]
