# -*- coding: utf-8 -*-
"""OpenAI-style adapter routes for the Kunlun open-gateway LLM endpoint.

Fronts the 云算网智算统一网关 (subscription 1043177) chat-completions API
registered on the Kunlun capability-open-platform gateway. The upstream is
already OpenAI-compatible (``cryptEnable=false``, plain JSON), so this
adapter only has to solve auth + gateway headers:

* **Token** — OAuth2 ``client_credentials`` against the gateway's
  ``/kunlun-auth-service/oauth2/token`` endpoint with HTTP Basic
  ``appCode:appSecret`` (flow recovered from the official SDK and the
  decrypted ``deliverables.enc``). Tokens are cached and refreshed ahead
  of expiry; a 401 from the upstream forces one refresh + retry.
* **X-Authorization** — the backend model's own ``sk-proj-*`` credential,
  sent as ``X-Authorization: Bearer <sk-key>`` alongside the gateway
  OAuth2 JWT in ``Authorization``. The APISIX gateway rewrites it into
  the upstream's expected ``Authorization: Bearer sk-...`` when
  forwarding. Confirmed working end-to-end (2026-07-07, HTTP 200 through
  the full chain). The key is a secret, resolved from
  ``QWENPAW_KUNLUN_SK_KEY`` (settings-page DB > env), never hard-coded.
* **定制请求头** — ``X-Client-Request-Id`` (uuid per request, trace id),
  plus configurable ``X-Model-Id`` / ``X-Client-Id`` / ``X-AI-User-Id``.
  The gateway team confirmed on 2026-07-07 that ``Kunlun-Sign`` /
  ``Kunlun-Nonc`` / ``Kunlun-Timestamp`` are not required, so no
  signature headers are sent.

Config resolves through :mod:`kunlun_settings_store`
(settings-page DB > ``QWENPAW_KUNLUN_*`` env > default).
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from qwenpaw.extensions.api import kunlun_settings_store

router = APIRouter(prefix="/kunlun-adapter/v1", tags=["kunlun-adapter"])

_DEFAULT_TIMEOUT_SECONDS = 300.0
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SECONDS = 1.0
# Refresh the cached token this long before it actually expires (the
# official SDK refreshes 5 minutes ahead).
_TOKEN_REFRESH_MARGIN_SECONDS = 300.0


def _read_env(*names: str, default: str = "") -> str:
    # Settings-page DB override > env (QWENPAW_/COPAW_) > default. The
    # store resolves the first (canonical QWENPAW_) name; unmodelled names
    # fall through to the legacy os.getenv loop below.
    if names:
        resolved = kunlun_settings_store.resolve_text(names[0])
        if resolved:
            return resolved
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _read_timeout_seconds() -> float:
    raw = _read_env(
        "QWENPAW_KUNLUN_TIMEOUT_SECONDS",
        "COPAW_KUNLUN_TIMEOUT_SECONDS",
        default=str(_DEFAULT_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Kunlun adapter timeout configuration.",
        ) from exc
    if timeout <= 0:
        raise HTTPException(
            status_code=500,
            detail="Kunlun adapter timeout must be greater than 0.",
        )
    return timeout


def _read_retry_attempts() -> int:
    raw = _read_env(
        "QWENPAW_KUNLUN_RETRY_ATTEMPTS",
        "COPAW_KUNLUN_RETRY_ATTEMPTS",
        default=str(_DEFAULT_RETRY_ATTEMPTS),
    )
    try:
        attempts = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Kunlun adapter retry attempts configuration.",
        ) from exc
    return max(1, attempts)


def _read_retry_delay_seconds() -> float:
    raw = _read_env(
        "QWENPAW_KUNLUN_RETRY_DELAY_SECONDS",
        "COPAW_KUNLUN_RETRY_DELAY_SECONDS",
        default=str(_DEFAULT_RETRY_DELAY_SECONDS),
    )
    try:
        delay = float(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Kunlun adapter retry delay configuration.",
        ) from exc
    return max(0.0, delay)


def _read_verify_ssl() -> bool:
    # The gateway serves an enterprise/self-signed certificate and the
    # official SDK hard-codes verify=False; default matches it.
    raw = _read_env(
        "QWENPAW_KUNLUN_VERIFY_SSL",
        "COPAW_KUNLUN_VERIFY_SSL",
        default="False",
    )
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _configured_model_ids() -> list[str]:
    raw = _read_env(
        "QWENPAW_KUNLUN_MODELS",
        "COPAW_KUNLUN_MODELS",
        default=kunlun_settings_store.DEFAULT_MODELS,
    )
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return models or [kunlun_settings_store.DEFAULT_MODELS]


def _resolve_base_url() -> str:
    return _read_env(
        "QWENPAW_KUNLUN_BASE_URL",
        "COPAW_KUNLUN_BASE_URL",
        default=kunlun_settings_store.DEFAULT_BASE_URL,
    ).rstrip("/")


def _resolve_upstream_url() -> str:
    explicit_url = _read_env(
        "QWENPAW_KUNLUN_CHAT_URL",
        "COPAW_KUNLUN_CHAT_URL",
    )
    if explicit_url:
        return explicit_url

    base_url = _resolve_base_url()
    if not base_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "Kunlun adapter is not configured. "
                "Set QWENPAW_KUNLUN_BASE_URL or QWENPAW_KUNLUN_CHAT_URL."
            ),
        )

    path = _read_env(
        "QWENPAW_KUNLUN_CHAT_PATH",
        "COPAW_KUNLUN_CHAT_PATH",
        default=kunlun_settings_store.DEFAULT_CHAT_PATH,
    ).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base_url}{path}"


def _resolve_auth_url() -> str:
    explicit_url = _read_env(
        "QWENPAW_KUNLUN_AUTH_URL",
        "COPAW_KUNLUN_AUTH_URL",
    )
    if explicit_url:
        return explicit_url
    base_url = _resolve_base_url()
    if not base_url:
        return ""
    return f"{base_url}{kunlun_settings_store.DEFAULT_AUTH_PATH}"


def _resolve_app_credentials() -> tuple[str, str]:
    app_code = _read_env(
        "QWENPAW_KUNLUN_APP_CODE",
        "COPAW_KUNLUN_APP_CODE",
    )
    app_secret = _read_env(
        "QWENPAW_KUNLUN_APP_SECRET",
        "COPAW_KUNLUN_APP_SECRET",
    )
    return app_code, app_secret


# ---------------------------------------------------------------------------
# OAuth2 client_credentials token cache
# ---------------------------------------------------------------------------

# Keyed by (auth_url, app_code) so editing credentials/URL on the settings
# page never serves a token minted for the previous configuration.
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}
_token_lock = asyncio.Lock()


def reset_token_cache() -> None:
    """Drop all cached tokens (test hook / forced refresh)."""
    _token_cache.clear()


async def _fetch_token(
    auth_url: str,
    app_code: str,
    app_secret: str,
) -> tuple[str, float]:
    timeout_seconds = _read_timeout_seconds()
    try:
        async with httpx.AsyncClient(
            timeout=min(timeout_seconds, 30.0),
            trust_env=False,
            verify=_read_verify_ssl(),
        ) as client:
            response = await client.post(
                auth_url,
                data={"grant_type": "client_credentials"},
                auth=(app_code, app_secret),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Kunlun token endpoint: {exc}",
        ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                "Kunlun token endpoint returned "
                f"{response.status_code}: {response.text[:200]}"
            ),
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Kunlun token endpoint returned a non-JSON body.",
        ) from exc
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise HTTPException(
            status_code=502,
            detail="Kunlun token endpoint returned no access_token.",
        )
    try:
        expires_in = float(payload.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600.0
    expires_at = time.monotonic() + max(
        expires_in - _TOKEN_REFRESH_MARGIN_SECONDS,
        30.0,
    )
    return token, expires_at


async def _get_token(*, force_refresh: bool = False) -> str:
    auth_url = _resolve_auth_url()
    app_code, app_secret = _resolve_app_credentials()
    if not auth_url or not app_code or not app_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "Kunlun adapter is not configured. Set "
                "QWENPAW_KUNLUN_APP_CODE and QWENPAW_KUNLUN_APP_SECRET "
                "(and QWENPAW_KUNLUN_BASE_URL / QWENPAW_KUNLUN_AUTH_URL)."
            ),
        )
    cache_key = (auth_url, app_code)
    async with _token_lock:
        if not force_refresh:
            cached = _token_cache.get(cache_key)
            if cached and cached[1] > time.monotonic():
                return cached[0]
        token, expires_at = await _fetch_token(
            auth_url,
            app_code,
            app_secret,
        )
        _token_cache[cache_key] = (token, expires_at)
        return token


# ---------------------------------------------------------------------------
# Request headers
# ---------------------------------------------------------------------------


def _format_bearer(raw: str) -> str:
    """Wrap a raw sk-key as ``Bearer <key>``, tolerating a pasted prefix.

    Users may paste either the bare key (``sk-proj-...``) or the whole
    ``Bearer sk-proj-...`` value into the settings page; store the bare
    key by convention but never emit a double ``Bearer Bearer`` prefix.
    """
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[len("bearer ") :].strip()
    return f"Bearer {raw}"


def _build_upstream_headers(
    request: Request,
    payload: dict[str, Any],
    token: str,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        # Gateway consumer auth (APISIX layer): the OAuth2 JWT.
        "Authorization": f"Bearer {token}",
        # 36 位 uuid 请求流水号 / trace id, per the subscription sheet.
        "X-Client-Request-Id": str(uuid.uuid4()),
    }

    # Backend model credential: the APISIX gateway rewrites
    # X-Authorization into the upstream's Authorization: Bearer sk-...
    # (mechanism verified 2026-07-07). Secret, resolved from settings.
    sk_key = _read_env(
        "QWENPAW_KUNLUN_SK_KEY",
        "COPAW_KUNLUN_SK_KEY",
    )
    if sk_key:
        headers["X-Authorization"] = _format_bearer(sk_key)

    model_id = (
        _read_env(
            "QWENPAW_KUNLUN_MODEL_ID_HEADER",
            "COPAW_KUNLUN_MODEL_ID_HEADER",
        )
        or str(payload.get("model") or "").strip()
    )
    if model_id:
        headers["X-Model-Id"] = model_id

    client_id = _read_env(
        "QWENPAW_KUNLUN_CLIENT_ID",
        "COPAW_KUNLUN_CLIENT_ID",
    )
    if client_id:
        headers["X-Client-Id"] = client_id

    ai_user_id = (request.headers.get("X-AI-User-Id") or "").strip()
    if not ai_user_id:
        ai_user_id = _read_env(
            "QWENPAW_KUNLUN_AI_USER_ID",
            "COPAW_KUNLUN_AI_USER_ID",
            default=kunlun_settings_store.DEFAULT_AI_USER_ID,
        )
    if ai_user_id:
        headers["X-AI-User-Id"] = ai_user_id

    return headers


def _normalize_request_body(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    # The subscription sheet marks stream_options as required whenever
    # stream=true (with {"include_usage": true} as the documented value).
    if normalized.get("stream") and not isinstance(
        normalized.get("stream_options"),
        dict,
    ):
        normalized["stream_options"] = {"include_usage": True}
    return normalized


def _response_media_type(headers: httpx.Headers, default: str) -> str:
    return headers.get("content-type", default)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "kunlun-adapter",
            }
            for model_id in _configured_model_ids()
        ],
    }


@router.get("/models/{model_id}")
async def get_model(model_id: str) -> dict[str, Any]:
    for configured_id in _configured_model_ids():
        if configured_id == model_id:
            return {
                "id": configured_id,
                "object": "model",
                "owned_by": "kunlun-adapter",
            }
    raise HTTPException(
        status_code=404,
        detail=f"Model '{model_id}' not found.",
    )


async def _proxy_non_streaming_completion(
    request: Request,
    upstream_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> Response:
    retry_attempts = _read_retry_attempts()
    retry_delay_seconds = _read_retry_delay_seconds()
    token = await _get_token()
    refreshed_token = False
    attempt = 0
    while True:
        headers = _build_upstream_headers(
            request,
            payload,
            token,
        )
        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds,
                trust_env=False,
                verify=_read_verify_ssl(),
            ) as client:
                response = await client.post(
                    upstream_url,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail="Kunlun upstream request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to Kunlun upstream: {exc}",
            ) from exc

        if response.status_code == 401 and not refreshed_token:
            # Token likely revoked/expired server-side: refresh once.
            token = await _get_token(force_refresh=True)
            refreshed_token = True
            continue
        if response.status_code == 429 and attempt < retry_attempts - 1:
            attempt += 1
            if retry_delay_seconds > 0:
                await asyncio.sleep(retry_delay_seconds * attempt)
            continue
        break

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=_response_media_type(
            response.headers,
            "application/json",
        ),
    )


async def _open_streaming_completion(
    request: Request,
    upstream_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[httpx.AsyncClient, httpx.Response]:
    retry_attempts = _read_retry_attempts()
    retry_delay_seconds = _read_retry_delay_seconds()
    token = await _get_token()
    refreshed_token = False
    attempt = 0
    while True:
        headers = _build_upstream_headers(
            request,
            payload,
            token,
        )
        client = httpx.AsyncClient(
            timeout=timeout_seconds,
            trust_env=False,
            verify=_read_verify_ssl(),
        )
        try:
            upstream_request = client.build_request(
                "POST",
                upstream_url,
                headers=headers,
                json=payload,
            )
            response = await client.send(upstream_request, stream=True)
        except httpx.TimeoutException as exc:
            await client.aclose()
            raise HTTPException(
                status_code=504,
                detail="Kunlun upstream streaming request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to Kunlun upstream: {exc}",
            ) from exc

        if response.status_code == 401 and not refreshed_token:
            await response.aread()
            await response.aclose()
            await client.aclose()
            token = await _get_token(force_refresh=True)
            refreshed_token = True
            continue
        if response.status_code == 429 and attempt < retry_attempts - 1:
            await response.aread()
            await response.aclose()
            await client.aclose()
            attempt += 1
            if retry_delay_seconds > 0:
                await asyncio.sleep(retry_delay_seconds * attempt)
            continue
        return client, response


async def _proxy_streaming_completion(
    request: Request,
    upstream_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> Response:
    client, response = await _open_streaming_completion(
        request,
        upstream_url,
        payload,
        timeout_seconds,
    )

    media_type = _response_media_type(response.headers, "text/event-stream")

    if response.status_code >= 400 or "event-stream" not in media_type.lower():
        # Error bodies (and any non-SSE fallback the gateway produces)
        # are small; read them fully and pass through unchanged.
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        return Response(
            content=body,
            status_code=response.status_code,
            media_type=_response_media_type(
                response.headers,
                "application/json",
            ),
        )

    async def _iter_body():
        # The upstream is OpenAI-compatible; stream bytes through verbatim.
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        _iter_body(),
        status_code=response.status_code,
        media_type=media_type,
    )


@router.post("/chat/completions")
async def create_chat_completions(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Response:
    upstream_url = _resolve_upstream_url()
    normalized_payload = _normalize_request_body(payload)
    timeout_seconds = _read_timeout_seconds()
    if normalized_payload.get("stream"):
        return await _proxy_streaming_completion(
            request,
            upstream_url,
            normalized_payload,
            timeout_seconds,
        )
    return await _proxy_non_streaming_completion(
        request,
        upstream_url,
        normalized_payload,
        timeout_seconds,
    )
