# -*- coding: utf-8 -*-
"""page-navigator 技能纯逻辑(runtime/menu.py)的单测。

该逻辑住在 ``deploy-all/.../skills/page-navigator``(技能树被 lint/格式
钩子排除),这里按仓库相对路径加载它,覆盖最易出 bug 的路由拼接与排序。
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
_MENU_PATH = (
    _REPO_ROOT
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "gateway"
    / "skills"
    / "page-navigator"
    / "runtime"
    / "menu.py"
)


def _load_menu():
    spec = importlib.util.spec_from_file_location(
        "page_navigator_menu", _MENU_PATH
    )
    assert spec and spec.loader, f"无法定位 menu.py: {_MENU_PATH}"
    module = importlib.util.module_from_spec(spec)
    # 必须先登记到 sys.modules,否则 `from __future__ import annotations`
    # 下 @dataclass 解析注解时 sys.modules.get(__module__) 为 None 会崩。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


menu = _load_menu()


# 一棵贴近真实 getRouters 的小树,覆盖各类拼接边界。
SAMPLE_TREE = [
    {
        "name": "Ops",
        "path": "/ops",
        "component": "Layout",
        "meta": {"title": "运维中心"},
        "children": [
            {
                "name": "Xj",
                "path": "xj",
                "component": "ParentView",
                "meta": {"title": "自动巡检"},
                "children": [
                    {
                        "name": "Results",
                        "path": "results",
                        "component": "ops/conf/_result/inspection/index.vue",
                        "meta": {"title": "结果报表"},
                    },
                    {
                        "name": "Template",
                        "path": "template",
                        "component": "ops/conf/_template/index.vue",
                        "meta": {"title": "巡检模板管理"},
                    },
                    {
                        "name": "Ops/task",
                        "path": "ops/task",
                        "component": "ops/conf/task",
                        "meta": {"title": "任务配置"},
                    },
                ],
            },
            {
                "name": "PredictionResult",
                "path": "predictionResult",
                "component": "ops/predictionResult/index",
                "meta": {"title": "结果预测"},
            },
            {
                "name": "home",
                "path": "/home",
                "component": "knbase/Home",
                "meta": {"title": "运维知识平台"},
            },
        ],
    },
    {
        "name": "/logs",
        "path": "//logs",
        "component": "Layout",
        "meta": {"title": "日志中心"},
        "children": [
            {
                "name": "syslog",
                "path": "syslog",
                "component": "logs/syslog/index",
                "meta": {"title": "syslog日志"},
            }
        ],
    },
]


def _by_title(entries, title):
    matches = [e for e in entries if e.title == title]
    assert matches, f"未找到标题为 {title!r} 的节点"
    return matches[0]


def test_relative_join_builds_target_path():
    entries = menu.flatten_menu(SAMPLE_TREE)
    assert _by_title(entries, "结果报表").path == "/ops/xj/results"


def test_absolute_child_path_used_as_is():
    entries = menu.flatten_menu(SAMPLE_TREE)
    # /home 带前导斜杠 → 绝对路径,不拼成 /ops/home。
    assert _by_title(entries, "运维知识平台").path == "/home"


def test_multi_segment_relative_child():
    entries = menu.flatten_menu(SAMPLE_TREE)
    assert _by_title(entries, "任务配置").path == "/ops/xj/ops/task"


def test_double_slash_preserved():
    entries = menu.flatten_menu(SAMPLE_TREE)
    assert _by_title(entries, "日志中心").path == "//logs"
    assert _by_title(entries, "syslog日志").path == "//logs/syslog"


def test_breadcrumb_is_full_trail():
    entries = menu.flatten_menu(SAMPLE_TREE)
    assert (
        _by_title(entries, "结果报表").breadcrumb
        == "运维中心 / 自动巡检 / 结果报表"
    )


@pytest.mark.parametrize(
    "query",
    ["巡检结果报表", "看巡检的结果报表", "结果报表"],
)
def test_search_finds_inspection_report(query):
    entries = menu.flatten_menu(SAMPLE_TREE)
    ranked = menu.search_pages(entries, query)
    assert ranked, f"{query!r} 应有候选"
    assert ranked[0].entry.title == "结果报表"


def test_results_outranks_prediction():
    entries = menu.flatten_menu(SAMPLE_TREE)
    ranked = menu.search_pages(entries, "结果报表")
    titles = [r.entry.title for r in ranked]
    assert titles[0] == "结果报表"
    if "结果预测" in titles:
        assert titles.index("结果报表") < titles.index("结果预测")


def test_resolve_navigate_emits_directive():
    result = menu.resolve(SAMPLE_TREE, "巡检结果报表")
    assert result["mode"] == "navigate"
    directive = result["directive"]
    match = re.search(r"```qwenpaw:navigate\s*([\s\S]*?)```", directive)
    assert match, "指令块应能被前端契约正则解析"
    payload = json.loads(match.group(1).strip())
    assert payload["path"] == "/ops/xj/results"
    assert payload["title"] == "结果报表"


def test_resolve_disambiguate_on_tie():
    # "结果" 同时命中 结果报表 / 结果预测 → 让用户确认。
    result = menu.resolve(SAMPLE_TREE, "结果")
    assert result["mode"] == "disambiguate"
    assert len(result["candidates"]) >= 2
    assert "directive" not in result


def test_resolve_not_found():
    result = menu.resolve(SAMPLE_TREE, "蓝牙耳机配对教程")
    assert result["mode"] == "not_found"
    assert "directive" not in result
