#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动作指令 CLI:在参数收集齐后,把"某个操作 + 一组参数"渲染成前端可执行
的 ``qwenpaw:action`` 指令块。必填参数没齐时拒绝出指令,并告诉 agent 还缺啥。

用法:
    # 方式一:内联 JSON
    python3 scripts/emit_action.py workflow.category.add \
        --params '{"categoryName":"财务类","code":"FIN"}'

    # 方式二:逐项 key=value(免去 JSON 转义,推荐在 shell 里用)
    python3 scripts/emit_action.py workflow.category.add \
        --set categoryName=财务类 --set code=FIN

输出模式:
    agent      确认话术 + 指令块(原样回给用户)。默认。
    directive  仅打印指令块。
    json       打印 payload / 缺参信息(调试用)。

退出码:
    0  成功生成指令
    2  必填参数未齐(stdout 给出还缺哪些)
    3  操作不存在 / 参数解析失败
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
    from runtime import directive as directive_mod
    from runtime import menu_client as menu_mod

    return catalog_mod, directive_mod, menu_mod


def _collect_params(args) -> dict:
    params: dict = {}
    if args.params:
        loaded = json.loads(args.params)
        if not isinstance(loaded, dict):
            raise ValueError("--params 必须是 JSON 对象")
        params.update(loaded)
    for item in args.set or []:
        if "=" not in item:
            raise ValueError(f"--set 需要 key=value,得到: {item!r}")
        key, value = item.split("=", 1)
        params[key.strip()] = value
    return params


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 action 指令")
    parser.add_argument("op_id", help="操作 id,如 workflow.category.add")
    parser.add_argument("--params", default="", help="内联 JSON 参数")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="key=value 形式逐项设参(可重复)",
    )
    parser.add_argument(
        "--output",
        choices=["agent", "directive", "json"],
        default="agent",
    )
    parser.add_argument(
        "--resolve-route",
        action="store_true",
        help="尝试用 getRouters 按 component 反查真实路由(失败回退目录 route)",
    )
    parser.add_argument("--catalog", default=None)
    args = parser.parse_args(argv)

    catalog_mod, directive_mod, menu_mod = _load_runtime()

    try:
        catalog = catalog_mod.load_catalog(args.catalog)
        params = _collect_params(args)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[error] 参数解析失败: {exc}", file=sys.stderr)
        return 3

    op = catalog.get(args.op_id)
    if op is None:
        print(f"[error] 操作不存在: {args.op_id}", file=sys.stderr)
        return 3

    missing = directive_mod.missing_required(op, params)
    if missing:
        if args.output == "json":
            print(
                json.dumps(
                    {
                        "status": "need_params",
                        "op": op.id,
                        "missing": [m.to_dict() for m in missing],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            lines = ["还差必填参数,请先向用户补全后再生成指令:"]
            for m in missing:
                lines.append(f"- {m.label} ({m.prop})")
            print("\n".join(lines))
        return 2

    route = None
    if args.resolve_route:
        route = menu_mod.resolve_live_route(
            component=op.component, name=op.page
        )

    payload = directive_mod.build_payload(op, params, route=route)
    block = directive_mod.build_action_directive(op, params, route=route)

    if args.output == "directive":
        print(block)
    elif args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        lines = [f"好的,我来帮您{op.name}。已为您预填以下内容,"]
        lines.append("请在打开的页面上核对后点击「确定」提交:")
        for f in op.fields:
            value = payload["params"].get(f.prop)
            if value not in (None, ""):
                lines.append(f"- {f.label}:{value}")
        lines.append("")
        lines.append(block)
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
