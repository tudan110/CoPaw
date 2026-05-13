# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.extensions.api.qiming_openai_adapter import router

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

    async def aiter_raw(self):
        yield self.content

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
    def __init__(self, recorder: dict[str, object], response: _FakeResponse) -> None:
        self._recorder = recorder
        self._response = response
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
        return self._response

    async def aclose(self) -> None:
        self.closed = True


async def test_list_models_uses_env_configuration(monkeypatch):
    monkeypatch.setenv("QWENPAW_QIMING_MODELS", "qiming25_72b_fc,qiming25_32b")

    resp = await _request("GET", "/api/portal/qiming-adapter/v1/models")

    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["data"]] == [
        "qiming25_72b_fc",
        "qiming25_32b",
    ]


async def test_chat_completions_injects_headers_and_normalizes_text_content(
    monkeypatch,
):
    monkeypatch.setenv("QWENPAW_QIMING_BASE_URL", "http://qiming.example.com")
    monkeypatch.setenv("QWENPAW_QIMING_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_QIMING_APP_KEY", "app-key")

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        content=b'{"id":"chatcmpl-1","object":"chat.completion","choices":[]}',
    )

    monkeypatch.setattr(
        "qwenpaw.extensions.api.qiming_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: _FakePostClient(recorder, fake_response),
    )

    resp = await _request(
        "POST",
        "/api/portal/qiming-adapter/v1/chat/completions",
        headers={"Authorization": "Bearer secret-token"},
        json={
            "model": "qiming25_72b_fc",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "ping"}],
                }
            ],
            "stream": False,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == "chatcmpl-1"
    assert recorder["url"] == "http://qiming.example.com/serviceAgent/rest/wsc/completions"
    assert recorder["headers"] == {
        "Content-Type": "application/json",
        "X-APP-ID": "app-id",
        "X-APP-KEY": "app-key",
        "Authorization": "Bearer secret-token",
    }
    assert recorder["json"] == {
        "model": "qiming25_72b_fc",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
    }


async def test_chat_completions_streaming_passthrough(monkeypatch):
    monkeypatch.setenv(
        "QWENPAW_QIMING_COMPLETIONS_URL",
        "http://qiming.example.com/serviceAgent/rest/wsc/completions",
    )
    monkeypatch.setenv("QWENPAW_QIMING_APP_ID", "app-id")
    monkeypatch.setenv("QWENPAW_QIMING_APP_KEY", "app-key")
    monkeypatch.setenv("QWENPAW_QIMING_BEARER_TOKEN", "env-token")

    recorder: dict[str, object] = {}
    fake_response = _FakeResponse(
        headers={"content-type": "text/event-stream"},
        content=b'data: {"id":"chatcmpl-1"}\n\n',
    )
    fake_client = _FakeStreamClient(recorder, fake_response)

    monkeypatch.setattr(
        "qwenpaw.extensions.api.qiming_openai_adapter.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    resp = await _request(
        "POST",
        "/api/portal/qiming-adapter/v1/chat/completions",
        json={
            "model": "qiming25_72b_fc",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.text == 'data: {"id":"chatcmpl-1"}\n\n'
    assert recorder["send_stream"] is True
    assert recorder["headers"] == {
        "Content-Type": "application/json",
        "X-APP-ID": "app-id",
        "X-APP-KEY": "app-key",
        "Authorization": "Bearer env-token",
    }
    assert fake_client.closed is True
