# -*- coding: utf-8 -*-
"""Per-session, append-only trace store backed by JSONL files.

Layout under ``WORKING_DIR/chat_traces/``::

    _index.json                       summary index (one row per session)
    <session_id>.jsonl                one event per line, append-only

Each event is a JSON object with at least::

    {"ts": <unix_seconds>, "type": <event_type>, ...}

Known event types (free-form strings; new types are ignored gracefully
by the UI):

* ``user_message``    — user-side input that started a turn
* ``agent_reasoning`` — assistant reasoning checkpoint
* ``tool_call``       — single tool invocation (start + result fields)
* ``skill_trigger``   — ``/<skill>`` invocation detected
* ``agent_reply``     — final assistant reply for a turn
* ``error``           — exception during processing

The store is callable from any async context.  Failures never
propagate to the caller — tracing must not break the agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from qwenpaw.constant import WORKING_DIR

logger = logging.getLogger(__name__)

_TRACE_DIR = WORKING_DIR / "chat_traces"
_INDEX_PATH = _TRACE_DIR / "_index.json"
_LOCK = asyncio.Lock()
_MAX_PREVIEW_CHARS = 240
_MAX_EVENT_BYTES = 64 * 1024


def _now() -> float:
    return time.time()


def _ensure_dir() -> None:
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    safe = session_id.replace("/", "_").replace("\\", "_")
    return _TRACE_DIR / f"{safe}.jsonl"


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion of arbitrary objects to JSON-safe form."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        try:
            return _to_jsonable(value.model_dump(mode="json"))
        except Exception:  # pylint: disable=broad-except
            pass
    if hasattr(value, "dict"):
        try:
            return _to_jsonable(value.dict())
        except Exception:  # pylint: disable=broad-except
            pass
    return {"repr": repr(value)[:512]}


def _truncate_preview(text: str) -> str:
    if not text:
        return ""
    if len(text) <= _MAX_PREVIEW_CHARS:
        return text
    return text[:_MAX_PREVIEW_CHARS] + "…"


def _serialize_event(event: dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True)
    if len(payload.encode("utf-8")) > _MAX_EVENT_BYTES:
        trimmed = dict(event)
        trimmed["_truncated"] = True
        trimmed.pop("args", None)
        trimmed.pop("result", None)
        payload = json.dumps(trimmed, ensure_ascii=False, sort_keys=True)
    return payload


def _read_index() -> dict[str, Any]:
    if not _INDEX_PATH.exists():
        return {"version": 1, "sessions": {}}
    try:
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "sessions": {}}
        data.setdefault("version", 1)
        data.setdefault("sessions", {})
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("trace_store: index unreadable, resetting: %s", exc)
        return {"version": 1, "sessions": {}}


def _write_index(index: dict[str, Any]) -> None:
    _ensure_dir()
    tmp = _INDEX_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(_INDEX_PATH)


def _update_index_entry(
    index: dict[str, Any],
    *,
    session_id: str,
    event_type: str,
    ts: float,
    extra: dict[str, Any] | None = None,
) -> None:
    sessions: dict[str, Any] = index.setdefault("sessions", {})
    entry = sessions.setdefault(
        session_id,
        {
            "session_id": session_id,
            "first_event_at": ts,
            "last_event_at": ts,
            "event_count": 0,
            "tool_call_count": 0,
            "error_count": 0,
            "user_id": "",
            "channel": "",
            "agent_id": "",
            "title": "",
            "preview": "",
            "status": "ok",
        },
    )
    entry["last_event_at"] = ts
    entry["event_count"] = int(entry.get("event_count", 0)) + 1
    if event_type == "tool_call":
        entry["tool_call_count"] = int(entry.get("tool_call_count", 0)) + 1
    if event_type == "llm_call":
        entry["llm_call_count"] = int(entry.get("llm_call_count", 0)) + 1
    if event_type == "error":
        entry["error_count"] = int(entry.get("error_count", 0)) + 1
        entry["status"] = "error"
    if extra and extra.get("add_tokens"):
        # llm_call events accumulate the trace's token total so the list
        # view can show Total tokens without re-reading the JSONL.
        try:
            entry["total_tokens"] = int(entry.get("total_tokens", 0)) + int(
                extra["add_tokens"]
            )
        except (TypeError, ValueError):
            pass
    if extra:
        for key in ("user_id", "channel", "agent_id"):
            value = extra.get(key)
            if value and not entry.get(key):
                entry[key] = str(value)
        title = extra.get("title")
        if isinstance(title, str) and title and not entry.get("title"):
            entry["title"] = _truncate_preview(title)
        preview = extra.get("preview")
        if isinstance(preview, str) and preview:
            entry["preview"] = _truncate_preview(preview)


async def record_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    agent_id: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    index_extra: dict[str, Any] | None = None,
) -> None:
    """Append a single event to the session's JSONL + bump the index.

    All failures are swallowed and logged at WARNING — tracing must
    never raise into the caller.
    """
    if not session_id:
        return
    ts = _now()
    event: dict[str, Any] = {
        "ts": ts,
        "type": str(event_type),
        "session_id": session_id,
    }
    if agent_id:
        event["agent_id"] = agent_id
    if user_id:
        event["user_id"] = user_id
    if channel:
        event["channel"] = channel
    if payload:
        event.update(_to_jsonable(payload))

    extra = {
        "user_id": user_id,
        "channel": channel,
        "agent_id": agent_id,
    }
    if index_extra:
        extra.update(index_extra)

    try:
        async with _LOCK:
            _ensure_dir()
            line = _serialize_event(event)
            with _session_path(session_id).open(
                "a",
                encoding="utf-8",
            ) as fh:
                fh.write(line + "\n")
            index = _read_index()
            _update_index_entry(
                index,
                session_id=session_id,
                event_type=event_type,
                ts=ts,
                extra=extra,
            )
            _write_index(index)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "trace_store: failed to record event type=%s session=%s: %s",
            event_type,
            session_id[:12],
            exc,
        )


def read_session(
    session_id: str,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    """Read events for one session.

    Returns ``{"session_id", "events", "total", "exists"}``.  When the
    file is missing, ``exists`` is ``False`` and ``events`` is empty.
    """
    path = _session_path(session_id)
    if not path.exists():
        return {
            "session_id": session_id,
            "events": [],
            "total": 0,
            "exists": False,
        }
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("trace_store: read failed for %s: %s", session_id, exc)
        return {
            "session_id": session_id,
            "events": [],
            "total": 0,
            "exists": False,
        }

    total = len(events)
    if offset < 0:
        offset = 0
    if limit is not None and limit > 0:
        sliced = events[offset : offset + limit]
    else:
        sliced = events[offset:]
    return {
        "session_id": session_id,
        "events": sliced,
        "total": total,
        "exists": True,
    }


def list_sessions(
    *,
    agent_id: str | None = None,
    keyword: str | None = None,
    only_errors: bool = False,
    since_ts: float | None = None,
    until_ts: float | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return paginated session summaries from the index file.

    The result is sorted by ``last_event_at`` desc so the freshest
    sessions appear first.
    """
    index = _read_index()
    sessions = list(index.get("sessions", {}).values())

    def _ok(entry: dict[str, Any]) -> bool:
        if agent_id and entry.get("agent_id") != agent_id:
            return False
        if only_errors and entry.get("status") != "error":
            return False
        if since_ts is not None and entry.get("last_event_at", 0) < since_ts:
            return False
        if until_ts is not None and entry.get("first_event_at", 0) > until_ts:
            return False
        if keyword:
            kw = keyword.lower()
            blob = " ".join(
                str(entry.get(field, ""))
                for field in (
                    "session_id",
                    "user_id",
                    "channel",
                    "agent_id",
                    "title",
                    "preview",
                )
            ).lower()
            if kw not in blob:
                return False
        return True

    filtered = [entry for entry in sessions if _ok(entry)]
    filtered.sort(key=lambda e: e.get("last_event_at", 0), reverse=True)
    total = len(filtered)
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 50
    page = filtered[offset : offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": page,
    }


def stats() -> dict[str, Any]:
    """Quick aggregate counts for the dashboard header."""
    index = _read_index()
    sessions = list(index.get("sessions", {}).values())
    total_events = sum(int(e.get("event_count", 0)) for e in sessions)
    total_tools = sum(int(e.get("tool_call_count", 0)) for e in sessions)
    total_errors = sum(int(e.get("error_count", 0)) for e in sessions)
    now = _now()
    one_day = 24 * 3600
    recent = [
        e for e in sessions if (now - float(e.get("last_event_at", 0))) <= one_day
    ]
    return {
        "session_count": len(sessions),
        "session_count_24h": len(recent),
        "event_count": total_events,
        "tool_call_count": total_tools,
        "error_count": total_errors,
    }


async def delete_session(session_id: str) -> bool:
    """Remove the session's JSONL and index entry.  Returns ``True`` if removed."""
    if not session_id:
        return False
    path = _session_path(session_id)
    async with _LOCK:
        removed = False
        if path.exists():
            try:
                path.unlink()
                removed = True
            except OSError as exc:
                logger.warning(
                    "trace_store: failed to delete %s: %s",
                    session_id,
                    exc,
                )
        index = _read_index()
        sessions = index.get("sessions", {})
        if session_id in sessions:
            sessions.pop(session_id, None)
            removed = True
            _write_index(index)
        return removed
