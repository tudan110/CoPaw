# -*- coding: utf-8 -*-
"""Unit tests for the Kunlun open-gateway OpenAI adapter.

Covers: model listing, the OAuth2 client_credentials token flow (fetch,
cache, 401-triggered refresh), gateway header injection
(Authorization / X-Authorization / X-Client-Request-Id / X-Model-Id /
X-AI-User-Id / X-Client-Id), stream_options injection for streaming
requests, and unconfigured-adapter errors.
"""
from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.extensions.api import kunlun_openai_adapter as adapter
from qwenpaw.extensions.api.kunlun_openai_adapter import router

app = FastAPI()
app.include_router(router, prefix="/api/portal")

_ENVS = (
    "QWENPAW_KUNLUN_BASE_URL",
    "COPAW_KUNLUN_BASE_URL",
    "QWENPAW_KUNLUN_CHAT_PATH",
    "QWENPAW_KUNLUN_CHAT_URL",
    "QWENPAW_KUNLUN_AUTH_URL",
    "QWENPAW_KUNLUN_APP_CODE",
    "QWENPAW_KUNLUN_APP_SECRET",
    "QWENPAW_KUNLUN_SK_KEY",
    "COPAW_KUNLUN_SK_KEY",
    "QWENPAW_KUNLUN_MODELS",
    "QWENPAW_KUNLUN_MODEL_ID_HEADER",
    "QWENPAW_KUNLUN_CLIENT_ID",
    "QWENPAW_KUNLUN_AI_USER_ID",
    "QWENPAW_KUNLUN_VERIFY_SSL",
)


@pytest.fixture(autouse=True)
def _isolate_adapter_state(monkeypatch):
    """Keep tests hermetic: ignore any local settings-page DB overrides
    (the store would otherwise shadow the monkeypatched env vars) and
    reset the module-level token cache around every test."""
    monkeypatch.setattr(
        adapter.kunlun_settings_store,
        "resolve_text",
        lambda env_var, **kwargs: "",
    )
    for name in _ENVS:
        monkeypatch.delenv(name, raising=False)
    adapter.reset_token_cache()
    yield
    adapter.reset_token_cache()


def _configure_env(monkeypatch):
    monkeypatch.setenv("QWENPAW_KUNLUN_BASE_URL", "https://gw.example:21000")
    monkeypatch.setenv("QWENPAW_KUNLUN_APP_CODE", "app-code-1")
    monkeypatch.setenv("QWENPAW_KUNLUN_APP_SECRET", "app-secret-1")


def _patch_token(monkeypatch, token: str = "tok-1"):
    """Bypass the HTTP token fetch; count invocations."""
    calls: list[tuple[str, str, str]] = []

    async def _fake_fetch(auth_url, app_code, app_secret):
        calls.append((auth_url, app_code, app_secret))
        return f"{token}-{len(calls)}", time.monotonic() + 3600

    monkeypatch.setattr(adapter, "_fetch_token", _fake_fetch)
    return calls


async def _request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.request(method, path, **kwargs)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"{}",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}
        self.content = content

    async def aread(self) -> bytes:
        return self.content

    def json(self):
        return json.loads(self.content.decode("utf-8"))

    async def aiter_raw(self):
        yield self.content

    async def aclose(self) -> None:
        return None


class _FakePostClient:
    """Stands in for httpx.AsyncClient in the non-streaming path."""

    def __init__(self, recorder: dict, responses: list[_FakeResponse]):
        self._recorder = recorder
        self._responses = responses

    def __call__(self, *args, **kwargs):
        # Constructed per attempt: adapter calls httpx.AsyncClient(...).
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, headers, json):
        self._recorder.setdefault("requests", []).append(
            {"url": url, "headers": headers, "json": json},
        )
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


class _FakeStreamClient:
    """Stands in for httpx.AsyncClient in the streaming path."""

    def __init__(self, recorder: dict, responses: list[_FakeResponse]):
        self._recorder = recorder
        self._responses = responses

    def __call__(self, *args, **kwargs):
        return self

    def build_request(self, method, url, *, headers, json):
        self._recorder.setdefault("requests", []).append(
            {"method": method, "url": url, "headers": headers, "json": json},
        )
        return SimpleNamespace(method=method, url=url)

    async def send(self, request, *, stream: bool = False):
        self._recorder["send_stream"] = stream
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]

    async def aclose(self) -> None:
        self._recorder["closed"] = True


async def test_list_models_uses_kunlun_env_configuration(monkeypatch):
    monkeypatch.setenv("QWENPAW_KUNLUN_MODELS", "app_001,app_002")

    resp = await _request("GET", "/api/portal/kunlun-adapter/v1/models")

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["data"]] == [
        "app_001",
        "app_002",
    ]


async def test_chat_completions_fetches_token_and_injects_headers(
    monkeypatch,
):
    _configure_env(monkeypatch)
    token_calls = _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakePostClient(
        recorder,
        [_FakeResponse(content=b'{"choices": []}')],
    )
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={
            "model": "app_001",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 200
    # Token fetched once, with credentials + derived auth endpoint.
    assert token_calls == [
        (
            "https://gw.example:21000/kunlun-auth-service/oauth2/token",
            "app-code-1",
            "app-secret-1",
        ),
    ]
    request = recorder["requests"][0]
    assert request["url"] == (
        "https://gw.example:21000"
        "/api/chinatelecom/cnos/swdd/cpn/aiapp/v1/chat/completions"
    )
    headers = request["headers"]
    assert headers["Authorization"] == "Bearer tok-1-1"
    # 36 位 uuid 请求流水号.
    assert len(headers["X-Client-Request-Id"]) == 36
    uuid.UUID(headers["X-Client-Request-Id"])
    # X-Model-Id falls back to the request body's model.
    assert headers["X-Model-Id"] == "app_001"
    assert headers["X-AI-User-Id"] == "zhiguan"
    # No sk configured here → no backend credential header; no client id
    # unless configured (resolve_text is stubbed to "" in this fixture);
    # signature-family headers are gone (gateway confirmed not needed).
    assert "X-Authorization" not in headers
    assert "X-Client-Id" not in headers
    assert "Kunlun-Timestamp" not in headers
    assert "Kunlun-Nonc" not in headers
    assert "Kunlun-Sign" not in headers
    # Non-streaming requests are passed through unchanged.
    assert "stream_options" not in request["json"]


async def test_configured_gateway_ids_win_over_body_model(monkeypatch):
    _configure_env(monkeypatch)
    monkeypatch.setenv("QWENPAW_KUNLUN_MODEL_ID_HEADER", "app-real")
    monkeypatch.setenv("QWENPAW_KUNLUN_CLIENT_ID", "platform-9")
    monkeypatch.setenv("QWENPAW_KUNLUN_AI_USER_ID", "ops-user")
    _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakePostClient(recorder, [_FakeResponse()])
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={"model": "app_001", "messages": []},
    )

    assert resp.status_code == 200
    headers = recorder["requests"][0]["headers"]
    assert headers["X-Model-Id"] == "app-real"
    assert headers["X-Client-Id"] == "platform-9"
    assert headers["X-AI-User-Id"] == "ops-user"


async def test_x_authorization_injected_when_sk_configured(monkeypatch):
    _configure_env(monkeypatch)
    monkeypatch.setenv("QWENPAW_KUNLUN_SK_KEY", "sk-proj-abc123")
    _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakePostClient(recorder, [_FakeResponse()])
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={"model": "app_001", "messages": []},
    )

    assert resp.status_code == 200
    headers = recorder["requests"][0]["headers"]
    # Backend sk credential rides in X-Authorization; the gateway JWT
    # stays in Authorization.
    assert headers["X-Authorization"] == "Bearer sk-proj-abc123"
    assert headers["Authorization"] == "Bearer tok-1-1"


async def test_x_authorization_tolerates_pasted_bearer_prefix(monkeypatch):
    _configure_env(monkeypatch)
    # A user who pastes the whole "Bearer sk-..." value must not produce a
    # doubled "Bearer Bearer" prefix on the wire.
    monkeypatch.setenv("QWENPAW_KUNLUN_SK_KEY", "Bearer sk-proj-abc123")
    _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakePostClient(recorder, [_FakeResponse()])
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={"model": "app_001", "messages": []},
    )

    assert resp.status_code == 200
    headers = recorder["requests"][0]["headers"]
    assert headers["X-Authorization"] == "Bearer sk-proj-abc123"


async def test_token_cached_across_requests(monkeypatch):
    _configure_env(monkeypatch)
    token_calls = _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakePostClient(recorder, [_FakeResponse()])
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    for _ in range(2):
        resp = await _request(
            "POST",
            "/api/portal/kunlun-adapter/v1/chat/completions",
            json={"model": "app_001", "messages": []},
        )
        assert resp.status_code == 200

    assert len(token_calls) == 1
    tokens = {
        item["headers"]["Authorization"] for item in recorder["requests"]
    }
    assert tokens == {"Bearer tok-1-1"}


async def test_upstream_401_refreshes_token_and_retries(monkeypatch):
    _configure_env(monkeypatch)
    token_calls = _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakePostClient(
        recorder,
        [
            _FakeResponse(status_code=401, content=b'{"error": "expired"}'),
            _FakeResponse(content=b'{"choices": []}'),
        ],
    )
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={"model": "app_001", "messages": []},
    )

    assert resp.status_code == 200
    # Initial fetch + forced refresh after the 401.
    assert len(token_calls) == 2
    sent = [item["headers"]["Authorization"] for item in recorder["requests"]]
    assert sent == ["Bearer tok-1-1", "Bearer tok-1-2"]


async def test_streaming_injects_stream_options_and_passes_through(
    monkeypatch,
):
    _configure_env(monkeypatch)
    _patch_token(monkeypatch)
    recorder: dict = {}
    sse_body = (
        b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    fake = _FakeStreamClient(
        recorder,
        [
            _FakeResponse(
                headers={"content-type": "text/event-stream"},
                content=sse_body,
            ),
        ],
    )
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={"model": "app_001", "messages": [], "stream": True},
    )

    assert resp.status_code == 200
    assert resp.content == sse_body
    request = recorder["requests"][0]
    # 订阅要求 stream=true 时必须携带 stream_options.include_usage.
    assert request["json"]["stream_options"] == {"include_usage": True}
    assert recorder["send_stream"] is True
    assert recorder["closed"] is True


async def test_streaming_respects_caller_stream_options(monkeypatch):
    _configure_env(monkeypatch)
    _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakeStreamClient(
        recorder,
        [
            _FakeResponse(
                headers={"content-type": "text/event-stream"},
                content=b"data: [DONE]\n\n",
            ),
        ],
    )
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={
            "model": "app_001",
            "messages": [],
            "stream": True,
            "stream_options": {"include_usage": False},
        },
    )

    assert resp.status_code == 200
    request = recorder["requests"][0]
    assert request["json"]["stream_options"] == {"include_usage": False}


async def test_missing_credentials_returns_503(monkeypatch):
    monkeypatch.setenv("QWENPAW_KUNLUN_BASE_URL", "https://gw.example:21000")

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={"model": "app_001", "messages": []},
    )

    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


async def test_upstream_error_body_passes_through(monkeypatch):
    _configure_env(monkeypatch)
    _patch_token(monkeypatch)
    recorder: dict = {}
    fake = _FakePostClient(
        recorder,
        [
            _FakeResponse(
                status_code=403,
                content=b'{"message": "no subscription"}',
            ),
        ],
    )
    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake)

    resp = await _request(
        "POST",
        "/api/portal/kunlun-adapter/v1/chat/completions",
        json={"model": "app_001", "messages": []},
    )

    assert resp.status_code == 403
    assert resp.json() == {"message": "no subscription"}
