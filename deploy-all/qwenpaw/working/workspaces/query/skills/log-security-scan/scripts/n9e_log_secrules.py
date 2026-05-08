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
"""log-security-scan — rule manager.

Modes:
    list     : show all loaded rules sorted by severity
    explain  : print one rule with pattern + description + examples
    test     : try a rule against a custom text (or its bundled examples)

Examples:
    uv run scripts/n9e_log_secrules.py --mode list
    uv run scripts/n9e_log_secrules.py --mode explain --rule-id secret-aws-ak
    uv run scripts/n9e_log_secrules.py --mode test --rule-id secret-aws-ak \\
        --text 'foo AKIAIOSFODNN7EXAMPLE bar'
    uv run scripts/n9e_log_secrules.py --mode test --rule-id pii-bankcard
        # uses the rule's bundled examples
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import _n9e_client as nc  # type: ignore[import-not-found]
import _rules_engine as re_engine  # type: ignore[import-not-found]


def _resolve_rules_file(args: argparse.Namespace) -> Path:
    if getattr(args, "rules_file", None):
        return Path(args.rules_file).expanduser().resolve()
    env_val = (os.getenv("SECURITY_RULES_FILE") or "").strip()
    if env_val:
        return Path(env_val).expanduser().resolve()
    here = Path(__file__).resolve()
    return here.parent.parent / "references" / "security_rules.yml"


def _load(args: argparse.Namespace) -> re_engine.LoadedRules:
    return re_engine.load_rules(_resolve_rules_file(args))


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------

def _cmd_list(args: argparse.Namespace) -> Dict[str, Any]:
    loaded = _load(args)
    return nc.make_ok(
        {
            "rules_file": str(_resolve_rules_file(args)),
            "rules": [r.to_dict() for r in loaded.rules],
            "skipped": loaded.skipped,
            "defaults": loaded.defaults,
        }
    )


def _find_rule(loaded: re_engine.LoadedRules, rule_id: str) -> re_engine.Rule:
    for r in loaded.rules:
        if r.rule_id == rule_id:
            return r
    raise ValueError(f"未找到 rule_id={rule_id}（已加载 {len(loaded.rules)} 条规则）")


def _cmd_explain(args: argparse.Namespace) -> Dict[str, Any]:
    if not args.rule_id:
        return nc.make_error(400, "explain 模式必须传 --rule-id")
    loaded = _load(args)
    try:
        rule = _find_rule(loaded, args.rule_id)
    except ValueError as exc:
        return nc.make_error(404, str(exc))
    return nc.make_ok(
        {
            **rule.to_dict(),
            "examples_hit": rule.examples_hit,
            "examples_miss": rule.examples_miss,
        }
    )


def _cmd_test(args: argparse.Namespace) -> Dict[str, Any]:
    if not args.rule_id:
        return nc.make_error(400, "test 模式必须传 --rule-id")
    loaded = _load(args)
    try:
        rule = _find_rule(loaded, args.rule_id)
    except ValueError as exc:
        return nc.make_error(404, str(exc))

    if args.text:
        hits = re_engine.scan_text(
            args.text,
            [rule],
            context_chars=int(loaded.defaults.get("context_chars", 24)),
            redact_keep=int(loaded.defaults.get("redact_keep", 2)),
            max_hits_per_rule=10,
        )
        return nc.make_ok(
            {
                "rule_id": rule.rule_id,
                "input": args.text,
                "hit_count": len(hits),
                "hits": hits,
            }
        )

    selftest = re_engine.selftest_rule(rule)
    return nc.make_ok(selftest)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

_SEVERITY_BADGE = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}


def _render_list(data: Dict[str, Any]) -> str:
    rules: List[Dict[str, Any]] = data.get("rules") or []
    skipped: List[Dict[str, Any]] = data.get("skipped") or []
    md = [
        "# log-security-scan 规则一览",
        "",
        f"- 规则文件：`{data.get('rules_file')}`",
        f"- 规则数：{len(rules)}（按 severity 排序）",
        f"- 默认 context_chars={data.get('defaults', {}).get('context_chars', 24)}，"
        f"redact_keep={data.get('defaults', {}).get('redact_keep', 2)}",
        "",
        "| severity | id | category | name | redact | post_filter | 描述 |",
        "|---------|----|----------|------|--------|-------------|------|",
    ]
    for r in rules:
        md.append(
            f"| {_SEVERITY_BADGE.get(r['severity'], '')} {r['severity']} | "
            f"`{r['id']}` | {r['category']} | {r['name']} | {r['redact']} | "
            f"{r.get('post_filter') or '—'} | {r['description']} |"
        )
    if skipped:
        md.append("")
        md.append("> ⚠️ 跳过的规则：")
        for s in skipped:
            md.append(f"> - `{s.get('id')}`：{s.get('reason')}")
    md.append("")
    return "\n".join(md) + "\n"


def _render_explain(data: Dict[str, Any]) -> str:
    md = [
        f"# 规则 `{data.get('id')}`：{data.get('name')}",
        "",
        f"- severity：{_SEVERITY_BADGE.get(data.get('severity', ''), '')} {data.get('severity')}",
        f"- category：{data.get('category')}",
        f"- redact：{data.get('redact')}",
        f"- post_filter：{data.get('post_filter') or '—'}",
        "",
        f"**描述**：{data.get('description')}",
        "",
        "**Pattern**：",
        "",
        "```regex",
        str(data.get("pattern") or ""),
        "```",
        "",
    ]
    hits = data.get("examples_hit") or []
    misses = data.get("examples_miss") or []
    if hits:
        md.append("**应命中的样例**：")
        for s in hits:
            md.append(f"- `{s}`")
        md.append("")
    if misses:
        md.append("**不应命中的样例**：")
        for s in misses:
            md.append(f"- `{s}`")
        md.append("")
    return "\n".join(md) + "\n"


def _render_test(data: Dict[str, Any]) -> str:
    if "all_passed" in data:  # selftest
        md = [
            f"# 规则自检 `{data.get('rule_id')}`",
            "",
            f"- 总体：{'✅ 通过' if data.get('all_passed') else '❌ 不通过'}",
            "",
            "**hit 样例（应命中）**：",
        ]
        for r in data.get("hit_results") or []:
            mark = "✅" if r["passed"] else "❌"
            md.append(f"- {mark} `{r['input']}`")
        md.append("")
        md.append("**miss 样例（不应命中）**：")
        for r in data.get("miss_results") or []:
            mark = "✅" if r["passed"] else "❌"
            md.append(f"- {mark} `{r['input']}`")
        md.append("")
        return "\n".join(md) + "\n"

    md = [
        f"# 规则试跑 `{data.get('rule_id')}`",
        "",
        f"- 输入：`{data.get('input') or ''}`",
        f"- 命中数：**{data.get('hit_count', 0)}**",
        "",
    ]
    hits = data.get("hits") or []
    if hits:
        md.append("| match (脱敏) | span | context |")
        md.append("|--------------|------|---------|")
        for h in hits:
            md.append(
                f"| `{h.get('match_redacted')}` | {h.get('span')} | `{h.get('context')}` |"
            )
    else:
        md.append("_未命中。_")
    md.append("")
    return "\n".join(md) + "\n"


def _render(mode: str, envelope: Dict[str, Any], output: str) -> str:
    if nc.is_error(envelope):
        return (
            f"# 规则 {mode} 失败\n\n"
            f"- 错误码：`{envelope.get('code')}`\n"
            f"- 错误信息：{envelope.get('msg')}\n"
        )
    if output == "json":
        return json.dumps(envelope, ensure_ascii=False, indent=2, default=str) + "\n"
    data = envelope.get("data") or {}
    if mode == "list":
        return _render_list(data)
    if mode == "explain":
        return _render_explain(data)
    return _render_test(data)


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="log-security-scan rule manager")
    p.add_argument("--mode", choices=["list", "explain", "test"], default="list")
    p.add_argument("--rule-id", help="(explain / test) 规则 id")
    p.add_argument("--text", help="(test) 自定义文本；不传时跑规则自带 examples")
    p.add_argument("--rules-file", default="", help="规则 yaml 路径")
    p.add_argument(
        "--output",
        choices=["json", "markdown"],
        default="markdown",
    )
    args = p.parse_args()

    try:
        if args.mode == "list":
            result = _cmd_list(args)
        elif args.mode == "explain":
            result = _cmd_explain(args)
        else:
            result = _cmd_test(args)
    except FileNotFoundError as exc:
        result = nc.make_error(400, str(exc))
    except RuntimeError as exc:
        result = nc.make_error(500, str(exc))

    sys.stdout.write(_render(args.mode, result, args.output))
    return 0 if not nc.is_error(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
