#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户菜单路由的纯逻辑层:拍平、检索、生成跳转指令。

只依赖标准库,不做任何 IO,方便单测。HTTP 拉取与缓存在
``runtime/client.py``,本模块只处理 ``getRouters`` 返回的 ``data`` 树。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable


# 这些 component 是布局容器,不是真正可导航的叶子页面,排序时降权。
CONTAINER_COMPONENTS = {"Layout", "ParentView", "InnerLink"}

# 跳转指令块使用的 fenced 语言标识,前后端共同约定。
DIRECTIVE_LANG = "qwenpaw:navigate"


@dataclass
class PageEntry:
    """一个可导航的菜单节点。"""

    path: str  # 完整路由,如 /ops/xj/results
    title: str  # 叶子标题,如 结果报表
    breadcrumb: str  # 面包屑,如 运维中心 / 自动巡检 / 结果报表
    name: str  # 路由 name,如 Results
    component: str  # vue 组件路径或容器标识
    hidden: bool  # 是否为隐藏菜单
    is_container: bool  # 是否为布局容器(非叶子页)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "breadcrumb": self.breadcrumb,
            "name": self.name,
            "component": self.component,
            "hidden": self.hidden,
            "is_container": self.is_container,
        }


def _join_path(parent_full: str, child: str) -> str:
    """复刻 Vue Router 的父子路径拼接规则。

    - child 以 ``/`` 开头视为绝对路径,直接使用(如运维中心下的
      ``/home``);
    - 否则把 child 追加到父路径之后。

    刻意不折叠多余斜杠、不做归一化,以保证生成的路由和 SPA 实际
    注册的逐字一致(例如 ``//logs``、``/ops/xj/ops/task``)。
    """
    child = child or ""
    if child.startswith("/"):
        return child
    if not parent_full:
        return child
    if parent_full.endswith("/"):
        return parent_full + child
    return parent_full + "/" + child


def _node_title(node: dict) -> str:
    meta = node.get("meta") or {}
    title = meta.get("title")
    if title:
        return str(title)
    return str(node.get("name") or node.get("path") or "")


def flatten_menu(tree: Iterable[dict]) -> list[PageEntry]:
    """把 ``getRouters`` 的 ``data`` 树拍平为 ``PageEntry`` 列表。"""
    entries: list[PageEntry] = []

    def walk(
        nodes: Any,
        parent_full: str,
        crumbs: list[str],
    ) -> None:
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            full = _join_path(parent_full, node.get("path") or "")
            title = _node_title(node)
            trail = crumbs + [title] if title else list(crumbs)
            comp = str(node.get("component") or "")
            children = node.get("children")
            entries.append(
                PageEntry(
                    path=full,
                    title=title,
                    breadcrumb=" / ".join(c for c in trail if c),
                    name=str(node.get("name") or ""),
                    component=comp,
                    hidden=bool(node.get("hidden")),
                    is_container=(
                        comp in CONTAINER_COMPONENTS or bool(children)
                    ),
                )
            )
            if children:
                walk(children, full, trail)

    walk(tree, "", [])
    return entries


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _score(entry: PageEntry, query: str) -> float:
    """给单个候选打分,范围约 [0, 1]。越大越匹配。"""
    q = _norm(query)
    if not q:
        return 0.0
    title = _norm(entry.title)
    crumb = _norm(entry.breadcrumb)
    name = _norm(entry.name)

    score = 0.0
    if title and q == title:
        score = max(score, 1.0)
    # 标题双向子串(用户原话往往比标题长,如"看巡检的结果报表")
    if title and (q in title or title in q):
        score = max(score, 0.85)
    if crumb and q in crumb:
        score = max(score, 0.7)
    # 英文路由名命中(如 results)
    if name and (q in name or name in q):
        score = max(score, 0.6)
    fuzzy = max(
        SequenceMatcher(None, q, title).ratio() if title else 0.0,
        SequenceMatcher(None, q, crumb).ratio() if crumb else 0.0,
    )
    score = max(score, fuzzy)

    if entry.is_container:
        score *= 0.6
    if entry.hidden:
        score *= 0.5
    return round(score, 4)


@dataclass
class Ranked:
    entry: PageEntry
    score: float

    def to_dict(self) -> dict[str, Any]:
        data = self.entry.to_dict()
        data["score"] = self.score
        return data


def search_pages(
    entries: Iterable[PageEntry],
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.45,
) -> list[Ranked]:
    """按相关度返回 top_k 候选(已过滤低分项)。"""
    ranked = [Ranked(e, _score(e, query)) for e in entries]
    ranked = [r for r in ranked if r.score >= min_score]
    # 同分时:叶子优先、路径短优先,保证稳定且更"可点"。
    ranked.sort(
        key=lambda r: (
            r.score,
            not r.entry.is_container,
            -len(r.entry.path),
        ),
        reverse=True,
    )
    return ranked[:top_k]


def decide_mode(
    ranked: list[Ranked],
    *,
    confident_min: float = 0.8,
    confident_gap: float = 0.15,
) -> str:
    """根据候选列表判断动作:navigate / disambiguate / not_found。"""
    if not ranked:
        return "not_found"
    top = ranked[0]
    if top.score < confident_min:
        return "disambiguate"
    if len(ranked) == 1:
        return "navigate"
    if top.score - ranked[1].score >= confident_gap:
        return "navigate"
    return "disambiguate"


def build_navigate_directive(entry: PageEntry) -> str:
    """生成前后端约定的跳转指令块(fenced code block)。"""
    payload = {
        "path": entry.path,
        "title": entry.title,
        "breadcrumb": entry.breadcrumb,
    }
    body = json.dumps(payload, ensure_ascii=False)
    return f"```{DIRECTIVE_LANG}\n{body}\n```"


def resolve(
    tree: Iterable[dict],
    query: str,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """一站式:拍平 + 检索 + 判定,返回给 CLI/agent 的结构化结果。"""
    entries = flatten_menu(tree)
    ranked = search_pages(entries, query, top_k=top_k)
    mode = decide_mode(ranked)
    result: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "candidates": [r.to_dict() for r in ranked],
    }
    if mode == "navigate" and ranked:
        result["directive"] = build_navigate_directive(ranked[0].entry)
    return result
