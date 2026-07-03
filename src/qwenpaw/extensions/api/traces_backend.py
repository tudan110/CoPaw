# -*- coding: utf-8 -*-
"""Portal traceability HTTP router.

Mounted at ``/api/portal/traces/*``.

Endpoints:

* ``GET    /api/portal/traces/sessions``       — paginated session index.
* ``GET    /api/portal/traces/sessions/{id}``  — full event timeline for a
  single session (supports ``offset`` / ``limit`` for very long traces).
* ``POST   /api/portal/traces/sessions/{id}/clear`` — drop a session's
  trace (POST instead of DELETE because DELETE is globally blocked by
  :class:`qwenpaw.extensions.api.delete_block_middleware`).
* ``GET    /api/portal/traces/stats``          — aggregate counts for the
  dashboard header.

The store itself lives in :mod:`qwenpaw.extensions.traceability.trace_store`
and is decoupled from this router; this module is only the HTTP surface.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from qwenpaw.extensions.traceability import trace_store

router = APIRouter(prefix="/api/portal/traces", tags=["portal", "traces"])


@router.get("/stats")
def traces_stats() -> dict:
    """Return aggregate counts across all sessions for the header tiles."""
    return trace_store.stats()


@router.get("/sessions")
def list_sessions(
    agent_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    only_errors: bool = Query(default=False),
    since_ts: float | None = Query(default=None, ge=0),
    until_ts: float | None = Query(default=None, ge=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    """Paginated index of sessions, freshest first."""
    return trace_store.list_sessions(
        agent_id=agent_id,
        keyword=keyword,
        only_errors=only_errors,
        since_ts=since_ts,
        until_ts=until_ts,
        offset=offset,
        limit=limit,
    )


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=0, ge=0, le=10000),
) -> dict:
    """Return the full event timeline for one session.

    When ``limit`` is ``0`` (default), all events are returned.
    """
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    result = trace_store.read_session(
        session_id,
        offset=offset,
        limit=limit if limit > 0 else None,
    )
    if not result["exists"]:
        raise HTTPException(
            status_code=404,
            detail=f"trace for session '{session_id}' not found",
        )
    return result


@router.get("/trends")
def trace_trends(
    window_s: int = Query(default=30 * 86400, ge=3600, le=366 * 86400),
    buckets: int = Query(default=30, ge=6, le=90),
) -> dict:
    """Bucketed trace count / avg duration / token totals for the three
    headline charts above the trace list (阿里云链路追踪同款)."""
    import time as _time

    now = _time.time()
    since = now - window_s
    bucket_s = max(60, window_s // buckets)
    index = trace_store.list_sessions(limit=500, since_ts=since)
    rows: dict[int, dict[str, float]] = {}
    for item in index.get("items", []):
        first = float(item.get("first_event_at") or 0)
        if first < since:
            continue
        bucket_ts = int(first) // bucket_s * bucket_s
        row = rows.setdefault(
            bucket_ts,
            {"traces": 0, "durationSum": 0.0, "tokens": 0},
        )
        row["traces"] += 1
        row["durationSum"] += max(
            0.0,
            float(item.get("last_event_at") or 0) - first,
        )
        row["tokens"] += int(item.get("total_tokens") or 0)
    return {
        "generatedAt": int(now),
        "windowS": window_s,
        "bucketS": bucket_s,
        "points": [
            {
                "ts": ts,
                "traces": int(row["traces"]),
                "avgDurationS": (
                    round(row["durationSum"] / row["traces"], 2)
                    if row["traces"]
                    else 0.0
                ),
                "tokens": int(row["tokens"]),
            }
            for ts, row in sorted(rows.items())
        ],
    }


@router.get("/spans")
def list_spans(
    span_type: str = Query(default="all", pattern="^(all|llm_call|tool_call)$"),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=300),
    max_sessions: int = Query(default=60, ge=1, le=300),
) -> dict:
    """Cross-session span rows (LLM / tool calls), freshest sessions first.

    Walks recent sessions' JSONL until ``limit`` spans are collected —
    an index-order scan, not a full-store scan, so cost stays bounded.
    """
    wanted = ("llm_call", "tool_call") if span_type == "all" else (span_type,)
    needle = (keyword or "").strip().lower()
    sessions = trace_store.list_sessions(limit=max_sessions).get("items", [])
    spans: list[dict] = []
    for item in sessions:
        session_id = str(item.get("session_id") or "")
        if not session_id:
            continue
        detail = trace_store.read_session(session_id)
        if not detail.get("exists"):
            continue
        for event in detail.get("events", []):
            etype = str(event.get("type") or "")
            if etype not in wanted:
                continue
            name = str(event.get("model") or event.get("tool_name") or "")
            if needle and needle not in name.lower():
                continue
            spans.append(
                {
                    "ts": float(event.get("ts") or 0),
                    "type": etype,
                    "name": name,
                    "sessionId": session_id,
                    "agentId": str(event.get("agent_id") or ""),
                    "durationMs": _safe_float(event.get("duration_ms")),
                    "status": str(event.get("status") or event.get("outcome") or "ok"),
                    "promptTokens": _safe_int(event.get("prompt_tokens")),
                    "completionTokens": _safe_int(event.get("completion_tokens")),
                    "ttftMs": _safe_float(event.get("ttft_ms")),
                }
            )
        if len(spans) >= limit * 3:  # enough to sort+trim
            break
    spans.sort(key=lambda s: s["ts"], reverse=True)
    return {"items": spans[:limit], "scannedSessions": len(sessions)}


def _safe_float(value) -> float | None:
    try:
        return round(float(value), 1) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@router.post("/sessions/{session_id}/clear")
async def remove_session(session_id: str) -> dict:
    """Clear a single session's trace file and drop its index entry."""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    deleted = await trace_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"trace for session '{session_id}' not found",
        )
    return {"deleted": True, "session_id": session_id}
