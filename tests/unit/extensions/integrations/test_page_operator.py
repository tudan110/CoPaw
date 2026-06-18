# -*- coding: utf-8 -*-
"""page-operator 技能纯逻辑(runtime/*.py)的单测。

该逻辑住在 ``deploy-all/.../workspaces/operator/skills/page-operator``
(技能树被 lint/格式钩子排除),这里按仓库相对路径把 runtime 当成一个
唯一命名的包加载,覆盖意图匹配、必填校验、指令生成与路由反查。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SKILL_ROOT = (
    _REPO_ROOT
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "operator"
    / "skills"
    / "page-operator"
)
_RUNTIME = _SKILL_ROOT / "runtime"
_PKG = "page_operator_runtime"


def _load_pkg():
    """把 runtime/ 作为唯一命名的包加载,使内部相对 import 正常解析。"""
    pkg_spec = importlib.util.spec_from_file_location(
        _PKG,
        _RUNTIME / "__init__.py",
        submodule_search_locations=[str(_RUNTIME)],
    )
    assert pkg_spec and pkg_spec.loader
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[_PKG] = pkg
    pkg_spec.loader.exec_module(pkg)

    def load(name):
        spec = importlib.util.spec_from_file_location(
            f"{_PKG}.{name}", _RUNTIME / f"{name}.py"
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PKG}.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    catalog = load("catalog")
    matcher = load("matcher")
    directive = load("directive")
    menu_client = load("menu_client")
    return catalog, matcher, directive, menu_client


catalog_mod, matcher_mod, directive_mod, menu_mod = _load_pkg()


def _catalog():
    return catalog_mod.load_catalog()


def _category_op():
    op = _catalog().get("workflow.category.add")
    assert op is not None, "种子目录应含 workflow.category.add"
    return op


# ---- 目录加载 ----


def test_seed_catalog_loads_category():
    op = _category_op()
    assert op.name == "新建流程分类"
    assert op.open == "handleAdd"
    assert op.model == "form"
    assert op.submit == "submitForm"
    required = {f.prop for f in op.required_fields()}
    assert required == {"categoryName", "code"}


# ---- 意图匹配 ----


@pytest.mark.parametrize(
    "query",
    ["帮我新建一个流程分类", "新建流程分类", "创建流程分类", "加一个流程分类"],
)
def test_match_create_category(query):
    result = matcher_mod.resolve(_catalog(), query)
    assert result["mode"] == "execute"
    assert result["candidates"][0]["id"] == "workflow.category.add"


def test_exact_intent_scores_full():
    op = _category_op()
    assert matcher_mod.score_operation(op, "新建流程分类") == 1.0


def test_unrelated_query_not_found():
    result = matcher_mod.resolve(_catalog(), "查一下今天的告警统计")
    assert result["mode"] == "not_found"
    assert result["candidates"] == []


# ---- 必填校验 ----


def test_missing_required_reports_code():
    op = _category_op()
    missing = directive_mod.missing_required(op, {"categoryName": "财务类"})
    assert [m.prop for m in missing] == ["code"]


def test_blank_value_counts_as_missing():
    op = _category_op()
    missing = directive_mod.missing_required(
        op, {"categoryName": "财务类", "code": "   "}
    )
    assert [m.prop for m in missing] == ["code"]


def test_all_required_present():
    op = _category_op()
    missing = directive_mod.missing_required(
        op, {"categoryName": "财务类", "code": "FIN"}
    )
    assert missing == []


# ---- 指令生成 ----


def test_directive_parses_with_frontend_contract():
    op = _category_op()
    block = directive_mod.build_action_directive(
        op, {"categoryName": "财务类", "code": "FIN", "remark": "x"}
    )
    match = re.search(r"```qwenpaw:action\s*([\s\S]*?)```", block)
    assert match, "指令块应能被前端契约正则解析"
    payload = json.loads(match.group(1).strip())
    assert payload["op"] == "workflow.category.add"
    assert payload["route"] == op.route  # 用目录实际 route,不写死
    assert payload["page"] == "Category"
    assert payload["open"] == "handleAdd"
    assert payload["model"] == "form"
    assert payload["submit"] == "submitForm"
    assert payload["action"] == "create"
    assert payload["params"] == {
        "categoryName": "财务类",
        "code": "FIN",
        "remark": "x",
    }


def test_payload_drops_undeclared_params():
    # 越权/多余字段不得带进提交,只透传目录声明过的字段。
    op = _category_op()
    payload = directive_mod.build_payload(
        op, {"categoryName": "财务类", "code": "FIN", "evil": "boom"}
    )
    assert "evil" not in payload["params"]
    assert set(payload["params"]) == {"categoryName", "code"}


def test_route_override_applied():
    op = _category_op()
    payload = directive_mod.build_payload(
        op, {"categoryName": "a", "code": "b"}, route="/live/route"
    )
    assert payload["route"] == "/live/route"


# ---- 菜单路由反查(纯逻辑,无网络) ----


_SAMPLE_TREE = [
    {
        "name": "Workflow",
        "path": "/workflow",
        "component": "Layout",
        "meta": {"title": "工单中心"},
        "children": [
            {
                "name": "Category",
                "path": "category",
                "component": "workflow/category/index",
                "meta": {"title": "流程分类"},
            }
        ],
    }
]


def test_resolve_route_by_component():
    path = menu_mod.resolve_route(
        _SAMPLE_TREE, component="workflow/category/index"
    )
    assert path == "/workflow/category"


def test_resolve_route_by_name_fallback():
    path = menu_mod.resolve_route(_SAMPLE_TREE, name="Category")
    assert path == "/workflow/category"


def test_resolve_route_miss_returns_none():
    assert menu_mod.resolve_route(_SAMPLE_TREE, component="no/such") is None
