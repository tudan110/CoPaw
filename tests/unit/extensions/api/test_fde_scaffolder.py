# -*- coding: utf-8 -*-
"""缺口：normalize_skill_name 是骨架渲染的关键路径（决定 staged/<name>/、
env key 前缀等），却一直没有独立单测。这里把它的归一化与拒绝行为钉死。

被测模块在 fde 技能里、不在 src/ 上，沿用 test_fde_selfcheck_findings.py
的 importlib 加载方式（scaffolder.py 只依赖标准库，可直接 exec）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCAFFOLDER_PATH = (
    REPO_ROOT
    / "deploy-all/qwenpaw/working/workspaces/fde/skills"
    / "fde-onboarding/runtime/scaffolder.py"
)


def _load_scaffolder():
    spec = importlib.util.spec_from_file_location(
        "fde_scaffolder_under_test", SCAFFOLDER_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


normalize_skill_name = _load_scaffolder().normalize_skill_name


# --- 合法：原样通过 -------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    [
        "abc-123",
        "a-b-c",
        "a",          # 单字符（边界）
        "5",          # 单字符数字（边界）
        "x" * 300,    # 超长（函数不设长度上限，应原样返回）
    ],
)
def test_valid_names_pass_through_unchanged(name):
    assert normalize_skill_name(name) == name


# --- 归一化：清洗后返回合法名（任务里列作「非法」，实际是被规整） ----------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("_foo", "foo"),                 # 下划线开头 → 去掉前导连字符
        ("abc-", "abc"),                 # 连字符结尾 → 去掉
        ("--x--", "x"),                  # 首尾连字符都去掉
        ("ABC", "abc"),                  # 大写转小写
        ("MySkill", "myskill"),
        ("a--b", "a-b"),                 # 多连字符压缩
        ("a---b", "a-b"),
        ("order_workflow", "order-workflow"),   # 下划线转连字符
        ("big screen!!!", "big-screen"),        # 空格/标点成串 → 单连字符再修边
        ("  Spaced Name  ", "spaced-name"),      # 首尾空白 + 空格 + 大写
    ],
)
def test_names_are_normalized(raw, expected):
    assert normalize_skill_name(raw) == expected


# --- 拒绝：清洗后为空 → ValueError ---------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        "",        # 空串
        "   ",     # 纯空白
        None,      # None（str(name or "") → ""）
        "_",       # 单个非法字符（边界）
        "@",
        "___",     # 全下划线
        "@#$",     # 全标点
        "----",    # 全连字符
    ],
)
def test_empty_or_all_invalid_raises(bad):
    with pytest.raises(ValueError):
        normalize_skill_name(bad)


# --- 边界：超长但混合内容也能规整并保持合法 ------------------------------
def test_long_mixed_name_stays_valid():
    out = normalize_skill_name("a-" * 100)   # 200 字符、以连字符结尾
    assert out == "a-" * 99 + "a"            # 尾部连字符被剥掉，无双连字符
    assert not out.startswith("-") and not out.endswith("-")
    # 幂等：已归一化的名字再跑一次不应改变
    assert normalize_skill_name(out) == out
