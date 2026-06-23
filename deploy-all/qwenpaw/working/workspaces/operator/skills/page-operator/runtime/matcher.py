#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把用户自然语言诉求匹配到操作目录里的某个操作。

纯逻辑、不依赖网络:基于每个操作的 ``intent`` 同义词 + 名称做打分
(精确/双向子串/模糊),与 page-navigator 的菜单匹配同构。返回置信度分档:
execute(单个高置信)/ disambiguate(多个相近)/ not_found。
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .catalog import Catalog, Operation


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def score_operation(op: Operation, query: str) -> float:
    """给单个操作打分,范围约 [0, 1]。越大越匹配。"""
    q = _norm(query)
    if not q:
        return 0.0
    best = 0.0
    phrases = list(op.intent) + [op.name]
    for phrase in phrases:
        p = _norm(phrase)
        if not p:
            continue
        if q == p:
            best = max(best, 1.0)
        elif p in q or q in p:
            # 用户原话往往比意图词长(如"帮我新建一个流程分类")
            best = max(best, 0.86)
        else:
            best = max(best, SequenceMatcher(None, q, p).ratio())
    return round(best, 4)


@dataclass
class Ranked:
    op: Operation
    score: float

    def to_dict(self) -> dict[str, Any]:
        data = self.op.to_dict()
        data["score"] = self.score
        return data


def search(
    catalog: Catalog,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.5,
) -> list[Ranked]:
    """按相关度返回 top_k 候选操作。"""
    ranked = [
        Ranked(op, score_operation(op, query)) for op in catalog.operations
    ]
    ranked = [r for r in ranked if r.score >= min_score]
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:top_k]


def decide_mode(
    ranked: list[Ranked],
    *,
    confident_gap: float = 0.15,
) -> str:
    """判断动作档位:execute / disambiguate / not_found。

    - 0 个候选 → not_found。
    - 1 个候选 → execute(直接进入参数收集)。
    - 多个候选:头名与次名分差 >= confident_gap(明显领先)→ execute;
      否则(几个相近、分不清)→ disambiguate,让用户挑一个。
    """
    if not ranked:
        return "not_found"
    if len(ranked) == 1:
        return "execute"
    if ranked[0].score - ranked[1].score >= confident_gap:
        return "execute"
    return "disambiguate"


def resolve(catalog: Catalog, query: str, *, top_k: int = 5) -> dict[str, Any]:
    """一站式:检索 + 判定,返回给 CLI/agent 的结构化结果。"""
    ranked = search(catalog, query, top_k=top_k)
    mode = decide_mode(ranked)
    return {
        "query": query,
        "mode": mode,
        "candidates": [r.to_dict() for r in ranked],
    }
