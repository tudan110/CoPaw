# -*- coding: utf-8 -*-
"""OpenAI-style adapter routes for the Qiming completion endpoint."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

router = APIRouter(prefix="/qiming-adapter/v1", tags=["qiming-adapter"])

_DEFAULT_COMPLETIONS_PATH = "/serviceAgent/rest/wsc/completions"
_DEFAULT_MODEL_ID = "qiming25_72b_fc"
_DEFAULT_TIMEOUT_SECONDS = 300.0


def _read_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _read_timeout_seconds() -> float:
    raw = _read_env(
        "QWENPAW_QIMING_TIMEOUT_SECONDS",
        "COPAW_QIMING_TIMEOUT_SECONDS",
        default=str(_DEFAULT_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Qiming adapter timeout configuration.",
        ) from exc
    if timeout <= 0:
        raise HTTPException(
            status_code=500,
            detail="Qiming adapter timeout must be greater than 0.",
        )
    return timeout


def _configured_model_ids() -> list[str]:
    raw = _read_env(
        "QWENPAW_QIMING_MODELS",
        "COPAW_QIMING_MODELS",
        default=_DEFAULT_MODEL_ID,
    )
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return models or [_DEFAULT_MODEL_ID]


def _resolve_upstream_url() -> str:
    explicit_url = _read_env(
        "QWENPAW_QIMING_COMPLETIONS_URL",
        "COPAW_QIMING_COMPLETIONS_URL",
    )
    if explicit_url:
        return explicit_url

    base_url = _read_env(
        "QWENPAW_QIMING_BASE_URL",
        "COPAW_QIMING_BASE_URL",
    ).rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "Qiming adapter is not configured. "
                "Set QWENPAW_QIMING_BASE_URL or "
                "QWENPAW_QIMING_COMPLETIONS_URL."
            ),
        )

    path = _read_env(
        "QWENPAW_QIMING_COMPLETIONS_PATH",
        "COPAW_QIMING_COMPLETIONS_PATH",
        default=_DEFAULT_COMPLETIONS_PATH,
    ).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base_url}{path}"


def _resolve_authorization(request: Request) -> str:
    inbound = (request.headers.get("Authorization") or "").strip()
    if inbound:
        return inbound

    token = _read_env(
        "QWENPAW_QIMING_BEARER_TOKEN",
        "COPAW_QIMING_BEARER_TOKEN",
    )
    if not token:
        return ""
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def _build_upstream_headers(request: Request) -> dict[str, str]:
    app_id = _read_env("QWENPAW_QIMING_APP_ID", "COPAW_QIMING_APP_ID")
    app_key = _read_env("QWENPAW_QIMING_APP_KEY", "COPAW_QIMING_APP_KEY")
    if not app_id or not app_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Qiming adapter is not configured. "
                "Set QWENPAW_QIMING_APP_ID and QWENPAW_QIMING_APP_KEY."
            ),
        )

    headers = {
        "Content-Type": "application/json",
        "X-APP-ID": app_id,
        "X-APP-KEY": app_key,
    }
    authorization = _resolve_authorization(request)
    if authorization:
        headers["Authorization"] = authorization
    return headers


def _normalize_message_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content

    texts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            return content
        item_type = str(item.get("type", "text")).strip().lower()
        if item_type != "text":
            return content
        text = item.get("text")
        if text is None:
            continue
        texts.append(str(text))
    return "\n".join(texts)


def _normalize_request_body(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        return normalized

    messages: list[dict[str, Any]] = []
    for message in raw_messages:
        if not isinstance(message, dict):
            messages.append(message)
            continue
        item = dict(message)
        item["content"] = _normalize_message_content(item.get("content"))
        messages.append(item)
    normalized["messages"] = messages
    return normalized


def _response_media_type(headers: httpx.Headers, default: str) -> str:
    return headers.get("content-type", default)


@router.get("/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "qiming-adapter",
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
                "owned_by": "qiming-adapter",
            }
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")


async def _proxy_non_streaming_completion(
    upstream_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> Response:
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.post(
                upstream_url,
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Qiming upstream request timed out.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to Qiming upstream: {exc}",
        ) from exc

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=_response_media_type(response.headers, "application/json"),
    )


async def _proxy_streaming_completion(
    upstream_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> Response:
    try:
        client = httpx.AsyncClient(
            timeout=timeout_seconds,
            trust_env=False,
        )
        request = client.build_request(
            "POST",
            upstream_url,
            headers=headers,
            json=payload,
        )
        response = await client.send(request, stream=True)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Qiming upstream streaming request timed out.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to Qiming upstream: {exc}",
        ) from exc

    if response.status_code >= 400:
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        return Response(
            content=body,
            status_code=response.status_code,
            media_type=_response_media_type(response.headers, "application/json"),
        )

    async def _iter_body():
        try:
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        _iter_body(),
        status_code=response.status_code,
        media_type=_response_media_type(response.headers, "text/event-stream"),
    )


@router.post("/chat/completions")
async def create_chat_completions(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Response:
    upstream_url = _resolve_upstream_url()
    headers = _build_upstream_headers(request)
    normalized_payload = _normalize_request_body(payload)
    timeout_seconds = _read_timeout_seconds()
    if normalized_payload.get("stream"):
        return await _proxy_streaming_completion(
            upstream_url,
            headers,
            normalized_payload,
            timeout_seconds,
        )
    return await _proxy_non_streaming_completion(
        upstream_url,
        headers,
        normalized_payload,
        timeout_seconds,
    )
