# -*- coding: utf-8 -*-
"""渠道出口包装 (channel outbound patching).

在 **每个 channel 类自身 ``__dict__`` 中定义的** 出站方法上挂脱敏包装：

* ``send``                  —— 主动/定时消息、send_response 等纯文本出口；
* ``send_content_parts``    —— 常规回复、工具输出、错误提示（9 个渠道有
  自己的 override，console 甚至不经过 ``send``）；
* ``on_streaming_delta`` / ``on_streaming_end`` —— 4 个流式渠道
  （dingtalk/feishu/telegram/wecom）只用 ``accumulated_text`` 全量刷新
  气泡，包装该参数即可保证最终态脱敏；delta 时附加尾部防护。

只包装类自身定义的方法（不碰继承副本），``super()`` 调用链保持不变；
基类与子类都被包装时，重复脱敏因 redactor 的幂等性而无害。包装函数带
``_qwenpaw_output_guard`` 标记，重复 ``install()`` 为 no-op。

**fail-open**：脱敏过程任何异常都只记 ERROR 日志并放行原文，绝不让
一条回复因脱敏器故障而发送失败。
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, List, Optional, Tuple

from .redactor import OutputGuardSettings, redact

logger = logging.getLogger(__name__)

_MARK = "_qwenpaw_output_guard"

# Resolved settings provider; replaced by output_guard.install() with the
# config.json/env-aware loader. Defaults keep the module usable standalone.
_settings_loader: Callable[[], OutputGuardSettings] = OutputGuardSettings

__all__ = ["install"]


def _safe_redact(
    text: Any,
    *,
    streaming: bool = False,
    tail_guard: bool = False,
) -> Tuple[Any, List[str]]:
    """Redact ``text`` with full fail-open semantics."""
    if not isinstance(text, str) or not text:
        return text, []
    try:
        cfg = _settings_loader()
        if not cfg.active:
            return text, []
        if streaming and not cfg.mask_streaming:
            return text, []
        return redact(text, cfg=cfg, streaming_tail_guard=tail_guard)
    except Exception:
        logger.exception(
            "output_guard: redaction failed; sending original text",
        )
        return text, []


def _log_hits(channel: Any, where: str, hits: List[str]) -> None:
    if hits:
        logger.info(
            "output_guard: masked %s in %s.%s",
            ",".join(hits),
            getattr(channel, "channel", type(channel).__name__),
            where,
        )


def _redact_part(part: Any) -> Any:
    """Return a redacted copy of a text/refusal part; others pass through."""
    for attr in ("text", "refusal"):
        value = getattr(part, attr, None)
        if isinstance(value, str) and value:
            new_value, hits = _safe_redact(value)
            if not hits:
                return part, []
            try:
                return part.model_copy(update={attr: new_value}), hits
            except Exception:
                import copy as _copy

                clone = _copy.copy(part)
                setattr(clone, attr, new_value)
                return clone, hits
    return part, []


def _wrap_send(fn: Callable) -> Callable:
    @functools.wraps(fn)
    async def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        if "text" in kwargs:
            kwargs["text"], hits = _safe_redact(kwargs["text"])
        elif len(args) >= 2:
            new_text, hits = _safe_redact(args[1])
            args = args[:1] + (new_text,) + args[2:]
        else:
            hits = []
        _log_hits(self, "send", hits)
        return await fn(self, *args, **kwargs)

    return wrapper


def _wrap_send_content_parts(fn: Callable) -> Callable:
    @functools.wraps(fn)
    async def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        try:
            parts: Any = kwargs.get("parts")
            if parts is None and len(args) >= 2:
                parts = args[1]
            if isinstance(parts, (list, tuple)):
                hits: List[str] = []
                new_parts = []
                for part in parts:
                    new_part, part_hits = _redact_part(part)
                    new_parts.append(new_part)
                    hits.extend(part_hits)
                if "parts" in kwargs:
                    kwargs["parts"] = new_parts
                else:
                    args = args[:1] + (new_parts,) + args[2:]
                _log_hits(self, "send_content_parts", hits)
        except Exception:
            logger.exception(
                "output_guard: part redaction failed; sending original",
            )
        return await fn(self, *args, **kwargs)

    return wrapper


def _wrap_streaming(*, tail_guard: bool) -> Callable[[Callable], Callable]:
    def factory(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            # accumulated_text is the 6th positional param (idx 5 after
            # self) and is passed as a keyword by BaseChannel.
            if "accumulated_text" in kwargs:
                kwargs["accumulated_text"], hits = _safe_redact(
                    kwargs["accumulated_text"],
                    streaming=True,
                    tail_guard=tail_guard,
                )
            elif len(args) >= 6:
                new_text, hits = _safe_redact(
                    args[5],
                    streaming=True,
                    tail_guard=tail_guard,
                )
                args = args[:5] + (new_text,) + args[6:]
            else:
                hits = []
            _log_hits(self, "streaming", hits)
            return await fn(self, *args, **kwargs)

        return wrapper

    return factory


_WRAPPERS: Tuple[Tuple[str, Callable[[Callable], Callable]], ...] = (
    ("send", _wrap_send),
    ("send_content_parts", _wrap_send_content_parts),
    ("on_streaming_delta", _wrap_streaming(tail_guard=True)),
    ("on_streaming_end", _wrap_streaming(tail_guard=False)),
)


def _wrap_class(cls: type) -> int:
    wrapped = 0
    for name, factory in _WRAPPERS:
        fn = cls.__dict__.get(name)  # own dict only — never inherited
        if fn is None or not callable(fn):
            continue
        if getattr(fn, _MARK, False):
            continue
        new_fn = factory(fn)
        setattr(new_fn, _MARK, True)
        setattr(cls, name, new_fn)
        wrapped += 1
    return wrapped


def install(
    settings_loader: Optional[Callable[[], OutputGuardSettings]] = None,
) -> int:
    """Wrap outbound methods of BaseChannel and all registered channels.

    Idempotent: already-wrapped methods (marker attribute) are skipped.
    Returns the number of methods wrapped in this call.
    """
    global _settings_loader
    if settings_loader is not None:
        _settings_loader = settings_loader

    from qwenpaw.app.channels.base import BaseChannel
    from qwenpaw.app.channels.registry import get_channel_registry

    classes = {BaseChannel}
    try:
        classes.update(get_channel_registry().values())
    except Exception:
        logger.exception(
            "output_guard: channel registry unavailable; "
            "only BaseChannel wrapped",
        )

    total = 0
    for cls in classes:
        try:
            total += _wrap_class(cls)
        except Exception:
            logger.exception(
                "output_guard: failed to wrap channel class %s",
                cls,
            )
    logger.info(
        "output_guard: installed on %d channel classes (%d methods)",
        len(classes),
        total,
    )
    return total
