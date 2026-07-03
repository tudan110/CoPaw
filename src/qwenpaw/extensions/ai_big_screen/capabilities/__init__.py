# -*- coding: utf-8 -*-
"""L2 data layer: capability descriptor registry + honest execution.

Replaces the legacy ``_execute_data_capability`` if-ladder with a
descriptor registry and a single execution path that owns:

- thread offloading (``asyncio.to_thread``) + per-capability timeouts;
- **honest status adjudication** — exception/timeout → ``failed``,
  zero rows on success → ``empty``, capability-gap → ``gap`` (spec §5);
- a per-pipeline-run **fetch-once cache** keyed by
  ``(capabilityId, normalized params)`` so multiple components share
  one fetch.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from qwenpaw.extensions.ai_big_screen.capabilities import descriptors as _d
from qwenpaw.extensions.ai_big_screen.schemas import (
    CapabilityResult,
    SourceStatus,
)

DEFAULT_TIMEOUT_SECONDS = 30.0

_RESERVED_DATA_KEYS = {
    "sourceStatus",
    "rows",
    "series",
    "nodes",
    "categories",
    "metrics",
    "columns",
    "fields",
    "total",
    "message",
}


@dataclass(frozen=True)
class CapabilityDescriptor:
    """One registered data capability (spec §5)."""

    id: str
    display_name: str
    domain: str
    fetcher: Callable[[Mapping[str, Any]], dict[str, Any]]
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    is_gap: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _dispatch_fetcher(
    capability_id: str,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Late-binding dispatch through ``descriptors.FETCHERS``.

    Resolving at call time (not registry-build time) keeps the fetcher
    table hot-swappable — tests monkeypatch ``FETCHERS`` entries, and
    future custom capabilities can replace fetchers at runtime.
    """

    def _fetch(query_params: Mapping[str, Any]) -> dict[str, Any]:
        return _d.FETCHERS[capability_id](query_params)

    return _fetch


def _build_registry() -> dict[str, CapabilityDescriptor]:
    registry: dict[str, CapabilityDescriptor] = {}
    for meta in _d.CAPABILITY_METADATA:
        capability_id = str(meta["id"])
        registry[capability_id] = CapabilityDescriptor(
            id=capability_id,
            display_name=str(meta.get("name") or capability_id),
            domain=str(meta.get("domain") or ""),
            fetcher=_dispatch_fetcher(capability_id),
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            is_gap=capability_id == "capability-gap",
            metadata=meta,
        )
    return registry


REGISTRY: dict[str, CapabilityDescriptor] = _build_registry()


def _proxy_descriptor(capability_id: str) -> CapabilityDescriptor | None:
    """Build a descriptor for an operator-registered connector (M3-B).

    Dynamic (not in REGISTRY) because connectors are added/edited at
    runtime via ``/proxy/datasources``. Discovery failures degrade to
    None so the static catalog always works.
    """
    from qwenpaw.extensions.ai_big_screen.capabilities import (
        proxy_capabilities,
    )

    meta = proxy_capabilities.get_proxy_metadata(capability_id)
    if meta is None:
        return None

    def _fetch(query_params: Mapping[str, Any]) -> dict[str, Any]:
        return proxy_capabilities.fetch_proxy_capability(
            capability_id,
            query_params,
        )

    public_meta = {
        key: value for key, value in meta.items() if not key.startswith("_")
    }
    return CapabilityDescriptor(
        id=capability_id,
        display_name=str(meta.get("name") or capability_id),
        domain=str(meta.get("domain") or "custom"),
        fetcher=_fetch,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        is_gap=False,
        metadata=public_meta,
    )


def _skill_descriptor(capability_id: str) -> CapabilityDescriptor | None:
    """Build a descriptor for a skill-backed capability (M3-C).

    Dynamic, like the proxy connectors: a skill that declares a
    ``bigscreen`` block in its SKILL.md becomes ``skill:<ws>:<skill>``.
    """
    from qwenpaw.extensions.ai_big_screen.capabilities import (
        skill_capabilities,
    )

    meta = skill_capabilities.get_skill_metadata(capability_id)
    if meta is None:
        return None

    def _fetch(query_params: Mapping[str, Any]) -> dict[str, Any]:
        return skill_capabilities.fetch_skill_capability(
            capability_id,
            query_params,
        )

    public_meta = {
        key: value for key, value in meta.items() if not key.startswith("_")
    }
    return CapabilityDescriptor(
        id=capability_id,
        display_name=str(meta.get("name") or capability_id),
        domain=str(meta.get("domain") or "skill"),
        fetcher=_fetch,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        is_gap=False,
        metadata=public_meta,
    )


def get_descriptor(capability_id: str) -> CapabilityDescriptor | None:
    cid = str(capability_id or "")
    static = REGISTRY.get(cid)
    if static is not None:
        return static
    if cid.startswith("proxy:"):
        return _proxy_descriptor(cid)
    if cid.startswith("skill:"):
        return _skill_descriptor(cid)
    return None


def list_capability_metadata() -> list[dict[str, Any]]:
    """Legacy-shaped capability catalog (for the AI prompt and API).

    Static built-ins plus any operator-registered connectors that
    opted into the big-screen catalog (discovered live each call so the
    LLM always sees the current set).
    """
    catalog = [copy.deepcopy(d.metadata) for d in REGISTRY.values()]
    try:
        from qwenpaw.extensions.ai_big_screen.capabilities import (
            proxy_capabilities,
            skill_capabilities,
        )

        catalog.extend(proxy_capabilities.metadata_for_registry())
        catalog.extend(skill_capabilities.metadata_for_registry())
    except Exception:  # dynamic discovery must never break the catalog
        _LOGGER.warning(
            "dynamic capability discovery failed",
            exc_info=True,
        )
    return catalog


class CapabilityCache:
    """Fetch-once cache for a single pipeline run.

    Stores the *task* (not the result) so concurrent requests for the
    same ``(capabilityId, params)`` await one underlying fetch.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[CapabilityResult]] = {}

    @staticmethod
    def key(capability_id: str, query_params: Mapping[str, Any]) -> str:
        params_key = json.dumps(
            dict(query_params or {}),
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return f"{capability_id}::{params_key}"

    async def get_or_run(
        self,
        cache_key: str,
        factory: Callable[[], Any],
    ) -> CapabilityResult:
        task = self._tasks.get(cache_key)
        if task is None:
            task = asyncio.ensure_future(factory())
            self._tasks[cache_key] = task
        return await asyncio.shield(task)


_LOGGER = logging.getLogger(__name__)

# Developer/CLI-flavoured failure text must not reach an ops screen —
# flags, env-file hints and stack traces mean nothing to the viewer.
_CLI_TRACE_RE = re.compile(
    r"(^|\s)--[A-Za-z][\w-]*|\.env\b|Traceback|File \"|Errno \d+"
    r"|stack ?trace",
    re.IGNORECASE,
)

# Technical connection-chain noise (requests/urllib3 reprs such as
# "ConnectTimeout: HTTPConnectionPool(...) Max retries exceeded") is
# as meaningless to a screen viewer as CLI flags. Short honest
# exception texts ("backend exploded") still pass through.
_EXCEPTION_NOISE_RE = re.compile(
    r"HTTPS?ConnectionPool|Max retries exceeded|NewConnectionError"
    r"|getaddrinfo|\bConnect(?:ion)?Timeout\b|\bReadTimeout\b"
    r"|[Cc]onnection (?:refused|aborted|reset)"
    # requests' raise_for_status text ("503 Server Error: … for url: http://…")
    # carries internal endpoints — collapse it like any transport noise.
    r"|\b\d{3} (?:Server|Client) Error\b|for url:",
)
_TIMEOUT_HINT_RE = re.compile(r"timed? ?out|timeout|超时", re.IGNORECASE)


def friendly_failure_message(raw: str, *, source: str) -> str:
    """Collapse CLI/stack-trace failure text into an operator-friendly
    message (the original goes to the log); business-worded messages
    pass through untouched."""
    message = str(raw or "").strip()
    if not message:
        return f"数据源暂不可用（{source or '未知来源'}）"
    if _CLI_TRACE_RE.search(message) or _EXCEPTION_NOISE_RE.search(message):
        _LOGGER.warning(
            "big-screen capability failure (source=%s): %s",
            source or "unknown",
            message,
        )
        if _TIMEOUT_HINT_RE.search(message):
            return f"数据源连接超时（{source or '未知来源'}），请稍后刷新重试。"
        return f"数据源暂不可用（{source or '未知来源'}），" "请检查该数据源的配置或服务状态。"
    return message


class TtlResultCache:
    """Cross-request result cache honouring capability cachePolicy.

    One instance per process; keys match the per-run fetch-once cache.
    Only honest successes (live/empty) are cached so a failing backend
    is re-probed immediately on the next request. TTL 0 disables
    caching for a capability (e.g. capability-gap).
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, CapabilityResult]] = {}

    def get(self, key: str, ttl_seconds: float) -> CapabilityResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, result = entry
        if time.monotonic() - stored_at >= ttl_seconds:
            self._entries.pop(key, None)
            return None
        return result

    def set(self, key: str, result: CapabilityResult) -> None:
        self._entries[key] = (time.monotonic(), result)

    def clear(self) -> None:
        self._entries.clear()


TTL_CACHE = TtlResultCache()


def _capability_ttl_seconds(descriptor: CapabilityDescriptor) -> float:
    policy = descriptor.metadata.get("cachePolicy")
    if not isinstance(policy, dict):
        return 0.0
    try:
        return max(0.0, float(policy.get("ttlSeconds") or 0))
    except (TypeError, ValueError):
        return 0.0


def _adjudicate(
    descriptor: CapabilityDescriptor,
    data: Mapping[str, Any],
) -> SourceStatus:
    """Map a fetcher payload onto the honest status taxonomy."""
    if descriptor.is_gap:
        return "gap"
    hint = str(data.get("sourceStatus") or "").strip().lower()
    if hint in ("unavailable", "failed", "error"):
        return "failed"
    if hint == "gap":
        return "gap"
    if hint in ("live", "empty"):
        return hint  # type: ignore[return-value]
    has_payload = any(
        bool(data.get(key))
        for key in ("rows", "series", "nodes", "categories", "metrics")
    )
    return "live" if has_payload else "empty"


def _to_result(
    descriptor: CapabilityDescriptor,
    data: Mapping[str, Any],
    status: SourceStatus,
) -> CapabilityResult:
    extra = {
        key: copy.deepcopy(value)
        for key, value in data.items()
        if key not in _RESERVED_DATA_KEYS
    }
    rows = data.get("rows")
    series = data.get("series")
    nodes = data.get("nodes")
    categories = data.get("categories")
    metrics = data.get("metrics")
    columns = data.get("columns")
    total = data.get("total")
    message = str(data.get("message") or "")
    if status == "failed":
        message = friendly_failure_message(
            message,
            source=str(data.get("source") or ""),
        )
    return CapabilityResult(
        capability_id=descriptor.id,
        source_status=status,
        rows=list(rows) if isinstance(rows, list) else None,
        series=list(series) if isinstance(series, list) else None,
        nodes=list(nodes) if isinstance(nodes, list) else None,
        categories=(
            list(categories) if isinstance(categories, list) else None
        ),
        metrics=dict(metrics) if isinstance(metrics, dict) else None,
        columns=list(columns) if isinstance(columns, list) else None,
        total=(
            int(total)
            if isinstance(total, (int, float)) and not isinstance(total, bool)
            else None
        ),
        message=message,
        extra=extra,
    )


def _failed_result(
    capability_id: str,
    message: str,
    *,
    source: str = "",
    status: SourceStatus = "failed",
) -> CapabilityResult:
    extra: dict[str, Any] = {}
    if source:
        extra["source"] = source
    return CapabilityResult(
        capability_id=capability_id,
        source_status=status,
        message=friendly_failure_message(message, source=source),
        extra=extra,
    )


async def _run_fetch(
    descriptor: CapabilityDescriptor,
    query_params: Mapping[str, Any],
    timeout: float,
    cache_key: str | None = None,
    read_ttl: bool = True,
) -> CapabilityResult:
    ttl_seconds = _capability_ttl_seconds(descriptor)
    if read_ttl and cache_key is not None and ttl_seconds > 0:
        cached = TTL_CACHE.get(cache_key, ttl_seconds)
        if cached is not None:
            return cached

    source = str(descriptor.metadata.get("dataSource") or "")
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(descriptor.fetcher, dict(query_params or {})),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return _failed_result(
            descriptor.id,
            f"数据能力查询超时（>{timeout:g}s）",
            source=source,
        )
    except Exception as exc:  # honest adjudication: failure is failure
        message = str(exc).strip() or exc.__class__.__name__
        return _failed_result(
            descriptor.id,
            f"{exc.__class__.__name__}: {message}",
            source=source,
        )
    if not isinstance(data, dict):
        return _failed_result(
            descriptor.id,
            "数据能力返回了无法识别的载荷",
            source=source,
        )
    result = _to_result(descriptor, data, _adjudicate(descriptor, data))
    if (
        cache_key is not None
        and ttl_seconds > 0
        and result.source_status in ("live", "empty")
    ):
        TTL_CACHE.set(cache_key, result)
    return result


async def execute_capability(
    query_params: Mapping[str, Any],
    *,
    capability_id: str | None = None,
    descriptor: CapabilityDescriptor | None = None,
    cache: CapabilityCache | None = None,
    timeout: float | None = None,
    fresh: bool = False,
) -> CapabilityResult:
    """Execute one capability honestly; never raises.

    Pass either a ``descriptor`` (tests / custom capabilities) or a
    ``capability_id`` resolved against the registry. ``fresh=True``
    bypasses the cross-request TTL cache *read* (refresh semantics)
    while still writing the new result back for other readers.
    """
    if descriptor is None:
        descriptor = get_descriptor(capability_id or "")
    if descriptor is None:
        return _failed_result(
            str(capability_id or ""),
            f"未接入数据能力：{capability_id}",
            source="unsupported",
        )
    effective_timeout = (
        timeout if timeout is not None else descriptor.timeout_seconds
    )
    cache_key = CapabilityCache.key(descriptor.id, query_params)
    read_ttl = not fresh

    if cache is None:
        return await _run_fetch(
            descriptor,
            query_params,
            effective_timeout,
            cache_key=cache_key,
            read_ttl=read_ttl,
        )

    return await cache.get_or_run(
        cache_key,
        lambda: _run_fetch(
            descriptor,
            query_params,
            effective_timeout,
            cache_key=cache_key,
            read_ttl=read_ttl,
        ),
    )
