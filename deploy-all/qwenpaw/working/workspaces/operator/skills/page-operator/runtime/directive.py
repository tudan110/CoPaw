#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成前后端约定的 ``qwenpaw:action`` 指令块,并校验必填参数。

后端 agent 无法直接操作浏览器,只能在回复里附一段约定指令块,由前端
执行器解析后驱动页面(跳转→打开新增弹窗→预填→高亮提交按钮),提交始终
由用户点击。指令块格式见 ``references/action-contract.md``。
"""
from __future__ import annotations

import json
from typing import Any

from .catalog import Field, Operation


# 指令块的 fenced 语言标识,前后端共同约定(与 qwenpaw:navigate 同族)。
DIRECTIVE_LANG = "qwenpaw:action"


def missing_required(
    op: Operation,
    params: dict[str, Any] | None,
) -> list[Field]:
    """返回还缺的必填字段(值为空/缺失视为未填)。"""
    params = params or {}
    missing: list[Field] = []
    for f in op.required_fields():
        value = params.get(f.prop)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(f)
    return missing


def build_payload(
    op: Operation,
    params: dict[str, Any] | None,
    *,
    route: str | None = None,
) -> dict[str, Any]:
    """组装 action 指令的 JSON 载荷。

    只透传目录里声明过的字段,避免把多余/越权字段带进提交。
    """
    allowed = op.field_map()
    clean = {
        k: v for k, v in (params or {}).items() if k in allowed
    }
    return {
        "op": op.id,
        "action": op.action,
        "route": route or op.route,
        "page": op.page,
        "open": op.open,
        "model": op.model,
        "submit": op.submit,
        "title": op.name,
        "breadcrumb": op.menu,
        "fields": [f.to_dict() for f in op.fields],
        "params": clean,
        "risk": op.risk,
    }


def build_action_directive(
    op: Operation,
    params: dict[str, Any] | None,
    *,
    route: str | None = None,
) -> str:
    """生成 fenced code block 形式的 action 指令(单行 JSON)。"""
    payload = build_payload(op, params, route=route)
    body = json.dumps(payload, ensure_ascii=False)
    return f"```{DIRECTIVE_LANG}\n{body}\n```"
