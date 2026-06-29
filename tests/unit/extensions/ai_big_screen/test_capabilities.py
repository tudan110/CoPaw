# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Mapping

import pytest

from qwenpaw.extensions.ai_big_screen import capabilities
from qwenpaw.extensions.ai_big_screen.capabilities import (
    CapabilityCache,
    CapabilityDescriptor,
    execute_capability,
    get_descriptor,
    list_capability_metadata,
)


def _descriptor(
    fetcher: Any,
    *,
    capability_id: str = "test-cap",
    timeout: float = 5.0,
    is_gap: bool = False,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        id=capability_id,
        display_name="测试能力",
        domain="test",
        fetcher=fetcher,
        timeout_seconds=timeout,
        is_gap=is_gap,
        metadata={"id": capability_id, "dataSource": "test-source"},
    )


class TestStatusAdjudication:
    async def test_exception_becomes_failed(self) -> None:
        def _boom(_params: Mapping[str, Any]) -> dict[str, Any]:
            raise RuntimeError("backend exploded")

        result = await execute_capability(
            {},
            descriptor=_descriptor(_boom),
        )
        assert result.source_status == "failed"
        assert "backend exploded" in result.message

    async def test_timeout_becomes_failed(self) -> None:
        def _slow(_params: Mapping[str, Any]) -> dict[str, Any]:
            import time

            time.sleep(5)
            return {"rows": []}

        result = await execute_capability(
            {},
            descriptor=_descriptor(_slow, timeout=0.1),
        )
        assert result.source_status == "failed"
        assert "超时" in result.message

    async def test_rows_become_live(self) -> None:
        result = await execute_capability(
            {},
            descriptor=_descriptor(lambda _p: {"rows": [{"a": 1}]}),
        )
        assert result.source_status == "live"
        assert result.rows == [{"a": 1}]

    async def test_zero_rows_become_empty(self) -> None:
        result = await execute_capability(
            {},
            descriptor=_descriptor(lambda _p: {"rows": []}),
        )
        assert result.source_status == "empty"

    async def test_legacy_unavailable_hint_maps_to_failed(self) -> None:
        result = await execute_capability(
            {},
            descriptor=_descriptor(
                lambda _p: {
                    "sourceStatus": "unavailable",
                    "message": "接口 500",
                },
            ),
        )
        assert result.source_status == "failed"

    async def test_gap_descriptor_maps_to_gap(self) -> None:
        result = await execute_capability(
            {},
            descriptor=_descriptor(
                lambda _p: {"sourceStatus": "unavailable", "rows": []},
                is_gap=True,
            ),
        )
        assert result.source_status == "gap"

    async def test_unknown_capability_failed(self) -> None:
        result = await execute_capability({}, capability_id="no-such-cap")
        assert result.source_status == "failed"
        assert "no-such-cap" in result.message

    async def test_extra_fields_round_trip_to_legacy_data(self) -> None:
        result = await execute_capability(
            {},
            descriptor=_descriptor(
                lambda _p: {
                    "rows": [{"a": 1}],
                    "trend": "最近 15 分钟",
                    "value": 7,
                    "unit": "条",
                },
            ),
        )
        data = result.to_legacy_data()
        assert data["trend"] == "最近 15 分钟"
        assert data["value"] == 7
        assert data["sourceStatus"] == "live"


class TestFetchOnceCache:
    async def test_same_params_fetch_once(self) -> None:
        calls: list[Mapping[str, Any]] = []

        def _fetcher(params: Mapping[str, Any]) -> dict[str, Any]:
            calls.append(params)
            return {"rows": [{"n": len(calls)}]}

        descriptor = _descriptor(_fetcher)
        cache = CapabilityCache()
        first = await execute_capability(
            {"limit": 10},
            descriptor=descriptor,
            cache=cache,
        )
        second = await execute_capability(
            {"limit": 10},
            descriptor=descriptor,
            cache=cache,
        )
        assert len(calls) == 1
        assert first.rows == second.rows

    async def test_different_params_fetch_twice(self) -> None:
        calls: list[Mapping[str, Any]] = []

        def _fetcher(params: Mapping[str, Any]) -> dict[str, Any]:
            calls.append(params)
            return {"rows": []}

        descriptor = _descriptor(_fetcher)
        cache = CapabilityCache()
        await execute_capability(
            {"limit": 10},
            descriptor=descriptor,
            cache=cache,
        )
        await execute_capability(
            {"limit": 20},
            descriptor=descriptor,
            cache=cache,
        )
        assert len(calls) == 2

    async def test_param_order_does_not_break_cache(self) -> None:
        calls: list[Mapping[str, Any]] = []

        def _fetcher(params: Mapping[str, Any]) -> dict[str, Any]:
            calls.append(params)
            return {"rows": []}

        descriptor = _descriptor(_fetcher)
        cache = CapabilityCache()
        await execute_capability(
            {"a": 1, "b": 2},
            descriptor=descriptor,
            cache=cache,
        )
        await execute_capability(
            {"b": 2, "a": 1},
            descriptor=descriptor,
            cache=cache,
        )
        assert len(calls) == 1


class TestRegistry:
    def test_all_legacy_capabilities_registered(self) -> None:
        ids = {item["id"] for item in list_capability_metadata()}
        assert ids == {
            "system-logs",
            "real-alarms",
            "cmdb-resources",
            "workorders",
            "alarm-top5",
            "topology-impact",
            "web-live-data",
            "capability-gap",
        }

    def test_metadata_keeps_legacy_shape(self) -> None:
        by_id = {item["id"]: item for item in list_capability_metadata()}
        logs = by_id["system-logs"]
        assert logs["dataSource"] == "zhiguan-log-service"
        assert logs["skillName"] == "nightingale-log"
        assert {"key", "label"} <= set(logs["availableFields"][0].keys())
        assert by_id["capability-gap"]["domain"] == "planning"

    def test_capability_gap_descriptor_is_gap(self) -> None:
        descriptor = get_descriptor("capability-gap")
        assert descriptor is not None
        assert descriptor.is_gap is True

    def test_metadata_carries_category_and_connection(self) -> None:
        by_id = {item["id"]: item for item in list_capability_metadata()}
        # every capability declares both classification keys
        for item in by_id.values():
            assert "category" in item
            assert "connection" in item
        # functional-domain mapping is honest about the backing connection
        assert by_id["real-alarms"]["category"] == "alarm"
        assert by_id["real-alarms"]["connection"] == "inoe"
        assert by_id["workorders"]["category"] == "workorder"
        assert by_id["workorders"]["connection"] == "inoe"
        assert by_id["cmdb-resources"]["category"] == "cmdb"
        assert by_id["system-logs"]["category"] == "logs"
        assert by_id["system-logs"]["connection"] == "n9e"
        # web/gap need no connection
        assert by_id["web-live-data"]["connection"] == ""
        assert by_id["capability-gap"]["connection"] == ""


class TestHonestIntegrationWiring:
    async def test_real_alarms_failure_is_failed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.integrations import portal_real_alarms

        def _raise(*_args: Any, **kwargs: Any) -> dict[str, Any]:
            assert kwargs.get("raise_on_error") is True
            raise ConnectionError("alarm backend down")

        monkeypatch.setattr(
            portal_real_alarms,
            "query_portal_real_alarms",
            _raise,
        )
        monkeypatch.setattr(
            "qwenpaw.extensions.integrations.working_secrets"
            ".ensure_working_secrets_loaded",
            lambda: None,
        )
        result = await execute_capability(
            {"limit": 5},
            capability_id="real-alarms",
        )
        assert result.source_status == "failed"
        assert "alarm backend down" in result.message

    async def test_real_alarms_rows_carry_rich_display_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.integrations import portal_real_alarms

        monkeypatch.setattr(
            "qwenpaw.extensions.integrations.working_secrets"
            ".ensure_working_secrets_loaded",
            lambda: None,
        )
        monkeypatch.setattr(
            portal_real_alarms,
            "query_portal_real_alarms",
            lambda **_kw: {
                "source": "live",
                "total": 1,
                "items": [
                    {
                        "id": "A-1",
                        "title": "内存使用率",
                        "level": "critical",
                        "levelName": "紧急",
                        "statusName": "活跃",
                        "className": "性能告警",
                        "deviceName": "智观部署虚机",
                        "manageIp": "82.156.83.38",
                        "ciId": "7953",
                        "speciality": "操作系统",
                        "eventTime": "2026-06-15 10:57:31",
                        "message": "【紧急】内存使用率｜智观部署虚机 82.156.83.38｜活跃",
                    },
                ],
            },
        )
        result = await execute_capability(
            {"limit": 5},
            capability_id="real-alarms",
        )
        assert result.source_status == "live"
        row = result.rows[0]
        assert row["levelName"] == "紧急"
        assert row["statusName"] == "活跃"
        assert row["ciId"] == "7953"
        assert row["deviceName"] == "智观部署虚机"
        assert row["message"]
        # default columns now mirror the chat alarm table (7 rich cols)
        column_keys = [c["key"] for c in (result.columns or [])]
        assert "levelName" in column_keys
        assert "ciId" in column_keys
        assert "statusName" in column_keys
        assert "level" not in column_keys  # raw tone key not a column

    async def test_workorders_non_live_source_blocked_as_failed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.integrations import order_workflow

        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: {"source": "mock", "items": [{"id": "x"}]},
        )
        result = await execute_capability(
            {"limit": 5},
            capability_id="workorders",
        )
        assert result.source_status == "failed"
        assert "阻断" in result.message or "实时" in result.message

    async def test_workorders_live_source_passes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.integrations import order_workflow

        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: {
                "source": "live",
                "total": 1,
                "items": [{"id": "wo-1", "title": "磁盘告警工单"}],
                "stats": {"todo": 1},
            },
        )
        result = await execute_capability(
            {"limit": 5},
            capability_id="workorders",
        )
        assert result.source_status == "live"
        assert result.rows is not None
        assert result.rows[0]["id"] == "wo-1"

    def test_descriptors_never_touch_mock_data_path(self) -> None:
        """USE_MOCK_DATA isolation: the big-screen fetchers must not
        route through alarm_workorders (the only integration with a
        mock_data fallback)."""
        from qwenpaw.extensions.ai_big_screen.capabilities import (
            descriptors,
        )

        source = inspect.getsource(descriptors)
        assert "alarm_workorders" not in source
        assert "mock_data" not in source

    async def test_use_mock_data_env_does_not_leak(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.integrations import order_workflow

        monkeypatch.setenv("USE_MOCK_DATA", "true")
        monkeypatch.setattr(
            order_workflow,
            "query_order_workorders",
            lambda **_kw: {"source": "mock-sample", "items": [{"id": "f"}]},
        )
        result = await execute_capability(
            {"limit": 5},
            capability_id="workorders",
        )
        # even with the env flag set, non-live data must stay blocked
        assert result.source_status == "failed"
        assert result.rows in (None, [])


class TestFriendlyFailureMessage:
    async def test_cli_trace_collapsed_for_screen(self) -> None:
        cli_text = (
            "未指定日志数据源 ID。请通过 --datasource <id> 传入，"
            "或在 .env 里设置 N9E_LOG_DATASOURCE_ID。"
        )
        result = await execute_capability(
            {},
            descriptor=_descriptor(
                lambda _p: {
                    "sourceStatus": "unavailable",
                    "source": "zhiguan-log-service",
                    "message": cli_text,
                },
            ),
        )
        assert result.source_status == "failed"
        assert "--datasource" not in result.message
        assert ".env" not in result.message
        assert "数据源暂不可用" in result.message
        assert "zhiguan-log-service" in result.message

    async def test_business_message_passes_through(self) -> None:
        result = await execute_capability(
            {},
            descriptor=_descriptor(
                lambda _p: {
                    "sourceStatus": "unavailable",
                    "message": "工单能力未返回实时来源，已阻断展示。",
                },
            ),
        )
        assert result.message == "工单能力未返回实时来源，已阻断展示。"

    async def test_exception_with_cli_marker_collapsed(self) -> None:
        def _boom(_p: Mapping[str, Any]) -> dict[str, Any]:
            raise RuntimeError("请通过 --token 传入凭据")

        result = await execute_capability({}, descriptor=_descriptor(_boom))
        assert "--token" not in result.message
        assert "数据源暂不可用" in result.message

    async def test_connection_timeout_repr_collapsed(self) -> None:
        # the exact shape that leaked to a live screen: a wrapped
        # requests/urllib3 connection chain
        def _boom(_p: Mapping[str, Any]) -> dict[str, Any]:
            raise RuntimeError(
                "ConnectTimeout: HTTPConnectionPool(host='172.28.75.4',"
                " port=30080): Max retries exceeded with url:"
                " /flowable/workflow/workOrder/getWorkOrder",
            )

        result = await execute_capability({}, descriptor=_descriptor(_boom))
        assert result.source_status == "failed"
        assert "HTTPConnectionPool" not in result.message
        assert "172.28.75.4" not in result.message
        assert "数据源连接超时" in result.message
        assert "刷新重试" in result.message

    async def test_connection_refused_repr_collapsed(self) -> None:
        def _boom(_p: Mapping[str, Any]) -> dict[str, Any]:
            raise OSError("Connection refused by host 10.0.0.1")

        result = await execute_capability({}, descriptor=_descriptor(_boom))
        assert "Connection refused" not in result.message
        assert "数据源暂不可用" in result.message

    async def test_friendly_timeout_message_passes_through(self) -> None:
        result = await execute_capability(
            {},
            descriptor=_descriptor(
                lambda _p: {
                    "sourceStatus": "unavailable",
                    "message": "请求超时，请稍后重试或缩小时间范围",
                },
            ),
        )
        assert result.message == "请求超时，请稍后重试或缩小时间范围"


class TestTtlCache:
    @staticmethod
    def _ttl_descriptor(fetcher: Any, ttl: float) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            id="ttl-cap",
            display_name="TTL 能力",
            domain="test",
            fetcher=fetcher,
            timeout_seconds=5.0,
            metadata={"id": "ttl-cap", "cachePolicy": {"ttlSeconds": ttl}},
        )

    async def test_cross_request_hit_within_ttl(self) -> None:
        calls: list[int] = []

        def _fetcher(_p: Mapping[str, Any]) -> dict[str, Any]:
            calls.append(1)
            return {"rows": [{"n": len(calls)}]}

        descriptor = self._ttl_descriptor(_fetcher, ttl=60)
        first = await execute_capability({"q": 1}, descriptor=descriptor)
        second = await execute_capability({"q": 1}, descriptor=descriptor)
        assert len(calls) == 1  # second served from TTL cache
        assert first.rows == second.rows

    async def test_expired_entry_refetches(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import time as time_module

        calls: list[int] = []

        def _fetcher(_p: Mapping[str, Any]) -> dict[str, Any]:
            calls.append(1)
            return {"rows": []}

        descriptor = self._ttl_descriptor(_fetcher, ttl=10)
        base = time_module.monotonic()
        await execute_capability({}, descriptor=descriptor)
        monkeypatch.setattr(
            "qwenpaw.extensions.ai_big_screen.capabilities.time.monotonic",
            lambda: base + 99,
        )
        await execute_capability({}, descriptor=descriptor)
        assert len(calls) == 2

    async def test_failed_results_not_cached(self) -> None:
        state = {"fail": True}

        def _fetcher(_p: Mapping[str, Any]) -> dict[str, Any]:
            if state["fail"]:
                raise ConnectionError("down")
            return {"rows": [{"ok": 1}]}

        descriptor = self._ttl_descriptor(_fetcher, ttl=60)
        first = await execute_capability({}, descriptor=descriptor)
        assert first.source_status == "failed"
        state["fail"] = False
        second = await execute_capability({}, descriptor=descriptor)
        assert second.source_status == "live"  # 恢复立即可见

    async def test_zero_ttl_never_caches(self) -> None:
        calls: list[int] = []

        def _fetcher(_p: Mapping[str, Any]) -> dict[str, Any]:
            calls.append(1)
            return {"rows": []}

        descriptor = self._ttl_descriptor(_fetcher, ttl=0)
        await execute_capability({}, descriptor=descriptor)
        await execute_capability({}, descriptor=descriptor)
        assert len(calls) == 2


class TestConcurrency:
    async def test_parallel_execution_shares_cache(self) -> None:
        calls: list[int] = []

        def _fetcher(_params: Mapping[str, Any]) -> dict[str, Any]:
            calls.append(1)
            return {"rows": [{"a": 1}]}

        descriptor = _descriptor(_fetcher)
        cache = CapabilityCache()
        results = await asyncio.gather(
            *(
                execute_capability(
                    {"limit": 1},
                    descriptor=descriptor,
                    cache=cache,
                )
                for _ in range(5)
            ),
        )
        assert all(r.source_status == "live" for r in results)
        assert len(calls) == 1


def test_registry_is_importable_without_heavy_modules() -> None:
    """Descriptor metadata must be importable without integrations."""
    assert capabilities.get_descriptor("system-logs") is not None
