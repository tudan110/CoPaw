# -*- coding: utf-8 -*-
"""Unit tests for the OAuth2 SSO signing helpers and settings store.

The signature must match the IdP's reference implementation byte-for-byte
(``docs/sso/Oauth2SignDemo.java``): non-empty params joined as
``key=value&key=value`` in key order, then HMAC-SHA256(secret) as lowercase
hex. The known-good hash below was produced independently with
``openssl dgst -sha256 -hmac``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.api import sso_settings_store as store
from qwenpaw.extensions.api.sso_backend import (
    _canonical,
    _cookie_token_from_header,
    _extract_user,
    _get_request_cookie,
    _sign,
    router,
)

_SECRET = "CGQlJs*Z@&X@a"


def test_canonical_sorts_and_drops_empty() -> None:
    params = {
        "clientId": "ndai",
        "code": "76471f74764f4ae0aeec108ad5250dd7",
        "redirectUri": "https://extsysA.example.com/sso/callback",
        "timestamp": "1782800000000",
        "nonce": "2f8c1e7a8b5d4e2f9012ab34cd56ef78",
        "scope": "",        # empty -> dropped
        "state": None,      # None -> dropped
    }
    assert _canonical(params) == (
        "clientId=ndai"
        "&code=76471f74764f4ae0aeec108ad5250dd7"
        "&nonce=2f8c1e7a8b5d4e2f9012ab34cd56ef78"
        "&redirectUri=https://extsysA.example.com/sso/callback"
        "&timestamp=1782800000000"
    )


def test_canonical_matches_doc_authorize_example() -> None:
    # The exact ordered string from OAuth2-单点登录对接文档.md §3.
    params = {
        "clientId": "extsysA",
        "redirectUri": "https://extsysA.example.com/sso/callback",
        "phonenumber": "15888888888",
        "scope": "basic",
        "state": "xyz123",
        "timestamp": "1782800000000",
        "nonce": "2f8c1e7a8b5d4e2f9012ab34cd56ef78",
    }
    assert _canonical(params) == (
        "clientId=extsysA"
        "&nonce=2f8c1e7a8b5d4e2f9012ab34cd56ef78"
        "&phonenumber=15888888888"
        "&redirectUri=https://extsysA.example.com/sso/callback"
        "&scope=basic"
        "&state=xyz123"
        "&timestamp=1782800000000"
    )


def test_sign_matches_known_good_openssl_hash() -> None:
    params = {
        "clientId": "ndai",
        "code": "76471f74764f4ae0aeec108ad5250dd7",
        "redirectUri": "https://extsysA.example.com/sso/callback",
        "timestamp": "1782800000000",
        "nonce": "2f8c1e7a8b5d4e2f9012ab34cd56ef78",
    }
    # Independently computed: printf '%s' "<canonical>" |
    #   openssl dgst -sha256 -hmac 'CGQlJs*Z@&X@a'
    assert _sign(params, _SECRET) == (
        "3a5d4648465cbcb5f3c61b4f4f36e166dbc3f8cc67da91cd2ab92efc4c7f2fc1"
    )


def test_sign_is_lowercase_hex_64() -> None:
    sign = _sign({"a": "1"}, _SECRET)
    assert len(sign) == 64
    assert sign == sign.lower()
    assert all(c in "0123456789abcdef" for c in sign)


# ---------------------------------------------------------------------------
# Settings store
# ---------------------------------------------------------------------------


def _db(tmp_path: Path) -> Path:
    return tmp_path / "sso_settings.db"


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "QWENPAW_SSO_GATEWAY_BASE_URL",
        "QWENPAW_SSO_CLIENT_ID",
        "QWENPAW_SSO_CLIENT_SECRET",
        "QWENPAW_SSO_REDIRECT_URI",
        "INOE_API_BASE_URL",
    ):
        monkeypatch.delenv(var, False)


def test_gateway_derives_from_inoe_then_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    # No SSO override -> derived from the platform INOE gateway + /auth/oauth2
    # (here the INOE hard-coded default, since no INOE override/env either).
    assert store.get_gateway_base_url(db_path=db) == (
        "http://gateway:8080/auth/oauth2"
    )
    # Change the platform INOE gateway -> SSO base follows it.
    monkeypatch.setenv("INOE_API_BASE_URL", "http://gw:30080/")
    assert store.get_gateway_base_url(db_path=db) == (
        "http://gw:30080/auth/oauth2"
    )
    # Explicit SSO override wins (e.g. nginx /prod-api path).
    monkeypatch.setenv(
        "QWENPAW_SSO_GATEWAY_BASE_URL",
        "http://host/prod-api/auth/oauth2/",
    )
    assert store.get_gateway_base_url(db_path=db) == (
        "http://host/prod-api/auth/oauth2"
    )


def test_authorization_code_configured_needs_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    # Gateway derives from INOE, but the (unused) code flow also needs client
    # creds, so is_configured stays False until they're supplied.
    assert store.is_configured(db_path=db) is False
    monkeypatch.setenv("QWENPAW_SSO_CLIENT_ID", "ndai")
    monkeypatch.setenv("QWENPAW_SSO_CLIENT_SECRET", _SECRET)
    assert store.get_client_id(db_path=db) == "ndai"
    assert store.get_client_secret(db_path=db) == _SECRET
    assert store.is_configured(db_path=db) is True
    # Page override wins over env.
    store.set_overrides({"sso_client_id": "other"}, db_path=db)
    assert store.get_client_id(db_path=db) == "other"


def test_payload_masks_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    store.set_overrides({"sso_client_secret": "supersecretvalue"}, db_path=db)
    payload = store.build_settings_payload(db_path=db)
    secret_eff = payload["effective"]["sso_client_secret"]
    assert secret_eff["is_set"] is True
    assert "supersecretvalue" not in str(payload)
    assert secret_eff["masked"].endswith("alue")


def test_apply_update_empty_secret_is_noop_and_clear_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    store.apply_settings_update({"sso_client_secret": "abc123"}, db_path=db)
    assert store.get_client_secret(db_path=db) == "abc123"
    # Empty string keeps the stored secret untouched.
    store.apply_settings_update({"sso_client_secret": ""}, db_path=db)
    assert store.get_client_secret(db_path=db) == "abc123"
    # CLEAR_SENTINEL deletes the override.
    store.apply_settings_update(
        {"sso_client_secret": store.CLEAR_SENTINEL}, db_path=db
    )
    assert store.has_override("sso_client_secret", db_path=db) is False


def test_apply_update_rejects_unknown_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        store.apply_settings_update({"nope": "x"}, db_path=db)
    # Sanity: store is reachable and isolated to tmp db.
    assert settings_store.get_namespace("sso", db_path=db) == {}


def test_userinfo_url_derives_and_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.delenv("QWENPAW_SSO_USERINFO_PATH", False)
    monkeypatch.setenv("INOE_API_BASE_URL", "http://gw:30080/")
    # Default path joined to the INOE gateway *root* (not /auth/oauth2).
    assert store.get_userinfo_url(db_path=db) == (
        "http://gw:30080/admin/user/getInfo"
    )
    assert store.is_token_login_ready(db_path=db) is True
    # Switching to the documented OAuth2 userinfo path.
    store.set_overrides(
        {"sso_userinfo_path": "/auth/oauth2/userinfo"}, db_path=db
    )
    assert store.get_userinfo_url(db_path=db) == (
        "http://gw:30080/auth/oauth2/userinfo"
    )
    # An absolute URL override is taken verbatim.
    store.set_overrides(
        {"sso_userinfo_path": "https://idp.example.com/userinfo"}, db_path=db
    )
    assert store.get_userinfo_url(db_path=db) == (
        "https://idp.example.com/userinfo"
    )


def test_extract_user_ruoyi_getinfo_drops_secrets() -> None:
    # Shape returned by INOE's /admin/user/getInfo (truncated).
    body = {
        "code": 200,
        "roles": ["admin"],
        "permissions": ["*:*:*"],
        "user": {
            "userId": 1,
            "userName": "zhiguan",
            "nickName": "智观",
            "phonenumber": "189*****999",
            "deptId": "1",
            "email": "",
            "password": "$2a$10$hash",
            "dept": {"deptId": 1},
        },
    }
    user = _extract_user(body)
    assert user == {
        "userId": 1,
        "username": "zhiguan",
        "nickName": "智观",
        "phonenumber": "189*****999",
        "deptId": "1",
    }
    # The whitelist is the security boundary — no secrets leak through.
    assert "password" not in user
    assert "roles" not in user and "dept" not in user


def test_extract_user_flat_oauth2_userinfo() -> None:
    # Shape from the documented OAuth2 /userinfo (flat, username spelling).
    body = {
        "userId": "7",
        "username": "lisi",
        "nickName": "李四",
        "phonenumber": "15800000000",
        "deptId": "100",
        "email": "lisi@example.com",
    }
    assert _extract_user(body) == body


def test_cookie_token_from_header_extracts_target_cookie() -> None:
    raw_cookie = (
        "username=zhiguan; "
        "Cnos-Inoe-Admin-Expires-In=720; "
        "Cnos-Inoe-Admin-Token=fresh-token; sidebarStatus=1"
    )
    assert _cookie_token_from_header(raw_cookie, "Cnos-Inoe-Admin-Token") == (
        "fresh-token"
    )
    assert _cookie_token_from_header(raw_cookie, "missing") == ""


def test_get_request_cookie_falls_back_to_raw_cookie_header() -> None:
    app = FastAPI()

    @app.get("/cookie")
    async def cookie_echo(request):
        return {
            "token": _get_request_cookie(request, "Cnos-Inoe-Admin-Token"),
            "expires": _get_request_cookie(
                request, "Cnos-Inoe-Admin-Expires-In"
            ),
        }

    client = TestClient(app)
    response = client.get(
        "/cookie",
        headers={
            "Cookie": (
                "username=zhiguan; "
                "Cnos-Inoe-Admin-Expires-In=720; "
                "Cnos-Inoe-Admin-Token=fresh-token; sidebarStatus=1"
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "token": "fresh-token",
        "expires": "720",
    }


@pytest.fixture()
def sso_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = _db(tmp_path)
    monkeypatch.setattr(store, "DEFAULT_DB_PATH", db)
    monkeypatch.setattr(settings_store, "DEFAULT_DB_PATH", db)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_token_login_retries_cookie_when_body_token_is_stale(
    sso_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INOE_API_BASE_URL", "http://gw:30080")

    async def fake_get_json(url: str, token: str, *, endpoint: str):
        assert url == "http://gw:30080/admin/user/getInfo"
        assert endpoint == "userinfo"
        if token == "stale-token":
            return {"code": 401, "msg": "登录状态已过期"}
        if token == "fresh-token":
            return {
                "code": 200,
                "user": {
                    "userId": 1,
                    "userName": "zhiguan",
                },
            }
        pytest.fail(f"unexpected token: {token}")

    monkeypatch.setattr(
        "qwenpaw.extensions.api.sso_backend._get_json", fake_get_json
    )

    response = sso_client.post(
        "/sso/token-login",
        json={"token": "stale-token"},
        cookies={
            "Cnos-Inoe-Admin-Token": "fresh-token",
            "Cnos-Inoe-Admin-Expires-In": "720",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "fresh-token",
        "token_type": "Bearer",
        "expires_in_seconds": 43200,
        "user": {
            "userId": 1,
            "username": "zhiguan",
        },
    }


def test_token_login_keeps_cookie_fallback_disabled_when_same_token(
    sso_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INOE_API_BASE_URL", "http://gw:30080")
    seen: list[str] = []

    async def fake_get_json(url: str, token: str, *, endpoint: str):
        seen.append(token)
        return {"code": 401, "msg": "登录状态已过期"}

    monkeypatch.setattr(
        "qwenpaw.extensions.api.sso_backend._get_json", fake_get_json
    )

    response = sso_client.post(
        "/sso/token-login",
        json={"token": "same-token"},
        cookies={
            "Cnos-Inoe-Admin-Token": "same-token",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "登录状态已过期"}
    assert seen == ["same-token"]
