# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.extensions.ai_big_screen import connection_status as cs


@pytest.fixture(autouse=True)
def _clear_conn_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "INOE_API_BASE_URL",
        "INOE_API_TOKEN",
        "N9E_API_BASE_URL",
        "N9E_USER_TOKEN",
        "ZGOPS_BASE_URL",
        "ZGOPS_USERNAME",
        "ZGOPS_PASSWORD",
        "ORDER_API_BASE_URL",
        "ORDER_AUTHORIZATION",
    ):
        monkeypatch.delenv(var, raising=False)


class TestInoe:
    def test_unconfigured_when_default_gateway(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("INOE_API_BASE_URL", "http://gateway:8080")
        monkeypatch.setenv("INOE_API_TOKEN", "tok")
        status = cs.connection_status("inoe")
        assert status["configured"] is False
        assert status["settingsTab"] == "inoe"
        assert "默认" in status["reason"] or "集群" in status["reason"]

    def test_unconfigured_when_no_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("INOE_API_BASE_URL", "http://82.156.83.38:30080")
        status = cs.connection_status("inoe")
        assert status["configured"] is False
        assert "token" in status["reason"]

    def test_configured_with_real_host_and_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("INOE_API_BASE_URL", "http://82.156.83.38:30080")
        monkeypatch.setenv("INOE_API_TOKEN", "tok")
        status = cs.connection_status("inoe")
        assert status["configured"] is True
        assert status["label"] == "INOE 网关"
        assert status["reason"] == ""


class TestOthers:
    def test_n9e_needs_base_and_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert cs.connection_status("n9e")["configured"] is False
        monkeypatch.setenv("N9E_API_BASE_URL", "http://10.1.2.3:17000")
        monkeypatch.setenv("N9E_USER_TOKEN", "t")
        assert cs.connection_status("n9e")["configured"] is True

    def test_zgops_needs_base_and_cred(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert cs.connection_status("zgops")["configured"] is False
        monkeypatch.setenv("ZGOPS_BASE_URL", "http://10.1.2.3:5000")
        monkeypatch.setenv("ZGOPS_USERNAME", "admin")
        assert cs.connection_status("zgops")["configured"] is True

    def test_empty_and_web_always_configured(self) -> None:
        assert cs.connection_status("")["configured"] is True
        assert cs.connection_status("web")["configured"] is True

    def test_skill_uses_underlying_inoe(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # a skill capability inherits the inoe connection health
        assert (
            cs.connection_status("skill:inspection:inspection-analyst")[
                "configured"
            ]
            is False
        )
        monkeypatch.setenv("INOE_API_BASE_URL", "http://82.156.83.38:30080")
        monkeypatch.setenv("INOE_API_TOKEN", "tok")
        assert (
            cs.connection_status("skill:inspection:inspection-analyst")[
                "configured"
            ]
            is True
        )

    def test_proxy_missing_datasource_unconfigured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        monkeypatch.setattr(svc, "get_datasource", lambda _did: None)
        status = cs.connection_status("proxy:nope")
        assert status["configured"] is False


class TestOrder:
    def test_own_ferry_config_is_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(
            "ORDER_API_BASE_URL", "http://192.168.132.66:30080/ferry"
        )
        monkeypatch.setenv("ORDER_AUTHORIZATION", "Bearer x")
        status = cs.connection_status("order")
        assert status["configured"] is True
        assert status["label"] == "工单 / ferry"
        assert status["settingsTab"] == "order"
        assert status["reason"] == ""

    def test_falls_back_to_inoe_when_order_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # no ORDER_*; but INOE is configured → fallback keeps it usable
        monkeypatch.setenv("INOE_API_BASE_URL", "http://82.156.83.38:30080")
        monkeypatch.setenv("INOE_API_TOKEN", "tok")
        status = cs.connection_status("order")
        assert status["configured"] is True
        assert "回退" in status["reason"]

    def test_unconfigured_when_neither_order_nor_inoe(self) -> None:
        status = cs.connection_status("order")
        assert status["configured"] is False
        assert status["settingsTab"] == "order"
        assert status["reason"]

    def test_own_ferry_ignores_placeholder_host(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # cluster-internal default host is not "configured" on its own,
        # and with no INOE fallback the connection is unconfigured
        monkeypatch.setenv("ORDER_API_BASE_URL", "http://gateway:8080/ferry")
        monkeypatch.setenv("ORDER_AUTHORIZATION", "Bearer x")
        status = cs.connection_status("order")
        assert status["configured"] is False
