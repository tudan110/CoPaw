# -*- coding: utf-8 -*-
"""Global block of HTTP DELETE for QwenPaw + Portal.

Internal hardening: deletion of any registered resource (skill, provider,
agent, MCP server, local model, chat history, cron job, env var, config
entry, ...) can be forbidden across the operations stack. Operators should
replace destructive removal with archiving / disabling flows instead.

Resolution order for whether DELETE is blocked:
    1. env var ``QWENPAW_DELETE_OPS_DISABLED`` (if set) — emergency override
    2. ``config.json`` -> ``security.delete_ops_disabled``
    3. default ``True``

So the deployment posture lives in ``config.json`` (which travels with the
working dir under every deployment method); the env var is just an override.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ...constant import EnvVarLoader

logger = logging.getLogger(__name__)

_TRUE_STRINGS = {"true", "1", "yes", "on"}
_FALSE_STRINGS = {"false", "0", "no", "off"}


def _delete_ops_disabled() -> bool:
    raw = EnvVarLoader.get_str("QWENPAW_DELETE_OPS_DISABLED")
    if raw is not None and raw.strip():
        token = raw.strip().lower()
        if token in _FALSE_STRINGS:
            return False
        if token in _TRUE_STRINGS:
            return True
        # unrecognised value -> fall through to config
    try:
        from ...config import load_config

        return bool(load_config().security.delete_ops_disabled)
    except Exception:  # pragma: no cover - defensive (config not ready)
        return True


class DeleteBlockMiddleware(BaseHTTPMiddleware):
    """Reject every HTTP DELETE request before it reaches a router."""

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() != "DELETE":
            return await call_next(request)

        if not _delete_ops_disabled():
            return await call_next(request)

        client_ip = request.client.host if request.client else "?"
        logger.warning(
            "[DELETE_BLOCK] rejected DELETE %s from %s",
            request.url.path,
            client_ip,
        )

        return JSONResponse(
            status_code=403,
            content={
                "error": "deletion_disabled",
                "code": "DELETION_DISABLED",
                "message": (
                    "删除类操作已在系统中全局禁用。"
                    "如需调整某条资源，请改用停用/归档/重命名流程，"
                    "或联系运维管理员通过审计变更流程办理。"
                ),
                "message_en": (
                    "Deletion is globally disabled by security policy. "
                    "Use disable/archive/rename instead, or request a "
                    "change-control override."
                ),
                "path": request.url.path,
            },
        )
