# -*- coding: utf-8 -*-
"""缺口B：_scan() 必须把 Finding 的富字段透出给前端「体检报告」。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[4]
SELFCHECK_PATH = (
    REPO_ROOT
    / "deploy-all/qwenpaw/working/workspaces/fde/skills"
    / "fde-onboarding/runtime/selfcheck.py"
)


def _load_selfcheck():
    spec = importlib.util.spec_from_file_location(
        "fde_selfcheck_under_test", SELFCHECK_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scan_surfaces_rich_finding_fields(monkeypatch, tmp_path):
    mod = _load_selfcheck()
    fake_finding = SimpleNamespace(
        severity=SimpleNamespace(value="medium"),
        title="疑似硬编码凭证",
        file_path="runtime/tool_adapters.py",
        line_number=42,
        snippet='token = "Bearer abc123"',
        remediation="移到 .env，用 os.environ[...] 读取",
        category=SimpleNamespace(value="hardcoded_secret"),
        rule_id="hardcoded_secrets",
        description="疑似把令牌写死在源码里",
    )
    fake_result = SimpleNamespace(
        findings=[fake_finding],
        is_safe=True,
        max_severity=SimpleNamespace(value="medium"),
    )
    monkeypatch.setattr(
        "qwenpaw.security.skill_scanner.scan_skill_directory",
        lambda *a, **k: fake_result,
    )
    out = mod._scan(tmp_path, "demo")
    f = out["findings"][0]
    assert f["severity"] == "medium"
    assert f["title"] == "疑似硬编码凭证"
    assert f["file"] == "runtime/tool_adapters.py"
    assert f["line"] == 42
    assert f["snippet"] == 'token = "Bearer abc123"'
    assert "os.environ" in f["remediation"]
    assert f["category"] == "hardcoded_secret"
    assert f["rule_id"] == "hardcoded_secrets"
    assert "令牌" in f["description"]
