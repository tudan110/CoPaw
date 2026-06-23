#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nightingale (n9e) log query — search hits.

Examples:
    python3 scripts/n9e_log_query.py --from-time now-15m --size 20 --output markdown
    python3 scripts/n9e_log_query.py --query 'level:ERROR' --from-time now-1h
    python3 scripts/n9e_log_query.py --query 'message:"connection refused"'
    python3 scripts/n9e_log_query.py --query 'service:nginx AND level:ERROR' \\
        --from-time now-30m --size 50 --output markdown
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

import _n9e_client as nc  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# common field probing — many indices use slightly different field names
# ---------------------------------------------------------------------------

_LEVEL_CANDIDATES = [
    "log_level", "log.level", "level", "severity", "loglevel",
    "raw_event.log_level",
]
_HOST_CANDIDATES = [
    "agent_hostname", "host.name", "host.hostname", "agent.hostname",
    "hostname", "syslog_hostname", "beat.hostname", "nodename", "host",
    "raw_event.agent_hostname",
]
_SERVICE_CANDIDATES = [
    "fcservice", "service.name", "service", "app", "application",
    "syslog_program", "kubernetes.labels.app", "container.name",
    "raw_event.fcservice",
]
# n9e/Categraf-collected logs typically put the rendered log line into
# `app_json` and the raw syslog frame into `raw_event.message`. We try those
# first, then standard ECS / generic field names.
_MESSAGE_CANDIDATES = [
    "app_json", "message", "msg", "log.message", "log",
    "raw_event.message", "_raw",
]


def _pick(source: Dict[str, Any], candidates: List[str], override: Optional[str]) -> str:
    if override:
        v = nc.deep_get(source, override)
        if v not in (None, ""):
            return _stringify(v)
    for cand in candidates:
        v = nc.deep_get(source, cand)
        if v not in (None, ""):
            return _stringify(v)
    return ""


def _stringify(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(_stringify(x) for x in v if x is not None)
    if isinstance(v, dict):
        # prefer a `name` / `keyword` if present
        for k in ("name", "keyword", "value"):
            if k in v:
                return _stringify(v[k])
        return str(v)
    return str(v)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def _do_search(args: argparse.Namespace) -> Dict[str, Any]:
    from_ms = nc.parse_time(args.from_time, default="now-15m")
    to_ms = nc.parse_time(args.to_time, default="now")
    if from_ms >= to_ms:
        return nc.make_error(400, "时间范围非法：from-time 必须早于 to-time")

    ds_id = _resolve_ds_id(args)
    if ds_id is None:
        return nc.make_error(
            400,
            "未指定日志数据源 ID。请通过 --datasource <id> 传入，"
            "或在 .env 里设置 N9E_LOG_DATASOURCE_ID。",
        )
    index = args.index or nc.get_default_index()

    size = max(0, min(int(args.size or 20), nc.get_max_size()))
    sort_field = args.sort_field or nc.get_timestamp_field()
    sort_order = "asc" if (args.sort_order or "desc").lower() == "asc" else "desc"
    fields_filter = (
        [f.strip() for f in args.fields.split(",") if f.strip()]
        if args.fields
        else None
    )

    query = nc.build_query_dsl(
        query_string=args.query,
        from_ms=from_ms,
        to_ms=to_ms,
        timestamp_field=nc.get_timestamp_field(),
    )
    body = nc.build_search_body(
        query=query,
        size=size,
        sort_field=sort_field,
        sort_order=sort_order,
        fields=fields_filter,
    )
    res = nc.es_search(ds_id, index, body)
    if nc.is_error(res):
        return res

    raw = res.get("data") or {}
    hits_obj = raw.get("hits") or {}
    total_raw = hits_obj.get("total")
    total = total_raw.get("value") if isinstance(total_raw, dict) else (total_raw or 0)
    hits = hits_obj.get("hits") or []

    level_override = args.level_field or nc.get_level_field()
    host_override = args.host_field or nc.get_host_field()
    service_override = args.service_field or nc.get_service_field()

    rows = [
        {
            "ts_ms": _hit_ts_ms(h, nc.get_timestamp_field()),
            "level": _pick(h.get("_source") or {}, _LEVEL_CANDIDATES, level_override),
            "host": _pick(h.get("_source") or {}, _HOST_CANDIDATES, host_override),
            "service": _pick(h.get("_source") or {}, _SERVICE_CANDIDATES, service_override),
            "message": _pick(h.get("_source") or {}, _MESSAGE_CANDIDATES, None),
            "_source": h.get("_source"),
            "_index": h.get("_index"),
            "_id": h.get("_id"),
        }
        for h in hits
    ]
    return nc.make_ok(
        {
            "total": int(total or 0),
            "returned": len(rows),
            "datasource_id": ds_id,
            "index": index,
            "from_ms": from_ms,
            "to_ms": to_ms,
            "query": args.query or "",
            "rows": rows,
        }
    )


def _hit_ts_ms(hit: Dict[str, Any], ts_field: str) -> Optional[int]:
    src = hit.get("_source") or {}
    val = nc.deep_get(src, ts_field)
    if val is None:
        return None
    if isinstance(val, (int, float)):
        v = int(val)
        # crude unit detection (ms vs s)
        return v if v > 10**12 else v * 1000
    if isinstance(val, str):
        try:
            return nc.parse_time(val)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _render_markdown(result: Dict[str, Any], show_raw: bool) -> str:
    if nc.is_error(result):
        return _render_error(result)
    data = result.get("data") or {}
    rows = data.get("rows") or []
    total = data.get("total") or 0
    from_ms = data.get("from_ms") or 0
    to_ms = data.get("to_ms") or 0
    query = data.get("query") or ""
    ds_id = data.get("datasource_id")
    index = data.get("index")

    md = [
        "# 智观日志检索结果",
        "",
        f"- 数据源 ID：`{ds_id}`",
        f"- 索引：`{index}`",
        f"- 时间范围：`{nc.format_ms(from_ms)}` ~ `{nc.format_ms(to_ms)}`",
        f"- 查询：`{query or '(空，仅按时间过滤)'}`",
        f"- 命中：**{total}** 条，本次返回 **{len(rows)}** 条",
        "",
    ]
    if not rows:
        md.append("_未命中日志。可放宽时间范围或调整关键字。_")
        return "\n".join(md)

    md.append("| 时间 | 级别 | 主机 | 服务 | 摘要 |")
    md.append("|------|------|------|------|------|")
    for r in rows:
        ts = nc.format_ms(r["ts_ms"]) if r.get("ts_ms") else ""
        msg = nc.truncate(r.get("message") or "", 200)
        md.append(
            f"| {ts} | {r.get('level', '')} | {r.get('host', '')} | "
            f"{r.get('service', '')} | {_md_escape(msg)} |"
        )

    if show_raw:
        import json

        md.append("")
        md.append("## 原始命中（前 5 条 _source）")
        md.append("")
        for r in rows[:5]:
            md.append("```json")
            md.append(
                json.dumps(r.get("_source") or {}, ensure_ascii=False, indent=2, default=str)
            )
            md.append("```")
    return "\n".join(md) + "\n"


def _md_escape(text: str) -> str:
    if not text:
        return ""
    return text.replace("|", "\\|")


def _render_error(envelope: Dict[str, Any]) -> str:
    return (
        "# 智观日志检索失败\n\n"
        f"- 错误码：`{envelope.get('code')}`\n"
        f"- 错误信息：{envelope.get('msg')}\n"
    )


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def _resolve_ds_id(args: argparse.Namespace) -> Optional[int]:
    if getattr(args, "datasource", None):
        try:
            return int(args.datasource)
        except (ValueError, TypeError):
            return None
    return nc.get_default_datasource_id()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Nightingale (n9e) log query — search hits"
    )
    p.add_argument("--datasource", help="数据源 ID（覆盖 .env 默认）")
    p.add_argument("--index", help="索引或索引模式（覆盖 .env 默认）")
    p.add_argument(
        "--query",
        default="",
        help="Lucene query_string，例如 'level:ERROR AND service:nginx'",
    )
    p.add_argument("--from-time", default="now-15m", help="起始时间（ISO 或 now-15m）")
    p.add_argument("--to-time", default="now", help="结束时间（ISO 或 now）")
    p.add_argument("--size", type=int, default=20, help="返回最多多少条（默认 20）")
    p.add_argument("--fields", help="逗号分隔的 _source 字段过滤")
    p.add_argument("--sort-field", help="排序字段（默认时间字段）")
    p.add_argument("--sort-order", choices=["asc", "desc"], default="desc")
    p.add_argument("--level-field", help="级别字段名（覆盖自动探测）")
    p.add_argument("--host-field", help="主机字段名（覆盖自动探测）")
    p.add_argument("--service-field", help="服务字段名（覆盖自动探测）")
    p.add_argument(
        "--show-raw",
        action="store_true",
        help="markdown 输出时附带前 5 条 _source",
    )
    p.add_argument("--output", choices=["json", "markdown"], default="markdown")
    args = p.parse_args()

    try:
        result = _do_search(args)
    except ValueError as exc:
        result = nc.make_error(400, str(exc))

    if args.output == "json":
        nc.stdout_json(result)
    else:
        sys.stdout.write(_render_markdown(result, args.show_raw))

    return 0 if not nc.is_error(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
