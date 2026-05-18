# -*- coding: utf-8 -*-
"""Traceability subsystem.

Captures every step an agent executes (tool calls, skill triggers,
reasoning checkpoints, user / assistant messages, errors) into a
per-session JSONL file under ``WORKING_DIR/chat_traces``.

Public entry points used by the rest of the codebase:

* :func:`trace_store.record_event`  — fire-and-forget event emitter.
* :func:`trace_store.read_session`  — load a session timeline.
* :func:`trace_store.list_sessions` — paginated list with filters.

The store is intentionally simple (append-only JSONL + a JSON index
file) so it has zero migration concerns and survives restart.
"""
