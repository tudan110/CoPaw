# -*- coding: utf-8 -*-
"""Portal-side OAuth2 single-sign-on with the INOE auth gateway (IdP).

The browser handoff works like this:

1. The user is logged into INOE and clicks the portal entry. INOE (which
   knows the logged-in user's phone number) mints a one-time authorization
   ``code`` and 302-redirects the browser to ``<portal>/sso/callback?code=…``.
2. The portal frontend hands that ``code`` to :func:`exchange` here.
3. This module signs a ``/token`` request (HMAC-SHA256 over the canonical
   param string, per the IdP contract), exchanges the ``code`` for the
   IdP's access token, then reads ``/userinfo`` with it.

The phone number never travels through the browser, and the ``client_secret``
never leaves the backend — it is only used to compute the signature. See
``docs/sso/OAuth2-单点登录对接文档.md`` for the wire contract and
``docs/sso/Oauth2SignDemo.java`` for the reference signing implementation.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request

from qwenpaw.extensions.api import sso_settings_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sso", tags=["sso"])

# The IdP enforces a ±60s window on the request timestamp, so the outbound
# call must be quick. Keep the timeout tight but tolerant of a slow gateway.
_HTTP_TIMEOUT_SECONDS = 15.0

# ``expires_in`` from the token endpoint is in MINUTES (a quirk of the IdP,
# documented in the contract), not the OAuth2-standard seconds.
_EXPIRES_IN_UNIT_SECONDS = 60

# The login token INOE drops in the browser after sign-in. In the "token
# pass-through" flow the user is already logged into INOE, so we reuse this
# token directly: the frontend forwards it (or, when portal shares INOE's
# hostname, the browser sends this cookie automatically) and we validate it
# against /userinfo. No phone number, no authorization code, no signing.
_INOE_LOGIN_COOKIE = "Cnos-Inoe-Admin-Token"

# INOE drops this alongside the token cookie at login — the same
# ``expires_in`` (minutes) its native /login response carries. Only trust it
# as an anchor at the moment we first see a given token (see setSession() on
# the frontend, which keeps the previously-computed deadline instead of
# re-deriving it on every revalidation) — INOE does not refresh this cookie
# as time passes, so re-reading it later and treating it as "N minutes from
# now" would keep pushing the deadline out indefinitely.
_INOE_EXPIRES_IN_COOKIE = "Cnos-Inoe-Admin-Expires-In"


def _canonical(params: dict[str, str]) -> str:
    """Join non-empty params as ``key=value&key=value`` sorted by key asc.

    Matches ``Oauth2SignDemo.canonical``: a ``TreeMap`` iterated in key
    order, skipping null/empty values.
    """
    items = sorted(
        (k, v) for k, v in params.items() if v is not None and v != ""
    )
    return "&".join(f"{k}={v}" for k, v in items)


def _sign(params: dict[str, str], secret: str) -> str:
    """HMAC-SHA256 of the canonical string, returned as lowercase hex."""
    canonical = _canonical(params)
    digest = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return digest.hex()


def _now_ms() -> str:
    # Imported lazily so the module stays import-safe under the workflow
    # sandbox (which forbids argless time/date at import time elsewhere).
    import time

    return str(int(time.time() * 1000))


async def _exchange_code_for_token(
    *,
    base_url: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    """POST ``/token``: trade the one-time code for the IdP access token."""
    signed: dict[str, str] = {
        "clientId": client_id,
        "code": code,
        "timestamp": _now_ms(),
        "nonce": uuid.uuid4().hex,
    }
    # redirectUri only participates when configured; if present at /authorize
    # time it must match here and be part of the signature.
    if redirect_uri:
        signed["redirectUri"] = redirect_uri
    sign = _sign(signed, client_secret)

    payload = {
        "grantType": "authorization_code",
        **signed,
        "sign": sign,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.post(f"{base_url}/token", json=payload)
    return _parse_idp_response(resp, endpoint="token")


async def _get_json(
    url: str, token: str, *, endpoint: str
) -> dict[str, Any]:
    """GET ``url`` with a Bearer token, returning the parsed JSON body."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers=headers)
    return _parse_idp_response(resp, endpoint=endpoint)


async def _fetch_userinfo(
    *, base_url: str, access_token: str
) -> dict[str, Any]:
    """GET ``/userinfo`` (authorization-code flow)."""
    return await _get_json(
        f"{base_url}/userinfo", access_token, endpoint="userinfo"
    )


def _parse_idp_response(
    resp: httpx.Response, *, endpoint: str
) -> dict[str, Any]:
    """Return the JSON body on success; raise HTTPException on IdP error.

    The IdP returns the RFC-6749 error body ``{error, error_description}``
    on failure. We surface ``error_description`` (never the secret) and keep
    the upstream status code so the frontend can tell the user what to do.
    """
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.is_success:
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=502,
                detail=f"SSO {endpoint} 返回了非预期的响应",
            )
        return body
    detail = ""
    if isinstance(body, dict):
        detail = str(
            body.get("error_description") or body.get("error") or ""
        ).strip()
    detail = detail or f"SSO {endpoint} 调用失败 (HTTP {resp.status_code})"
    # Map upstream 5xx to 502 (bad gateway) but keep client errors as-is.
    status = resp.status_code if resp.status_code < 500 else 502
    raise HTTPException(status_code=status, detail=detail)


def _extract_user(body: dict[str, Any]) -> dict[str, Any]:
    """Pull the whitelisted user fields, tolerant of both response shapes.

    INOE's getInfo wraps the user in ``{"code":200,"user":{...}}`` with
    RuoYi field names (``userName``); the OAuth2 ``/userinfo`` is flat
    (``username``). We read from the nested object when present and accept
    either spelling. The whitelist is the security boundary: it drops
    getInfo's ``password`` hash, ``roles``, ``dept`` and anything else, so
    only these six fields ever reach the browser.
    """
    src = body.get("user") if isinstance(body.get("user"), dict) else body

    def pick(*keys: str) -> Any:
        for key in keys:
            value = src.get(key)
            if value not in (None, ""):
                return value
        return None

    user = {
        "userId": pick("userId", "user_id"),
        "username": pick("username", "userName"),
        "nickName": pick("nickName", "nick_name"),
        "phonenumber": pick("phonenumber", "phone"),
        "deptId": pick("deptId", "dept_id"),
        "email": pick("email"),
    }
    return {key: value for key, value in user.items() if value is not None}


@router.get("/status")
async def sso_status() -> dict[str, Any]:
    """Whether the backend is ready to log a user in. No secrets exposed.

    ``configured`` is the token-passthrough readiness — it only needs the
    gateway base URL (to call /userinfo). ``authorization_code_ready`` adds
    the client credentials required by the (currently unused) code flow.
    """
    return {
        "configured": sso_settings_store.is_token_login_ready(),
        "authorization_code_ready": sso_settings_store.is_configured(),
    }


@router.post("/token-login")
async def token_login(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Log in by validating an existing INOE login token (token pass-through).

    The token is taken from the request body (``{"token": "..."}``) or, when
    portal shares INOE's hostname, from the ``Cnos-Inoe-Admin-Token`` cookie
    the browser sends automatically. We validate it against ``/userinfo`` —
    a success both proves the token is genuine and yields the user. Returns
    the same shape as :func:`exchange` so the frontend treats both uniformly.
    """
    token = str(body.get("token") or "").strip()
    if not token:
        token = (request.cookies.get(_INOE_LOGIN_COOKIE) or "").strip()
    if token.lower().startswith("bearer "):
        token = token[len("bearer ") :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="缺少 INOE 登录凭证")

    userinfo_url = sso_settings_store.get_userinfo_url()
    if not userinfo_url:
        raise HTTPException(
            status_code=400, detail="SSO 未配置(平台 INOE 网关地址缺失)"
        )

    try:
        user_body = await _get_json(userinfo_url, token, endpoint="userinfo")
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="SSO 网关请求超时")
    except httpx.HTTPError as exc:
        logger.warning("SSO 网关连接失败: %s", exc)
        raise HTTPException(status_code=502, detail="SSO 网关连接失败")

    # RuoYi getInfo replies HTTP 200 even on an invalid token, signalling the
    # real status in the body ``code`` (e.g. 401 令牌不能为空). Treat any
    # non-200 body code as an auth failure.
    body_code = user_body.get("code")
    if body_code is not None and str(body_code) != "200":
        raise HTTPException(
            status_code=401,
            detail=str(user_body.get("msg") or "INOE 登录态校验失败"),
        )

    user = _extract_user(user_body)
    if not (user.get("userId") or user.get("username")):
        raise HTTPException(
            status_code=401, detail="未能从 INOE 获取用户信息,token 可能已失效"
        )
    try:
        expires_in_minutes = float(
            request.cookies.get(_INOE_EXPIRES_IN_COOKIE) or 0
        )
    except (TypeError, ValueError):
        expires_in_minutes = 0.0
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in_seconds": int(expires_in_minutes * _EXPIRES_IN_UNIT_SECONDS),
        "user": user,
    }


@router.post("/exchange")
async def exchange(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Exchange an authorization ``code`` for portal login material.

    Body: ``{"code": "...", "state": "..."}``. Returns
    ``{access_token, token_type, expires_in_seconds, user}``. The frontend
    stores this as its login state.
    """
    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少授权码 code")

    base_url = sso_settings_store.get_gateway_base_url()
    client_id = sso_settings_store.get_client_id()
    client_secret = sso_settings_store.get_client_secret()
    redirect_uri = sso_settings_store.get_redirect_uri()
    if not (base_url and client_id and client_secret):
        raise HTTPException(
            status_code=400,
            detail="SSO 未配置(网关地址 / client_id / client_secret 缺失)",
        )

    try:
        token_body = await _exchange_code_for_token(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
        access_token = str(token_body.get("access_token") or "").strip()
        if not access_token:
            raise HTTPException(
                status_code=502, detail="SSO token 响应缺少 access_token"
            )
        user_body = await _fetch_userinfo(
            base_url=base_url, access_token=access_token
        )
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="SSO 网关请求超时")
    except httpx.HTTPError as exc:
        logger.warning("SSO 网关连接失败: %s", exc)
        raise HTTPException(status_code=502, detail="SSO 网关连接失败")

    try:
        expires_in_minutes = float(token_body.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in_minutes = 0.0
    expires_in_seconds = int(expires_in_minutes * _EXPIRES_IN_UNIT_SECONDS)
    return {
        "access_token": access_token,
        "token_type": str(token_body.get("token_type") or "Bearer"),
        "expires_in_seconds": expires_in_seconds,
        "scope": token_body.get("scope"),
        "user": _extract_user(user_body),
    }


# ---------------------------------------------------------------------------
# Settings API: /sso/sso-settings GET/PUT + reset (mirrors inoe-settings)
# ---------------------------------------------------------------------------


@router.get("/sso-settings")
async def get_sso_settings() -> dict[str, Any]:
    """Return SSO credentials as ``{effective, env, overrides}``.

    The client secret is masked in both layers.
    """
    return sso_settings_store.build_settings_payload()


@router.put("/sso-settings")
async def put_sso_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the SSO credentials.

    Page values win over env. The secret left empty keeps the stored value;
    sending ``sso_settings_store.CLEAR_SENTINEL`` clears it.
    """
    try:
        sso_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return sso_settings_store.build_settings_payload()


@router.post("/sso-settings/reset")
async def reset_sso_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one SSO field's override so it falls back to env/default.

    Body: ``{"key": "<field>"}``.
    """
    key = str(body.get("key") or "").strip()
    try:
        sso_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return sso_settings_store.build_settings_payload()
