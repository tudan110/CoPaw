#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作识别 CLI:把用户的操作诉求匹配到操作目录里的某个操作,并告诉
agent 这个操作需要收集哪些参数。

用法:
    python3 scripts/find_op.py "<用户原话>" [--output agent|json] [--top-k 5]

输出模式:
    agent  给 agent 看的人话(命中时列出需要收集的字段 + 下一步命令)。默认。
    json   完整候选结构(含 score / fields),调试用。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _load_runtime():
    skill_root = Path(__file__).resolve().parents[1]
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))
    from runtime import catalog as catalog_mod
    from runtime import matcher as matcher_mod

    return catalog_mod, matcher_mod


def _fields_lines(op: dict) -> list[str]:
    lines = []
    for f in op.get("fields", []):
        flag = "必填" if f.get("required") else "可选"
        lines.append(
            f"- {f.get('label')}  ({f.get('prop')}) [{flag}]"
        )
    return lines


def _emit_hint(op: dict) -> str:
    required = [
        f.get("prop") for f in op.get("fields", []) if f.get("required")
    ]
    sample = ",".join(f'"{p}":"…"' for p in required) or '"…":"…"'
    return (
        "python3 scripts/emit_action.py "
        f"{op.get('id')} --params '{{{sample}}}'"
    )


def _format_agent(result: dict) -> str:
    mode = result["mode"]
    cands = result["candidates"]
    lines: list[str] = []
    if mode == "execute":
        op = cands[0]
        lines.append(f"命中操作:{op['name']}  (op: {op['id']})")
        if op.get("menu"):
            lines.append(f"位置:{op['menu']}")
        lines.append("")
        lines.append("这个操作需要这些参数:")
        lines.extend(_fields_lines(op))
        lines.append("")
        lines.append(
            "请从用户原话里抽取已给出的参数,把【必填】项收集齐(可向用户追问"
            "缺的);凑齐后执行:"
        )
        lines.append(f"  {_emit_hint(op)}")
    elif mode == "disambiguate":
        lines.append("匹配到多个可能的操作,请用户确认要哪一个:")
        for i, c in enumerate(cands, 1):
            lines.append(f"{i}. {c['name']}  ({c.get('menu') or c['id']})")
        lines.append("")
        lines.append("回复编号或操作名称即可。")
    else:
        lines.append(
            "没有匹配到可执行的操作。可能该操作还没登记进操作目录,"
            "或用户说的不是一个写操作。请让用户换个说法,或改用普通对话/导航。"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="操作识别")
    parser.add_argument("query", help="用户的操作诉求/原话")
    parser.add_argument(
        "--output",
        choices=["agent", "json"],
        default="agent",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--catalog",
        default=None,
        help="操作目录 JSON 路径(缺省 catalog/operations.json)",
    )
    args = parser.parse_args(argv)

    catalog_mod, matcher_mod = _load_runtime()
    catalog = catalog_mod.load_catalog(args.catalog)
    result = matcher_mod.resolve(catalog, args.query, top_k=args.top_k)

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_agent(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
