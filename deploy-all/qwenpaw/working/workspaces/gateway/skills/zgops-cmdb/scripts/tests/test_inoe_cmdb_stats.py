import unittest

import inoe_cmdb_stats


class InoeCmdbStatsTest(unittest.TestCase):
    def test_middleware_maps_to_type_6(self):
        resource = inoe_cmdb_stats.normalize_resource("中间件", None)
        self.assertEqual(resource["type_id"], "6")
        self.assertEqual(resource["label"], "中间件")
        self.assertEqual(resource["type_source"], "fallback")

    def test_server_and_os_fallback_to_group_ids(self):
        self.assertEqual(inoe_cmdb_stats.normalize_resource("服务器", None)["type_id"], "2")
        self.assertEqual(inoe_cmdb_stats.normalize_resource("操作系统", None)["type_id"], "17")

    def test_vendor_aliases(self):
        self.assertEqual(inoe_cmdb_stats.normalize_attr("制造商"), "vendor")
        self.assertEqual(inoe_cmdb_stats.normalize_attr("厂商"), "vendor")

    def test_type_id_overrides_resource_type(self):
        resource = inoe_cmdb_stats.normalize_resource("database", "6")
        self.assertEqual(resource["type_id"], "6")
        self.assertEqual(resource["type_source"], "explicit")

    def test_dynamic_group_resolution_prefers_group_id(self):
        original = inoe_cmdb_stats.query_type_catalog
        try:
            inoe_cmdb_stats.query_type_catalog = lambda: {
                "groups": [
                    {
                        "id": 6,
                        "name": "中间件",
                        "ci_types": [
                            {"id": 61, "name": "redis", "alias": "Redis"},
                        ],
                    }
                ],
                "ci_types": [
                    {"id": 61, "name": "redis", "alias": "Redis"},
                ],
            }
            resource = inoe_cmdb_stats.resolve_resource("middleware", None)
        finally:
            inoe_cmdb_stats.query_type_catalog = original

        self.assertEqual(resource["type_id"], "6")
        self.assertEqual(resource["label"], "中间件")
        self.assertEqual(resource["type_source"], "cmdb_group")

    def test_dynamic_type_resolution_when_specific_model(self):
        original = inoe_cmdb_stats.query_type_catalog
        try:
            inoe_cmdb_stats.query_type_catalog = lambda: {
                "groups": [
                    {"id": 6, "name": "中间件", "ci_types": []},
                ],
                "ci_types": [
                    {"id": 62, "name": "Kafka", "alias": "Kafka"},
                ],
            }
            resource = inoe_cmdb_stats.resolve_resource("Kafka", None)
        finally:
            inoe_cmdb_stats.query_type_catalog = original

        self.assertEqual(resource["type_id"], "62")
        self.assertEqual(resource["type_source"], "ci_type")


if __name__ == "__main__":
    unittest.main()
