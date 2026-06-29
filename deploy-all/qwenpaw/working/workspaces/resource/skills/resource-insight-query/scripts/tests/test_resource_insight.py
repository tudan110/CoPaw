import unittest

import resource_insight


class ResourceInsightTest(unittest.TestCase):
    def test_normalize_resource_type_database(self):
        resource = resource_insight.normalize_resource_type("db")
        self.assertEqual(resource["api_type"], "数据库")
        self.assertEqual(resource["default_order_code"], "diskRate")

    def test_normalize_resource_type_server(self):
        resource = resource_insight.normalize_resource_type("计算资源")
        self.assertEqual(resource["api_type"], "服务器")
        self.assertEqual(resource["default_order_code"], "cpuRate")

    def test_build_top_metric_payload_uses_default_order_code(self):
        payload = resource_insight.build_top_metric_payload("database", 5)
        self.assertEqual(payload, {"topNum": 5, "type": "数据库", "orderCode": "diskRate"})

    def test_build_top_metric_payload_allows_order_override(self):
        payload = resource_insight.build_top_metric_payload("network", 10, "memRate")
        self.assertEqual(payload, {"topNum": 10, "type": "网络设备", "orderCode": "memRate"})

    # --- host/主机 alias (RC3a) -------------------------------------------
    def test_normalize_resource_type_host_alias(self):
        for raw in ("host", "主机", "主机系统"):
            resource = resource_insight.normalize_resource_type(raw)
            self.assertEqual(resource["api_type"], "操作系统", raw)
            self.assertEqual(resource["default_order_code"], "diskRate", raw)

    # --- min_rate threshold filter (RC3c) ---------------------------------
    def test_filter_payload_rows_by_min_rate_keeps_above_threshold(self):
        payload = {
            "code": 200,
            "data": [
                {"devName": "a", "metricData": {"diskRate": 92}},
                {"devName": "b", "metricData": {"diskRate": "85.5%"}},
                {"devName": "c", "metricData": {"diskRate": 40}},
                {"devName": "d", "diskRate": None},
            ],
        }
        out = resource_insight.filter_payload_rows_by_min_rate(payload, "diskRate", 80)
        names = [r["devName"] for r in out["data"]]
        self.assertEqual(names, ["a", "b"])

    def test_filter_payload_rows_by_min_rate_noop_without_threshold(self):
        payload = {"code": 200, "data": [{"x": 1}]}
        out = resource_insight.filter_payload_rows_by_min_rate(payload, "diskRate", None)
        self.assertEqual(out["data"], [{"x": 1}])

    def test_filter_payload_rows_by_min_rate_skips_non_success(self):
        payload = {"code": 500, "msg": "boom", "data": None}
        out = resource_insight.filter_payload_rows_by_min_rate(payload, "diskRate", 80)
        self.assertEqual(out, {"code": 500, "msg": "boom", "data": None})

    def test_to_float_parses_percent_and_numbers(self):
        self.assertEqual(resource_insight._to_float("85.5%"), 85.5)
        self.assertEqual(resource_insight._to_float(90), 90.0)
        self.assertIsNone(resource_insight._to_float(""))
        self.assertIsNone(resource_insight._to_float("n/a"))

    # --- top-resource-metric optional type (RC3b) -------------------------
    def test_query_top_resource_metric_injects_type_when_given(self):
        captured = {}

        def fake_request_json(method, path, json_payload=None, **kwargs):
            captured["payload"] = json_payload
            return {"code": 200, "data": []}

        original = resource_insight.request_json
        resource_insight.request_json = fake_request_json
        try:
            resource_insight.query_top_resource_metric(
                top_num=5, order_key="diskRate", resource_type="主机"
            )
            self.assertEqual(captured["payload"]["type"], "操作系统")
            # default (no resource_type) stays type-less / backward compatible
            resource_insight.query_top_resource_metric(top_num=5)
            self.assertNotIn("type", captured["payload"])
        finally:
            resource_insight.request_json = original


if __name__ == "__main__":
    unittest.main()
