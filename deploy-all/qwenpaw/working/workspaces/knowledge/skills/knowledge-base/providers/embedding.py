"""DashScope text-embedding-v4 client.

Pure stdlib (urllib + json). Returns one float vector per input text.
Errors raised as EmbeddingError subclasses so callers can map to 503/429.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request


DASHSCOPE_ENDPOINT = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
)
DEFAULT_MODEL = "text-embedding-v4"
DEFAULT_DIM = 1024
MAX_TEXTS_PER_CALL = 10
SLOW_CALL_MS = 8_000


class EmbeddingError(Exception):
    reason: str = "unknown"


class EmbeddingDisabled(EmbeddingError):
    reason = "disabled"


class EmbeddingTimeout(EmbeddingError):
    reason = "timeout"


class EmbeddingRateLimit(EmbeddingError):
    reason = "rate_limited"


class EmbeddingProviderError(EmbeddingError):
    reason = "server_error"


class EmbeddingInvalidResponse(EmbeddingError):
    reason = "invalid_response"


def is_available() -> bool:
    return bool(os.environ.get("DASHSCOPE_API_KEY"))


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    timeout_s: float = 30.0,
    api_key: str | None = None,
    batch_id: str | None = None,
) -> list[list[float]]:
    """Embed up to MAX_TEXTS_PER_CALL texts in one request. Use embed_batched()
    for arbitrary length lists."""
    api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise EmbeddingDisabled("DASHSCOPE_API_KEY not set")
    if not texts:
        return []
    if len(texts) > MAX_TEXTS_PER_CALL:
        raise EmbeddingProviderError(
            f"call exceeds MAX_TEXTS_PER_CALL ({len(texts)} > {MAX_TEXTS_PER_CALL}); "
            f"use embed_batched()"
        )

    model_name = model or DEFAULT_MODEL
    payload = json.dumps(
        {"model": model_name, "input": texts, "encoding_format": "float"},
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib_request.Request(
        DASHSCOPE_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "QwenPawKB/1.0",
        },
    )

    started = time.monotonic()
    try:
        with urllib_request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib_error.HTTPError as exc:
        latency = _ms(started)
        if exc.code == 429:
            _log(model_name, len(texts), latency, "rate_limited", batch_id,
                 error=f"HTTP 429: {exc.reason}")
            raise EmbeddingRateLimit(f"dashscope 429: {exc.reason}") from exc
        _log(model_name, len(texts), latency, "server_error", batch_id,
             error=f"HTTP {exc.code}: {exc.reason}")
        raise EmbeddingProviderError(
            f"dashscope HTTP {exc.code}: {exc.reason}"
        ) from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        latency = _ms(started)
        reason_str = str(getattr(exc, "reason", exc))
        if isinstance(exc, TimeoutError) or "timed out" in reason_str.lower():
            _log(model_name, len(texts), latency, "timeout", batch_id,
                 error=reason_str)
            raise EmbeddingTimeout(f"dashscope timeout: {reason_str}") from exc
        _log(model_name, len(texts), latency, "server_error", batch_id,
             error=reason_str)
        raise EmbeddingProviderError(
            f"dashscope transport: {reason_str}"
        ) from exc

    latency = _ms(started)
    if not raw:
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error="empty body")
        raise EmbeddingInvalidResponse("empty response body")

    try:
        data = json.loads(raw.decode("utf-8"))
        items = data["data"]
        vectors = [item["embedding"] for item in items]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error=f"shape: {exc}")
        raise EmbeddingInvalidResponse(f"unexpected shape: {exc}") from exc

    if len(vectors) != len(texts):
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error=f"count mismatch: sent {len(texts)} got {len(vectors)}")
        raise EmbeddingInvalidResponse(
            f"count mismatch: sent {len(texts)} got {len(vectors)}"
        )
    if vectors and not vectors[0]:
        raise EmbeddingInvalidResponse("empty vector returned")

    usage = data.get("usage") or {}
    tokens_in = int(usage.get("total_tokens", 0) or usage.get("prompt_tokens", 0) or 0)
    _log(model_name, len(texts), latency, "success", batch_id, tokens_in=tokens_in)
    return vectors


def embed_batched(
    texts: list[str],
    *,
    model: str | None = None,
    timeout_s: float = 30.0,
    api_key: str | None = None,
    batch_id: str | None = None,
) -> list[list[float]]:
    """Embed an arbitrary-length text list, splitting into MAX_TEXTS_PER_CALL
    requests and concatenating results in order."""
    out: list[list[float]] = []
    for i in range(0, len(texts), MAX_TEXTS_PER_CALL):
        batch = texts[i:i + MAX_TEXTS_PER_CALL]
        sub_id = f"{batch_id or 'batch'}#{i // MAX_TEXTS_PER_CALL}"
        out.extend(
            embed_texts(
                batch,
                model=model,
                timeout_s=timeout_s,
                api_key=api_key,
                batch_id=sub_id,
            )
        )
    return out


def embed_query(
    text: str,
    *,
    model: str | None = None,
    timeout_s: float = 5.0,
    api_key: str | None = None,
) -> list[float]:
    """Single-query convenience. Tighter default timeout than ingest path."""
    vectors = embed_texts(
        [text],
        model=model,
        timeout_s=timeout_s,
        api_key=api_key,
        batch_id="query",
    )
    return vectors[0] if vectors else []


def _ms(started_monotonic: float) -> int:
    return int((time.monotonic() - started_monotonic) * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log(
    model: str,
    n_texts: int,
    latency_ms: int,
    status: str,
    batch_id: str | None,
    *,
    tokens_in: int = 0,
    error: str | None = None,
) -> None:
    entry = {
        "ts": _now_iso(),
        "batch_id": batch_id,
        "provider": "dashscope",
        "model": model,
        "n_texts": n_texts,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "status": status,
    }
    if error:
        entry["error"] = error
    prefix = "WARN:[embed]" if latency_ms > SLOW_CALL_MS else "[embed]"
    print(f"{prefix} {json.dumps(entry, ensure_ascii=False)}", flush=True)
