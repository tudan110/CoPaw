# -*- coding: utf-8 -*-
"""Regression tests for client-facing error friendliness.

Guarantee: the text the frontend receives (``ctx.extras["_error_text"]``)
never carries a raw stack, the internal temp-dump path, or the raw provider
reason — while still keeping the non-sensitive category code so the UI can map
it to a localized, friendly message.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.exceptions import convert_model_exception
from qwenpaw.hooks.error.error_hook import ErrorNormalizeHook, _public_error_text
from qwenpaw.runtime.hooks import HookContext


def _model_exc(status_code=None, message="boom"):
    exc = RuntimeError(message)
    if status_code is not None:
        exc.status_code = status_code
    return exc


def _build_ctx(exc):
    request = SimpleNamespace(session_id="s1", user_id="u1", channel="console")
    return HookContext(
        request=request,
        session_id="s1",
        agent_id="a1",
        root_session_id="s1",
        root_agent_id="a1",
        workspace_dir=None,
        workspace=None,
        app_services=None,
        error=exc,
    )


@pytest.fixture(autouse=True)
def _stub_dump(monkeypatch):
    """Default: no real temp-file dump (tests opt into a fake path)."""
    monkeypatch.setattr(
        "qwenpaw.app.chats.query_error_dump.write_query_error_dump",
        lambda *a, **k: None,
    )


def _run_hook(exc):
    ctx = _build_ctx(exc)
    asyncio.run(ErrorNormalizeHook().run(ctx))
    return ctx.extras.get("_error_text", "")


# ── _public_error_text (pure) ───────────────────────────────────────────


def test_public_error_text_strips_reason_keeps_code():
    exc = _model_exc(status_code=429, message="rate limit exceeded: acct 42")
    normalized = convert_model_exception(exc)
    assert ". Reason:" in (normalized.message or "")  # precondition

    public = _public_error_text(normalized, exc)
    assert ". Reason:" not in public
    assert "acct 42" not in public  # raw provider detail removed
    assert "MODEL_QUOTA_EXCEEDED" in public  # category token kept


def test_public_error_text_never_empty():
    exc = RuntimeError("")
    public = _public_error_text(convert_model_exception(exc), exc)
    assert public


# ── ErrorNormalizeHook (integration) ────────────────────────────────────


def test_hook_never_leaks_dump_path_or_stack(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.app.chats.query_error_dump.write_query_error_dump",
        lambda *a, **k: "/tmp/qwenpaw_query_error_FAKE.json",
    )
    exc = _model_exc(
        status_code=401,
        message='Traceback (most recent call last): secret-token',
    )
    text = _run_hook(exc)

    assert text
    assert "/tmp/qwenpaw_query_error_FAKE.json" not in text
    assert "[dump:" not in text
    assert ". Reason:" not in text
    assert "Traceback" not in text
    assert "secret-token" not in text
    assert "UNAUTHORIZED_MODEL_ACCESS" in text  # frontend can still categorize


@pytest.mark.parametrize(
    "status_code, message, expected_code",
    [
        (401, "unauthorized", "UNAUTHORIZED_MODEL_ACCESS"),
        (429, "rate limit", "MODEL_QUOTA_EXCEEDED"),
        (None, "request timed out", "MODEL_TIMEOUT"),
        (None, "maximum context length exceeded", "MODEL_CONTEXT_LENGTH_EXCEEDED"),
        (None, "some api weirdness", "MODEL_EXECUTION_ERROR"),
    ],
)
def test_hook_categories_carry_code_without_leak(status_code, message, expected_code):
    text = _run_hook(_model_exc(status_code=status_code, message=message))
    assert expected_code in text
    assert ". Reason:" not in text
    assert "/tmp" not in text
