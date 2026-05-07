"""Tests for the inline-attribute fallback in app_topology.py.

Some VEOPS deployments express a project's relationships not as `ci_relations`
rows but as inline string attributes on the project CI itself (e.g. a `Kafka`
field whose value is `"kafka-web01, kafka-web02"`). These tests guarantee that
`app_topology` resolves those values into real CI items even when
`/api/v0.1/ci_relations/s` returns an empty result set.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_DIR = Path(__file__).resolve().parents[1]
# Make sibling modules importable (app_topology imports from find_project).
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
APP_TOPOLOGY = _load_module("zgops_app_topology", SCRIPT_DIR / "app_topology.py")


class _StubClient:
    """Mimics the subset of CmdbHttpClient that app_topology touches."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.requested_paths: list[str] = []

    def _request_json(self, path: str, **_: Any) -> Any:  # noqa: D401
        self.requested_paths.append(path)
        if path in self._responses:
            return self._responses[path]
        for prefix, payload in self._responses.items():
            if prefix.endswith("*") and path.startswith(prefix[:-1]):
                return payload
        raise RuntimeError(f"unexpected path: {path}")


class AppTopologyInlineFallbackTests(unittest.TestCase):
    def _make_client(self) -> _StubClient:
        return _StubClient(
            {
                "/api/v0.1/ci_types?per_page=200": {
                    "result": [
                        {"name": "Kafka", "alias": "Kafka"},
                        {"name": "mysql", "alias": "MySQL"},
                        {"name": "redis", "alias": "Redis"},
                        {"name": "operatingsystem", "alias": "操作系统"},
                    ]
                },
                "/api/v0.1/ci/4310": {
                    "result": {
                        "_id": 4310,
                        "ci_type": "project",
                        "project_name": "准能网站系统",
                        "Kafka": ["kafka-web01", "kafka-web02"],
                        "mysql": "MySQL_web01,MySQL_web02",
                        "redis": "redis-web02",
                        "operatingsystem": "Windows_2022",
                        # Noise attributes that should be ignored.
                        "description": "门户应用",
                        "platform": ["私有云"],
                    }
                },
                # Per-type CI catalogs used to resolve inline values.
                "/api/v0.1/ci/s?q=_type:Kafka&count=10000&page=1": {
                    "result": [
                        {
                            "_id": 1001,
                            "ci_type": "Kafka",
                            "middleware_name": "kafka-web01",
                            "middleware_ip": "10.10.1.21",
                        },
                        {
                            "_id": 1002,
                            "ci_type": "Kafka",
                            "middleware_name": "kafka-web02",
                            "middleware_ip": "10.10.1.57",
                        },
                        {
                            "_id": 1003,
                            "ci_type": "Kafka",
                            "middleware_name": "kafka-other",
                            "middleware_ip": "10.10.1.99",
                        },
                    ]
                },
                "/api/v0.1/ci/s?q=_type:mysql&count=10000&page=1": {
                    "result": [
                        {
                            "_id": 2001,
                            "ci_type": "mysql",
                            "db_instance": "MySQL_web01",
                            "manage_ip": "10.10.1.91",
                        },
                        {
                            "_id": 2002,
                            "ci_type": "mysql",
                            "db_instance": "MySQL_web02",
                            "manage_ip": "10.10.1.92",
                        },
                    ]
                },
                "/api/v0.1/ci/s?q=_type:redis&count=10000&page=1": {
                    "result": [
                        {
                            "_id": 3001,
                            "ci_type": "redis",
                            "middleware_name": "redis-web02",
                            "middleware_ip": "10.10.1.14",
                        }
                    ]
                },
                "/api/v0.1/ci/s?q=_type:operatingsystem&count=10000&page=1": {
                    "result": [
                        {
                            "_id": 4001,
                            "ci_type": "operatingsystem",
                            "name": "Windows_2022",
                        }
                    ]
                },
            }
        )

    def test_inline_attributes_resolve_when_relations_empty(self) -> None:
        client = self._make_client()
        project_detail = APP_TOPOLOGY._fetch_ci_detail(client, 4310)
        items = APP_TOPOLOGY._resolve_inline_resources(client, project_detail)

        ids = sorted(item["_id"] for item in items)
        # All four inline-referenced CIs come back, the unrelated `kafka-other`
        # is filtered out by name matching.
        self.assertEqual(ids, [1001, 1002, 2001, 2002, 3001, 4001])

    def test_merge_dedupes_by_id(self) -> None:
        primary = [
            {"_id": 1001, "ci_type": "Kafka", "middleware_name": "kafka-web01"},
        ]
        extra = [
            {"_id": 1001, "ci_type": "Kafka", "middleware_name": "kafka-web01"},
            {"_id": 1002, "ci_type": "Kafka", "middleware_name": "kafka-web02"},
        ]
        merged = APP_TOPOLOGY._merge_items(primary, extra)
        self.assertEqual([item["_id"] for item in merged], [1001, 1002])

    def test_inline_resolution_skips_project_self_reference(self) -> None:
        client = _StubClient(
            {
                "/api/v0.1/ci_types?per_page=200": {"result": []},
                "/api/v0.1/ci/s?q=_type:project&count=10000&page=1": {"result": []},
            }
        )
        # A project field literally named `project` should never recurse into
        # the project type — that would re-add the root and break the tree.
        items = APP_TOPOLOGY._resolve_inline_resources(
            client,
            {"_id": 1, "ci_type": "project", "project": "self"},
        )
        self.assertEqual(items, [])
        self.assertNotIn(
            "/api/v0.1/ci/s?q=_type:project&count=10000&page=1",
            client.requested_paths,
        )

    def test_catalog_falls_back_when_metadata_unreachable(self) -> None:
        class _BoomClient(_StubClient):
            def _request_json(self, path: str, **_: Any) -> Any:
                self.requested_paths.append(path)
                if path == "/api/v0.1/ci_types?per_page=200":
                    raise RuntimeError("metadata endpoint down")
                return super()._request_json(path)

        client = _BoomClient(
            {
                "/api/v0.1/ci/s?q=_type:Kafka&count=10000&page=1": {
                    "result": [
                        {
                            "_id": 1001,
                            "ci_type": "Kafka",
                            "middleware_name": "kafka-web01",
                        }
                    ]
                }
            }
        )
        items = APP_TOPOLOGY._resolve_inline_resources(
            client,
            {"_id": 9, "ci_type": "project", "Kafka": "kafka-web01"},
        )
        self.assertEqual([item["_id"] for item in items], [1001])


if __name__ == "__main__":
    unittest.main()
