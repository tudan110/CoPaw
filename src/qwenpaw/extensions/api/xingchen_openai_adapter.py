# -*- coding: utf-8 -*-
"""OpenAI-style adapter routes for the Xingchen telechat endpoint."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

router = APIRouter(prefix="/xingchen-adapter/v1", tags=["xingchen-adapter"])

_DEFAULT_CHAT_PATH = "/aipaas/lm/v1/telechat/chat115b"
_DEFAULT_MODEL_ID = "telechat-115b"
_DEFAULT_TIMEOUT_SECONDS = 300.0
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SECONDS = 1.0
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TOOL_RETRY_THRESHOLD = 5


def _read_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _read_timeout_seconds() -> float:
    raw = _read_env(
        "QWENPAW_XINGCHEN_TIMEOUT_SECONDS",
        "COPAW_XINGCHEN_TIMEOUT_SECONDS",
        default=str(_DEFAULT_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Xingchen adapter timeout configuration.",
        ) from exc
    if timeout <= 0:
        raise HTTPException(
            status_code=500,
            detail="Xingchen adapter timeout must be greater than 0.",
        )
    return timeout


def _configured_model_ids() -> list[str]:
    raw = _read_env(
        "QWENPAW_XINGCHEN_MODELS",
        "COPAW_XINGCHEN_MODELS",
        default=_DEFAULT_MODEL_ID,
    )
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return models or [_DEFAULT_MODEL_ID]


def _read_retry_attempts() -> int:
    raw = _read_env(
        "QWENPAW_XINGCHEN_RETRY_ATTEMPTS",
        "COPAW_XINGCHEN_RETRY_ATTEMPTS",
        default=str(_DEFAULT_RETRY_ATTEMPTS),
    )
    try:
        attempts = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Xingchen adapter retry attempts configuration.",
        ) from exc
    return max(1, attempts)


def _read_retry_delay_seconds() -> float:
    raw = _read_env(
        "QWENPAW_XINGCHEN_RETRY_DELAY_SECONDS",
        "COPAW_XINGCHEN_RETRY_DELAY_SECONDS",
        default=str(_DEFAULT_RETRY_DELAY_SECONDS),
    )
    try:
        delay = float(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Xingchen adapter retry delay configuration.",
        ) from exc
    return max(0.0, delay)


def _read_default_max_tokens() -> int:
    raw = _read_env(
        "QWENPAW_XINGCHEN_DEFAULT_MAX_TOKENS",
        "COPAW_XINGCHEN_DEFAULT_MAX_TOKENS",
        default=str(_DEFAULT_MAX_TOKENS),
    )
    try:
        max_tokens = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Xingchen adapter default max tokens configuration.",
        ) from exc
    if max_tokens <= 0:
        raise HTTPException(
            status_code=500,
            detail="Xingchen adapter default max tokens must be greater than 0.",
        )
    return max_tokens


def _resolve_upstream_url() -> str:
    explicit_url = _read_env(
        "QWENPAW_XINGCHEN_CHAT_URL",
        "COPAW_XINGCHEN_CHAT_URL",
    )
    if explicit_url:
        return explicit_url

    base_url = _read_env(
        "QWENPAW_XINGCHEN_BASE_URL",
        "COPAW_XINGCHEN_BASE_URL",
    ).rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "Xingchen adapter is not configured. "
                "Set QWENPAW_XINGCHEN_BASE_URL or QWENPAW_XINGCHEN_CHAT_URL."
            ),
        )

    path = _read_env(
        "QWENPAW_XINGCHEN_CHAT_PATH",
        "COPAW_XINGCHEN_CHAT_PATH",
        default=_DEFAULT_CHAT_PATH,
    ).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base_url}{path}"


def _resolve_header_value(
    request: Request,
    header_name: str,
    *env_names: str,
) -> str:
    inbound = (request.headers.get(header_name) or "").strip()
    if inbound:
        return inbound
    return _read_env(*env_names)


def _normalize_authorization(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return ""
    if normalized.lower().startswith("bearer "):
        normalized = normalized[7:].strip()
    return normalized


def _build_upstream_headers(request: Request) -> dict[str, str]:
    app_id = _resolve_header_value(
        request,
        "X-APP-ID",
        "QWENPAW_XINGCHEN_APP_ID",
        "COPAW_XINGCHEN_APP_ID",
    )
    order_num = _resolve_header_value(
        request,
        "Order-Num",
        "QWENPAW_XINGCHEN_ORDER_NUM",
        "COPAW_XINGCHEN_ORDER_NUM",
    )
    authorization = _normalize_authorization(
        _resolve_header_value(
            request,
            "Authorization",
            "QWENPAW_XINGCHEN_AUTHORIZATION",
            "COPAW_XINGCHEN_AUTHORIZATION",
        ),
    )
    if not app_id or not order_num or not authorization:
        raise HTTPException(
            status_code=503,
            detail=(
                "Xingchen adapter is not configured. "
                "Set QWENPAW_XINGCHEN_APP_ID, QWENPAW_XINGCHEN_ORDER_NUM, "
                "and QWENPAW_XINGCHEN_AUTHORIZATION."
            ),
        )

    return {
        "Content-Type": "application/json",
        "X-APP-ID": app_id,
        "Order-Num": order_num,
        "Authorization": authorization,
    }


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


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
        return value if value > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _normalize_request_body(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    completion_tokens = _coerce_positive_int(
        normalized.pop("max_completion_tokens", None),
    )
    max_tokens = _coerce_positive_int(normalized.get("max_tokens"))
    if max_tokens is None:
        normalized["max_tokens"] = completion_tokens or _read_default_max_tokens()
    else:
        normalized["max_tokens"] = max_tokens
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


def _tool_retry_threshold() -> int:
    raw = _read_env(
        "QWENPAW_XINGCHEN_TOOL_RETRY_THRESHOLD",
        "COPAW_XINGCHEN_TOOL_RETRY_THRESHOLD",
        default=str(_DEFAULT_TOOL_RETRY_THRESHOLD),
    )
    try:
        threshold = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid Xingchen adapter tool retry threshold configuration.",
        ) from exc
    return max(1, threshold)


def _should_retry_without_tools(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    return isinstance(tools, list) and len(tools) > _tool_retry_threshold()


def _payload_without_tools(payload: dict[str, Any]) -> dict[str, Any]:
    retried = dict(payload)
    retried.pop("tools", None)
    retried.pop("tool_choice", None)
    retried.pop("parallel_tool_calls", None)
    return retried


def _normalize_tool_call_arguments(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_response_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    choices = normalized.get("choices")
    if not isinstance(choices, list):
        return normalized

    next_choices: list[Any] = []
    for choice in choices:
        if not isinstance(choice, dict):
            next_choices.append(choice)
            continue
        next_choice = dict(choice)
        for field in ("message", "delta"):
            block = next_choice.get(field)
            if not isinstance(block, dict):
                continue
            next_block = dict(block)
            tool_calls = next_block.get("tool_calls")
            if isinstance(tool_calls, list):
                next_tool_calls: list[Any] = []
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        next_tool_calls.append(tool_call)
                        continue
                    next_tool_call = dict(tool_call)
                    function = next_tool_call.get("function")
                    if isinstance(function, dict) and "arguments" in function:
                        next_function = dict(function)
                        next_function["arguments"] = _normalize_tool_call_arguments(
                            function.get("arguments"),
                        )
                        next_tool_call["function"] = next_function
                    next_tool_calls.append(next_tool_call)
                next_block["tool_calls"] = next_tool_calls
            next_choice[field] = next_block
        next_choices.append(next_choice)
    normalized["choices"] = next_choices
    return normalized


def _extract_stream_content_fragments(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    fragments: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if text is not None:
            fragments.append(str(text))
    return fragments


def _payload_stream_signal(payload: Any) -> tuple[bool, list[str]]:
    if not isinstance(payload, dict):
        return False, []
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False, []

    saw_tool_signal = False
    fragments: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for field in ("message", "delta"):
            block = choice.get(field)
            if not isinstance(block, dict):
                continue
            tool_calls = block.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                saw_tool_signal = True
            fragments.extend(
                _extract_stream_content_fragments(block.get("content")),
            )
    return saw_tool_signal, fragments


def _strip_tool_call_markup(text: str) -> str:
    cleaned = text
    while True:
        start = cleaned.find("<tool_call>")
        if start < 0:
            break
        end = cleaned.find("</tool_call>", start)
        if end < 0:
            cleaned = cleaned[:start]
            break
        cleaned = cleaned[:start] + cleaned[end + len("</tool_call>") :]
    return cleaned.replace("<tool_call>", "").replace("</tool_call>", "")


def _has_meaningful_stream_text(text: str) -> bool:
    return bool(_strip_tool_call_markup(text).strip())


def _is_error_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and "code" in payload
        and "message" in payload
        and "choices" not in payload
    )


def _normalize_sse_line(line: str) -> tuple[bytes, Any | None]:
    if not line:
        return b"\n", None
    if not line.startswith("data: "):
        return f"{line}\n".encode("utf-8"), None

    data = line[6:]
    if data == "[DONE]":
        return b"data: [DONE]\n", None
    try:
        payload = json.loads(data)
    except ValueError:
        return f"{line}\n".encode("utf-8"), None
    payload = _normalize_response_payload(payload)
    return (
        f"data: {json.dumps(payload, ensure_ascii=False)}\n".encode("utf-8"),
        payload,
    )


def _encode_sse_error_event(payload: Any) -> bytes:
    return (
        f"data: {json.dumps({'error': payload}, ensure_ascii=False)}\n\n".encode(
            "utf-8",
        )
    )


def _build_sse_error_payload(body: bytes, fallback_message: str) -> Any:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"message": fallback_message}
    return parsed


@router.get("/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "xingchen-adapter",
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
                "owned_by": "xingchen-adapter",
            }
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")


async def _proxy_non_streaming_completion(
    upstream_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> Response:
    retry_attempts = _read_retry_attempts()
    retry_delay_seconds = _read_retry_delay_seconds()
    for attempt in range(retry_attempts):
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
                detail="Xingchen upstream request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to Xingchen upstream: {exc}",
            ) from exc
        if response.status_code != 429 or attempt >= retry_attempts - 1:
            break
        if retry_delay_seconds > 0:
            await asyncio.sleep(retry_delay_seconds * (attempt + 1))

    media_type = _response_media_type(response.headers, "application/json")
    if "json" not in media_type.lower():
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=media_type,
        )

    try:
        payload = response.json()
    except ValueError:
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=media_type,
        )

    payload = _normalize_response_payload(payload)
    status_code = response.status_code
    if status_code < 400 and _is_error_payload(payload):
        status_code = 400
    return Response(
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        status_code=status_code,
        media_type=media_type,
    )


async def _open_streaming_completion(
    upstream_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[httpx.AsyncClient, httpx.Response]:
    retry_attempts = _read_retry_attempts()
    retry_delay_seconds = _read_retry_delay_seconds()
    for attempt in range(retry_attempts):
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
                detail="Xingchen upstream streaming request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to Xingchen upstream: {exc}",
            ) from exc
        if response.status_code != 429 or attempt >= retry_attempts - 1:
            return client, response
        await response.aread()
        await response.aclose()
        await client.aclose()
        if retry_delay_seconds > 0:
            await asyncio.sleep(retry_delay_seconds * (attempt + 1))
    raise HTTPException(status_code=502, detail="Xingchen upstream request failed.")


async def _proxy_streaming_completion(
    upstream_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> Response:
    client, response = await _open_streaming_completion(
        upstream_url,
        headers,
        payload,
        timeout_seconds,
    )

    media_type = _response_media_type(response.headers, "text/event-stream")

    if response.status_code >= 400:
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        return Response(
            content=body,
            status_code=response.status_code,
            media_type=_response_media_type(response.headers, "application/json"),
        )

    if "event-stream" not in media_type.lower():
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return Response(
                content=body,
                status_code=response.status_code,
                media_type=media_type,
            )
        payload = _normalize_response_payload(payload)
        status_code = response.status_code
        if status_code < 400 and _is_error_payload(payload):
            status_code = 400
        return Response(
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            status_code=status_code,
            media_type="application/json",
        )

    async def _iter_body():
        buffered_chunks: list[bytes] = []
        saw_payload = False
        saw_tool_signal = False
        accumulated_text = ""
        stream_started = False
        try:
            async for line in response.aiter_lines():
                chunk, parsed_payload = _normalize_sse_line(line)
                if parsed_payload is not None:
                    saw_payload = True
                    tool_signal, fragments = _payload_stream_signal(parsed_payload)
                    saw_tool_signal = saw_tool_signal or tool_signal
                    if fragments:
                        accumulated_text += "".join(fragments)
                if stream_started:
                    yield chunk
                    continue
                buffered_chunks.append(chunk)
                if not _has_meaningful_stream_text(accumulated_text):
                    continue
                stream_started = True
                for buffered in buffered_chunks:
                    yield buffered
                buffered_chunks.clear()
        finally:
            await response.aclose()
            await client.aclose()

        if stream_started:
            return

        should_retry = _should_retry_without_tools(payload)
        if not should_retry:
            for buffered in buffered_chunks:
                yield buffered
            return

        retry_payload = _payload_without_tools(payload)
        retry_client, retry_response = await _open_streaming_completion(
            upstream_url,
            headers,
            retry_payload,
            timeout_seconds,
        )
        retry_media_type = _response_media_type(
            retry_response.headers,
            "text/event-stream",
        )
        try:
            if retry_response.status_code >= 400:
                body = await retry_response.aread()
                yield _encode_sse_error_event(
                    _build_sse_error_payload(
                        body,
                        "Xingchen retry without tools failed.",
                    ),
                )
                return
            if "event-stream" not in retry_media_type.lower():
                body = await retry_response.aread()
                yield _encode_sse_error_event(
                    _build_sse_error_payload(
                        body,
                        "Xingchen retry without tools returned a non-stream response.",
                    ),
                )
                return
            async for line in retry_response.aiter_lines():
                chunk, _ = _normalize_sse_line(line)
                yield chunk
        finally:
            await retry_response.aclose()
            await retry_client.aclose()

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
