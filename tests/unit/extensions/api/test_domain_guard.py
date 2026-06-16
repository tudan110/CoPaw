# -*- coding: utf-8 -*-
"""Tests for the domain-relevance guard (extensions/api/domain_guard)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import qwenpaw.extensions.api.domain_guard as dg


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------
def _make_llm(payload_for):
    """Build a fake LLM coroutine. ``payload_for`` maps a substring -> JSON str."""

    async def _fake(messages):
        prompt = messages[-1]["content"].lower()
        for needle, out in payload_for.items():
            if needle.lower() in prompt:
                return out
        # default: relevant network-mgmt verdict
        return '{"relevant": true, "confidence": 0.9, "category": "故障/告警管理", "reason": "围绕告警"}'

    return _fake


@pytest.fixture(autouse=True)
def _reset_guard(monkeypatch):
    """Clear the verdict cache and any leftover LLM override before each test."""
    dg._clear_cache()
    dg._llm_override = None
    # neutralise env so config defaults apply
    for key in (
        "QWENPAW_DOMAIN_GUARD_MODE",
        "QWENPAW_DOMAIN_GUARD_CONFIDENCE",
        "QWENPAW_DOMAIN_GUARD_LLM_TIMEOUT",
        "QWENPAW_DOMAIN_GUARD_ALLOWLIST",
        "COPAW_DOMAIN_GUARD_MODE",
        "COPAW_DOMAIN_GUARD_ALLOWLIST",
    ):
        monkeypatch.delenv(key, raising=False)
    yield
    dg._clear_cache()
    dg._llm_override = None


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def test_config_defaults():
    cfg = dg.load_config()
    assert cfg.mode == "block"
    assert cfg.confidence_threshold == pytest.approx(0.7)
    assert cfg.llm_timeout_seconds == pytest.approx(15.0)
    assert cfg.extra_allowlist == ()


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("QWENPAW_DOMAIN_GUARD_MODE", "WARN")
    monkeypatch.setenv("QWENPAW_DOMAIN_GUARD_CONFIDENCE", "0.55")
    monkeypatch.setenv("QWENPAW_DOMAIN_GUARD_ALLOWLIST", "shell_runner, https://x.io/mcp\nfoo")
    cfg = dg.load_config()
    assert cfg.mode == "warn"
    assert cfg.confidence_threshold == pytest.approx(0.55)
    assert cfg.extra_allowlist == ("shell_runner", "https://x.io/mcp", "foo")


# ---------------------------------------------------------------------------
# keyword prefilter
# ---------------------------------------------------------------------------
def test_prefilter_signals():
    sig = dg._prefilter("这是一个告警收敛与根因分析技能，会调用 CMDB 和 Grafana")
    assert "告警" in sig["positive"] or "根因" in sig["positive"]
    assert "cmdb" in sig["positive"]
    assert "grafana" in sig["borderline"]
    assert sig["negative"] == []

    sig2 = dg._prefilter("识别发票并做会计记账")
    assert "发票" in sig2["negative"]
    assert sig2["positive"] == []


# ---------------------------------------------------------------------------
# L0 short-circuits (no LLM)
# ---------------------------------------------------------------------------
def test_mode_off_allows_everything():
    import os

    os.environ["QWENPAW_DOMAIN_GUARD_MODE"] = "off"
    try:
        # no LLM override set -> if it tried to call the model it would fail,
        # but mode=off must short-circuit before that.
        v = dg.judge_text(kind="skill", name="invoice_ocr", description="发票识别")
        assert v.allowed and v.source == "disabled"
    finally:
        del os.environ["QWENPAW_DOMAIN_GUARD_MODE"]


def test_builtin_allowed_without_llm():
    v = dg.judge_text(
        kind="skill", name="QA_source_index", description="x", content="y", is_builtin=True
    )
    assert v.allowed and v.source == "builtin"


def test_allowlist_allows_without_llm(monkeypatch):
    monkeypatch.setenv("QWENPAW_DOMAIN_GUARD_ALLOWLIST", "shell_runner,https://tools.example/mcp")
    v1 = dg.judge_text(kind="skill", name="shell_runner", description="执行任意命令")
    assert v1.allowed and v1.source == "allowlist"
    v2 = dg.judge_text(
        kind="mcp",
        name="some-tool",
        description="generic",
        extra={"url": "https://tools.example/mcp", "transport": "streamable_http"},
    )
    assert v2.allowed and v2.source == "allowlist"


# ---------------------------------------------------------------------------
# L2/L3 LLM verdict + confidence banding
# ---------------------------------------------------------------------------
def test_strong_lexicon_signal_allows_without_llm():
    """>=2 positive terms, 0 negative, 0 borderline -> fast-path allow."""
    calls = []

    async def _llm_should_not_be_called(messages):
        calls.append(1)
        return '{"relevant": false, "confidence": 0.99, "category": "x", "reason": "y"}'

    dg._llm_override = _llm_should_not_be_called
    v = dg.judge_text(
        kind="mcp",
        name="nms_cmdb_query",
        description="网管 CMDB 查询工具：按设备/链路/IP/网元查询配置项与拓扑关系，供故障分析、巡检与告警处置引用",
    )
    assert v.allowed and v.source == "lexicon"
    assert len(calls) == 0  # LLM was not consulted


def test_off_domain_with_negative_signal_still_goes_to_llm():
    """A negative-signal hit disqualifies the lexicon fast-path."""
    dg._llm_override = _make_llm(
        {"trader": '{"relevant": false, "confidence": 0.95, "category": "金融交易", "reason": "炒股工具"}'}
    )
    v = dg.judge_text(
        kind="mcp",
        name="stock_trader",
        description="连接券商接口，查询行情、下单买卖、管理持仓与止盈止损交易策略",
    )
    assert not v.allowed and v.decision == "reject" and v.source == "llm"


def test_relevant_high_confidence_allows():
    dg._llm_override = _make_llm({})
    v = dg.judge_text(
        # <2 lexicon hits -> below the fast-path threshold -> the LLM decides
        kind="skill", name="incident_assistant", description="辅助处理一线告警事件"
    )
    assert v.allowed and v.source == "llm" and v.category


def test_not_relevant_rejects():
    dg._llm_override = _make_llm(
        {"invoice": '{"relevant": false, "confidence": 0.95, "category": "财务/票据", "reason": "票据识别属财务"}'}
    )
    v = dg.judge_text(kind="skill", name="invoice-ocr", description="识别 invoice 抽取金额")
    assert not v.allowed and v.decision == "reject"
    msg = v.reject_message()
    assert "网络管理" in msg and "财务" in msg


def test_relevant_but_low_confidence_is_rejected_strict():
    dg._llm_override = _make_llm(
        {"shell-runner": '{"relevant": true, "confidence": 0.5, "category": "通用工具", "reason": "未声明网管用途"}'}
    )
    v = dg.judge_text(kind="skill", name="shell-runner", description="执行任意 shell 命令")
    assert not v.allowed and v.decision == "reject"
    assert "从严" in v.reject_message() or "置信度" in v.reject_message()


def test_custom_threshold(monkeypatch):
    monkeypatch.setenv("QWENPAW_DOMAIN_GUARD_CONFIDENCE", "0.4")
    dg._llm_override = _make_llm(
        {"borderline": '{"relevant": true, "confidence": 0.5, "category": "运维工具", "reason": "x"}'}
    )
    v = dg.judge_text(kind="skill", name="borderline", description="borderline tool")
    # 0.5 >= 0.4 -> allowed now
    assert v.allowed


def test_llm_error_denies():
    async def _boom(messages):
        raise RuntimeError("model down")

    dg._llm_override = _boom
    v = dg.judge_text(kind="mcp", name="weird", description="???")
    assert not v.allowed and v.decision == "reject_unavailable"
    assert "审核失败" in v.reject_message()


def test_unparseable_llm_output_denies():
    async def _garbage(messages):
        return "I think this is fine, sure!"

    dg._llm_override = _garbage
    v = dg.judge_text(kind="skill", name="x", description="y")
    assert not v.allowed and v.decision == "reject_unavailable"


def test_llm_unavailable_falls_back_to_lexicon_when_on_domain():
    """Judge down + strong on-domain lexicon signal -> graceful admit.

    Mirrors the real ``zgops-cmdb-import`` case: a clearly network-management
    skill must still import when the model is slow / rate-limited, instead of
    being walled off by fail-closed. A borderline word ("浏览器") keeps it off
    the no-LLM fast-path, so the fallback branch is what admits it.
    """

    async def _boom(messages):
        raise RuntimeError("model down")

    dg._llm_override = _boom
    v = dg.judge_text(
        kind="skill",
        name="zgops-cmdb-import",
        description="CMDB 资源导入：批量导入资源清单到 CMDB，不要打开浏览器",
    )
    assert v.allowed and v.source == "lexicon-fallback"


def test_llm_unavailable_does_not_rescue_off_domain():
    """Fallback only rescues clean on-domain signals; any negative-signal hit
    keeps the fail-closed reject when the judge is down."""

    async def _boom(messages):
        raise RuntimeError("model down")

    dg._llm_override = _boom
    v = dg.judge_text(
        kind="skill",
        name="cmdb-invoice",
        description="把 CMDB 资源导出后生成财务报表与发票",
    )
    assert not v.allowed and v.decision == "reject_unavailable"


def test_warn_mode_does_not_block(monkeypatch):
    monkeypatch.setenv("QWENPAW_DOMAIN_GUARD_MODE", "warn")
    dg._llm_override = _make_llm(
        {"invoice": '{"relevant": false, "confidence": 0.99, "category": "财务", "reason": "x"}'}
    )
    v = dg.judge_text(kind="skill", name="invoice-thing", description="识别 invoice")
    assert v.allowed  # warn mode -> passes through with a flag

    async def _boom(messages):
        raise RuntimeError("down")

    dg._llm_override = _boom
    v2 = dg.judge_text(kind="skill", name="x", description="y")
    assert v2.allowed  # error in warn mode also passes


def test_json_fenced_output_is_parsed():
    async def _fenced(messages):
        return '```json\n{"relevant": true, "confidence": 0.85, "category": "监控", "reason": "ok"}\n```'

    dg._llm_override = _fenced
    v = dg.judge_text(kind="skill", name="monitor-x", description="监控指标采集")
    assert v.allowed and v.category == "监控"


# ---------------------------------------------------------------------------
# caching
# ---------------------------------------------------------------------------
def test_verdict_is_cached_by_content():
    calls = []

    async def _counting(messages):
        calls.append(1)
        return '{"relevant": true, "confidence": 0.9, "category": "告警", "reason": "x"}'

    dg._llm_override = _counting
    # No lexicon keywords here -> the fast-path is skipped and the LLM runs.
    kw = dict(kind="skill", name="acme_tracker", description="排查现场问题", content="详细步骤见下")
    v1 = dg.judge_text(**kw)
    v2 = dg.judge_text(**kw)
    assert v1.allowed and v2.allowed
    assert len(calls) == 1  # second call served from cache

    # different content -> not cached
    dg.judge_text(kind="skill", name="acme_tracker", description="排查现场问题", content="另一段内容")
    assert len(calls) == 2


def test_error_verdicts_are_not_cached():
    state = {"fail": True}

    async def _flaky(messages):
        if state["fail"]:
            raise RuntimeError("transient")
        return '{"relevant": true, "confidence": 0.9, "category": "告警", "reason": "x"}'

    dg._llm_override = _flaky
    kw = dict(kind="skill", name="acme_probe", description="排查现场问题", content="c")
    v1 = dg.judge_text(**kw)
    assert v1.decision == "reject_unavailable"
    state["fail"] = False
    v2 = dg.judge_text(**kw)
    assert v2.allowed  # retried, not stuck on the cached error


# ---------------------------------------------------------------------------
# async entry point
# ---------------------------------------------------------------------------
async def test_judge_text_async():
    dg._llm_override = _make_llm(
        {"cmdb": '{"relevant": true, "confidence": 0.92, "category": "资源/CMDB", "reason": "查询网管 CMDB"}'}
    )
    v = await dg.judge_text_async(
        kind="mcp",
        name="cmdb-sql",
        description="连接网管 CMDB 数据库执行只读 SQL",
        extra={"transport": "stdio", "command": "python cmdb.py"},
    )
    assert v.allowed and v.category == "资源/CMDB"


# ---------------------------------------------------------------------------
# payload / message shapes
# ---------------------------------------------------------------------------
def test_to_payload_shape():
    v = dg.DomainVerdict(False, 0.9, "财务/票据", "票据识别属财务", "reject", "llm")
    p = v.to_payload(kind="skill", name="invoice-ocr")
    assert p["type"] == "domain_rejected"
    assert p["kind"] == "skill" and p["name"] == "invoice-ocr"
    assert p["category"] == "财务/票据"
    assert "网络管理" in p["detail"]

    v2 = dg.DomainVerdict(False, 0.0, "", "x", "reject_unavailable", "error")
    p2 = v2.to_payload(kind="mcp", name="z")
    assert p2["type"] == "domain_check_unavailable"
    assert "审核失败" in p2["detail"]


# ---------------------------------------------------------------------------
# skill-scanner analyzer integration
# ---------------------------------------------------------------------------
def _write_skill(tmp: Path, name: str, description: str) -> Path:
    d = tmp / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\n---\n\n# {name}\n\n{description}\n',
        encoding="utf-8",
    )
    return d


def test_skill_scanner_analyzer_blocks_off_domain():
    from qwenpaw.extensions.api.domain_guard.analyzer import (
        register_skill_domain_analyzer,
    )
    from qwenpaw.security.skill_scanner import SkillScanError, scan_skill_directory

    dg._llm_override = _make_llm(
        {"invoice": '{"relevant": false, "confidence": 0.95, "category": "财务/票据", "reason": "票据识别属财务"}'}
    )
    register_skill_domain_analyzer()  # idempotent

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        good = _write_skill(tmp, "alarm_skill", "活动告警根因分析与闭环处置")
        bad = _write_skill(tmp, "invoice_ocr", "识别 invoice 图片并抽取金额税号")

        # good skill: no domain block
        try:
            scan_skill_directory(good, skill_name="alarm_skill", block=True, timeout=20)
        except SkillScanError as exc:  # pragma: no cover - would be a bug
            pytest.fail(f"good skill unexpectedly blocked: {exc}")

        # off-domain skill: blocked with domain.off_topic
        with pytest.raises(SkillScanError) as ei:
            scan_skill_directory(bad, skill_name="invoice_ocr", block=True, timeout=20)
        rule_ids = {f.rule_id for f in ei.value.result.findings}
        assert "domain.off_topic" in rule_ids
        df = next(f for f in ei.value.result.findings if f.rule_id == "domain.off_topic")
        assert "网络管理" in df.description and df.file_path == "SKILL.md"
        assert df.severity.value == "HIGH"
