#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests>=2.31.0",
#     "python-dotenv>=1.0.0",
#     "drain3>=0.9.11",
# ]
# ///
"""log-hazard-detection — single-window log clustering.

Pulls a sample of recent logs from n9e/ES, runs Drain3 in-memory template
mining, and reports the dominant templates with frequency, hosts, services,
and an `error_score` so a hazard model can rank "weird-looking" templates.

Examples:
    python3 scripts/n9e_log_cluster.py --from-time now-15m --top 20 --output markdown
    python3 scripts/n9e_log_cluster.py --query 'level:ERROR' --from-time now-1h --output markdown
    python3 scripts/n9e_log_cluster.py --from-time now-15m --output markdown-echarts-only
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

import _drain_helper as dh  # type: ignore[import-not-found]
import _n9e_client as nc  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# argument shaping
# ---------------------------------------------------------------------------

def _resolve_ds_id(args: argparse.Namespace) -> Optional[int]:
    if getattr(args, "datasource", None):
        try:
            return int(args.datasource)
        except (ValueError, TypeError):
            return None
    return nc.get_default_datasource_id()


def _ds_index(args: argparse.Namespace) -> Tuple[Optional[int], Optional[str], Optional[Dict[str, Any]]]:
    ds_id = _resolve_ds_id(args)
    if ds_id is None:
        return None, None, nc.make_error(
            400,
            "未指定日志数据源 ID。请通过 --datasource <id> 或 .env 中 N9E_LOG_DATASOURCE_ID 设置。",
        )
    return ds_id, args.index or nc.get_default_index(), None


def _time_range(args: argparse.Namespace) -> Tuple[Optional[int], Optional[int], Optional[Dict[str, Any]]]:
    try:
        from_ms = nc.parse_time(args.from_time, default="now-15m")
        to_ms = nc.parse_time(args.to_time, default="now")
    except ValueError as exc:
        return None, None, nc.make_error(400, str(exc))
    if from_ms >= to_ms:
        return None, None, nc.make_error(400, "时间范围非法：from-time 必须早于 to-time")
    return from_ms, to_ms, None


# ---------------------------------------------------------------------------
# fetch + fit
# ---------------------------------------------------------------------------

def _resolve_sample_size(requested: int) -> int:
    cap = nc.get_max_size()
    return max(1, min(int(requested), cap))


def _fetch_hits(
    *,
    ds_id: int,
    index: str,
    query_string: Optional[str],
    from_ms: int,
    to_ms: int,
    sample_size: int,
    sample_mode: str,
) -> Dict[str, Any]:
    """Pull a sample of hits with track_total_hits so we can show the sampling
    ratio and decide whether to switch to random_score sampling."""
    base_query = nc.build_query_dsl(
        query_string=query_string, from_ms=from_ms, to_ms=to_ms
    )
    if sample_mode == "random":
        wrapped_query = {
            "function_score": {
                "query": base_query,
                "random_score": {},
                "boost_mode": "replace",
            }
        }
        body: Dict[str, Any] = {
            "size": sample_size,
            "query": wrapped_query,
            "track_total_hits": True,
        }
    else:
        sort_order = "desc" if sample_mode == "tail" else "asc"
        body = nc.build_search_body(
            query=base_query,
            size=sample_size,
            sort_field=nc.get_timestamp_field(),
            sort_order=sort_order,
            track_total_hits=True,
        )
    return nc.es_search(ds_id, index, body)


def run_cluster(args: argparse.Namespace) -> Dict[str, Any]:
    ds_id, index, err = _ds_index(args)
    if err is not None:
        return err
    from_ms, to_ms, err = _time_range(args)
    if err is not None:
        return err

    sample_size = _resolve_sample_size(args.sample_size)

    res = _fetch_hits(
        ds_id=ds_id,
        index=index,
        query_string=args.query,
        from_ms=from_ms,
        to_ms=to_ms,
        sample_size=sample_size,
        sample_mode=args.sample_mode,
    )
    if nc.is_error(res):
        return res

    es_data = res.get("data") or {}
    hits_block = es_data.get("hits") or {}
    total_block = hits_block.get("total") or {}
    total_value = (
        int(total_block.get("value") or 0)
        if isinstance(total_block, dict)
        else int(total_block or 0)
    )
    raw_hits = hits_block.get("hits") or []

    # Auto-fall back to random_score sampling when the requested window has way
    # more than we can fit; surface the ratio to the user so they know.
    auto_random = False
    if args.sample_mode == "tail" and total_value > sample_size * 4:
        random_res = _fetch_hits(
            ds_id=ds_id,
            index=index,
            query_string=args.query,
            from_ms=from_ms,
            to_ms=to_ms,
            sample_size=sample_size,
            sample_mode="random",
        )
        if not nc.is_error(random_res):
            res = random_res
            es_data = random_res.get("data") or {}
            raw_hits = (es_data.get("hits") or {}).get("hits") or []
            auto_random = True

    message_fields = [
        f.strip() for f in (args.message_fields or "").split(",") if f.strip()
    ] or list(dh.DEFAULT_MESSAGE_FIELDS)

    fit = dh.fit_hits(
        raw_hits,
        message_fields=message_fields,
        max_clusters=args.max_clusters,
        sim_th=args.sim_th,
    )

    templates = [t for t in fit["templates"] if t["count"] >= args.min_count]
    templates = templates[: args.top]

    sample_ratio = (len(raw_hits) / total_value) if total_value else 1.0

    return nc.make_ok(
        {
            "datasource_id": ds_id,
            "index": index,
            "from_ms": from_ms,
            "to_ms": to_ms,
            "query": args.query or "",
            "total": total_value,
            "fetched": len(raw_hits),
            "fit_count": fit["fit_count"],
            "skipped_count": fit["skipped_count"],
            "sample_mode": "random" if auto_random else args.sample_mode,
            "auto_sampled": auto_random,
            "sample_ratio": round(sample_ratio, 4),
            "fields_used": fit["fields_used"],
            "message_fields_requested": message_fields,
            "templates": templates,
            "min_count": args.min_count,
            "top": args.top,
        }
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _build_pie(templates: List[Dict[str, Any]]) -> str:
    if not templates:
        return ""
    title = "日志模板 Top 分布"
    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item"},
        "legend": {"orient": "vertical", "left": "left", "type": "scroll"},
        "series": [
            {
                "name": title,
                "type": "pie",
                "radius": ["35%", "65%"],
                "data": [
                    {"name": nc.truncate(t["template"], 40), "value": int(t["count"])}
                    for t in templates
                ],
            }
        ],
    }
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, indent=2) + "\n```"


def _build_bar(templates: List[Dict[str, Any]]) -> str:
    if not templates:
        return ""
    title = "日志模板命中数 Top"
    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": [f"#{t['id']}" for t in templates],
            "axisLabel": {"interval": 0, "rotate": 30},
        },
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "bar",
                "data": [int(t["count"]) for t in templates],
            }
        ],
    }
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, indent=2) + "\n```"


def _render_markdown(data: Dict[str, Any], echarts_only: bool) -> str:
    templates: List[Dict[str, Any]] = data.get("templates") or []
    pie = _build_pie(templates)
    bar = _build_bar(templates)
    if echarts_only:
        return ((pie + "\n" + bar) if pie or bar else "") + "\n"

    md = [
        "# 智观日志模板挖掘（Drain3）",
        "",
        f"- 数据源 ID：`{data.get('datasource_id')}`",
        f"- 索引：`{data.get('index')}`",
        f"- 时间范围：`{nc.format_ms(data.get('from_ms') or 0)}`"
        f" ~ `{nc.format_ms(data.get('to_ms') or 0)}`",
        f"- 查询：`{data.get('query') or '(空)'}`",
        f"- 命中总数：**{data.get('total', 0)}**，本次抽样：**{data.get('fetched', 0)}**"
        f"（采样比 {round((data.get('sample_ratio') or 0) * 100, 2)}%，"
        f"sample_mode={data.get('sample_mode')}{'，自动降级为 random' if data.get('auto_sampled') else ''}）",
        f"- 实际入参字段：{('、'.join(data.get('fields_used') or []) or '无')}"
        f"（请求字段：{', '.join(data.get('message_fields_requested') or [])}）",
        f"- 模板总数：**{len(templates)}**（min_count={data.get('min_count')}，"
        f"top={data.get('top')}）",
        "",
    ]
    if not templates:
        md.append("_未挖掘出任何模板。可放宽 --query / --from-time、增大 --sample-size，或检查 --message-fields 是否存在。_")
        return "\n".join(md) + "\n"

    md.append("| # | 命中 | 占比 | 错误密度 | 主机 Top | 服务 Top | 模板 |")
    md.append("|---|----:|----:|------:|---------|---------|-----|")
    total = sum(t["count"] for t in templates) or 1
    for t in templates:
        pct = (t["count"] / total) * 100
        hosts = ", ".join(
            f"{h['key']}({h['count']})" for h in (t.get("hosts") or [])[:3]
        ) or "—"
        services = ", ".join(
            f"{s['key']}({s['count']})" for s in (t.get("services") or [])[:3]
        ) or "—"
        md.append(
            f"| #{t['id']} | {t['count']} | {pct:.1f}% | {t['error_score']:.2f} | "
            f"{hosts} | {services} | `{nc.truncate(t['template'], 100)}` |"
        )
    md.append("")
    if pie:
        md.append(pie)
        md.append("")
    if bar:
        md.append(bar)
    return "\n".join(md) + "\n"


def _render(envelope: Dict[str, Any], output: str) -> str:
    if nc.is_error(envelope):
        return (
            "# 智观日志聚类失败\n\n"
            f"- 错误码：`{envelope.get('code')}`\n"
            f"- 错误信息：{envelope.get('msg')}\n"
        )
    if output == "json":
        return json.dumps(envelope, ensure_ascii=False, indent=2, default=str) + "\n"
    return _render_markdown(envelope.get("data") or {}, echarts_only=output == "markdown-echarts-only")


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Nightingale log clustering (Drain3)")
    p.add_argument("--datasource", help="数据源 ID（覆盖 .env 默认）")
    p.add_argument("--index", help="索引或索引模式（覆盖 .env 默认）")
    p.add_argument("--query", default="", help="预过滤 Lucene query_string")
    p.add_argument("--from-time", default="now-15m", help="起始时间")
    p.add_argument("--to-time", default="now", help="结束时间")
    p.add_argument("--sample-size", type=int, default=2000, help="本次最多抽多少条入 drain3")
    p.add_argument("--sample-mode", choices=["tail", "head", "random"], default="tail")
    p.add_argument("--top", type=int, default=30, help="模板表显示上限")
    p.add_argument("--min-count", type=int, default=2, help="少于该计数的模板不进表")
    p.add_argument("--message-fields", default="app_json,message", help="逗号分隔的字段名，按顺序拼接为 drain3 输入行")
    p.add_argument("--max-clusters", type=int, default=2000, help="drain3 最大簇数（兜底）")
    p.add_argument("--sim-th", type=float, default=0.4, help="drain3 simTh（相似度阈值）")
    p.add_argument(
        "--output",
        choices=["json", "markdown", "markdown-echarts-only"],
        default="markdown",
    )
    args = p.parse_args()

    try:
        result = run_cluster(args)
    except RuntimeError as exc:
        result = nc.make_error(500, str(exc))

    sys.stdout.write(_render(result, args.output))
    return 0 if not nc.is_error(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
