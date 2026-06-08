# -*- coding: utf-8 -*-
"""digest + 持久化人工审查闸门（方案 P）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.extensions.api import fde_workbench_service as svc


def _make_staged(staged_root: Path, name: str = "demo") -> Path:
    """Hand-build a minimal staged skill (no subprocess)."""
    d = staged_root / name
    (d / "runtime").mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 网管告警查询\n"
        "triggers: [\"告警\"]\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    (d / "runtime" / "tool_adapters.py").write_text(
        "X = 1\n", encoding="utf-8",
    )
    (d / "_fde_meta.json").write_text(
        json.dumps(
            {
                "schema": "fde-staged-skill.v1",
                "skill_name": name,
                "target_workspace": "query",
            },
        ),
        encoding="utf-8",
    )
    return d


def test_digest_is_stable_and_content_sensitive(tmp_path):
    d = _make_staged(tmp_path)
    base = svc._staged_content_digest(d)
    assert base == svc._staged_content_digest(d)  # stable

    (d / "runtime" / "tool_adapters.py").write_text("X = 2\n", "utf-8")
    assert svc._staged_content_digest(d) != base  # content change moves it


def test_digest_ignores_internal_meta_files(tmp_path):
    d = _make_staged(tmp_path)
    base = svc._staged_content_digest(d)
    # mutating _fde_meta.json / GENERATION.md must NOT change the digest
    # (the review block itself lives in _fde_meta.json — no self-reference)
    meta = json.loads((d / "_fde_meta.json").read_text("utf-8"))
    meta["review"] = {"status": "approved"}
    (d / "_fde_meta.json").write_text(json.dumps(meta), "utf-8")
    (d / "GENERATION.md").write_text("# notes\n", "utf-8")
    assert svc._staged_content_digest(d) == base


def test_review_state_defaults_to_pending(tmp_path):
    d = _make_staged(tmp_path)
    meta = svc._load_staged_meta(d)
    rv = svc._review_state(d, meta)
    assert rv["status"] == "pending"
    assert rv["effective"] == "pending"
    assert rv["digest_matches"] is False


def test_review_state_approved_then_stale_on_edit(tmp_path):
    d = _make_staged(tmp_path)
    meta = svc._load_staged_meta(d)
    meta["review"] = {
        "status": "approved",
        "approved_by": "op",
        "approved_at": "2026-06-08T00:00:00+00:00",
        "content_digest": svc._staged_content_digest(d),
    }
    svc._save_staged_meta(d, meta)

    rv = svc._review_state(d, svc._load_staged_meta(d))
    assert rv["effective"] == "approved"

    # edit a managed file -> digest drifts -> approval goes stale
    (d / "runtime" / "tool_adapters.py").write_text("X = 99\n", "utf-8")
    rv2 = svc._review_state(d, svc._load_staged_meta(d))
    assert rv2["status"] == "approved"
    assert rv2["digest_matches"] is False
    assert rv2["effective"] == "stale"


@pytest.fixture
def staged_review_env(monkeypatch, tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setenv("QWENPAW_FDE_STAGED_DIR", str(staged))
    monkeypatch.setattr(
        svc, "show_staged_skill",
        lambda name, **k: {"skill_name": name, "files": []},
    )
    return staged


def test_approve_requires_ready_for_review(staged_review_env, monkeypatch):
    _make_staged(staged_review_env)
    monkeypatch.setattr(
        svc, "selfcheck_staged_skill",
        lambda name: {"ready_for_review": False,
                      "blocked_reasons": ["语法错误"]},
    )
    with pytest.raises(svc.FdeWorkbenchError):
        svc.set_staged_review("demo", action="approve")


def test_approve_then_reset_review(staged_review_env, monkeypatch):
    d = _make_staged(staged_review_env)
    monkeypatch.setattr(
        svc, "selfcheck_staged_skill",
        lambda name: {"ready_for_review": True},
    )
    out = svc.set_staged_review("demo", action="approve", approved_by="vince")
    rv = out["staged"]["review"]
    assert rv["effective"] == "approved"
    assert rv["approved_by"] == "vince"
    assert rv["content_digest"] == svc._staged_content_digest(d)

    out2 = svc.set_staged_review("demo", action="reset")
    assert out2["staged"]["review"]["effective"] == "pending"
    assert out2["staged"]["review"]["content_digest"] is None
