# -*- coding: utf-8 -*-
"""Tests for QwenPawAgent fast-fail / tool-storm convergence detection.

The detector nudges the agent to stop when it is stuck in a tool-call storm
(repeated identical calls, or a run of empty/error results) instead of
flailing until ``max_iters`` / timeout. These tests exercise the pure
detection logic and the cooldown on hint injection without constructing a
full agent.
"""

# pylint: disable=protected-access

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.constant import (
    FASTFAIL_CONVERGE_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)


def _agent(context: list, *, language: str = "zh", cur_iter: int = 5):
    """Build a bare QwenPawAgent with just the state the detector touches."""
    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._language = language
    agent.state = SimpleNamespace(context=context, cur_iter=cur_iter)
    return agent


def _msg(*blocks):
    return SimpleNamespace(content=list(blocks))


def _call(name: str, args: dict | str):
    return {"type": "tool_call", "name": name, "input": args}


def _result(output, state: str = "success"):
    return {"type": "tool_result", "output": output, "state": state}


# --------------------------------------------------------------------------
# Duplicate-call storm
# --------------------------------------------------------------------------


def test_detects_repeated_identical_tool_calls():
    ctx = [
        _msg(_call("execute_shell_command", {"cmd": "psql -c 'select 1'"})),
        _msg(_result("ok")),
        _msg(_call("execute_shell_command", {"cmd": "psql -c 'select 1'"})),
        _msg(_result("ok")),
        _msg(_call("execute_shell_command", {"cmd": "psql -c 'select 1'"})),
        _msg(_result("ok")),
    ]
    hint = _agent(ctx)._detect_non_convergence()
    assert hint is not None
    assert "execute_shell_command" in hint
    assert "停止重试" in hint  # zh convergence directive


def test_arg_key_reordering_still_counts_as_duplicate():
    ctx = [
        _msg(_call("q", '{"a":1,"b":2}')),
        _msg(_result("x")),
        _msg(_call("q", '{"b":2,"a":1}')),
        _msg(_result("x")),
        _msg(_call("q", '{"a":1, "b":2}')),
        _msg(_result("x")),
    ]
    assert _agent(ctx)._detect_non_convergence() is not None


# --------------------------------------------------------------------------
# Empty / error streak
# --------------------------------------------------------------------------


def test_detects_consecutive_empty_results():
    # Four different calls, each returning empty/not-found → data unavailable.
    ctx = []
    for i in range(4):
        ctx.append(_msg(_call(f"tool_{i}", {"q": i})))
        ctx.append(_msg(_result('{"code":200,"msg":"ok","data":null}')))
    hint = _agent(ctx)._detect_non_convergence()
    assert hint is not None
    assert "数据源" in hint or "未查询到" in hint


def test_detects_error_state_streak():
    ctx = []
    for i in range(4):
        ctx.append(_msg(_call(f"t{i}", {})))
        ctx.append(_msg(_result("接口返回空响应", state="error")))
    assert _agent(ctx)._detect_non_convergence() is not None


def test_marker_in_text_counts_as_empty():
    ctx = []
    for i in range(4):
        ctx.append(_msg(_call(f"t{i}", {})))
        ctx.append(_msg(_result("查询结果：暂无数据")))
    assert _agent(ctx)._detect_non_convergence() is not None


# --------------------------------------------------------------------------
# Healthy trajectories must NOT trigger (no false positives)
# --------------------------------------------------------------------------


def test_distinct_calls_with_real_data_do_not_trigger():
    ctx = [
        _msg(_call("a", {"x": 1})),
        _msg(_result('{"code":200,"data":[1,2,3]}')),
        _msg(_call("b", {"x": 2})),
        _msg(_result('{"code":200,"data":{"total":42}}')),
        _msg(_call("c", {"x": 3})),
        _msg(_result("这是一段有内容的正常结果文本")),
    ]
    assert _agent(ctx)._detect_non_convergence() is None


def test_one_empty_then_recovery_does_not_trigger():
    ctx = [
        _msg(_call("a", {})),
        _msg(_result('{"code":200,"data":null}')),  # one empty
        _msg(_call("b", {})),
        _msg(_result('{"code":200,"data":[1]}')),  # recovered → streak broken
    ]
    assert _agent(ctx)._detect_non_convergence() is None


def test_empty_context_returns_none():
    assert _agent([])._detect_non_convergence() is None


# --------------------------------------------------------------------------
# Injection + cooldown
# --------------------------------------------------------------------------


def test_inject_appends_tagged_hint_once_then_cools_down():
    ctx = [
        _msg(_call("q", {"a": 1})),
        _msg(_result("暂无数据")),
        _msg(_call("q", {"a": 1})),
        _msg(_result("暂无数据")),
        _msg(_call("q", {"a": 1})),
        _msg(_result("暂无数据")),
    ]
    agent = _agent(ctx, cur_iter=5)

    before = len(ctx)
    agent._maybe_inject_convergence_hint()
    assert len(ctx) == before + 1
    injected = ctx[-1]
    assert injected.metadata[QWENPAW_MESSAGE_TAG_KEY] == (
        FASTFAIL_CONVERGE_MESSAGE_TAG
    )

    # Same iteration → cooldown suppresses a second injection.
    agent._maybe_inject_convergence_hint()
    assert len(ctx) == before + 1
