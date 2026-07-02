# -*- coding: utf-8 -*-
"""Tests for QwenPawAgent fast-fail / tool-storm convergence detection.

The detector nudges the agent to stop when it is stuck in a tool-call storm
(repeated identical calls, or a run of empty/error results) instead of
flailing until ``max_iters`` / timeout. For repeated identical calls with a
usable prior result, it echoes that result back (soft cache) so the model
reuses it instead of re-running — safe even for shell/mutating tools because
nothing is silently suppressed. These tests exercise the pure detection logic
and the cooldown on hint injection without constructing a full agent.
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


def _call(name: str, args, cid: str = "c1"):
    return {"type": "tool_call", "id": cid, "name": name, "input": args}


def _result(output, state: str = "success", cid: str = "c1"):
    return {"type": "tool_result", "id": cid, "output": output, "state": state}


def _pair(name, args, output, *, i, state="success"):
    """A tool_call + its matching tool_result, sharing a unique id."""
    cid = f"c{i}"
    return [_msg(_call(name, args, cid)), _msg(_result(output, state, cid))]


# --------------------------------------------------------------------------
# Duplicate-call storm — with a usable prior result → echo it back (reuse)
# --------------------------------------------------------------------------


def test_repeated_call_echoes_prior_result_for_reuse():
    ctx = []
    for i in range(3):
        ctx += _pair(
            "execute_shell_command",
            {"cmd": "psql -c 'select count(*)'"},
            "count = 42",
            i=i,
        )
    hint = _agent(ctx)._detect_non_convergence()
    assert hint is not None
    assert "execute_shell_command" in hint
    assert "复用" in hint            # reuse directive
    assert "count = 42" in hint      # prior result echoed back


def test_arg_key_reordering_still_counts_as_duplicate():
    ctx = []
    for i, args in enumerate(('{"a":1,"b":2}', '{"b":2,"a":1}', '{"a":1, "b":2}')):
        ctx += _pair("q", args, "some result", i=i)
    assert _agent(ctx)._detect_non_convergence() is not None


def test_repeated_call_all_empty_reports_unavailable():
    # Same call 3x, every result empty → nothing to reuse → unavailable hint.
    ctx = []
    for i in range(3):
        ctx += _pair("q", {"x": 1}, '{"code":200,"data":null}', i=i)
    hint = _agent(ctx)._detect_non_convergence()
    assert hint is not None
    assert "数据源" in hint or "未查询到" in hint
    assert "复用" not in hint  # no usable result → not a reuse hint


# --------------------------------------------------------------------------
# Empty / error streak (distinct calls) → stop + report unavailable
# --------------------------------------------------------------------------


def test_detects_consecutive_empty_results():
    ctx = []
    for i in range(4):
        ctx += _pair(f"tool_{i}", {"q": i}, '{"code":200,"data":null}', i=i)
    hint = _agent(ctx)._detect_non_convergence()
    assert hint is not None
    assert "数据源" in hint or "未查询到" in hint


def test_detects_error_state_streak():
    ctx = []
    for i in range(4):
        ctx += _pair(f"t{i}", {}, "接口返回空响应", i=i, state="error")
    assert _agent(ctx)._detect_non_convergence() is not None


def test_marker_in_text_counts_as_empty():
    ctx = []
    for i in range(4):
        ctx += _pair(f"t{i}", {}, "查询结果：暂无数据", i=i)
    assert _agent(ctx)._detect_non_convergence() is not None


def test_delegation_no_text_content_counts_as_empty():
    # chat_with_agent to a sub-agent that keeps returning empty text → the
    # "(No text content in response)" outputs must trip the empty streak so
    # the delegation loop converges instead of spinning to timeout.
    ctx = []
    for i in range(4):
        ctx += _pair(
            "chat_with_agent",
            {"to_agent": "query", "text": f"q{i}"},
            "[SESSION: gateway:to:query:x] (No text content in response)",
            i=i,
        )
    hint = _agent(ctx)._detect_non_convergence()
    assert hint is not None


# --------------------------------------------------------------------------
# Healthy trajectories must NOT trigger (no false positives)
# --------------------------------------------------------------------------


def test_distinct_calls_with_real_data_do_not_trigger():
    ctx = []
    ctx += _pair("a", {"x": 1}, '{"code":200,"data":[1,2,3]}', i=0)
    ctx += _pair("b", {"x": 2}, '{"code":200,"data":{"total":42}}', i=1)
    ctx += _pair("c", {"x": 3}, "这是一段有内容的正常结果文本", i=2)
    assert _agent(ctx)._detect_non_convergence() is None


def test_one_empty_then_recovery_does_not_trigger():
    ctx = []
    ctx += _pair("a", {}, '{"code":200,"data":null}', i=0)   # one empty
    ctx += _pair("b", {}, '{"code":200,"data":[1]}', i=1)    # recovered
    assert _agent(ctx)._detect_non_convergence() is None


def test_empty_context_returns_none():
    assert _agent([])._detect_non_convergence() is None


def _user_msg(text: str):
    return SimpleNamespace(role="user", metadata={}, content=[])


def test_detection_scoped_to_current_turn_ignores_prior_turn_calls():
    # Turn 1: one call. Genuine user message. Turn 2: two identical calls.
    # Scoped to turn 2 (start after the user msg), only 2 dups < threshold 3.
    ctx = []
    ctx += _pair("q", {"a": 1}, "r", i=0)          # prior turn
    ctx.append(_user_msg("再查一次"))               # real user turn boundary
    ctx += _pair("q", {"a": 1}, "r", i=1)
    ctx += _pair("q", {"a": 1}, "r", i=2)
    agent = _agent(ctx)
    start = agent._current_turn_start(ctx)
    # Whole-context scan would see 3 dups (trigger); current-turn scan sees 2.
    assert agent._detect_non_convergence(ctx, start) is None
    assert agent._detect_non_convergence(ctx, 0) is not None


def test_current_turn_start_skips_injected_tagged_user_msgs():
    tagged = SimpleNamespace(
        role="user", metadata={QWENPAW_MESSAGE_TAG_KEY: "auto_continue"},
        content=[],
    )
    ctx = [_user_msg("真问题"), tagged]
    # start points at the genuine user msg (index 0), not the tagged one.
    assert _agent(ctx)._current_turn_start(ctx) == 0


def test_result_snippet_truncates_long_results():
    long = "x" * 5000
    ctx = []
    for i in range(3):
        ctx += _pair("q", {"a": 1}, long, i=i)
    hint = _agent(ctx)._detect_non_convergence()
    assert hint is not None
    assert "截断" in hint            # truncation marker present
    assert len(hint) < 3000          # not the full 5000-char result


# --------------------------------------------------------------------------
# Injection + cooldown
# --------------------------------------------------------------------------


def test_inject_appends_tagged_hint_once_then_cools_down():
    ctx = []
    for i in range(3):
        ctx += _pair("q", {"a": 1}, "暂无数据", i=i)
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
