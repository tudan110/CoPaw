import importlib.util
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_DIR = Path(__file__).resolve().parents[1]
METRIC_MODULE = _load_module("alarm_metric_fallback_test", SCRIPT_DIR / "get_metric_definitions.py")


class MetricHttpFallbackTests(unittest.TestCase):
    def test_fetch_metric_definitions_uses_curl_after_requests_connection_error(self):
        response_payload = {
            "code": 200,
            "msg": "ok",
            "data": [
                {
                    "metricCode": "mysql_global_status_innodb_row_lock_time",
                    "metricName": "InnoDB 总锁等待时长",
                    "metricType": "mysql",
                    "valUnit": "ms",
                }
            ],
        }

        def _fake_run(args, capture_output, text, encoding, timeout, check):
            body_path = args[args.index("-o") + 1]
            Path(body_path).write_text(json.dumps(response_payload, ensure_ascii=False), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="200", stderr="")

        with patch.object(METRIC_MODULE.requests, "post", side_effect=requests.ConnectionError("No route to host")):
            with patch.object(METRIC_MODULE.subprocess, "run", side_effect=_fake_run):
                result = METRIC_MODULE.fetch_metric_definitions(
                    metric_type="mysql",
                    api_base_url="http://gateway:8080",
                    token="token",
                )

        self.assertEqual(result["source"], "live")
        self.assertEqual(result["metricsTotal"], 1)
        self.assertIsNone(result["fallbackReason"])
        self.assertEqual(result["metrics"][0]["code"], "mysql_global_status_innodb_row_lock_time")

    def test_fetch_metric_data_uses_curl_after_requests_connection_error(self):
        response_payload = {
            "code": 200,
            "msg": "ok",
            "data": [
                {
                    "resId": "3094",
                    "processData": {
                        "unit": "ms",
                        "mysql_global_status_innodb_row_lock_timeMin": "1",
                        "mysql_global_status_innodb_row_lock_timeAvg": "2",
                        "mysql_global_status_innodb_row_lock_timeMax": "3",
                    },
                    "originalDatas": [
                        {
                            "formatTime": "2026-04-22 10:00:00",
                            "mysql_global_status_innodb_row_lock_time": "2",
                        }
                    ],
                }
            ],
        }

        def _fake_run(args, capture_output, text, encoding, timeout, check):
            body_path = args[args.index("-o") + 1]
            Path(body_path).write_text(json.dumps(response_payload, ensure_ascii=False), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="200", stderr="")

        with patch.object(METRIC_MODULE.requests, "post", side_effect=requests.ConnectionError("No route to host")):
            with patch.object(METRIC_MODULE.subprocess, "run", side_effect=_fake_run):
                result = METRIC_MODULE.fetch_metric_data(
                    res_id="3094",
                    metric_code="mysql_global_status_innodb_row_lock_time",
                    api_base_url="http://gateway:8080",
                    token="token",
                )

        self.assertEqual(result["source"], "live")
        self.assertIsNone(result["fallbackReason"])
        self.assertEqual(result["latestValue"], "2")
        self.assertEqual(result["avgValue"], "2")
        self.assertEqual(result["unit"], "ms")


if __name__ == "__main__":
    unittest.main()
