# -*- coding: utf-8 -*-
"""Unit tests for the big-screen Veops application query (T-031)."""

from __future__ import annotations

from typing import Any

import pytest

from qwenpaw.extensions.integrations.zgops_cmdb import application_query

_CONFIG = {
    "ZGOPS_BASE_URL": "http://cmdb.example:31089",
    "ZGOPS_USERNAME": "user",
    "ZGOPS_PASSWORD": "pass",
}


class TestResolveConfig:
    def test_environ_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in _CONFIG.items():
            monkeypatch.setenv(key, value)
        assert application_query._resolve_config() == _CONFIG

    def test_env_file_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        for key in _CONFIG:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
        secrets = tmp_path / "secrets"
        secrets.mkdir()
        (secrets / "zgops-cmdb.env").write_text(
            "# comment\n"
            "ZGOPS_BASE_URL=http://cmdb.example:31089\n"
            'ZGOPS_USERNAME="user"\n'
            "ZGOPS_PASSWORD='pass'\n",
            encoding="utf-8",
        )
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
        monkeypatch.delenv("ZGOPS_BASE_URL")
        monkeypatch.setenv("QWENPAW_WORKING_DIR", "/nonexistent-t031")
        payload = application_query.query_application_cis()
        assert payload["source"] == "error"
        assert payload["items"] == []
        assert "CMDB / 资源导入" in payload["message"]

    def test_live_search_returns_items(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[tuple[str, str]] = []

        def _fake_request(url: str, **kwargs: Any) -> Any:
            calls.append((url, str(kwargs.get("token") or "")))
            if url.endswith("/api/v1/acl/login"):
                return {"token": "tok-1"}
            assert kwargs.get("token") == "tok-1"
            assert "q=_type:project" in url
            assert "count=50" in url
            return {"numfound": 1, "result": [{"_id": 7954}]}

        monkeypatch.setattr(application_query, "_request_json", _fake_request)
        payload = application_query.query_application_cis(limit=50)
        assert len(calls) == 2
        assert payload["source"] == "live"
        assert payload["total"] == 1
        assert payload["items"] == [{"_id": 7954}]

    def test_empty_result_is_empty_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _fake_request(url: str, **_kwargs: Any) -> Any:
            if url.endswith("/api/v1/acl/login"):
                return {"token": "tok"}
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
        monkeypatch.setattr(
            application_query,
            "_request_json",
            lambda url, **_kwargs: {},
        )
        payload = application_query.query_application_cis()
        assert payload["source"] == "error"
        assert "RuntimeError" in payload["message"]

    def test_limit_is_clamped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, str] = {}

        def _fake_request(url: str, **_kwargs: Any) -> Any:
            if url.endswith("/api/v1/acl/login"):
                return {"token": "tok"}
            seen["url"] = url
            return {"numfound": 0, "result": []}

        monkeypatch.setattr(application_query, "_request_json", _fake_request)
        application_query.query_application_cis(limit=9999)
        assert "count=500" in seen["url"]
