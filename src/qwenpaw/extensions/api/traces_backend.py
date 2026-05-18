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
