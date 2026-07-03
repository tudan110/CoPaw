# -*- coding: utf-8 -*-
"""Retry wrapper for ChatModelBase instances.

Transparently retries LLM API calls on transient errors (rate-limit,
timeout, connection) with configurable exponential back-off.

Concurrency and rate-limit control (LLMRateLimiter):
- A global semaphore caps the number of concurrent in-flight LLM calls,
  preventing a burst of requests from hammering the upstream API.
- When a 429 is received every concurrent caller is paused for the same
  duration (plus per-caller jitter) before re-trying, eliminating the
  thundering-herd problem where multiple callers retry at the same instant.

Semaphore ownership rules:
- Non-streaming: __call__'s finally block always releases the slot
  (owns_semaphore stays True throughout).
- Streaming: ownership transfers to _consume_stream_with_slot the moment
  __call__ returns the generator.  owns_semaphore is set to False before
  the return so __call__'s finally skips the release.
  _consume_stream_with_slot releases after the first chunk arrives.
- Cancellation safety: the boolean flag `acquired` tracks whether the
  semaphore slot has actually been taken; the final block only releases
  when acquired is True, preventing a spurious release on CancelledError.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from qwenpaw.exceptions import (
    RateLimitExceededException,
)

from ..constant import (
    LLM_ACQUIRE_TIMEOUT,
    LLM_BACKOFF_BASE,
    LLM_BACKOFF_CAP,
    LLM_MAX_CONCURRENT,
    LLM_MAX_RETRIES,
    LLM_MAX_QPM,
    LLM_RATE_LIMIT_JITTER,
    LLM_RATE_LIMIT_PAUSE,
)
from .model_capability_cache import get_capability_cache
from .rate_limiter import LLMRateLimiter, get_rate_limiter

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}


def _sm_record_llm(model_key: str, status: str, duration_s: float) -> None:
    """Self-monitor tap (L3): one terminal sample per LLM attempt.

    Strictly fail-open — monitoring must never affect the call path.
    429s additionally emit a dedup-merged event so a limiter storm shows
    up as one event row with a running count.
    """
    try:
        from ..self_monitor import emit_event, get_registry

        registry = get_registry()
        registry.counter("qwenpaw_llm_requests_total").inc(
            {"model": model_key, "status": status}
        )
        registry.histogram("qwenpaw_llm_request_duration_seconds").observe(
            duration_s, {"model": model_key, "status": status}
        )
        if status == "429":
            emit_event(
                "llm.rate_limit_storm",
                severity="warn",
                layer="l3",
                source=model_key,
                message="upstream 429 (count = hits within the window)",
                dedup_key=f"llm.429|{model_key}",
            )
    except Exception:  # pragma: no cover - tap must never break calls
        logger.debug("self-monitor llm tap failed", exc_info=True)


def _sm_count_retry() -> None:
    """Self-monitor tap: one retry attempt scheduled (fail-open)."""
    try:
        from ..self_monitor import get_registry

        get_registry().counter("qwenpaw_llm_retries_total").inc()
    except Exception:  # pragma: no cover
        pass


def _trace_llm_call(
    model_key: str,
    status: str,
    duration_s: float,
    usage: Any = None,
    ttft_s: float | None = None,
) -> None:
    """Fire-and-forget ``llm_call`` trace event for the current session.

    This is what turns the traceability center into a span view: every
    terminal LLM attempt becomes one span row (model / duration / tokens
    / TTFT). Background pipelines without a session context (big screen,
    cron dreams) are skipped on purpose — they have no trace to join.
    Strictly fail-open.
    """
    try:
        from ..app.agent_context import (
            get_current_agent_id,
            get_current_channel,
            get_current_session_id,
            get_current_user_id,
        )

        session_id = str(get_current_session_id() or "")
        if not session_id:
            return
        payload: dict[str, Any] = {
            "model": model_key,
            "status": status,
            "duration_ms": round(duration_s * 1000.0, 1),
        }
        total_tokens = 0
        if usage is not None:
            prompt = int(getattr(usage, "input_tokens", 0) or 0)
            completion = int(getattr(usage, "output_tokens", 0) or 0)
            if prompt or completion:
                payload["prompt_tokens"] = prompt
                payload["completion_tokens"] = completion
                total_tokens = prompt + completion
        if ttft_s is not None:
            payload["ttft_ms"] = round(max(0.0, ttft_s) * 1000.0, 1)

        from qwenpaw.extensions.traceability import trace_store

        coro = trace_store.record_event(
            session_id,
            "llm_call",
            payload,
            agent_id=str(get_current_agent_id() or "") or None,
            user_id=str(get_current_user_id() or "") or None,
            channel=str(get_current_channel() or "") or None,
            index_extra={"add_tokens": total_tokens} if total_tokens else None,
        )
        asyncio.get_running_loop().create_task(coro)
    except Exception:  # pragma: no cover - tracing must never break calls
        pass


def _sm_record_first_token(latency_s: float, model_key: str = "") -> None:
    """Self-monitor tap: slot request → first streamed chunk. The wait
    inside the limiter (cooldown/semaphore) is included on purpose —
    this is the user-perceived first-token latency."""
    try:
        from ..self_monitor import get_registry

        get_registry().histogram("qwenpaw_llm_first_token_seconds").observe(
            max(0.0, latency_s), {"model": model_key} if model_key else None
        )
    except Exception:  # pragma: no cover
        pass


_openai_retryable: tuple[type[Exception], ...] | None = None
_anthropic_retryable: tuple[type[Exception], ...] | None = None
_httpx_retryable: tuple[type[Exception], ...] | None = None


class _AcquireTimeoutError(RateLimitExceededException):
    """Raised when ``limiter.acquire()`` times out internally.

    Distinct from a real API 429 so the retry loop can identify it via
    ``isinstance`` and raise immediately without calling
    ``report_rate_limit()`` or attempting another retry.
    """


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Retry policy for transient LLM API failures."""

    enabled: bool = LLM_MAX_RETRIES > 0
    max_retries: int = max(LLM_MAX_RETRIES, 1)
    backoff_base: float = LLM_BACKOFF_BASE
    backoff_cap: float = LLM_BACKOFF_CAP


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Rate-limiting policy for LLM calls.

    Controls the global LLMRateLimiter singleton that caps concurrency and
    coordinates pauses when a 429 is received.  The singleton is initialised
    on the *first* call; subsequent callers share the same instance.

    Attributes:
        max_concurrent: Maximum concurrent in-flight LLM calls.
        max_qpm: Maximum queries per minute (sliding window). 0 = disabled.
        pause_seconds: Global pause duration (s) on a 429 response.
        jitter_range: Random jitter (s) added on top of the pause.
        acquire_timeout: Max seconds to wait for a slot before raising.
    """

    max_concurrent: int = LLM_MAX_CONCURRENT
    max_qpm: int = LLM_MAX_QPM
    pause_seconds: float = LLM_RATE_LIMIT_PAUSE
    jitter_range: float = LLM_RATE_LIMIT_JITTER
    acquire_timeout: float = LLM_ACQUIRE_TIMEOUT


def _get_openai_retryable() -> tuple[type[Exception], ...]:
    global _openai_retryable
    if _openai_retryable is None:
        try:
            import openai

            _openai_retryable = (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
            )
        except ImportError:
            _openai_retryable = ()
    return _openai_retryable


def _get_anthropic_retryable() -> tuple[type[Exception], ...]:
    global _anthropic_retryable
    if _anthropic_retryable is None:
        try:
            import anthropic

            _anthropic_retryable = (
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
            )
        except ImportError:
            _anthropic_retryable = ()
    return _anthropic_retryable


def _get_httpx_retryable() -> tuple[type[Exception], ...]:
    global _httpx_retryable
    if _httpx_retryable is None:
        try:
            import httpx

            _httpx_retryable = (
                httpx.RemoteProtocolError,
                httpx.TimeoutException,
            )
        except ImportError:
            _httpx_retryable = ()
    return _httpx_retryable


def _is_retryable(exc: Exception) -> bool:
    """Return *True* if *exc* should trigger a retry."""
    retryable = (
        _get_openai_retryable() + _get_anthropic_retryable() + _get_httpx_retryable()
    )
    if retryable and isinstance(exc, retryable):
        return True

    status = getattr(exc, "status_code", None)
    if status is not None and status in RETRYABLE_STATUS_CODES:
        return True

    return False


def _is_rate_limit(exc: Exception) -> bool:
    """Return *True* if *exc* is specifically a 429 rate-limit error."""
    return getattr(exc, "status_code", None) == 429


def _is_missing_reasoning_content_error(exc: Exception) -> bool:
    """Return *True* if *exc* is a 400 about missing ``reasoning_content``.

    DeepSeek (and compatible providers) require every assistant message to
    carry ``reasoning_content`` when thinking mode is active.  When the
    conversation history was produced by a non-reasoning model, these
    fields are absent and the API rejects the request with a 400.
    """
    if getattr(exc, "status_code", None) != 400:
        return False
    return "reasoning_content" in str(exc)


def _inject_reasoning_content(
    args: tuple,
    kwargs: dict[str, Any],
) -> bool:
    """Add ``reasoning_content = " "`` to assistant messages that lack it.

    Modifies the formatted message dicts **in-place** so the subsequent
    retry sees the updated values.  Returns *True* when at least one
    message was patched.
    """
    messages: list[dict] | None = kwargs.get("messages")
    if messages is None and args:
        candidate = args[0]
        if isinstance(candidate, list):
            messages = candidate

    if not messages:
        return False

    modified = False
    for msg in messages:
        if (
            isinstance(msg, dict)
            and msg.get("role") == "assistant"
            and "reasoning_content" not in msg
        ):
            msg["reasoning_content"] = " "
            modified = True

    return modified


def _extract_retry_after(exc: Exception) -> float | None:
    """Parse the Retry-After header value (in seconds) from an exception.

    Handles both OpenAI and Anthropic SDK exception shapes, which expose
    headers either directly on the exception or on an attached response object.
    """
    headers = getattr(exc, "headers", None) or getattr(
        getattr(exc, "response", None),
        "headers",
        None,
    )
    if headers:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return None


def _normalize_retry_config(retry_config: RetryConfig | None) -> RetryConfig:
    """Normalize externally supplied retry config into safe bounds."""
    if retry_config is None:
        return RetryConfig()
    normalized_backoff_base = max(0.1, retry_config.backoff_base)
    normalized_backoff_cap = max(
        0.5,
        retry_config.backoff_cap,
        normalized_backoff_base,
    )
    return RetryConfig(
        enabled=retry_config.enabled,
        max_retries=max(1, retry_config.max_retries),
        backoff_base=normalized_backoff_base,
        backoff_cap=normalized_backoff_cap,
    )


def _normalize_rate_limit_config(
    cfg: RateLimitConfig | None,
) -> RateLimitConfig:
    """Normalize externally supplied rate-limit config into safe bounds."""
    if cfg is None:
        return RateLimitConfig()
    return RateLimitConfig(
        max_concurrent=max(1, cfg.max_concurrent),
        max_qpm=max(0, cfg.max_qpm),
        pause_seconds=max(1.0, cfg.pause_seconds),
        jitter_range=max(0.0, cfg.jitter_range),
        acquire_timeout=max(10.0, cfg.acquire_timeout),
    )


def _compute_backoff(attempt: int, retry_config: RetryConfig) -> float:
    """Exponential back-off: base * 2^(attempt-1), capped."""
    return min(
        retry_config.backoff_cap,
        retry_config.backoff_base * (2 ** max(0, attempt - 1)),
    )


class RetryChatModel(ChatModelBase):
    """Transparent retry wrapper around any :class:`ChatModelBase`.

    The wrapper delegates every call to the underlying *inner* model and
    retries on transient errors with exponential back-off.  Streaming
    responses are also covered: if the stream fails mid-consumption the
    entire request is retried from scratch.

    A global LLMRateLimiter is consulted on every call to cap concurrency and
    to coordinate a shared pause across all callers when a 429 is received.
    """

    def __init__(
        self,
        inner: ChatModelBase,
        retry_config: RetryConfig | None = None,
        rate_limit_config: RateLimitConfig | None = None,
    ) -> None:
        # agentscope 2.0 ChatModelBase requires credential/model/parameters;
        # forward the inner wrapper's own values so attribute access stays
        # transparent.
        super().__init__(
            credential=getattr(inner, "credential", None),
            model=getattr(inner, "model", "unknown"),
            parameters=getattr(inner, "parameters", None) or ChatModelBase.Parameters(),
            stream=getattr(inner, "stream", True),
            context_size=getattr(inner, "context_size", 32768),
        )
        self._inner = inner
        self._retry_config = _normalize_retry_config(retry_config)
        self._rate_limit_config = _normalize_rate_limit_config(
            rate_limit_config,
        )

    # Expose the real model's class so that formatter mapping keeps working
    # when code inspects ``model.__class__`` after wrapping.
    @property
    def inner_class(self) -> type:
        return self._inner.__class__

    @property
    def model_key(self) -> str:
        """Stable key for the underlying model: ``provider_id:model_name``."""
        provider_id = getattr(self._inner, "_provider_id", None)
        name = self._inner.model
        return f"{provider_id}:{name}" if provider_id else name

    @staticmethod
    async def _handle_rate_limit_exc(
        exc: Exception,
        limiter: LLMRateLimiter,
    ) -> None:
        """Inspect *exc* and update the rate limiter accordingly.

        - Internal acquire timeout (``_AcquireTimeoutError``): re-raise as-is;
          no report, no retry.
        - Retryable API 429 with Retry-After > ``MAX_PAUSE_SECONDS``: re-raise
          immediately — retrying after the capped pause would just get another
          429 (e.g. Anthropic FreeUsageLimitError with Retry-After: 51496 s).
        - Normal 429: call ``report_rate_limit()`` to set the per-model pause.
        """
        if isinstance(exc, _AcquireTimeoutError):
            raise exc
        if _is_retryable(exc) and _is_rate_limit(exc):
            retry_after = _extract_retry_after(exc)
            if (
                retry_after is not None
                and retry_after > LLMRateLimiter.MAX_PAUSE_SECONDS
            ):
                raise exc
            await limiter.report_rate_limit(retry_after)

    async def _consume_stream_with_slot(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        limiter: LLMRateLimiter,
        acquired_at: float,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Yield all chunks from *stream*, managing the semaphore slot
        lifecycle.

        Releases the semaphore slot after the first chunk arrives — once the
        API starts streaming the request has been accepted and will not be
        rate-limited mid-flight, so holding the slot for the full streaming
        duration would unnecessarily starve other callers.

        Always closes *stream* on completion or error.  Any exception raised
        during iteration propagates to the caller's ``async for`` loop
        (i.e. _wrap_stream), which handles retry decisions.  The exception
        does not propagate to the final consumer unless all retries are
        exhausted.

        Args:
            acquired_at: Timestamp from ``limiter.acquire()``, forwarded to
                ``on_success()`` so only stale pauses are cleared.
        """
        first_chunk = True
        ttft_s: float | None = None
        last_chunk: Any = None
        try:
            async for chunk in stream:
                if first_chunk:
                    first_chunk = False
                    # return the slot once the API starts delivering
                    limiter.release()
                    # streaming success: clear any stale 429 pause so
                    # subsequent callers (including user chats) are not
                    # held back by a pause set by a background task.
                    await limiter.on_success(acquired_at)
                    ttft_s = time.monotonic() - acquired_at
                    _sm_record_first_token(ttft_s, self.model_key)
                last_chunk = chunk
                yield chunk
            # Stream drained normally: emit the llm_call span. Usage rides
            # on the final chunk (cumulative) when the provider reports it.
            _trace_llm_call(
                self.model_key,
                "ok",
                time.monotonic() - acquired_at,
                usage=getattr(last_chunk, "usage", None),
                ttft_s=ttft_s,
            )
        finally:
            await stream.aclose()
            if first_chunk:
                # Stream failed before producing any chunk;
                # slot not yet released.
                limiter.release()

    async def generate_structured_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return await self._inner.generate_structured_output(*args, **kwargs)

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        cache = get_capability_cache()
        key = self.model_key

        if cache.get(key, "needs_reasoning_content", False):
            _inject_reasoning_content(args, kwargs)

        # Each model gets its own rate limiter keyed by
        # "provider_id:model_name" so that a 429 on one model (e.g. from a
        # dream/cron task) cannot stall user chats on a different provider.
        limiter = await get_rate_limiter(
            limiter_key=self.model_key,
            max_concurrent=self._rate_limit_config.max_concurrent,
            max_qpm=self._rate_limit_config.max_qpm,
            default_pause_seconds=self._rate_limit_config.pause_seconds,
            jitter_range=self._rate_limit_config.jitter_range,
        )

        retries = self._retry_config.max_retries if self._retry_config.enabled else 0
        attempts = retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            # Acquire a semaphore slot, with a timeout to prevent
            # indefinite blocking. `acquired` tracks whether the slot was
            # taken so the final block can skip the release on
            # CancelledError (slot was never acquired).
            acquired = False
            owns_semaphore = True
            acquired_at: float = 0.0
            # Self-monitor attempt clock; failure durations include any
            # semaphore/cooldown wait, success durations are re-based
            # below once the slot is held.
            attempt_started = time.monotonic()
            try:
                try:
                    acquired_at = await asyncio.wait_for(
                        limiter.acquire(),
                        timeout=self._rate_limit_config.acquire_timeout,
                    )
                    acquired = True
                except asyncio.TimeoutError as exc:
                    # Internal acquire timeout — NOT an API 429.
                    # _AcquireTimeoutError is a typed subclass so the outer
                    # handler can use isinstance() instead of a sentinel attr.
                    raise _AcquireTimeoutError(
                        operation="LLM execution",
                        retry_after=int(
                            self._rate_limit_config.acquire_timeout,
                        ),
                        details={
                            "reason": "Timed out waiting for execution slot",
                        },
                    ) from exc

                attempt_started = time.monotonic()
                try:
                    result = await self._inner(*args, **kwargs)
                except Exception as inner_exc:
                    if not (
                        _is_missing_reasoning_content_error(inner_exc)
                        and _inject_reasoning_content(args, kwargs)
                    ):
                        raise
                    cache.learn(key, "needs_reasoning_content", True)
                    logger.warning(
                        "Thinking-mode model requires reasoning_content "
                        "on every assistant message. Injecting empty "
                        "values and retrying (learned for future calls).",
                    )
                    result = await self._inner(*args, **kwargs)

                if isinstance(result, AsyncGenerator):
                    # Transfer semaphore ownership to _wrap_stream, which uses
                    # _consume_stream_with_slot internally and handles
                    # retries on stream failure.
                    _sm_record_llm(key, "ok", time.monotonic() - attempt_started)
                    owns_semaphore = False
                    return self._wrap_stream(
                        result,
                        args,
                        kwargs,
                        attempt,
                        attempts,
                        limiter,
                        acquired_at,
                    )

                # Non-streaming success: clear any stale rate-limit pause so
                # subsequent callers are not held back by a pause set by an
                # unrelated background task (e.g. dream/cron 429).
                await limiter.on_success(acquired_at)
                _sm_record_llm(key, "ok", time.monotonic() - attempt_started)
                _trace_llm_call(
                    key,
                    "ok",
                    time.monotonic() - attempt_started,
                    usage=getattr(result, "usage", None),
                )
                return result

            except Exception as exc:
                last_exc = exc
                _sm_record_llm(
                    key,
                    "429" if _is_rate_limit(exc) else "error",
                    time.monotonic() - attempt_started,
                )
                _trace_llm_call(
                    key,
                    "429" if _is_rate_limit(exc) else "error",
                    time.monotonic() - attempt_started,
                )
                await self._handle_rate_limit_exc(exc, limiter)

                if not _is_retryable(exc) or attempt >= attempts:
                    raise

                _sm_count_retry()
                delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. " "Retrying in %.1fs ...",
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

            finally:
                if owns_semaphore and acquired:
                    limiter.release()

        # Should be unreachable, but satisfies the type-checker.
        raise last_exc  # type: ignore[misc]

    # pylint: disable=too-many-branches
    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        call_args: tuple,
        call_kwargs: dict,
        current_attempt: int,
        max_attempts: int,
        limiter: LLMRateLimiter,
        acquired_at: float = 0.0,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Yield chunks from *stream*; on transient failure, retry the full
        request and yield from the new stream instead.

        Args:
            acquired_at: Timestamp from ``limiter.acquire()``, forwarded to
                ``on_success()`` so stale pauses are cleared but fresh ones
                (set by a concurrent 429 after this call acquired) are kept.
        """
        attempt = current_attempt
        pending_stream: AsyncGenerator[ChatResponse, None] | None = stream
        pending_acquired_at = acquired_at
        reasoning_injected = False

        while True:
            try:
                if pending_stream is not None:
                    async for chunk in self._consume_stream_with_slot(
                        pending_stream,
                        limiter,
                        pending_acquired_at,
                    ):
                        yield chunk
                    return  # stream completed without error

                acquired = False
                owns_semaphore = True
                retry_acquired_at: float = 0.0
                try:
                    try:
                        retry_acquired_at = await asyncio.wait_for(
                            limiter.acquire(),
                            timeout=self._rate_limit_config.acquire_timeout,
                        )
                        acquired = True
                    except asyncio.TimeoutError as exc:
                        raise _AcquireTimeoutError(
                            operation="LLM execution (stream retry)",
                            retry_after=int(
                                self._rate_limit_config.acquire_timeout,
                            ),
                            details={
                                "reason": ("Timed out waiting for execution slot"),
                            },
                        ) from exc

                    result = await self._inner(*call_args, **call_kwargs)

                    if isinstance(result, AsyncGenerator):
                        owns_semaphore = False
                        pending_stream = result
                        pending_acquired_at = retry_acquired_at
                        continue

                    yield result
                    return
                finally:
                    if owns_semaphore and acquired:
                        limiter.release()

            except Exception as retry_exc:
                pending_stream = None
                if (
                    not reasoning_injected
                    and _is_missing_reasoning_content_error(retry_exc)
                    and _inject_reasoning_content(call_args, call_kwargs)
                ):
                    reasoning_injected = True
                    get_capability_cache().learn(
                        self.model_key,
                        "needs_reasoning_content",
                        True,
                    )
                    logger.warning(
                        "Thinking-mode stream requires reasoning_content "
                        "on every assistant message. Injecting empty "
                        "values and retrying (learned for future calls).",
                    )
                    continue

                if _is_retryable(retry_exc) and _is_rate_limit(retry_exc):
                    await limiter.report_rate_limit(
                        _extract_retry_after(retry_exc),
                    )

                if not _is_retryable(retry_exc) or attempt >= max_attempts:
                    raise

                retry_delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    "LLM stream failed (attempt %d/%d): %s. " "Retrying in %.1fs ...",
                    attempt,
                    max_attempts,
                    retry_exc,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                attempt += 1
