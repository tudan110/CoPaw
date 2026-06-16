#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库检索 CLI:给定问题,从共享知识库检索原文证据,供 gateway 带引用作答。

设计要点:
- 本技能只负责"检索",最终回答由 gateway agent 基于证据合成(可带引用、可追问)。
- 强制关闭 HyDE:模型限流时它只会拖慢(每次多一次 LLM 调用、易超时);且当前
  没有 embedding key、走的是 BM25,HyDE 生成的假想答案根本没地方做向量召回,
  纯属浪费。关掉后检索稳定在 ~1s。
- 复用全局共享知识库(knowledge 工作区下的 knowledge.db),只读,不写。
"""
from __future__ import annotations

# 必须在导入 KB 引擎之前设置 —— retrieval 模块在 import 时就读这个 env。
import os

os.environ.setdefault("KNOWLEDGE_BASE_HYDE_ENABLED", "false")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _query(text: str) -> dict:
    from qwenpaw.extensions.integrations import knowledge_base

    return knowledge_base.query_knowledge({"query": text})


def _format_agent(result: dict) -> str:
    ev = result.get("relevant_evidence") or []
    flags = result.get("flags") or {}
    lines: list[str] = []

    if flags.get("insufficient_evidence") or not ev:
        lines.append("知识库中未找到与该问题相关的资料。")
        boundary = result.get("evidence_boundary_statement")
        if boundary:
            lines.append(boundary)
        lines.append(
            "请如实告诉用户:知识库里没有相关内容,不要凭常识编造答案。"
        )
        return "\n".join(lines)

    conf = ev[0].get("confidence_level") or ""
    lines.append(f"已从知识库检索到 {len(ev)} 条原文证据(置信度 {conf}):")
    lines.append("")
    for i, item in enumerate(ev, 1):
        cit = item.get("citation") or {}
        src = cit.get("source_label") or "未知来源"
        sec = cit.get("section_path")
        head = f"【证据{i}】来源:{src}"
        if sec:
            head += f"  章节:{sec}"
        lines.append(head)
        lines.append((item.get("chunk_text") or "").strip())
        lines.append("")
    lines.append(
        "——以上为知识库原文证据。请【只依据这些证据】用中文回答用户问题,"
        "答案末尾用「参考来源:<文件名>」列出引用到的来源;"
        "若证据不足以回答,如实说明,切勿编造。"
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="知识库检索")
    parser.add_argument("query", help="用户的问题(已去掉【知识库】标记)")
    parser.add_argument(
        "--output",
        choices=["agent", "json"],
        default="agent",
    )
    args = parser.parse_args(argv)

    query = (args.query or "").strip()
    if not query:
        print("[error] 空问题", file=sys.stderr)
        return 2
    try:
        result = _query(query)
    except Exception as exc:  # noqa: BLE001 - 检索失败给可读错误
        print(f"[error] 知识库检索失败:{exc}", file=sys.stderr)
        return 2

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_agent(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
