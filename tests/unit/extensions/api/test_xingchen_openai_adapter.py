# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.extensions.api.xingchen_openai_adapter import router

app = FastAPI()
app.include_router(router, prefix="/api/portal")


async def _request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
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

    async def aiter_bytes(self):
        yield self.content

    async def aiter_lines(self):
        for line in self.content.decode("utf-8").splitlines():
            yield line

    async def aclose(self) -> None:
        return None


class _FakePostClient:
    def __init__(self, recorder: dict[str, object], response: _FakeResponse) -> None:
        self._recorder = recorder
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
        self._recorder["url"] = url
        self._recorder["headers"] = headers
        self._recorder["json"] = json
        return self._response


class _FakeStreamClient:
    def __init__(
        self,
        recorder: dict[str, object],
        response: _FakeResponse | list[_FakeResponse],
    ) -> None:
        self._recorder = recorder
        self._responses = response if isinstance(response, list) else [response]
        self.closed = False

    def build_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ):
        self._recorder["method"] = method
        self._recorder["url"] = url
        self._recorder["headers"] = headers
        self._recorder["json"] = json
        return SimpleNamespace(
            method=method,
            url=url,
            headers=headers,
            json=json,
        )

    async def send(self, request, *, stream: bool = False):
        self._recorder["send_stream"] = stream
        self._recorder["request"] = request
        self._recorder.setdefault("requests", []).append(request)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]

    async def aclose(self) -> None:
        self.closed = True


async def test_list_models_uses_xingchen_env_configuration(monkeypatch):
    monkeypatch.setenv("QWENPAW_XINGCHEN_MODELS", "telechat-115b,telechat-13b")

    resp = await _request("GET", "/api/portal/xingchen-adapter/v1/models")

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["data"]] == [
        "telechat-115b",
        "telechat-13b",
    ]


async def test_chat_completions_injects_headers_and_normalizes_text_content(
    monkeypatch,
):
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_BASE_URL",
        "https://openapi.teleagi.cn:443",
    )
    monkeypatch.setenv("QWENPAW_XINGCHEN_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_XINGCHEN_ORDER_NUM", "order-001")

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        content=b'{"id":"chatcmpl-1","object":"chat.completion","choices":[]}',
    )

    monkeypatch.setattr(
        "qwenpaw.extensions.api.xingchen_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: _FakePostClient(recorder, fake_response),
    )

    resp = await _request(
        "POST",
        "/api/portal/xingchen-adapter/v1/chat/completions",
        headers={
            "Authorization": (
                "Bearer teleai-cloud-auth-v1/app-id/BJ/1778572215/"
                "999999/x-app-id/signature"
            )
        },
        json={
            "model": "telechat-115b",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "ping"}],
                }
            ],
            "max_completion_tokens": 123,
            "stream": False,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "chatcmpl-1"
    assert recorder["url"] == "https://openapi.teleagi.cn:443/aipaas/lm/v1/telechat/chat115b"
    assert recorder["headers"] == {
        "Content-Type": "application/json",
        "X-APP-ID": "app-id",
        "Order-Num": "order-001",
        "Authorization": "teleai-cloud-auth-v1/app-id/BJ/1778572215/999999/x-app-id/signature",
    }
    assert recorder["json"] == {
        "model": "telechat-115b",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 123,
        "stream": False,
    }


async def test_chat_completions_replaces_null_max_tokens(monkeypatch):
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_BASE_URL",
        "https://openapi.teleagi.cn:443",
    )
    monkeypatch.setenv("QWENPAW_XINGCHEN_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_XINGCHEN_ORDER_NUM", "order-001")

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        content=b'{"id":"chatcmpl-1","object":"chat.completion","choices":[]}',
    )

    monkeypatch.setattr(
        "qwenpaw.extensions.api.xingchen_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: _FakePostClient(recorder, fake_response),
    )

    resp = await _request(
        "POST",
        "/api/portal/xingchen-adapter/v1/chat/completions",
        headers={
            "Authorization": (
                "Bearer teleai-cloud-auth-v1/app-id/BJ/1778572215/"
                "999999/x-app-id/signature"
            )
        },
        json={
            "model": "telechat-115b",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": None,
            "max_completion_tokens": 123,
            "stream": False,
        },
    )

    assert resp.status_code == 200
    assert recorder["json"]["max_tokens"] == 123
    assert "max_completion_tokens" not in recorder["json"]


async def test_chat_completions_drops_max_completion_tokens_when_max_tokens_exists(
    monkeypatch,
):
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_BASE_URL",
        "https://openapi.teleagi.cn:443",
    )
    monkeypatch.setenv("QWENPAW_XINGCHEN_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_XINGCHEN_ORDER_NUM", "order-001")

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        content=b'{"id":"chatcmpl-1","object":"chat.completion","choices":[]}',
    )

    monkeypatch.setattr(
        "qwenpaw.extensions.api.xingchen_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: _FakePostClient(recorder, fake_response),
    )

    resp = await _request(
        "POST",
        "/api/portal/xingchen-adapter/v1/chat/completions",
        headers={
            "Authorization": (
                "Bearer teleai-cloud-auth-v1/app-id/BJ/1778572215/"
                "999999/x-app-id/signature"
            )
        },
        json={
            "model": "telechat-115b",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 32,
            "max_completion_tokens": 123,
            "stream": False,
        },
    )

    assert resp.status_code == 200
    assert recorder["json"]["max_tokens"] == 32
    assert "max_completion_tokens" not in recorder["json"]


async def test_chat_completions_adds_default_max_tokens_when_missing(monkeypatch):
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_BASE_URL",
        "https://openapi.teleagi.cn:443",
    )
    monkeypatch.setenv("QWENPAW_XINGCHEN_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_XINGCHEN_ORDER_NUM", "order-001")
    monkeypatch.setenv("QWENPAW_XINGCHEN_DEFAULT_MAX_TOKENS", "2048")

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        content=b'{"id":"chatcmpl-1","object":"chat.completion","choices":[]}',
    )

    monkeypatch.setattr(
        "qwenpaw.extensions.api.xingchen_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: _FakePostClient(recorder, fake_response),
    )

    resp = await _request(
        "POST",
        "/api/portal/xingchen-adapter/v1/chat/completions",
        headers={
            "Authorization": (
                "Bearer teleai-cloud-auth-v1/app-id/BJ/1778572215/"
                "999999/x-app-id/signature"
            )
        },
        json={
            "model": "telechat-115b",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
        },
    )

    assert resp.status_code == 200
    assert recorder["json"]["max_tokens"] == 2048


async def test_chat_completions_streaming_uses_xingchen_envs(monkeypatch):
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_CHAT_URL",
        "https://openapi.teleagi.cn:443/aipaas/lm/v1/telechat/chat115b",
    )
    monkeypatch.setenv("QWENPAW_XINGCHEN_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_XINGCHEN_ORDER_NUM", "order-001")
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_AUTHORIZATION",
        "teleai-cloud-auth-v1/app-id/BJ/1778572215/999999/x-app-id/signature",
    )

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        headers={"content-type": "text/event-stream"},
        content=(
            b'data: {"id":"chatcmpl-1","choices":[{"delta":{"tool_calls":[{"index":0,'
            b'"function":{"arguments":{"name":"db_mysql_001"}}}]}}]}\n\n'
            b"data: [DONE]\n\n"
        ),
    )
    fake_client = _FakeStreamClient(recorder, fake_response)

    monkeypatch.setattr(
        "qwenpaw.extensions.api.xingchen_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    resp = await _request(
        "POST",
        "/api/portal/xingchen-adapter/v1/chat/completions",
        json={
            "model": "telechat-115b",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert (
        'data: {"id": "chatcmpl-1", "choices": [{"delta": {"tool_calls": '
        '[{"index": 0, "function": {"arguments": "{\\"name\\":\\"db_mysql_001\\"}"}}]}}]}\n\n'
        "data: [DONE]\n\n"
    ) == resp.text
    assert recorder["send_stream"] is True
    assert recorder["json"]["max_tokens"] == 4096
    assert recorder["headers"] == {
        "Content-Type": "application/json",
        "X-APP-ID": "app-id",
        "Order-Num": "order-001",
        "Authorization": "teleai-cloud-auth-v1/app-id/BJ/1778572215/999999/x-app-id/signature",
    }
    assert fake_client.closed is True


async def test_chat_completions_streaming_surfaces_upstream_json_error(monkeypatch):
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_CHAT_URL",
        "https://openapi.teleagi.cn:443/aipaas/lm/v1/telechat/chat115b",
    )
    monkeypatch.setenv("QWENPAW_XINGCHEN_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_XINGCHEN_ORDER_NUM", "order-001")
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_AUTHORIZATION",
        "teleai-cloud-auth-v1/app-id/BJ/1778572215/999999/x-app-id/signature",
    )

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        headers={"content-type": "application/json"},
        content=b'{"code":"01110002","message":"Invalid request data: max_completion_tokens is unknow"}',
    )
    fake_client = _FakeStreamClient(recorder, fake_response)

    monkeypatch.setattr(
        "qwenpaw.extensions.api.xingchen_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    resp = await _request(
        "POST",
        "/api/portal/xingchen-adapter/v1/chat/completions",
        json={
            "model": "telechat-115b",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["message"] == "Invalid request data: max_completion_tokens is unknow"


async def test_chat_completions_streaming_retries_without_tools_when_tool_call_only(
    monkeypatch,
):
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_CHAT_URL",
        "https://openapi.teleagi.cn:443/aipaas/lm/v1/telechat/chat115b",
    )
    monkeypatch.setenv("QWENPAW_XINGCHEN_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_XINGCHEN_ORDER_NUM", "order-001")
    monkeypatch.setenv(
        "QWENPAW_XINGCHEN_AUTHORIZATION",
        "teleai-cloud-auth-v1/app-id/BJ/1778572215/999999/x-app-id/signature",
    )

    recorder: dict[str, object] = {}
    tool_call_only_response = _FakeResponse(
        headers={"content-type": "text/event-stream"},
        content=(
            (
                'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"<tool_call>\\n'
                '{\\"name\\":\\"tool_0\\",\\"arguments\\":{\\"query\\":\\"hello\\"}}\\n'
                '</tool_call>"}}]}\n\n'
                "data: [DONE]\n\n"
            ).encode("utf-8")
        ),
    )
    retry_response = _FakeResponse(
        headers={"content-type": "text/event-stream"},
        content=(
            b'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"hello"}}]}\n\n'
            b"data: [DONE]\n\n"
        ),
    )
    fake_client = _FakeStreamClient(
        recorder,
        [tool_call_only_response, retry_response],
    )

    monkeypatch.setattr(
        "qwenpaw.extensions.api.xingchen_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    resp = await _request(
        "POST",
        "/api/portal/xingchen-adapter/v1/chat/completions",
        json={
            "model": "telechat-115b",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {"type": "function", "function": {"name": f"tool_{idx}"}}
                for idx in range(6)
            ],
            "stream": True,
        },
    )

    assert resp.status_code == 200
    assert resp.text == 'data: {"id": "chatcmpl-1", "choices": [{"delta": {"content": "hello"}}]}\n\ndata: [DONE]\n\n'
    assert len(recorder["requests"]) == 2
    assert recorder["requests"][0].json["tools"]
    assert "tools" not in recorder["requests"][1].json
