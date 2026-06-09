# -*- coding: utf-8 -*-
"""External API proxy routes — datasource CRUD + request forwarding."""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from qwenpaw.extensions.api.proxy_datasource_models import (
    DatasourceConfig,
    DatasourceSummary,
)
from qwenpaw.extensions.api.proxy_datasource_service import (
    delete_datasource,
    get_datasource,
    get_datasource_summary,
    list_datasources,
    save_datasource,
    update_datasource,
)

router = APIRouter(prefix="/proxy", tags=["portal"])

# ─── SSRF protection ──────────────────────────────────────────────────────────

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_host(hostname: str) -> bool:
    """Reject requests to private/loopback IPs (SSRF mitigation)."""
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # hostname is a domain, not an IP — allow (DNS could resolve to
        # private but we can't check without resolving; rate-limit helps)
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


# ─── Rate limiting (in-memory, per datasource) ───────────────────────────────

_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 30  # requests per window per datasource
_rate_counters: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(datasource_id: str) -> None:
    """Raise 429 if datasource exceeds rate limit."""
    now = time.monotonic()
    window = _rate_counters[datasource_id]
    # prune old entries
    _rate_counters[datasource_id] = [t for t in window if now - t < _RATE_LIMIT_WINDOW]
    window = _rate_counters[datasource_id]
    if len(window) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"数据源 '{datasource_id}' 请求频率超限 ({_RATE_LIMIT_MAX}/{_RATE_LIMIT_WINDOW}s)",
        )
    window.append(now)


# ─── Datasource CRUD ─────────────────────────────────────────────────────────


@router.get("/datasources", response_model=list[DatasourceSummary])
async def list_datasources_endpoint():
    """列出所有外部数据源(不含鉴权头)."""
    return list_datasources()


@router.post("/datasources", response_model=DatasourceSummary)
async def create_datasource(body: DatasourceConfig):
    """创建新的外部数据源配置."""
    try:
        cfg = save_datasource(body)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return get_datasource_summary(cfg.id)


@router.get("/datasources/{datasource_id}", response_model=DatasourceSummary)
async def get_datasource_endpoint(datasource_id: str):
    """获取单个数据源信息(不含鉴权头)."""
    summary = get_datasource_summary(datasource_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return summary


@router.put("/datasources/{datasource_id}", response_model=DatasourceSummary)
async def update_datasource_endpoint(datasource_id: str, body: DatasourceConfig):
    """更新数据源配置."""
    try:
        cfg = update_datasource(datasource_id, body)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if cfg is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return get_datasource_summary(cfg.id)


@router.delete("/datasources/{datasource_id}")
async def delete_datasource_endpoint(datasource_id: str):
    """删除数据源配置."""
    if not delete_datasource(datasource_id):
        raise HTTPException(status_code=404, detail="数据源不存在")
    return {"detail": "已删除"}


# ─── Proxy forwarding ─────────────────────────────────────────────────────────


def _resolve_url(url_template: str, params: dict[str, Any]) -> str:
    """Resolve {param} placeholders in the URL template."""
    try:
        return url_template.format(**params)
    except KeyError as e:
        raise HTTPException(
            status_code=400,
            detail=f"URL 模板缺少参数: {e}",
        )


@router.api_route(
    "/{datasource_id}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def proxy_request(
    datasource_id: str,
    request: Request,
):
    """代理转发请求到外部数据源.

    客户端通过 query params 传递参数,代理注入鉴权头后转发.
    支持 GET/POST/PUT/DELETE.
    """
    cfg = get_datasource(datasource_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if not cfg.enabled:
        raise HTTPException(status_code=403, detail="数据源已禁用")

    _check_rate_limit(datasource_id)

    # Merge params: default_params < query_params
    params = {**cfg.default_params}
    if request.method == "GET":
        params.update(dict(request.query_params))
    else:
        params.update(dict(request.query_params))
        # also accept JSON body params for POST/PUT
        try:
            body = await request.json()
            if isinstance(body, dict):
                params.update(body)
        except Exception:
            pass

    # Resolve URL
    target_url = _resolve_url(cfg.url_template, params)

    # SSRF check on the host
    from urllib.parse import urlparse

    parsed = urlparse(target_url)
    if _is_private_host(parsed.hostname or ""):
        raise HTTPException(
            status_code=403,
            detail="不允许代理到内网地址",
        )

    # Build upstream headers
    upstream_headers = dict(cfg.headers)
    # copy some safe forwarding headers
    if "x-forwarded-for" not in [k.lower() for k in upstream_headers]:
        upstream_headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"

    # Build request body for POST/PUT
    upstream_body: str | bytes | None = None
    if cfg.method in ("POST", "PUT") and cfg.body_template is not None:
        if isinstance(cfg.body_template, str):
            try:
                upstream_body = cfg.body_template.format(**params)
            except KeyError:
                upstream_body = cfg.body_template
        else:
            # dict template — shallow merge with params
            merged = {**cfg.body_template, **params}
            import json

            upstream_body = json.dumps(merged, ensure_ascii=False)

    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        try:
            resp = await client.request(
                method=cfg.method,
                url=target_url,
                headers=upstream_headers,
                content=upstream_body,
            )
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="无法连接到外部数据源")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="外部数据源响应超时")

    # Stream back the response
    content_type = resp.headers.get("content-type", "application/json")
    if "text/event-stream" in content_type or "application/x-ndjson" in content_type:
        # streaming response — forward chunks
        async def _stream():
            async for chunk in resp.aiter_bytes():
                yield chunk
            await resp.aclose()

        return StreamingResponse(
            _stream(),
            status_code=resp.status_code,
            media_type=content_type,
        )

    # regular response
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
    )
