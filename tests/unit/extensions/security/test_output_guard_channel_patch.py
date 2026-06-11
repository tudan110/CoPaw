# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for output-guard channel patching (extensions/security)."""
from __future__ import annotations

import pytest

from qwenpaw.extensions.security.output_guard import (
    OutputGuardSettings,
    redactor,
)
from qwenpaw.extensions.security.output_guard import channel_patch

SECRET = "sk-test1234567890abcdefghijklmn"
SECRET_HIDDEN = "1234567890abcdefghijklm"


class _TextPart:
    """Minimal stand-in for TextContent (no pydantic dependency)."""

    def __init__(self, text: str):
        self.text = text


class _ImagePart:
    def __init__(self, url: str):
        self.url = url


class _FakeChannel:
    """Stand-in channel defining all four outbound methods."""

    channel = "fake"

    def __init__(self):
        self.sent_texts = []
        self.sent_parts = []
        self.stream_texts = []

    async def send(self, to_handle, text, meta=None):
        self.sent_texts.append(text)

    async def send_content_parts(self, to_handle, parts, meta=None):
        self.sent_parts.append(parts)

    async def on_streaming_delta(
        self,
        request,
        to_handle,
        event,
        send_meta,
        stream_type,
        accumulated_text="",
    ):
        self.stream_texts.append(accumulated_text)

    async def on_streaming_end(
        self,
        request,
        to_handle,
        event,
        send_meta,
        stream_type,
        accumulated_text="",
    ):
        self.stream_texts.append(accumulated_text)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    redactor.clear_caches()
    monkeypatch.setattr(
        channel_patch,
        "_settings_loader",
        OutputGuardSettings,
    )
    yield
    redactor.clear_caches()


@pytest.fixture()
def patched_channel():
    cls = type("PatchedChannel", (_FakeChannel,), dict(_FakeChannel.__dict__))
    channel_patch._wrap_class(cls)
    return cls()


# ---------------------------------------------------------------------------
# send / send_content_parts
# ---------------------------------------------------------------------------
async def test_send_masks_secret(patched_channel):
    await patched_channel.send("u1", f"key: {SECRET}", {})
    assert len(patched_channel.sent_texts) == 1
    assert SECRET_HIDDEN not in patched_channel.sent_texts[0]
    assert "sk-tes" in patched_channel.sent_texts[0]


async def test_send_with_text_kwarg(patched_channel):
    await patched_channel.send("u1", text=f"key: {SECRET}")
    assert SECRET_HIDDEN not in patched_channel.sent_texts[0]


async def test_send_content_parts_masks_text_parts(patched_channel):
    parts = [_TextPart(f"key: {SECRET}"), _ImagePart("http://x/img.png")]
    await patched_channel.send_content_parts("u1", parts, {})
    sent = patched_channel.sent_parts[0]
    assert SECRET_HIDDEN not in sent[0].text
    assert sent[1] is parts[1]  # media part passes through untouched
    # caller's original part object is not mutated
    assert parts[0].text == f"key: {SECRET}"


async def test_streaming_accumulated_text_masked(patched_channel):
    await patched_channel.on_streaming_delta(
        None,
        "u1",
        None,
        {},
        "message",
        accumulated_text=f"k: {SECRET}",
    )
    assert SECRET_HIDDEN not in patched_channel.stream_texts[0]


async def test_streaming_tail_guard_on_delta_only(patched_channel):
    await patched_channel.on_streaming_delta(
        None,
        "u1",
        None,
        {},
        "message",
        accumulated_text="key is sk-abc",
    )
    assert not patched_channel.stream_texts[0].endswith("sk-abc")
    await patched_channel.on_streaming_end(
        None,
        "u1",
        None,
        {},
        "message",
        accumulated_text="key is sk-abc",
    )
    assert patched_channel.stream_texts[1] == "key is sk-abc"


async def test_mask_streaming_disabled(monkeypatch, patched_channel):
    monkeypatch.setattr(
        channel_patch,
        "_settings_loader",
        lambda: OutputGuardSettings(mask_streaming=False),
    )
    await patched_channel.on_streaming_delta(
        None,
        "u1",
        None,
        {},
        "message",
        accumulated_text=f"k: {SECRET}",
    )
    assert patched_channel.stream_texts[0] == f"k: {SECRET}"


async def test_guard_off_passthrough(monkeypatch, patched_channel):
    monkeypatch.setattr(
        channel_patch,
        "_settings_loader",
        lambda: OutputGuardSettings(mode="off"),
    )
    await patched_channel.send("u1", SECRET, {})
    assert patched_channel.sent_texts[0] == SECRET


# ---------------------------------------------------------------------------
# idempotent install / inheritance
# ---------------------------------------------------------------------------
def test_wrap_class_idempotent():
    cls = type("C1", (_FakeChannel,), dict(_FakeChannel.__dict__))
    assert channel_patch._wrap_class(cls) == 4
    fn_first = cls.__dict__["send"]
    assert channel_patch._wrap_class(cls) == 0
    assert cls.__dict__["send"] is fn_first


def test_wrap_class_skips_inherited_methods():
    cls = type("C2", (_FakeChannel,), {})  # defines nothing of its own
    assert channel_patch._wrap_class(cls) == 0


async def test_double_wrap_base_and_subclass_idempotent_output():
    base = type("B", (_FakeChannel,), dict(_FakeChannel.__dict__))

    class Sub(base):
        async def send(self, to_handle, text, meta=None):
            await super().send(to_handle, text, meta)

    channel_patch._wrap_class(base)
    channel_patch._wrap_class(Sub)
    ch = Sub()
    await ch.send("u1", f"key: {SECRET}", {})
    # masked exactly once thanks to redaction idempotency
    assert SECRET_HIDDEN not in ch.sent_texts[0]
    assert ch.sent_texts[0].count("sk-tes") == 1


# ---------------------------------------------------------------------------
# fail-open
# ---------------------------------------------------------------------------
async def test_redactor_error_fails_open(monkeypatch, patched_channel):
    def _boom():
        raise RuntimeError("config exploded")

    monkeypatch.setattr(channel_patch, "_settings_loader", _boom)
    await patched_channel.send("u1", SECRET, {})
    assert patched_channel.sent_texts[0] == SECRET  # original still sent


# ---------------------------------------------------------------------------
# real registry install (BaseChannel + built-ins)
# ---------------------------------------------------------------------------
def test_install_wraps_real_channels():
    from qwenpaw.app.channels.base import BaseChannel

    channel_patch.install()
    assert getattr(
        BaseChannel.__dict__["send_content_parts"],
        channel_patch._MARK,
        False,
    )
    # second install is a no-op
    assert channel_patch.install() == 0
