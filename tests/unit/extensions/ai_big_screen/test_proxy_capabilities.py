# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen.capabilities import (
    execute_capability,
    get_descriptor,
    list_capability_metadata,
    proxy_capabilities,
)
from qwenpaw.extensions.api.proxy_datasource_models import (
    BigScreenBinding,
    BigScreenField,
    BigScreenParam,
    DatasourceConfig,
)


def _cfg(**overrides: Any) -> DatasourceConfig:
    base: dict[str, Any] = {
        "id": "inspect",
        "name": "巡检指标",
        "description": "系统巡检指标查询",
        "url_template": "http://172.28.75.4:30080/inspect/{resId}",
        "method": "GET",
        "big_screen": BigScreenBinding(
            enabled=True,
            domain="inspection",
            rows_path="data.items",
            value_path="data.total",
            unit="项",
            fields=[
                BigScreenField(key="metric", label="指标"),
                BigScreenField(key="value", label="值"),
            ],
            params=[
                BigScreenParam(name="resId", required=True, default=""),
            ],
            example_prompts=["巡检 7953 的指标"],
        ),
    }
    base.update(overrides)
    return DatasourceConfig.model_validate(base)


def _patch_one(monkeypatch: pytest.MonkeyPatch, cfg: DatasourceConfig) -> None:
    from qwenpaw.extensions.api import proxy_datasource_service as svc

    monkeypatch.setattr(svc, "list_bigscreen_datasources", lambda: [cfg])
    monkeypatch.setattr(
        svc,
        "get_datasource",
        lambda did: cfg if did == cfg.id else None,
    )


class TestDiscovery:
    def test_discover_exposes_capability_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_one(monkeypatch, _cfg())
        metas = proxy_capabilities.discover_proxy_capabilities()
        assert len(metas) == 1
        meta = metas[0]
        assert meta["id"] == "proxy:inspect"
        assert meta["domain"] == "inspection"
        assert {f["key"] for f in meta["availableFields"]} == {
            "metric",
            "value",
        }
        # supported visuals are all real D-max types
        assert "table" in meta["supportedVisuals"]

    def test_listed_in_catalog_and_resolvable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_one(monkeypatch, _cfg())
        catalog_ids = {m["id"] for m in list_capability_metadata()}
        assert "proxy:inspect" in catalog_ids
        # private keys are stripped from the catalog
        meta = next(
            m for m in list_capability_metadata() if m["id"] == "proxy:inspect"
        )
        assert "_proxyParamNames" not in meta
        descriptor = get_descriptor("proxy:inspect")
        assert descriptor is not None
        assert descriptor.domain == "inspection"

    def test_unknown_proxy_id_resolves_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        monkeypatch.setattr(svc, "get_datasource", lambda _did: None)
        assert get_descriptor("proxy:nope") is None


class TestFetchMapping:
    def test_maps_rows_and_value_from_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = _cfg()
        _patch_one(monkeypatch, cfg)
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        monkeypatch.setattr(
            svc,
            "execute_datasource_request",
            lambda _cfg, _params: {
                "status_code": 200,
                "json": {
                    "data": {
                        "total": 2,
                        "items": [
                            {"metric": "cpu", "value": 88},
                            {"metric": "mem", "value": 91},
                        ],
                    },
                },
            },
        )
        out = proxy_capabilities.fetch_proxy_capability(
            "proxy:inspect",
            {"resId": "7953"},
        )
        assert out["sourceStatus"] == "live"
        assert out["value"] == 2
        assert out["unit"] == "项"
        assert len(out["rows"]) == 2
        assert out["rows"][0]["metric"] == "cpu"
        assert {c["key"] for c in out["columns"]} == {"metric", "value"}

    def test_empty_when_no_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = _cfg()
        _patch_one(monkeypatch, cfg)
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        monkeypatch.setattr(
            svc,
            "execute_datasource_request",
            lambda _cfg, _params: {
                "status_code": 200,
                "json": {"data": {"total": 0, "items": []}},
            },
        )
        out = proxy_capabilities.fetch_proxy_capability("proxy:inspect", {})
        assert out["sourceStatus"] == "empty"

    def test_http_error_is_failed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = _cfg()
        _patch_one(monkeypatch, cfg)
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        monkeypatch.setattr(
            svc,
            "execute_datasource_request",
            lambda _cfg, _params: {"status_code": 503, "json": None},
        )
        out = proxy_capabilities.fetch_proxy_capability("proxy:inspect", {})
        assert out["sourceStatus"] == "failed"
        assert "503" in out["message"]

    def test_only_declared_params_forwarded(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = _cfg()
        _patch_one(monkeypatch, cfg)
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        captured: dict[str, Any] = {}

        def _exec(_cfg: Any, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"status_code": 200, "json": {"data": {"items": []}}}

        monkeypatch.setattr(svc, "execute_datasource_request", _exec)
        proxy_capabilities.fetch_proxy_capability(
            "proxy:inspect",
            {"resId": "7953", "evil": "drop-me"},
        )
        assert captured == {"resId": "7953"}  # 'evil' filtered out


class TestExecuteCapabilityEndToEnd:
    async def test_execute_capability_resolves_proxy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = _cfg()
        _patch_one(monkeypatch, cfg)
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        monkeypatch.setattr(
            svc,
            "execute_datasource_request",
            lambda _cfg, _params: {
                "status_code": 200,
                "json": {"data": {"total": 1, "items": [{"metric": "x"}]}},
            },
        )
        result = await execute_capability(
            {"resId": "1"},
            capability_id="proxy:inspect",
        )
        assert result.source_status == "live"
        assert result.rows and result.rows[0]["metric"] == "x"


class TestServiceHostLock:
    def test_path_param_cannot_escape_locked_host(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from qwenpaw.extensions.api import proxy_datasource_service as svc

        from urllib.parse import urlparse

        called: dict[str, Any] = {}

        class _Client:
            def __init__(self, *_a: Any, **_k: Any) -> None:
                pass

            def __enter__(self) -> "_Client":
                return self

            def __exit__(self, *_a: Any) -> None:
                return None

            def request(self, *, url: str, **_k: Any) -> Any:
                called["url"] = url

                class _R:
                    status_code = 200

                    def json(self) -> dict[str, Any]:
                        return {}

                    text = ""

                return _R()

        monkeypatch.setattr(httpx, "Client", _Client)
        cfg = _cfg(url_template="http://172.28.75.4:30080/x/{path}")
        # even a hostile-looking path param stays on the operator host
        svc.execute_datasource_request(cfg, {"path": "@evil.example.com"})
        assert urlparse(called["url"]).netloc == "172.28.75.4:30080"

    def test_host_placeholder_rejected(self) -> None:
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        cfg = _cfg(url_template="http://{host}/x")
        with pytest.raises(RuntimeError):
            svc.execute_datasource_request(cfg, {"host": "10.0.0.1"})

    def test_happy_path_calls_locked_host(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx

        from qwenpaw.extensions.api import proxy_datasource_service as svc

        called: dict[str, Any] = {}

        class _Resp:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"ok": True}

            text = ""

        class _Client:
            def __init__(self, *_a: Any, **_k: Any) -> None:
                pass

            def __enter__(self) -> "_Client":
                return self

            def __exit__(self, *_a: Any) -> None:
                return None

            def request(self, *, method: str, url: str, **_k: Any) -> _Resp:
                called["url"] = url
                called["method"] = method
                return _Resp()

        monkeypatch.setattr(httpx, "Client", _Client)
        cfg = _cfg(url_template="http://172.28.75.4:30080/inspect/{resId}")
        out = svc.execute_datasource_request(cfg, {"resId": "7953"})
        assert out["status_code"] == 200
        assert called["url"] == "http://172.28.75.4:30080/inspect/7953"
