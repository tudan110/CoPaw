#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests>=2.31.0",
#     "python-dotenv>=1.0.0",
#     "pyyaml>=6.0",
# ]
# ///
"""log-security-scan — sensitive info & attack-signal scan.

Pulls log hits from n9e/ES, runs a YAML rule set over message-like fields,
aggregates by rule & severity, and emits a Markdown report with redacted
sample contexts so the report is safe to forward.

Examples:
    uv run scripts/n9e_log_secscan.py --from-time now-15m --output markdown
    uv run scripts/n9e_log_secscan.py --severity-min high --max-docs 3000
    uv run scripts/n9e_log_secscan.py --rules-file references/security_rules.yml \\
        --from-time now-1h --show-samples 5 --output markdown
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _n9e_client as nc  # type: ignore[import-not-found]
import _rules_engine as re_engine  # type: ignore[import-not-found]


DEFAULT_MESSAGE_FIELDS = ["app_json", "message"]


# ---------------------------------------------------------------------------
# resolution
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


def _resolve_rules_file(args: argparse.Namespace) -> Path:
    if args.rules_file:
        return Path(args.rules_file).expanduser().resolve()
    env_val = (os.getenv("SECURITY_RULES_FILE") or "").strip()
    if env_val:
        return Path(env_val).expanduser().resolve()
    here = Path(__file__).resolve()
    return here.parent.parent / "references" / "security_rules.yml"


def _resolve_max_docs(requested: int) -> int:
    cap_env = (os.getenv("SECURITY_SCAN_MAX_DOCS") or "").strip()
    cap = int(cap_env) if cap_env.isdigit() else 0
    base = max(1, int(requested))
    return min(base, cap) if cap > 0 else base


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def _fetch_hits(
    *,
    ds_id: int,
    index: str,
    query_string: Optional[str],
    from_ms: int,
    to_ms: int,
    max_docs: int,
    sample_mode: str,
) -> Dict[str, Any]:
    base_query = nc.build_query_dsl(
        query_string=query_string, from_ms=from_ms, to_ms=to_ms
    )
    if sample_mode == "random":
        body: Dict[str, Any] = {
            "size": max_docs,
            "query": {
                "function_score": {
                    "query": base_query,
                    "random_score": {},
                    "boost_mode": "replace",
                }
            },
            "track_total_hits": True,
        }
    else:
        sort_order = "desc" if sample_mode == "tail" else "asc"
        body = nc.build_search_body(
            query=base_query,
            size=max_docs,
            sort_field=nc.get_timestamp_field(),
            sort_order=sort_order,
            track_total_hits=True,
        )
    return nc.es_search(ds_id, index, body)


def _compose_text(source: Dict[str, Any], fields: List[str], max_len: int) -> str:
    parts: List[str] = []
    for fld in fields:
        v = nc.deep_get(source, fld)
        if v in (None, "", [], {}):
            continue
        if isinstance(v, (dict, list)):
            try:
                v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                v = str(v)
        parts.append(str(v))
    text = " ".join(parts)
    if len(text) > max_len:
        text = text[:max_len]
    return text


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

def run_scan(args: argparse.Namespace) -> Dict[str, Any]:
    ds_id, index, err = _ds_index(args)
    if err is not None:
        return err
    from_ms, to_ms, err = _time_range(args)
    if err is not None:
        return err

    rules_path = _resolve_rules_file(args)
    try:
        loaded = re_engine.load_rules(rules_path)
    except FileNotFoundError as exc:
        return nc.make_error(400, str(exc))
    except RuntimeError as exc:
        return nc.make_error(500, str(exc))

    rules = re_engine.filter_by_severity(loaded.rules, args.severity_min)

    max_docs = _resolve_max_docs(args.max_docs)
    message_fields = [
        f.strip() for f in (args.message_fields or "").split(",") if f.strip()
    ] or list(DEFAULT_MESSAGE_FIELDS)

    res = _fetch_hits(
        ds_id=ds_id,
        index=index,
        query_string=args.query,
        from_ms=from_ms,
        to_ms=to_ms,
        max_docs=max_docs,
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

    auto_random = False
    if args.sample_mode == "tail" and total_value > max_docs * 4:
        random_res = _fetch_hits(
            ds_id=ds_id,
            index=index,
            query_string=args.query,
            from_ms=from_ms,
            to_ms=to_ms,
            max_docs=max_docs,
            sample_mode="random",
        )
        if not nc.is_error(random_res):
            es_data = random_res.get("data") or {}
            raw_hits = (es_data.get("hits") or {}).get("hits") or []
            auto_random = True

    context_chars = int(loaded.defaults.get("context_chars", 24))
    redact_keep = int(loaded.defaults.get("redact_keep", 2))

    rule_aggs: Dict[str, Dict[str, Any]] = {
        r.rule_id: {
            "rule_id": r.rule_id,
            "rule_name": r.name,
            "severity": r.severity,
            "category": r.category,
            "description": r.description,
            "hit_count": 0,
            "doc_count": 0,
            "hosts": Counter(),
            "services": Counter(),
            "indices": Counter(),
            "samples": [],
        }
        for r in rules
    }

    docs_with_hits = 0
    text_max_len = 8000

    host_pool = ["agent_hostname", "host.name", "hostname", "agent.hostname"]
    svc_pool = ["fcservice", "service.name", "service", "app", "syslog_program"]

    for hit in raw_hits:
        src = (hit.get("_source") or {}) if isinstance(hit, dict) else {}
        text = _compose_text(src, message_fields, text_max_len)
        if not text:
            continue
        hits_for_doc = re_engine.scan_text(
            text,
            rules,
            context_chars=context_chars,
            redact_keep=redact_keep,
            max_hits_per_rule=2,  # cap per-doc to avoid one log dominating
        )
        if hits_for_doc:
            docs_with_hits += 1
        host = _first_present(src, host_pool) or ""
        service = _first_present(src, svc_pool) or ""
        index_name = (hit.get("_index") or "") if isinstance(hit, dict) else ""
        seen_ids_in_doc: set = set()
        for h in hits_for_doc:
            agg = rule_aggs[h["rule_id"]]
            agg["hit_count"] += 1
            if h["rule_id"] not in seen_ids_in_doc:
                agg["doc_count"] += 1
                seen_ids_in_doc.add(h["rule_id"])
            if host:
                agg["hosts"][host] += 1
            if service:
                agg["services"][service] += 1
            if index_name:
                agg["indices"][index_name] += 1
            if len(agg["samples"]) < args.show_samples:
                agg["samples"].append(
                    {
                        "host": host,
                        "service": service,
                        "index": index_name,
                        "context": h["context"],
                    }
                )

    rule_results = [r for r in rule_aggs.values() if r["hit_count"] > 0]
    rule_results.sort(
        key=lambda r: (
            -re_engine.SEVERITY_ORDER[r["severity"]],
            -r["hit_count"],
        )
    )

    severity_counter: Counter = Counter()
    category_counter: Counter = Counter()
    for r in rule_results:
        severity_counter[r["severity"]] += r["hit_count"]
        category_counter[r["category"]] += r["hit_count"]

    return nc.make_ok(
        {
            "datasource_id": ds_id,
            "index": index,
            "from_ms": from_ms,
            "to_ms": to_ms,
            "query": args.query or "",
            "rules_file": str(rules_path),
            "rules_loaded": len(loaded.rules),
            "rules_skipped": loaded.skipped,
            "rules_active": len(rules),
            "severity_min": args.severity_min,
            "scanned_docs": len(raw_hits),
            "total_docs": total_value,
            "docs_with_hits": docs_with_hits,
            "auto_random": auto_random,
            "rule_results": [_finalize(r) for r in rule_results],
            "by_severity": dict(severity_counter),
            "by_category": dict(category_counter),
        }
    )


def _finalize(agg: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(agg)
    out["hosts"] = [{"key": k, "count": v} for k, v in agg["hosts"].most_common(5)]
    out["services"] = [{"key": k, "count": v} for k, v in agg["services"].most_common(5)]
    out["indices"] = [{"key": k, "count": v} for k, v in agg["indices"].most_common(5)]
    return out


def _first_present(src: Dict[str, Any], fields: List[str]) -> Optional[str]:
    for fld in fields:
        v = nc.deep_get(src, fld)
        if v not in (None, "", [], {}):
            return str(v)
    return None


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

_SEVERITY_BADGE = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}


def _build_severity_pie(by_sev: Dict[str, int]) -> str:
    if not by_sev:
        return ""
    option = {
        "title": {"text": "命中按 severity 分布", "left": "center"},
        "tooltip": {"trigger": "item"},
        "legend": {"orient": "vertical", "left": "left"},
        "series": [
            {
                "name": "severity",
                "type": "pie",
                "radius": ["35%", "65%"],
                "data": [
                    {"name": k, "value": int(v)}
                    for k, v in sorted(by_sev.items(), key=lambda kv: -re_engine.SEVERITY_ORDER.get(kv[0], 0))
                ],
            }
        ],
    }
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, indent=2) + "\n```"


def _build_rule_bar(rule_results: List[Dict[str, Any]]) -> str:
    rule_results = rule_results[:10]
    if not rule_results:
        return ""
    option = {
        "title": {"text": "命中数 Top 规则", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": [r["rule_id"] for r in rule_results],
            "axisLabel": {"interval": 0, "rotate": 30},
        },
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "data": [r["hit_count"] for r in rule_results]}
        ],
    }
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, indent=2) + "\n```"


def _render_markdown(data: Dict[str, Any], echarts_only: bool) -> str:
    pie = _build_severity_pie(data.get("by_severity") or {})
    bar = _build_rule_bar(data.get("rule_results") or [])
    if echarts_only:
        return ((pie + "\n" + bar) if pie or bar else "") + "\n"

    md = [
        "# 夜莺日志安全扫描报告",
        "",
        f"- 数据源 ID：`{data.get('datasource_id')}`，索引：`{data.get('index')}`",
        f"- 时间范围：`{nc.format_ms(data.get('from_ms') or 0)}` ~ "
        f"`{nc.format_ms(data.get('to_ms') or 0)}`",
        f"- 查询：`{data.get('query') or '(空)'}`",
        f"- 规则文件：`{data.get('rules_file')}`，加载 {data.get('rules_loaded')} 条，"
        f"启用 {data.get('rules_active')} 条（severity_min={data.get('severity_min')}）",
        f"- 扫描：{data.get('scanned_docs', 0)} 条 / 总命中 {data.get('total_docs', 0)} 条"
        f"{'（自动 random 抽样）' if data.get('auto_random') else ''}，"
        f"命中规则的 doc 数：{data.get('docs_with_hits', 0)}",
        "",
    ]

    skipped = data.get("rules_skipped") or []
    if skipped:
        md.append("> ⚠️ 规则加载告警：")
        for s in skipped:
            md.append(f"> - `{s.get('id')}`：{s.get('reason')}")
        md.append("")

    rule_results = data.get("rule_results") or []
    if not rule_results:
        md.append("**无命中**。可放宽 `--from-time`、调低 `--severity-min`、或扩大 `--max-docs`。")
        return "\n".join(md) + "\n"

    md.append("## 总览")
    md.append("")
    md.append("| 指标 | 值 |")
    md.append("|------|----|")
    md.append(f"| 命中规则数 | {len(rule_results)} |")
    md.append(f"| 总命中数 | {sum(r['hit_count'] for r in rule_results)} |")
    by_sev = data.get("by_severity") or {}
    for sev in ("critical", "high", "medium", "low"):
        if sev in by_sev:
            md.append(f"| {_SEVERITY_BADGE.get(sev, '')} {sev} 命中数 | {by_sev[sev]} |")
    md.append("")
    if pie:
        md.append(pie)
        md.append("")

    md.append("## 命中明细（按 severity → hit_count 排序）")
    md.append("")
    md.append("| severity | 规则 | 命中数 | doc 数 | 主机 Top | 服务 Top |")
    md.append("|---------|------|------:|------:|---------|---------|")
    for r in rule_results:
        hosts = ", ".join(
            f"{h['key']}({h['count']})" for h in (r.get("hosts") or [])[:3]
        ) or "—"
        services = ", ".join(
            f"{s['key']}({s['count']})" for s in (r.get("services") or [])[:3]
        ) or "—"
        md.append(
            f"| {_SEVERITY_BADGE.get(r['severity'], '')} {r['severity']} | "
            f"`{r['rule_id']}` ({r['rule_name']}) | "
            f"{r['hit_count']} | {r['doc_count']} | {hosts} | {services} |"
        )
    md.append("")
    if bar:
        md.append(bar)
        md.append("")

    md.append("## 命中样例（脱敏）")
    md.append("")
    for r in rule_results:
        if not r.get("samples"):
            continue
        md.append(f"### {_SEVERITY_BADGE.get(r['severity'], '')} `{r['rule_id']}` — {r['rule_name']}")
        md.append("")
        md.append(r.get("description") or "")
        md.append("")
        md.append("| 主机 | 服务 | 索引 | 上下文（脱敏） |")
        md.append("|------|------|------|---------------|")
        for s in r["samples"]:
            md.append(
                f"| {s.get('host') or '—'} | {s.get('service') or '—'} | "
                f"`{s.get('index') or '—'}` | `{nc.truncate(s.get('context') or '', 200)}` |"
            )
        md.append("")
    return "\n".join(md) + "\n"


def _render(envelope: Dict[str, Any], output: str) -> str:
    if nc.is_error(envelope):
        return (
            "# 夜莺日志安全扫描失败\n\n"
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
    p = argparse.ArgumentParser(description="Nightingale log security / sensitive-info scan")
    p.add_argument("--datasource")
    p.add_argument("--index")
    p.add_argument("--query", default="")
    p.add_argument("--from-time", default="now-15m")
    p.add_argument("--to-time", default="now")
    p.add_argument("--rules-file", default="", help="规则 yaml 路径；默认 references/security_rules.yml")
    p.add_argument(
        "--severity-min",
        choices=["critical", "high", "medium", "low"],
        default="medium",
        help="低于该 severity 的规则不参与扫描",
    )
    p.add_argument("--max-docs", type=int, default=5000, help="本次最多拉多少条入扫描")
    p.add_argument("--sample-mode", choices=["tail", "head", "random"], default="tail")
    p.add_argument("--message-fields", default="app_json,message")
    p.add_argument("--show-samples", type=int, default=3, help="每条规则展示的样例上限")
    p.add_argument(
        "--output",
        choices=["json", "markdown", "markdown-echarts-only"],
        default="markdown",
    )
    args = p.parse_args()

    try:
        result = run_scan(args)
    except RuntimeError as exc:
        result = nc.make_error(500, str(exc))

    sys.stdout.write(_render(result, args.output))
    return 0 if not nc.is_error(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
