import unittest

import monitoring_overview


class MonitoringOverviewTest(unittest.TestCase):
    def test_build_topology_tree_data_uses_first_node_as_root(self):
        tree = monitoring_overview.build_topology_tree_data(
            [
                {"id": "1", "type": "天翼智观", "alarmStatus": "0", "deviceCount": 3},
                {
                    "id": "2",
                    "type": "PostgreSQL",
                    "alarmStatus": "1",
                    "deviceCount": 2,
                    "data": {
                        "resources": [
                            {"name": "PG-01", "manage_ip": "10.0.0.1", "alarm_status": "1"},
                        ],
                    },
                },
            ]
        )
        self.assertEqual(tree["name"], "天翼智观")
        self.assertEqual(len(tree["children"]), 1)
        self.assertEqual(tree["children"][0]["name"], "PostgreSQL (2)")
        self.assertEqual(tree["children"][0]["children"][0]["name"], "PG-01\\n10.0.0.1")

    def test_format_alarm_top5_markdown_contains_chart_block(self):
        markdown = monitoring_overview.format_alarm_top5_markdown(
            {
                "code": 200,
                "data": [
                    {"title": "ping异常", "count": 33},
                    {"title": "丢包异常", "count": 12},
                ],
            }
        )
        self.assertIn("### 告警对象 Top5", markdown)
        self.assertIn("```echarts", markdown)
        self.assertIn("ping异常", markdown)

    def test_format_asset_overview_markdown_contains_summary(self):
        markdown = monitoring_overview.format_asset_overview_markdown(
            {
                "code": 200,
                "data": {
                    "totalResources": 10,
                    "healthRate": 98.5,
                    "healthStatus": "green",
                    "resourceTypeStats": {
                        "数据库": {
                            "resourceTypeName": "数据库",
                            "totalCount": 4,
                            "normalCount": 4,
                            "alarmCount": 0,
                        }
                    },
                    "applicationHealthList": [],
                    "hostResourceTop": {},
                },
            }
        )
        self.assertIn("### 监控资产总览", markdown)
        self.assertIn("资源总数：10", markdown)
        self.assertIn("数据库", markdown)


if __name__ == "__main__":
    unittest.main()
