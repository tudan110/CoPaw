# -*- coding: utf-8 -*-
"""Unit tests for the big-screen Veops application query (T-031)."""

from __future__ import annotations

from typing import Any

import pytest

from qwenpaw.extensions.integrations.zgops_cmdb import application_query

_CONFIG = {
    "INOE_API_BASE_URL": "http://gateway.example:8080",
    "INOE_API_TOKEN": "inoe-token",
}


class TestResolveConfig:
    def test_environ_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in _CONFIG.items():
            monkeypatch.setenv(key, value)
        assert application_query._resolve_config() == _CONFIG


class TestQueryApplicationCis:
    @pytest.fixture(autouse=True)
    def _configured_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in _CONFIG.items():
            monkeypatch.setenv(key, value)

    def test_unconfigured_returns_error_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("INOE_API_TOKEN")
        payload = application_query.query_application_cis()
        assert payload["source"] == "error"
        assert payload["items"] == []
        assert "平台" in payload["message"]

    def test_live_search_returns_items(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[tuple[str, str]] = []

        def _fake_request(url: str, **kwargs: Any) -> Any:
            calls.append((url, str(kwargs.get("token") or "")))
            assert kwargs.get("token") == "inoe-token"
            assert "/cmdb/api/v0.1/ci/s" in url
            assert "q=_type:project" in url
            assert "count=50" in url
            return {"numfound": 1, "result": [{"_id": 7954}]}

        monkeypatch.setattr(application_query, "_request_json", _fake_request)
        payload = application_query.query_application_cis(limit=50)
        assert len(calls) == 1
        assert payload["source"] == "live"
        assert payload["total"] == 1
        assert payload["items"] == [{"_id": 7954}]

    def test_empty_result_is_empty_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _fake_request(url: str, **_kwargs: Any) -> Any:
            return {"numfound": 0, "result": []}

        monkeypatch.setattr(application_query, "_request_json", _fake_request)
        payload = application_query.query_application_cis()
        assert payload["source"] == "empty"
        assert "暂无应用系统记录" in payload["message"]

    def test_transport_failure_is_error_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom(url: str, **_kwargs: Any) -> Any:
            raise TimeoutError("slow link")

        monkeypatch.setattr(application_query, "_request_json", _boom)
        payload = application_query.query_application_cis()
        assert payload["source"] == "error"
        assert "TimeoutError" in payload["message"]

    def test_missing_token_is_error_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("INOE_API_TOKEN")
        payload = application_query.query_application_cis()
        assert payload["source"] == "error"
        assert "平台" in payload["message"]

    def test_limit_is_clamped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, str] = {}

        def _fake_request(url: str, **_kwargs: Any) -> Any:
            seen["url"] = url
            return {"numfound": 0, "result": []}

        monkeypatch.setattr(application_query, "_request_json", _fake_request)
        application_query.query_application_cis(limit=9999)
        assert "count=500" in seen["url"]
