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
"""log-hazard-detection — combined hazard report.

A one-shot entry point that runs Drain3 over the current window and produces
a single Markdown report covering:
    1. Top templates by frequency
    2. Error-dense templates (containing ERROR/Exception/failed/...)
    3. Rare templates (very low footprint, possibly anomalies)
    4. Drift vs baseline (24h / 7d), if --include-drift

This is the recommended entry point for an LLM agent answering "what's hazardous
in the recent logs" — it returns a self-contained report with chart blocks.

Examples:
    uv run scripts/n9e_log_hazard.py --output markdown
    uv run scripts/n9e_log_hazard.py --from-time now-1h --baseline 24h --output markdown
    uv run scripts/n9e_log_hazard.py --include-drift false --output markdown
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

import _drain_helper as dh  # type: ignore[import-not-found]
import _n9e_client as nc  # type: ignore[import-not-found]


_BASELINE_PRESETS = {
    "24h": 24 * 3600 * 1000,
    "7d": 7 * 24 * 3600 * 1000,
}


# ---------------------------------------------------------------------------
# resolution helpers (intentionally duplicated with cluster/drift to keep the
# scripts independently runnable; small enough to not warrant a shared module)
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


def _parse_window(args: argparse.Namespace) -> Tuple[Optional[int], Optional[int], Optional[Dict[str, Any]]]:
    try:
        from_ms = nc.parse_time(args.from_time, default="now-15m")
        to_ms = nc.parse_time(args.to_time, default="now")
    except ValueError as exc:
        return None, None, nc.make_error(400, str(exc))
    if from_ms >= to_ms:
        return None, None, nc.make_error(400, "时间范围非法：from-time 必须早于 to-time")
    return from_ms, to_ms, None


def _resolve_sample_size(requested: int) -> int:
    cap = nc.get_max_size()
    return max(1, min(int(requested), cap))


def _bool_arg(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _fetch_and_fit(
    *,
    ds_id: int,
    index: str,
    query_string: Optional[str],
    from_ms: int,
    to_ms: int,
    sample_size: int,
    message_fields: List[str],
    max_clusters: int,
    sim_th: float,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]], Dict[str, Any]]:
    base_query = nc.build_query_dsl(
        query_string=query_string, from_ms=from_ms, to_ms=to_ms
    )
    body = nc.build_search_body(
        query=base_query,
        size=sample_size,
        sort_field=nc.get_timestamp_field(),
        sort_order="desc",
        track_total_hits=True,
    )
    res = nc.es_search(ds_id, index, body)
    if nc.is_error(res):
        return None, res, {}
    es_data = res.get("data") or {}
    hits_block = es_data.get("hits") or {}
    total_block = hits_block.get("total") or {}
    total_value = (
        int(total_block.get("value") or 0)
        if isinstance(total_block, dict)
        else int(total_block or 0)
    )
    raw_hits = hits_block.get("hits") or []
    auto_random = False
    if total_value > sample_size * 4:
        random_body: Dict[str, Any] = {
            "size": sample_size,
            "query": {
                "function_score": {
                    "query": base_query,
                    "random_score": {},
                    "boost_mode": "replace",
                }
            },
            "track_total_hits": True,
        }
        random_res = nc.es_search(ds_id, index, random_body)
        if not nc.is_error(random_res):
            es_data = random_res.get("data") or {}
            raw_hits = (es_data.get("hits") or {}).get("hits") or []
            auto_random = True
    fit = dh.fit_hits(
        raw_hits,
        message_fields=message_fields,
        max_clusters=max_clusters,
        sim_th=sim_th,
    )
    return (
        fit["templates"],
        None,
        {
            "total": total_value,
            "fetched": len(raw_hits),
            "fit_count": fit["fit_count"],
            "skipped_count": fit["skipped_count"],
            "auto_random": auto_random,
            "fields_used": fit["fields_used"],
            "sample_ratio": round((len(raw_hits) / total_value) if total_value else 1.0, 4),
        },
    )


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

def run_hazard(args: argparse.Namespace) -> Dict[str, Any]:
    ds_id, index, err = _ds_index(args)
    if err is not None:
        return err
    cur_from, cur_to, err = _parse_window(args)
    if err is not None:
        return err

    sample_size = _resolve_sample_size(args.sample_size)
    message_fields = [
        f.strip() for f in (args.message_fields or "").split(",") if f.strip()
    ] or list(dh.DEFAULT_MESSAGE_FIELDS)

    cur_templates, err, cur_meta = _fetch_and_fit(
        ds_id=ds_id,
        index=index,
        query_string=args.query,
        from_ms=cur_from,
        to_ms=cur_to,
        sample_size=sample_size,
        message_fields=message_fields,
        max_clusters=args.max_clusters,
        sim_th=args.sim_th,
    )
    if err is not None:
        return err

    include_drift = _bool_arg(args.include_drift, True)
    drift_section: Optional[Dict[str, Any]] = None
    base_meta: Dict[str, Any] = {}
    base_window: Dict[str, Any] = {}
    if include_drift:
        shift = _BASELINE_PRESETS.get(args.baseline)
        if shift is not None:
            base_from = cur_from - shift
            base_to = cur_to - shift
            base_templates, base_err, base_meta = _fetch_and_fit(
                ds_id=ds_id,
                index=index,
                query_string=args.query,
                from_ms=base_from,
                to_ms=base_to,
                sample_size=sample_size,
                message_fields=message_fields,
                max_clusters=args.max_clusters,
                sim_th=args.sim_th,
            )
            if base_err is None and base_templates is not None:
                diff = dh.diff_templates(current=cur_templates, baseline=base_templates)
                drift_section = {k: v[: args.top] for k, v in diff.items()}
                base_window = {"from_ms": base_from, "to_ms": base_to, **base_meta}
            else:
                drift_section = {"_error": (base_err or {}).get("msg") or "baseline 拉取失败"}
                base_window = {"from_ms": base_from, "to_ms": base_to}

    error_dense = (
        dh.find_error_dense(cur_templates) if _bool_arg(args.include_error_dense, True) else []
    )
    rare = dh.find_rare(cur_templates) if _bool_arg(args.include_rare, True) else []

    top_templates = cur_templates[: args.top]

    return nc.make_ok(
        {
            "datasource_id": ds_id,
            "index": index,
            "query": args.query or "",
            "current_window": {"from_ms": cur_from, "to_ms": cur_to, **cur_meta},
            "baseline_window": base_window,
            "baseline_preset": args.baseline,
            "top": args.top,
            "templates_top": top_templates,
            "templates_error_dense": error_dense[: args.top],
            "templates_rare": rare[: args.top],
            "drift": drift_section,
        }
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _format_template_table(rows: List[Dict[str, Any]], pct_total: int = 0) -> List[str]:
    if not rows:
        return ["_无_", ""]
    md = ["| # | 命中 | 占比 | 错误密度 | 主机 Top | 服务 Top | 模板 |",
          "|---|----:|----:|------:|---------|---------|-----|"]
    total = pct_total or sum(r["count"] for r in rows) or 1
    for r in rows:
        pct = (r["count"] / total) * 100
        hosts = ", ".join(
            f"{h['key']}({h['count']})" for h in (r.get("hosts") or [])[:3]
        ) or "—"
        services = ", ".join(
            f"{s['key']}({s['count']})" for s in (r.get("services") or [])[:3]
        ) or "—"
        md.append(
            f"| #{r['id']} | {r['count']} | {pct:.1f}% | {r['error_score']:.2f} | "
            f"{hosts} | {services} | `{nc.truncate(r['template'], 100)}` |"
        )
    md.append("")
    return md


def _format_drift_table(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return ["_无_", ""]
    md = ["| 模板 | 当前 | 基线 | Δ | 比例 | 主机 Top |",
          "|------|----:|----:|----:|-----:|---------|"]
    for r in rows:
        ratio = r.get("ratio")
        if ratio == float("inf"):
            ratio_str = "∞"
        elif ratio == 0.0:
            ratio_str = "0"
        elif ratio is None:
            ratio_str = "—"
        else:
            ratio_str = f"{ratio:.2f}x"
        hosts = ", ".join(
            f"{h['key']}({h['count']})" for h in (r.get("hosts") or [])[:3]
        ) or "—"
        md.append(
            f"| `{nc.truncate(r['template'], 80)}` | {r['current_count']} | "
            f"{r['baseline_count']} | {r['delta']:+d} | {ratio_str} | {hosts} |"
        )
    md.append("")
    return md


def _build_top_pie(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    option = {
        "title": {"text": "日志模板 Top 占比", "left": "center"},
        "tooltip": {"trigger": "item"},
        "legend": {"orient": "vertical", "left": "left", "type": "scroll"},
        "series": [
            {
                "name": "templates",
                "type": "pie",
                "radius": ["35%", "65%"],
                "data": [
                    {"name": nc.truncate(r["template"], 40), "value": int(r["count"])}
                    for r in rows
                ],
            }
        ],
    }
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, indent=2) + "\n```"


def _render_markdown(data: Dict[str, Any], echarts_only: bool) -> str:
    pie = _build_top_pie(data.get("templates_top") or [])
    if echarts_only:
        return pie + "\n" if pie else ""

    cur = data.get("current_window") or {}
    md = [
        "# 夜莺日志隐患识别（Hazard Report）",
        "",
        f"- 数据源 ID：`{data.get('datasource_id')}`，索引：`{data.get('index')}`",
        f"- 查询：`{data.get('query') or '(空)'}`",
        f"- 时间窗：`{nc.format_ms(cur.get('from_ms') or 0)}` ~ `{nc.format_ms(cur.get('to_ms') or 0)}`"
        f"，命中 {cur.get('total', 0)}，抽样 {cur.get('fetched', 0)}"
        f"（采样比 {round((cur.get('sample_ratio') or 0) * 100, 2)}%"
        f"{'，自动降级为 random' if cur.get('auto_random') else ''}）",
        f"- 实际入参字段：{('、'.join(cur.get('fields_used') or []) or '无')}",
        "",
        "## 1. 模板 Top（按命中数）",
        "",
    ]
    md += _format_template_table(data.get("templates_top") or [])
    if pie:
        md.append(pie)
        md.append("")

    md += [
        "## 2. 错误密集模板",
        "（含 ERROR/Exception/failed/timeout/refused/... 关键词，按错误密度排序）",
        "",
    ]
    md += _format_template_table(data.get("templates_error_dense") or [])

    md += [
        "## 3. 稀有模板",
        "（占比极小但出现至少 2 次，可能是异常或边角 case）",
        "",
    ]
    md += _format_template_table(data.get("templates_rare") or [])

    drift = data.get("drift")
    md += [
        f"## 4. 漂移分析（vs {data.get('baseline_preset', '24h')}）",
        "",
    ]
    if drift is None:
        md.append("_未启用（--include-drift=false）_")
        md.append("")
    elif "_error" in drift:
        md.append(f"_基线拉取失败：{drift['_error']}_")
        md.append("")
    else:
        md.append("### 突增模板")
        md += _format_drift_table((drift or {}).get("surged") or [])
        md.append("### 新增模板")
        md += _format_drift_table((drift or {}).get("new") or [])
        md.append("### 消失模板")
        md += _format_drift_table((drift or {}).get("vanished") or [])

    return "\n".join(md) + "\n"


def _render(envelope: Dict[str, Any], output: str) -> str:
    if nc.is_error(envelope):
        return (
            "# 夜莺日志隐患识别失败\n\n"
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
    p = argparse.ArgumentParser(description="Nightingale log hazard combined report")
    p.add_argument("--datasource")
    p.add_argument("--index")
    p.add_argument("--query", default="")
    p.add_argument("--from-time", default="now-15m")
    p.add_argument("--to-time", default="now")
    p.add_argument("--sample-size", type=int, default=2000)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--message-fields", default="app_json,message")
    p.add_argument("--max-clusters", type=int, default=2000)
    p.add_argument("--sim-th", type=float, default=0.4)
    p.add_argument("--baseline", choices=["24h", "7d"], default="24h")
    p.add_argument("--include-drift", default="true", help="是否计算 24h/7d 漂移（true/false）")
    p.add_argument("--include-rare", default="true", help="是否输出稀有模板（true/false）")
    p.add_argument("--include-error-dense", default="true", help="是否输出错误密集模板（true/false）")
    p.add_argument(
        "--output",
        choices=["json", "markdown", "markdown-echarts-only"],
        default="markdown",
    )
    args = p.parse_args()

    try:
        result = run_hazard(args)
    except RuntimeError as exc:
        result = nc.make_error(500, str(exc))

    sys.stdout.write(_render(result, args.output))
    return 0 if not nc.is_error(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
