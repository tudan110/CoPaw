#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill / employee "flail" scorecard from a comprehensive-eval run.log.

Turns a Playwright pressure-test log into a data-driven triage list so we fix
the FEW skills that actually flail (redundant / invalid / shell-fallback
tool storms) instead of auditing all ~28 by hand (pressure-test L3-triage).

Parses the strict-verdict failure lines emitted by the eval, e.g.:

    Error: [数据分析员] 严格判定失败: AI 应答超时 90s>90s。耗时=90440ms
    问句="..." 应答摘录: ... 思考 2 · 工具 11 · 中间回复 2 ...
    execute_shell_command 工具调用 read_file 工具调用 ...

For each digital employee it reports failure count, tool-call distribution
(median/max/mean), shell-fallback rate, repeated-tool rate, cross-agent
delegation-loop rate, capability-gap signals, and failure-reason buckets,
ranked worst-first by a composite flail score. Also attributes to individual
skills where the shell command reveals ``skills/<name>/``.

Usage:
    python scripts/skill_call_scorecard.py path/to/run.log
    python scripts/skill_call_scorecard.py path/to/report_dir      # finds run.log
    python scripts/skill_call_scorecard.py run.log --json

Pure stdlib. Read-only.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VERDICT_RE = re.compile(r"\[([^\]]+)\]\s*严格判定失败[:：]\s*(.*)")
DURATION_RE = re.compile(r"耗时=(\d+)ms")
TOOLCOUNT_RE = re.compile(r"工具\s*(\d+)")
THINK_RE = re.compile(r"思考\s*(\d+)")
TOOLTOK_RE = re.compile(r"([a-zA-Z_]+)\s*工具调用")
SKILL_RE = re.compile(r"skills/([a-z0-9][a-z0-9-]+)")

CAP_GAP_CUES = ("没有封装", "没有对应", "没有专用", "不涉及", "无法生成", "没有专门")


def _bucket(reason: str) -> list[str]:
    """Classify a failure reason into one or more buckets."""
    tags = []
    if "超时" in reason:
        tags.append("SLA_TIMEOUT")
    if "未命中领域关键词" in reason or "准确性" in reason:
        tags.append("ACCURACY")
    if "过短" in reason or "空答" in reason or "回显" in reason:
        tags.append("TOO_SHORT")
    if any(k in reason for k in ("网关", "5xx", "堆栈", "拒答", "500")):
        tags.append("INFRA")
    return tags or ["OTHER"]


def _parse(log_text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        m = VERDICT_RE.search(line)
        if not m:
            continue
        employee = m.group(1).strip()
        # Skip un-interpolated template placeholders.
        if "{" in employee or "$" in employee:
            employee = "(未命名用例)"
        reason = m.group(2)
        dur = DURATION_RE.search(line)
        tc = TOOLCOUNT_RE.search(line)
        th = THINK_RE.search(line)
        tokens = TOOLTOK_RE.findall(line)
        skills = SKILL_RE.findall(line)
        records.append(
            {
                "employee": employee,
                "buckets": _bucket(reason),
                "duration_ms": int(dur.group(1)) if dur else None,
                "tool_count": int(tc.group(1)) if tc else len(tokens),
                "think_count": int(th.group(1)) if th else None,
                "tokens": tokens,
                "skills": skills,
                "capability_gap": any(c in line for c in CAP_GAP_CUES),
            },
        )
    return records


def _rate(n: int, d: int) -> float:
    return round(n / d, 3) if d else 0.0


def _summarize(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_emp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_emp[r["employee"]].append(r)

    out: dict[str, dict[str, Any]] = {}
    for emp, recs in by_emp.items():
        n = len(recs)
        tool_counts = [r["tool_count"] for r in recs if r["tool_count"]]
        shell_heavy = sum(
            1 for r in recs if r["tokens"].count("execute_shell_command") >= 3
        )
        repeated = sum(
            1
            for r in recs
            if r["tokens"]
            and Counter(r["tokens"]).most_common(1)[0][1] >= 3
        )
        delegation = sum(1 for r in recs if "chat_with_agent" in r["tokens"])
        cap_gap = sum(1 for r in recs if r["capability_gap"])
        bucket_counts: Counter = Counter()
        for r in recs:
            bucket_counts.update(r["buckets"])

        med = statistics.median(tool_counts) if tool_counts else 0
        mx = max(tool_counts) if tool_counts else 0
        # Composite flail score: how hard this employee's failures thrash.
        flail = round(
            med
            + 6 * _rate(shell_heavy, n)
            + 5 * _rate(repeated, n)
            + 4 * _rate(cap_gap, n),
            2,
        )
        out[emp] = {
            "failures": n,
            "tool_median": med,
            "tool_max": mx,
            "tool_mean": round(statistics.mean(tool_counts), 1)
            if tool_counts
            else 0,
            "shell_heavy_rate": _rate(shell_heavy, n),
            "repeated_tool_rate": _rate(repeated, n),
            "delegation_rate": _rate(delegation, n),
            "capability_gap_rate": _rate(cap_gap, n),
            "buckets": dict(bucket_counts),
            "flail_score": flail,
        }
    return out


def _skill_table(records: list[dict[str, Any]]) -> list[tuple[str, int]]:
    c: Counter = Counter()
    for r in records:
        for s in r["skills"]:
            c[s] += 1
    return c.most_common()


def _resolve_log(path_arg: str) -> Path:
    p = Path(path_arg).expanduser()
    if p.is_dir():
        p = p / "run.log"
    return p


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Skill flail scorecard")
    parser.add_argument("log", help="path to run.log or the report dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    log_path = _resolve_log(args.log)
    if not log_path.is_file():
        print(f"未找到日志文件: {log_path}", file=sys.stderr)
        return 2

    records = _parse(log_path.read_text(encoding="utf-8", errors="ignore"))
    if not records:
        print("日志中未发现 '严格判定失败' 记录", file=sys.stderr)
        return 2

    summary = _summarize(records)
    ranked = sorted(
        summary.items(), key=lambda kv: kv[1]["flail_score"], reverse=True
    )
    skill_hits = _skill_table(records)

    if args.json:
        print(
            json.dumps(
                {
                    "total_failures": len(records),
                    "by_employee": summary,
                    "skill_shell_hits": skill_hits,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"解析失败记录 {len(records)} 条。按 flail 严重度排序：\n")
    header = (
        f"{'员工':<12}{'失败':>5}{'工具中位':>7}{'工具峰':>6}"
        f"{'shell重':>7}{'重复':>6}{'代理环':>7}{'能力缺':>7}{'flail':>7}"
    )
    print(header)
    print("-" * len(header))
    for emp, s in ranked:
        print(
            f"{emp:<12}{s['failures']:>5}{s['tool_median']:>7}"
            f"{s['tool_max']:>6}{s['shell_heavy_rate']:>7}"
            f"{s['repeated_tool_rate']:>6}{s['delegation_rate']:>7}"
            f"{s['capability_gap_rate']:>7}{s['flail_score']:>7}"
        )

    print("\n失败原因分桶（按员工）：")
    for emp, s in ranked:
        if s["buckets"]:
            parts = ", ".join(
                f"{k}={v}" for k, v in sorted(s["buckets"].items())
            )
            print(f"  {emp}: {parts}")

    if skill_hits:
        print("\nshell 命令命中的技能（次数）：")
        for name, cnt in skill_hits:
            print(f"  {name:<28}{cnt}")

    print(
        "\n提示：flail 高 + shell重/重复高 = 该员工的技能在瞎试；"
        "能力缺高 = 缺工具(补技能)；代理环高 = 跨 agent 委托空转。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
