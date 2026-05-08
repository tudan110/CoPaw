#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nightingale (n9e) log query — aggregations.

Modes:
- count     : total hit count for a query/time range
- level     : breakdown by log level (auto-probes log.level / level / severity)
- host      : breakdown by host (auto-probes host.name / hostname / ...)
- service   : breakdown by service (auto-probes service.name / service / app)
- terms     : generic terms aggregation on --field
- histogram : date histogram on the timestamp field

Examples:
    uv run scripts/n9e_log_aggregate.py --mode count --from-time now-1h
    uv run scripts/n9e_log_aggregate.py --mode level --from-time now-1h --output markdown
    uv run scripts/n9e_log_aggregate.py --mode host  --query 'level:ERROR' --top 10
    uv run scripts/n9e_log_aggregate.py --mode terms --field log.level --top 5
    uv run scripts/n9e_log_aggregate.py --mode histogram --interval 1m --from-time now-1h
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

import _n9e_client as nc  # type: ignore[import-not-found]


# Probe order for "vague" categorical aggregations. We send the first one to ES
# wrapped in an `exists` filter; if the bucket count is zero we fall through to
# the next candidate. Each `(label_field, agg_field)` pair is a (filter_field,
# bucket_field) — when the field has a `keyword` sub-field, ES needs the
# keyword form for term aggregations.
_LEVEL_CANDIDATES: List[Tuple[str, str]] = [
    ("log_level", "log_level.keyword"),
    ("log_level", "log_level"),
    ("log.level", "log.level.keyword"),
    ("log.level", "log.level"),
    ("level", "level.keyword"),
    ("level", "level"),
    ("severity", "severity.keyword"),
    ("severity", "severity"),
]
_HOST_CANDIDATES: List[Tuple[str, str]] = [
    ("agent_hostname", "agent_hostname.keyword"),
    ("agent_hostname", "agent_hostname"),
    ("host.name", "host.name.keyword"),
    ("host.name", "host.name"),
    ("hostname", "hostname.keyword"),
    ("hostname", "hostname"),
    ("agent.hostname", "agent.hostname.keyword"),
    ("agent.hostname", "agent.hostname"),
    ("syslog_hostname", "syslog_hostname.keyword"),
    ("syslog_hostname", "syslog_hostname"),
]
_SERVICE_CANDIDATES: List[Tuple[str, str]] = [
    ("fcservice", "fcservice.keyword"),
    ("fcservice", "fcservice"),
    ("service.name", "service.name.keyword"),
    ("service.name", "service.name"),
    ("service", "service.keyword"),
    ("service", "service"),
    ("app", "app.keyword"),
    ("app", "app"),
    ("syslog_program", "syslog_program.keyword"),
    ("syslog_program", "syslog_program"),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _resolve_ds_id(args: argparse.Namespace) -> Optional[int]:
    if getattr(args, "datasource", None):
        try:
            return int(args.datasource)
        except (ValueError, TypeError):
            return None
    return nc.get_default_datasource_id()


def _ds_index_or_error(args: argparse.Namespace) -> Tuple[Optional[int], Optional[str], Optional[Dict[str, Any]]]:
    ds_id = _resolve_ds_id(args)
    if ds_id is None:
        return None, None, nc.make_error(
            400,
            "未指定日志数据源 ID。请通过 --datasource <id> 或 .env 中 N9E_LOG_DATASOURCE_ID 设置。",
        )
    index = args.index or nc.get_default_index()
    return ds_id, index, None


def _time_range(args: argparse.Namespace) -> Tuple[Optional[int], Optional[int], Optional[Dict[str, Any]]]:
    try:
        from_ms = nc.parse_time(args.from_time, default="now-1h")
        to_ms = nc.parse_time(args.to_time, default="now")
    except ValueError as exc:
        return None, None, nc.make_error(400, str(exc))
    if from_ms >= to_ms:
        return None, None, nc.make_error(400, "时间范围非法：from-time 必须早于 to-time")
    return from_ms, to_ms, None


def _run_terms_agg(
    *,
    ds_id: int,
    index: str,
    query_string: Optional[str],
    from_ms: int,
    to_ms: int,
    candidates: List[Tuple[str, str]],
    explicit_field: Optional[str],
    top: int,
) -> Dict[str, Any]:
    """Try candidate fields in order until one returns non-empty buckets."""
    pairs: List[Tuple[str, str]]
    if explicit_field:
        # explicit field — try `.keyword` first, then bare
        pairs = [(explicit_field, f"{explicit_field}.keyword"), (explicit_field, explicit_field)]
    else:
        pairs = candidates

    last_envelope: Optional[Dict[str, Any]] = None
    for filter_field, bucket_field in pairs:
        body = nc.build_search_body(
            query=nc.build_query_dsl(
                query_string=query_string,
                from_ms=from_ms,
                to_ms=to_ms,
                extra_filters=[{"exists": {"field": filter_field}}],
            ),
            size=0,
            aggs={
                "by_field": {
                    "terms": {"field": bucket_field, "size": max(1, int(top)), "missing": "(unknown)"}
                }
            },
        )
        res = nc.es_search(ds_id, index, body)
        if nc.is_error(res):
            last_envelope = res
            continue
        buckets = (
            ((res.get("data") or {}).get("aggregations") or {})
            .get("by_field", {})
            .get("buckets")
            or []
        )
        # if ES rejected `.keyword` it would have errored; non-empty means we matched
        if buckets:
            total = ((res.get("data") or {}).get("hits") or {}).get("total") or {}
            total_value = total.get("value") if isinstance(total, dict) else (total or 0)
            return nc.make_ok(
                {
                    "field": bucket_field,
                    "total": int(total_value or 0),
                    "buckets": [
                        {"key": str(b.get("key")), "count": int(b.get("doc_count") or 0)}
                        for b in buckets
                    ],
                }
            )
        # zero buckets — fall through, but remember the envelope
        last_envelope = res
    if last_envelope and not nc.is_error(last_envelope):
        return nc.make_ok({"field": pairs[0][1], "total": 0, "buckets": []})
    return last_envelope or nc.make_error(500, "聚合失败：无可用字段")


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------

def _cmd_count(args: argparse.Namespace) -> Dict[str, Any]:
    ds_id, index, err = _ds_index_or_error(args)
    if err is not None:
        return err
    from_ms, to_ms, err = _time_range(args)
    if err is not None:
        return err
    body = nc.build_search_body(
        query=nc.build_query_dsl(
            query_string=args.query, from_ms=from_ms, to_ms=to_ms
        ),
        size=0,
    )
    res = nc.es_search(ds_id, index, body)
    if nc.is_error(res):
        return res
    total = ((res.get("data") or {}).get("hits") or {}).get("total") or {}
    value = total.get("value") if isinstance(total, dict) else (total or 0)
    return nc.make_ok(
        {
            "datasource_id": ds_id,
            "index": index,
            "from_ms": from_ms,
            "to_ms": to_ms,
            "query": args.query or "",
            "total": int(value or 0),
        }
    )


def _cmd_terms_like(args: argparse.Namespace, candidates: List[Tuple[str, str]], label: str) -> Dict[str, Any]:
    ds_id, index, err = _ds_index_or_error(args)
    if err is not None:
        return err
    from_ms, to_ms, err = _time_range(args)
    if err is not None:
        return err
    res = _run_terms_agg(
        ds_id=ds_id,
        index=index,
        query_string=args.query,
        from_ms=from_ms,
        to_ms=to_ms,
        candidates=candidates,
        explicit_field=args.field,
        top=args.top,
    )
    if nc.is_error(res):
        return res
    data = res["data"]
    data.update(
        {
            "datasource_id": ds_id,
            "index": index,
            "from_ms": from_ms,
            "to_ms": to_ms,
            "query": args.query or "",
            "label": label,
        }
    )
    return res


def _cmd_histogram(args: argparse.Namespace) -> Dict[str, Any]:
    ds_id, index, err = _ds_index_or_error(args)
    if err is not None:
        return err
    from_ms, to_ms, err = _time_range(args)
    if err is not None:
        return err
    interval = args.interval or "1m"
    body = nc.build_search_body(
        query=nc.build_query_dsl(
            query_string=args.query, from_ms=from_ms, to_ms=to_ms
        ),
        size=0,
        aggs={
            "ts": {
                "date_histogram": {
                    "field": nc.get_timestamp_field(),
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                    "extended_bounds": {"min": from_ms, "max": to_ms},
                }
            }
        },
    )
    res = nc.es_search(ds_id, index, body)
    if nc.is_error(res):
        return res
    buckets = (
        ((res.get("data") or {}).get("aggregations") or {})
        .get("ts", {})
        .get("buckets", [])
        or []
    )
    total = ((res.get("data") or {}).get("hits") or {}).get("total") or {}
    total_value = total.get("value") if isinstance(total, dict) else (total or 0)
    return nc.make_ok(
        {
            "datasource_id": ds_id,
            "index": index,
            "from_ms": from_ms,
            "to_ms": to_ms,
            "query": args.query or "",
            "interval": interval,
            "total": int(total_value or 0),
            "buckets": [
                {"ts_ms": int(b.get("key") or 0), "count": int(b.get("doc_count") or 0)}
                for b in buckets
            ],
        }
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _render(result: Dict[str, Any], mode: str, output: str) -> str:
    if nc.is_error(result):
        return _render_error(result)
    if output == "json":
        return json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"

    data = result.get("data") or {}
    if mode == "count":
        return _render_count(data, output)
    if mode == "histogram":
        return _render_histogram(data, output)
    return _render_terms(data, mode, output)


def _render_count(data: Dict[str, Any], output: str) -> str:
    if output == "markdown-echarts-only":
        return ""  # nothing graphical for a scalar
    return (
        "# 智观日志计数\n\n"
        f"- 数据源 ID：`{data.get('datasource_id')}`\n"
        f"- 索引：`{data.get('index')}`\n"
        f"- 时间范围：`{nc.format_ms(data.get('from_ms') or 0)}`"
        f" ~ `{nc.format_ms(data.get('to_ms') or 0)}`\n"
        f"- 查询：`{data.get('query') or '(空)'}`\n"
        f"- **命中数：{data.get('total', 0)}**\n"
    )


def _render_terms(data: Dict[str, Any], mode: str, output: str) -> str:
    buckets = data.get("buckets") or []
    title_map = {
        "level": "智观日志按级别统计",
        "host": "智观日志按主机统计",
        "service": "智观日志按服务统计",
        "terms": f"智观日志按 `{data.get('field') or 'field'}` 统计",
    }
    title = title_map.get(mode, "智观日志聚合统计")
    chart_type = "pie" if mode in {"level", "service"} else "bar"
    chart = _build_terms_echarts(title, buckets, chart_type)

    if output == "markdown-echarts-only":
        return chart + "\n"

    md = [
        f"# {title}",
        "",
        f"- 数据源 ID：`{data.get('datasource_id')}`",
        f"- 索引：`{data.get('index')}`",
        f"- 时间范围：`{nc.format_ms(data.get('from_ms') or 0)}` ~ `{nc.format_ms(data.get('to_ms') or 0)}`",
        f"- 查询：`{data.get('query') or '(空)'}`",
        f"- 字段：`{data.get('field') or '?'}`",
        f"- 命中：**{data.get('total', 0)}** 条",
        "",
    ]
    if not buckets:
        md.append("_未命中或字段不存在；可换字段、放宽时间范围、或检查 `n9e_log_meta.py --mode fields`_")
        return "\n".join(md) + "\n"
    md.append("| Key | 计数 |")
    md.append("|-----|----:|")
    for b in buckets:
        md.append(f"| {b.get('key', '')} | {b.get('count', 0)} |")
    md.append("")
    md.append(chart)
    return "\n".join(md) + "\n"


def _render_histogram(data: Dict[str, Any], output: str) -> str:
    buckets = data.get("buckets") or []
    interval = data.get("interval", "1m")
    chart = _build_histogram_echarts(buckets, interval)
    if output == "markdown-echarts-only":
        return chart + "\n"

    md = [
        "# 智观日志时间分布",
        "",
        f"- 数据源 ID：`{data.get('datasource_id')}`",
        f"- 索引：`{data.get('index')}`",
        f"- 时间范围：`{nc.format_ms(data.get('from_ms') or 0)}` ~ `{nc.format_ms(data.get('to_ms') or 0)}`",
        f"- 查询：`{data.get('query') or '(空)'}`",
        f"- 步长：`{interval}`",
        f"- 命中：**{data.get('total', 0)}** 条，桶数 {len(buckets)}",
        "",
    ]
    if not buckets:
        md.append("_未命中。可放宽时间范围或调整查询。_")
        return "\n".join(md) + "\n"
    md.append(chart)
    return "\n".join(md) + "\n"


def _build_terms_echarts(title: str, buckets: List[Dict[str, Any]], chart_type: str) -> str:
    if not buckets:
        return ""
    if chart_type == "pie":
        option = {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item"},
            "legend": {"orient": "vertical", "left": "left"},
            "series": [
                {
                    "name": title,
                    "type": "pie",
                    "radius": ["40%", "70%"],
                    "data": [
                        {"name": str(b.get("key", "")), "value": int(b.get("count") or 0)}
                        for b in buckets
                    ],
                }
            ],
        }
    else:
        option = {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {
                "type": "category",
                "data": [str(b.get("key", "")) for b in buckets],
                "axisLabel": {"interval": 0, "rotate": 30},
            },
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "data": [int(b.get("count") or 0) for b in buckets],
                }
            ],
        }
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, indent=2) + "\n```"


def _build_histogram_echarts(buckets: List[Dict[str, Any]], interval: str) -> str:
    if not buckets:
        return ""
    option = {
        "title": {"text": f"日志数变化（步长 {interval}）", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": [nc.format_ms(int(b.get("ts_ms") or 0)) for b in buckets],
            "axisLabel": {"rotate": 30},
        },
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "smooth": True,
                "areaStyle": {},
                "data": [int(b.get("count") or 0) for b in buckets],
            }
        ],
    }
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, indent=2) + "\n```"


def _render_error(envelope: Dict[str, Any]) -> str:
    return (
        "# 智观日志聚合失败\n\n"
        f"- 错误码：`{envelope.get('code')}`\n"
        f"- 错误信息：{envelope.get('msg')}\n"
    )


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Nightingale (n9e) log aggregation")
    p.add_argument(
        "--mode",
        required=True,
        choices=["count", "level", "host", "service", "terms", "histogram"],
    )
    p.add_argument("--datasource", help="数据源 ID（覆盖 .env 默认）")
    p.add_argument("--index", help="索引或索引模式（覆盖 .env 默认）")
    p.add_argument("--query", default="", help="Lucene query_string")
    p.add_argument("--from-time", default="now-1h", help="起始时间")
    p.add_argument("--to-time", default="now", help="结束时间")
    p.add_argument("--field", help="(terms 模式) 聚合字段名")
    p.add_argument("--top", type=int, default=10, help="terms / level / host / service 的桶数")
    p.add_argument("--interval", default="1m", help="(histogram 模式) ES fixed_interval，例如 1m, 5m, 1h")
    p.add_argument(
        "--output",
        choices=["json", "markdown", "markdown-echarts-only"],
        default="markdown",
    )
    args = p.parse_args()

    # If the user pinned the field via .env, treat it as an explicit override
    # for the matching mode so we don't pay the candidate-probe cost.
    if args.mode == "level" and not args.field and nc.get_level_field():
        args.field = nc.get_level_field()
    elif args.mode == "host" and not args.field and nc.get_host_field():
        args.field = nc.get_host_field()
    elif args.mode == "service" and not args.field and nc.get_service_field():
        args.field = nc.get_service_field()

    if args.mode == "count":
        result = _cmd_count(args)
    elif args.mode == "level":
        result = _cmd_terms_like(args, _LEVEL_CANDIDATES, "level")
    elif args.mode == "host":
        result = _cmd_terms_like(args, _HOST_CANDIDATES, "host")
    elif args.mode == "service":
        result = _cmd_terms_like(args, _SERVICE_CANDIDATES, "service")
    elif args.mode == "terms":
        if not args.field:
            result = nc.make_error(400, "--field 必填（terms 模式需要明确字段名）")
        else:
            result = _cmd_terms_like(args, [(args.field, f"{args.field}.keyword"), (args.field, args.field)], args.field)
    elif args.mode == "histogram":
        result = _cmd_histogram(args)
    else:
        result = nc.make_error(400, f"未知 mode: {args.mode}")

    sys.stdout.write(_render(result, args.mode, args.output))
    return 0 if not nc.is_error(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
