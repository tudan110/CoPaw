#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户页面导航 CLI:把用户的页面诉求解析为可跳转的路由。

用法:
    python3 scripts/find_page.py "<用户原话/页面关键词>" [--output agent|json|directive]

输出模式:
    agent      给 agent 看的人话摘要(navigate 时含跳转指令块)。默认。
    json       完整候选结构(调试用)。
    directive  仅打印跳转指令块(navigate 时)。
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
    from runtime import client as client_mod
    from runtime import menu as menu_mod

    return menu_mod, client_mod


def _format_agent(result: dict) -> str:
    mode = result["mode"]
    cands = result["candidates"]
    lines: list[str] = []
    if mode == "navigate":
        top = cands[0]
        label = top["breadcrumb"] or top["title"]
        lines.append(f"好的,正在为您打开「{label}」。")
        lines.append("")
        lines.append(result["directive"])
    elif mode == "disambiguate":
        lines.append("我找到多个可能的页面,请问您要进入哪一个?")
        for i, c in enumerate(cands, 1):
            label = c["breadcrumb"] or c["title"]
            lines.append(f"{i}. {label}（{c['path']}）")
        lines.append("")
        lines.append("回复编号或页面名称即可,我再带您过去。")
    else:
        lines.append(
            "没有找到匹配的页面。请换个说法,或告诉我更完整的页面名称。"
        )
        if cands:
            lines.append("与您描述比较接近的有:")
            for c in cands[:3]:
                lines.append(f"- {c['breadcrumb'] or c['title']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="门户页面导航")
    parser.add_argument("query", help="用户的页面诉求/关键词")
    parser.add_argument(
        "--output",
        choices=["agent", "json", "directive"],
        default="agent",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="忽略缓存强制刷新菜单",
    )
    args = parser.parse_args(argv)

    menu_mod, client_mod = _load_runtime()
    try:
        tree = client_mod.get_menu_tree(force_refresh=args.refresh)
    except client_mod.MenuClientError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    result = menu_mod.resolve(tree, args.query, top_k=args.top_k)

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.output == "directive":
        print(result.get("directive", ""))
    else:
        print(_format_agent(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
