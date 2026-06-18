#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作目录(operation catalog)的加载与索引。

目录是一份 JSON(``catalog/operations.json``),每条描述一个可在传统门户
页面上执行的写操作(当前聚焦"新增"类):它在哪个页面、用哪个方法打开弹窗、
表单数据对象叫什么、有哪些字段、用哪个方法提交。前端执行器据此驱动页面;
本模块只把 JSON 读成带类型的结构,不做任何副作用,方便单测。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[1] / "catalog" / "operations.json"
)


@dataclass
class Field:
    """操作表单里的一个字段(对应页面 el-form-item 的 prop)。"""

    prop: str
    label: str
    type: str = "input"
    required: bool = False
    placeholder: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "prop": self.prop,
            "label": self.label,
            "type": self.type,
            "required": self.required,
        }
        if self.placeholder:
            data["placeholder"] = self.placeholder
        if self.options:
            data["options"] = self.options
        return data


@dataclass
class Operation:
    """目录里的一个操作。"""

    id: str
    name: str
    intent: list[str]
    route: str
    page: str
    open: str
    model: str
    submit: str
    fields: list[Field]
    action: str = "create"
    # kind 区分操作类型:
    #   create  —— 新增类:开弹窗 → 预填 model → 高亮提交(open/model/submit/fields)
    #   trigger —— 触发类(如导出):定位单个按钮 → 高亮让用户点(trigger/button)
    kind: str = "create"
    trigger: str = ""  # 触发类:要点的方法名,如 handleExport
    button: str = ""  # 触发类:按钮文案,如 导出(执行器据此定位高亮)
    menu: str = ""
    component: str = ""
    api: dict[str, Any] = field(default_factory=dict)
    risk: str = "create"
    permission: str = ""

    def required_fields(self) -> list[Field]:
        return [f for f in self.fields if f.required]

    def field_map(self) -> dict[str, Field]:
        return {f.prop: f for f in self.fields}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "intent": list(self.intent),
            "route": self.route,
            "page": self.page,
            "kind": self.kind,
            "open": self.open,
            "model": self.model,
            "submit": self.submit,
            "trigger": self.trigger,
            "button": self.button,
            "action": self.action,
            "menu": self.menu,
            "component": self.component,
            "fields": [f.to_dict() for f in self.fields],
            "api": dict(self.api),
            "risk": self.risk,
            "permission": self.permission,
        }


def _field_from(raw: dict[str, Any]) -> Field:
    return Field(
        prop=str(raw.get("prop") or ""),
        label=str(raw.get("label") or raw.get("prop") or ""),
        type=str(raw.get("type") or "input"),
        required=bool(raw.get("required")),
        placeholder=str(raw.get("placeholder") or ""),
        options=list(raw.get("options") or []),
    )


def _op_from(raw: dict[str, Any]) -> Operation:
    return Operation(
        id=str(raw["id"]),
        name=str(raw.get("name") or raw["id"]),
        intent=[str(x) for x in (raw.get("intent") or [])],
        route=str(raw.get("route") or ""),
        page=str(raw.get("page") or ""),
        open=str(raw.get("open") or "handleAdd"),
        model=str(raw.get("model") or "form"),
        submit=str(raw.get("submit") or "submitForm"),
        fields=[_field_from(f) for f in (raw.get("fields") or [])],
        action=str(raw.get("action") or "create"),
        kind=str(raw.get("kind") or "create"),
        trigger=str(raw.get("trigger") or ""),
        button=str(raw.get("button") or ""),
        menu=str(raw.get("menu") or ""),
        component=str(raw.get("component") or ""),
        api=dict(raw.get("api") or {}),
        risk=str(raw.get("risk") or "create"),
        permission=str(raw.get("permission") or ""),
    )


@dataclass
class Catalog:
    operations: list[Operation]

    def get(self, op_id: str) -> Operation | None:
        for op in self.operations:
            if op.id == op_id:
                return op
        return None

    def __len__(self) -> int:
        return len(self.operations)


def load_catalog(path: str | Path | None = None) -> Catalog:
    """从 JSON 读取操作目录。缺省读 ``catalog/operations.json``。"""
    target = Path(path) if path else DEFAULT_CATALOG
    data = json.loads(target.read_text(encoding="utf-8"))
    ops = [_op_from(o) for o in (data.get("operations") or [])]
    return Catalog(operations=ops)
