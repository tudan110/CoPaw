#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emit_operate.py —— 产出"就地操作"指令 ``qwenpaw:operate``。

agent **不要自己手写 JSON**(经验表明 LLM 经常写成 YAML/`steps:`/自然语言,导致
前端解析失败、页面无反应)。改为:决定好"去哪个页面、点第几行、点哪个按钮、填什么"
之后,运行本脚本带参数,把脚本输出**原样**返回给用户。脚本保证输出是一行合法 JSON。

用法示例:
  # 跨页 + 看某行详情:查看"待办工单"页第3条的详情
  uv run scripts/emit_operate.py --navigate 待办工单 --row-index 3 --row-click 详情 \
      --risk query --title "查看待办工单第3条详情"
  # 当前页搜索:流程名称=系统派单 → 点搜索
  uv run scripts/emit_operate.py --fill 流程名称=系统派单 --click 搜索 --risk query
  # 当前页新建(写操作,用户确认):点新增开弹窗
  uv run scripts/emit_operate.py --open 新增 --risk create --title 新建工单

要点:
- `--navigate` 用**具体的叶子页名**(如"待办工单"),不要用父级菜单名(如"工单管理"),
  否则前端找不到真实页、不会跳。
- 只读(搜索/查看/下载)用 `--risk query`(前端自动执行);新增/删除用 create/delete
  (前端只定位/预填,由用户点确认)。
"""
from __future__ import annotations

import argparse
import json
import sys


def build_payload(args: argparse.Namespace) -> dict:
    payload: dict = {"mode": "current"}
    if args.navigate:
        payload["navigate"] = args.navigate
    if args.page:
        payload["page"] = args.page

    fills = []
    for kv in args.fill or []:
        if "=" in kv:
            key, val = kv.split("=", 1)
            if key.strip():
                fills.append({"label": key.strip(), "value": val.strip()})
    if fills:
        payload["fill"] = fills

    if args.row_index or args.row_match:
        row: dict = {}
        if args.row_index:
            try:
                row["index"] = int(args.row_index)
            except ValueError:
                row["match"] = args.row_index
        if args.row_match:
            row["match"] = args.row_match
        row["click"] = args.row_click or "详情"
        payload["row"] = row

    if args.click:
        payload["click"] = args.click
    if args.open:
        payload["open"] = args.open
    if args.upload:
        payload["upload"] = True
    if args.accept:
        payload["accept"] = args.accept

    payload["risk"] = args.risk
    if args.title:
        payload["title"] = args.title
    return payload


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="产出 qwenpaw:operate 就地操作指令")
    p.add_argument("--navigate", default="", help="先跳转到的页面名(用具体叶子页名)")
    p.add_argument("--page", default="", help="当前页组件 name(可选)")
    p.add_argument("--fill", action="append", default=[], help="字段=值,可重复")
    p.add_argument("--click", default="", help="要点的按钮文案(如 搜索)")
    p.add_argument("--row-index", default="", help="表格第几行(从 1 开始)")
    p.add_argument("--row-match", default="", help="按某列文案定位行")
    p.add_argument("--row-click", default="", help="该行要点的按钮(如 详情/下载)")
    p.add_argument("--open", default="", help="要点开的弹窗按钮(如 新增/导入)")
    p.add_argument(
        "--upload",
        action="store_true",
        help="批量导入:在聊天里让用户上传文件并注入页面 el-upload",
    )
    p.add_argument(
        "--accept", default="", help="上传允许的文件类型(如 .xlsx,.xls)"
    )
    p.add_argument(
        "--risk",
        default="query",
        choices=["query", "create", "update", "delete"],
    )
    p.add_argument("--title", default="", help="一句话说明")
    p.add_argument(
        "--output",
        default="full",
        choices=["full", "directive", "json"],
        help="full=话术+指令块;directive=只指令块;json=只 JSON",
    )
    args = p.parse_args(argv)

    payload = build_payload(args)
    if not (
        payload.get("navigate")
        or payload.get("fill")
        or payload.get("click")
        or payload.get("row")
        or payload.get("open")
        or payload.get("upload")
    ):
        sys.stderr.write(
            "至少要给一个操作:--navigate / --fill / --click / --row-index|--row-match / --open\n"
        )
        return 2

    block = (
        "```qwenpaw:operate\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n```"
    )
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.output == "directive":
        print(block)
    else:
        lead = "好的," + (args.title or "正在为您操作") + "。"
        print(lead + "\n\n" + block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
