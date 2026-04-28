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


if __name__ == "__main__":
    unittest.main()
