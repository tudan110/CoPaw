# -*- coding: utf-8 -*-
"""操作目录 operations.json 的结构校验。

保证每条操作可被 operator agent(收参)+ 前端执行器(驱动页面)安全消费:
id 规范且唯一、有意图词、有 page/open/model/submit、有可定位的 route 或
component、字段结构良好。新增/扫描合入的条目都会被这里挡一道。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_CATALOG = (
    Path(__file__).resolve().parents[4]
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "operator"
    / "skills"
    / "page-operator"
    / "catalog"
    / "operations.json"
)

ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9]+)*\.(add|update|delete)$", re.I)
VALID_TYPES = {
    "input",
    "textarea",
    "select",
    "date",
    "switch",
    "radio",
    "checkbox",
    "number",
}


def _load() -> dict:
    return json.loads(_CATALOG.read_text(encoding="utf-8"))


_OPS = _load().get("operations") or []


def test_catalog_loads_and_has_seed():
    ids = {o["id"] for o in _OPS}
    assert _OPS, "目录不应为空"
    assert "workflow.category.add" in ids


def test_unique_ids():
    ids = [o["id"] for o in _OPS]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    assert not dups, f"存在重复 id: {dups}"


@pytest.mark.parametrize("op", _OPS, ids=[o["id"] for o in _OPS])
def test_each_operation_well_formed(op):
    assert ID_RE.match(op["id"]), f"id 命名不规范: {op['id']}"
    assert str(op.get("name", "")).strip(), f"{op['id']} 缺 name"

    intents = op.get("intent") or []
    assert (
        isinstance(intents, list)
        and intents
        and all(isinstance(x, str) and x.strip() for x in intents)
    ), f"{op['id']} intent 必须是非空字符串列表"

    assert str(op.get("page", "")).strip(), f"{op['id']} page(组件name)必填"
    for key in ("open", "model", "submit"):
        assert str(op.get(key, "")).strip(), f"{op['id']} {key} 必填"

    assert op.get("route") or op.get(
        "component"
    ), f"{op['id']} 需要 route 或 component 以定位页面"

    fields = op.get("fields") or []
    assert fields, f"{op['id']} fields 不应为空"
    props = []
    for f in fields:
        assert str(f.get("prop", "")).strip(), f"{op['id']} 字段缺 prop"
        assert str(f.get("label", "")).strip(), f"{op['id']} 字段缺 label"
        ftype = f.get("type", "input")
        assert ftype in VALID_TYPES, f"{op['id']} 未知字段类型 {ftype}"
        props.append(f["prop"])
    assert len(props) == len(set(props)), f"{op['id']} 字段 prop 重复"

    assert op.get("risk", "create") in {
        "create",
        "update",
        "delete",
    }, f"{op['id']} risk 取值非法"
