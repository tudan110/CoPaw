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

After Runtime 2.0 the actual event emitters no longer live in core; they
are re-attached non-invasively by :func:`install.install_traceability`,
called once from ``app/_app.py`` at startup (mirrors
:func:`qwenpaw.extensions.security.install_security_hardening`).
"""

from .install import install_traceability

__all__ = ["install_traceability"]
