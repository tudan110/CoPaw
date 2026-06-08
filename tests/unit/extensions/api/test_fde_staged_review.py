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
