#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# COPY OF nightingale-log/scripts/_n9e_client.py — sync manually when upstream changes.
"""Nightingale (n9e) log query — shared HTTP client and helpers.

Loads `.env` from the skill directory (preferred) or the project root.
Provides:
- env accessors (base URL, token, default datasource / index)
- time-range parsing (ISO + relative `now-15m` style)
- a thin client over `/api/n9e/proxy/<datasource_id>/...` for ES-compat calls
- a curl fallback for environments where `requests` cannot reach the gateway
- a uniform error envelope `{code, msg, data}` so callers stay consistent
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------

def _parse_env_file(path: Path, override: bool) -> None:
    """Tiny `.env` parser used when `python-dotenv` is not installed.

    Supports: ``KEY=VALUE`` lines, ``#`` comments, optional ``export`` prefix,
    and surrounding single/double quotes. Does not handle multi-line values
    or interpolation — fine for simple skill configs.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # strip an inline comment that follows whitespace + #, but only when
        # not inside quotes
        if value and value[0] not in "\"'":
            hash_pos = value.find(" #")
            if hash_pos >= 0:
                value = value[:hash_pos].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def _load_skill_env() -> None:
    """Load `.env` from the skill directory first, project root second.

    Prefers ``python-dotenv`` if available, falls back to a built-in parser.
    """
    here = Path(__file__).resolve()
    script_dir = here.parent
    skill_dir = script_dir.parent

    candidates: List[Tuple[Path, bool]] = [(skill_dir / ".env", True)]
    for parent in skill_dir.parents:
        candidates.append((parent / ".env", False))

    for candidate, override in candidates:
        if not candidate.exists():
            continue
        if HAS_DOTENV:
            load_dotenv(candidate, override=override)
        else:
            _parse_env_file(candidate, override=override)
        if override:
            # the skill-level .env wins; do not bleed in the project-root one
            return


_load_skill_env()


# ---------------------------------------------------------------------------
# config accessors
# ---------------------------------------------------------------------------

def get_base_url() -> str:
    return (os.getenv("N9E_API_BASE_URL") or "").strip().rstrip("/")


def get_user_token() -> str:
    return (os.getenv("N9E_USER_TOKEN") or "").strip()


def get_default_datasource_id() -> Optional[int]:
    raw = (os.getenv("N9E_LOG_DATASOURCE_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def get_default_index() -> str:
    return (os.getenv("N9E_LOG_INDEX") or "*").strip() or "*"


def get_timestamp_field() -> str:
    return (os.getenv("N9E_LOG_TIMESTAMP_FIELD") or "@timestamp").strip() or "@timestamp"


def get_level_field() -> Optional[str]:
    raw = (os.getenv("N9E_LOG_LEVEL_FIELD") or "").strip()
    return raw or None


def get_host_field() -> Optional[str]:
    raw = (os.getenv("N9E_LOG_HOST_FIELD") or "").strip()
    return raw or None


def get_service_field() -> Optional[str]:
    raw = (os.getenv("N9E_LOG_SERVICE_FIELD") or "").strip()
    return raw or None


def get_max_size() -> int:
    raw = (os.getenv("N9E_LOG_MAX_SIZE") or "500").strip()
    try:
        return max(1, min(int(raw), 10000))
    except ValueError:
        return 500


def get_timeout() -> int:
    raw = (os.getenv("N9E_LOG_TIMEOUT") or "30").strip()
    try:
        return max(5, int(raw))
    except ValueError:
        return 30


def use_http_proxy() -> bool:
    """Whether to honour the shell's http(s)_proxy / HTTP(S)_PROXY env vars.

    Default is False because n9e is typically deployed on an internal LAN
    where the developer's outbound proxy would only break the request.
    Set ``N9E_USE_HTTP_PROXY=true`` if the n9e gateway must really be reached
    through a proxy.
    """
    raw = (os.getenv("N9E_USE_HTTP_PROXY") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# error envelope
# ---------------------------------------------------------------------------

def make_error(code: int, msg: str) -> Dict[str, Any]:
    return {"code": code, "msg": msg, "data": None}


def make_ok(data: Any) -> Dict[str, Any]:
    return {"code": 200, "msg": "ok", "data": data}


def is_error(envelope: Dict[str, Any]) -> bool:
    return int(envelope.get("code") or 0) != 200


# ---------------------------------------------------------------------------
# config validation
# ---------------------------------------------------------------------------

def require_config() -> Optional[Dict[str, Any]]:
    """Return an error envelope if any required config is missing."""
    missing: List[str] = []
    if not get_base_url():
        missing.append("N9E_API_BASE_URL")
    if not get_user_token():
        missing.append("N9E_USER_TOKEN")
    if missing:
        return make_error(
            400,
            (
                "夜莺日志查询配置缺失: " + ", ".join(missing)
                + "。请在本技能目录的 .env 中补齐后重试，"
                "示例见 .env.example。"
            ),
        )
    return None


# ---------------------------------------------------------------------------
# time parsing
# ---------------------------------------------------------------------------

_REL_RE = re.compile(r"^now(?:\s*-\s*(\d+)\s*([smhdw]))?$", re.IGNORECASE)
_UNIT_TO_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_time(spec: Optional[str], default: Optional[str] = None) -> int:
    """Parse a time spec into milliseconds since epoch (UTC).

    Accepts:
    - `now`, `now-15m`, `now-1h`, `now-1d`, `now-7d`
    - ISO 8601 (`2026-05-06T08:00:00`, `2026-05-06 08:00:00`, optionally with `Z`)
    - epoch ms (a bare integer)
    """
    raw = (spec or default or "").strip()
    if not raw:
        raise ValueError("time spec is empty")

    # epoch ms?
    if raw.isdigit():
        return int(raw)

    # relative?
    m = _REL_RE.match(raw)
    if m:
        amount = int(m.group(1) or 0)
        unit = (m.group(2) or "s").lower()
        delta = timedelta(seconds=amount * _UNIT_TO_SECONDS.get(unit, 1))
        return int((datetime.now(timezone.utc) - delta).timestamp() * 1000)

    # ISO?
    cleaned = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError(
                f"无法解析时间表达式 '{raw}'。"
                "请使用 ISO 时间（2026-05-06T08:00:00）"
                "或相对时间（now、now-15m、now-1h、now-1d）。"
            ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def format_ms(ms: int) -> str:
    """Format epoch ms as a local-timezone-naive ISO-ish string for display."""
    try:
        return datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return str(ms)


# ---------------------------------------------------------------------------
# HTTP transport (requests + curl fallback)
# ---------------------------------------------------------------------------

def _build_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {
        "X-User-Token": get_user_token(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _request_with_curl(
    method: str,
    url: str,
    *,
    body: Optional[str] = None,
    content_type: str = "application/json",
    timeout: int,
) -> Dict[str, Any]:
    body_path: Optional[str] = None
    out_path: Optional[str] = None
    try:
        args = [
            "curl", "-sS", "-X", method.upper(),
            "--connect-timeout", str(timeout),
            "--max-time", str(timeout),
            "-H", f"X-User-Token: {get_user_token()}",
            "-H", f"Content-Type: {content_type}",
            "-H", "Accept: application/json",
        ]
        if not use_http_proxy():
            args.extend(["--noproxy", "*"])
        if body is not None:
            with tempfile.NamedTemporaryFile(
                "w", delete=False, encoding="utf-8", suffix=".body"
            ) as fh:
                fh.write(body)
                body_path = fh.name
            args.extend(["--data-binary", f"@{body_path}"])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".out") as fh:
            out_path = fh.name
        args.extend(["-o", out_path, "-w", "%{http_code}"])
        args.append(url)
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout + 5, check=False
        )
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "curl failed").strip()
            if "timed out" in err.lower():
                return make_error(408, f"请求超时: {err}")
            return make_error(500, f"curl 调用失败: {err}")
        status = int((completed.stdout or "0").strip() or "0")
        with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if status >= 400:
            return make_error(status, _http_error_msg(status, text))
        if not text.strip():
            return make_ok({})
        try:
            return make_ok(json.loads(text))
        except json.JSONDecodeError as exc:
            return make_error(500, f"响应不是合法 JSON: {exc}; raw[:200]={text[:200]}")
    finally:
        for p in (body_path, out_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _http_error_msg(status: int, body_text: str) -> str:
    base = {
        400: "请求参数错误",
        401: "认证失败，请检查 N9E_USER_TOKEN 是否有效或已过期",
        403: "权限不足，无法访问该数据源 / 索引",
        404: "接口或数据源不存在，请检查 N9E_API_BASE_URL / 数据源 ID / 索引名",
        408: "请求超时",
        500: "夜莺后端错误",
        502: "网关错误",
        503: "服务暂不可用",
    }.get(status, f"HTTP {status}")
    snippet = (body_text or "").strip().replace("\n", " ")
    if len(snippet) > 400:
        snippet = snippet[:400] + "..."
    return f"{base}: {snippet}" if snippet else base


def http_request(
    method: str,
    path: str,
    *,
    json_body: Optional[Any] = None,
    raw_body: Optional[str] = None,
    content_type: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Send a request to the n9e gateway.

    Either ``json_body`` (will be JSON-encoded, content-type application/json)
    or ``raw_body`` (sent verbatim with the given ``content_type``) may be set.
    """
    err = require_config()
    if err is not None:
        return err

    url = get_base_url() + (path if path.startswith("/") else "/" + path)
    eff_timeout = timeout or get_timeout()
    body_text: Optional[str]
    eff_ct: str
    if json_body is not None and raw_body is not None:
        return make_error(500, "internal: only one of json_body / raw_body allowed")
    if json_body is not None:
        body_text = json.dumps(json_body, ensure_ascii=False)
        eff_ct = "application/json"
    elif raw_body is not None:
        body_text = raw_body
        eff_ct = content_type or "application/x-ndjson"
    else:
        body_text = None
        eff_ct = "application/json"

    # n9e is typically on an internal LAN — bypass the dev shell's http_proxy
    # by default. Set N9E_USE_HTTP_PROXY=true to opt back in.
    proxies_kw = None if use_http_proxy() else {"http": None, "https": None}

    try:
        resp = requests.request(
            method.upper(),
            url,
            headers=_build_headers({"Content-Type": eff_ct}),
            data=body_text.encode("utf-8") if body_text is not None else None,
            timeout=eff_timeout,
            proxies=proxies_kw,
        )
    except requests.exceptions.Timeout:
        return make_error(408, "请求超时，请稍后重试或缩小时间范围")
    except requests.exceptions.ConnectionError:
        # fall back to curl in restricted environments
        return _request_with_curl(
            method, url, body=body_text, content_type=eff_ct, timeout=eff_timeout
        )
    except requests.exceptions.RequestException as exc:
        return make_error(500, f"请求异常: {exc}")

    if resp.status_code >= 400:
        return make_error(resp.status_code, _http_error_msg(resp.status_code, resp.text))
    if not resp.text.strip():
        return make_ok({})
    try:
        return make_ok(resp.json())
    except ValueError as exc:
        return make_error(500, f"响应不是合法 JSON: {exc}; raw[:200]={resp.text[:200]}")


# ---------------------------------------------------------------------------
# n9e proxy helpers (ES-compat path)
# ---------------------------------------------------------------------------

def proxy_path(datasource_id: int, sub_path: str) -> str:
    sub = sub_path if sub_path.startswith("/") else "/" + sub_path
    return f"/api/n9e/proxy/{int(datasource_id)}{sub}"


def es_search(
    datasource_id: int,
    index: str,
    body: Dict[str, Any],
    *,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /api/n9e/proxy/<id>/<index>/_search."""
    safe_index = index.strip().strip("/") or "*"
    return http_request(
        "POST",
        proxy_path(datasource_id, f"/{safe_index}/_search"),
        json_body=body,
        timeout=timeout,
    )


def es_msearch(
    datasource_id: int,
    pairs: Iterable[Tuple[Dict[str, Any], Dict[str, Any]]],
    *,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /api/n9e/proxy/<id>/_msearch with newline-delimited JSON."""
    lines: List[str] = []
    for header, query in pairs:
        lines.append(json.dumps(header or {}, ensure_ascii=False))
        lines.append(json.dumps(query or {}, ensure_ascii=False))
    body = "\n".join(lines) + "\n"
    return http_request(
        "POST",
        proxy_path(datasource_id, "/_msearch"),
        raw_body=body,
        content_type="application/x-ndjson",
        timeout=timeout,
    )


def es_get(
    datasource_id: int,
    sub_path: str,
    *,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """GET /api/n9e/proxy/<id>/<sub_path> (e.g. _cat/indices, <idx>/_mapping)."""
    return http_request(
        "GET", proxy_path(datasource_id, sub_path), timeout=timeout
    )


def list_datasources() -> Dict[str, Any]:
    """List configured data sources (best-effort across n9e variants)."""
    err = require_config()
    if err is not None:
        return err

    # n9e v8 primary: POST /api/n9e/datasource/list with filter body
    res = http_request(
        "POST",
        "/api/n9e/datasource/list",
        json_body={"typ": "elasticsearch", "p": 1, "limit": 1000},
    )
    if not is_error(res):
        return res
    primary_err = res

    # fallback: GET /api/n9e/datasource/brief
    res2 = http_request("GET", "/api/n9e/datasource/brief")
    if not is_error(res2):
        return res2

    # surface the primary error since brief is a coarser fallback
    return primary_err


# ---------------------------------------------------------------------------
# DSL builders
# ---------------------------------------------------------------------------

def build_query_dsl(
    *,
    query_string: Optional[str],
    from_ms: int,
    to_ms: int,
    timestamp_field: Optional[str] = None,
    extra_filters: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build an ES `query` clause that combines a Lucene query string with a
    time-range filter on the configured timestamp field."""
    ts_field = timestamp_field or get_timestamp_field()
    must: List[Dict[str, Any]] = []
    if query_string and query_string.strip():
        must.append({
            "query_string": {
                "query": query_string.strip(),
                "analyze_wildcard": True,
                "default_operator": "AND",
            }
        })
    filt: List[Dict[str, Any]] = [
        {
            "range": {
                ts_field: {
                    "gte": from_ms,
                    "lte": to_ms,
                    "format": "epoch_millis",
                }
            }
        }
    ]
    if extra_filters:
        filt.extend(extra_filters)
    return {"bool": {"must": must, "filter": filt}}


def build_search_body(
    *,
    query: Dict[str, Any],
    size: int,
    sort_field: Optional[str] = None,
    sort_order: str = "desc",
    fields: Optional[List[str]] = None,
    aggs: Optional[Dict[str, Any]] = None,
    track_total_hits: bool = True,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "size": max(0, int(size)),
        "query": query,
        "track_total_hits": track_total_hits,
    }
    if sort_field:
        body["sort"] = [{sort_field: {"order": sort_order}}]
    if fields:
        body["_source"] = list(fields)
    if aggs:
        body["aggs"] = aggs
    return body


# ---------------------------------------------------------------------------
# small utilities for output
# ---------------------------------------------------------------------------

def stdout_json(payload: Any) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    )


def truncate(text: str, limit: int = 200) -> str:
    if text is None:
        return ""
    s = str(text).replace("\n", " ").replace("\r", " ").strip()
    if len(s) <= limit:
        return s
    return s[:limit] + "..."


def deep_get(obj: Any, dotted: str, default: Any = None) -> Any:
    """Best-effort lookup of a dotted path inside a nested dict, with a literal
    fallback (some ES sources put fields in flat dotted keys)."""
    if obj is None:
        return default
    if dotted in obj:
        return obj[dotted]
    cur: Any = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def first_non_empty(*values: Any) -> Any:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None
