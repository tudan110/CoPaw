# -*- coding: utf-8 -*-
"""缺口A：引导字段 + 高级直改 + 路径安全。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from qwenpaw.extensions.api import fde_workbench_service as svc

SKILL_MD = (
    "---\n"
    "name: demo\n"
    "category: ops-delivery\n"
    "tags: [fde, demo]\n"
    "triggers: [告警, 查询]\n"
    "description: 老描述\n"
    "---\n\n"
    "# Demo\n\n正文保持不动。\n"
)


def test_rewrite_frontmatter_updates_keys_preserves_body():
    out = svc._rewrite_frontmatter(
        SKILL_MD,
        {
            "description": "新描述: 含冒号也安全",
            "triggers": ["应用拓扑", "查CMDB"],
        },
    )
    # body untouched
    assert "正文保持不动。" in out
    # frontmatter still valid YAML and reflects the edits
    block = out.split("---", 2)[1]
    data = yaml.safe_load(block)
    assert data["description"] == "新描述: 含冒号也安全"
    assert data["triggers"] == ["应用拓扑", "查CMDB"]
    # untouched keys survive
    assert data["name"] == "demo"
    assert data["category"] == "ops-delivery"


def test_rewrite_frontmatter_rejects_missing_frontmatter():
    with pytest.raises(svc.FdeWorkbenchError):
        svc._rewrite_frontmatter("no frontmatter here\n", {"description": "x"})


def test_update_env_example_sets_values_and_empties_secrets():
    text = "# token\nCMDB_TOKEN=\n# base url\nCMDB_BASE_URL=\n"
    out = svc._update_env_example(
        text,
        {
            "CMDB_TOKEN": "super-secret",      # secret -> emptied (D4)
            "CMDB_BASE_URL": "http://x:8000",  # non-secret -> kept
            "EXTRA_FLAG": "1",                 # new key appended
        },
    )
    assert "CMDB_TOKEN=\n" in out             # value stripped
    assert "super-secret" not in out          # secret never lands on disk
    assert "CMDB_BASE_URL=http://x:8000" in out
    assert "EXTRA_FLAG=1" in out
    # comments preserved
    assert "# token" in out and "# base url" in out


def test_is_secret_env_key_matches_credential_shapes():
    for k in ["CMDB_TOKEN", "API_KEY", "x_secret", "DB_PASSWORD", "AK", "app_sk"]:
        assert svc._is_secret_env_key(k) is True
    for k in ["CMDB_BASE_URL", "TIMEOUT", "TASK_URL", "REGION"]:
        assert svc._is_secret_env_key(k) is False


def _bare_staged(tmp_path: Path) -> Path:
    d = tmp_path / "demo"
    (d / "runtime").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: demo\n---\n", "utf-8")
    return d


def test_safe_staged_target_allows_normal_paths(tmp_path):
    d = _bare_staged(tmp_path)
    assert svc._safe_staged_target(d, "SKILL.md") == (d / "SKILL.md").resolve()
    assert svc._safe_staged_target(d, "runtime/x.py") == (
        d / "runtime" / "x.py"
    ).resolve()


@pytest.mark.parametrize(
    "rel",
    ["../escape.py", "/etc/passwd", "_fde_meta.json", "GENERATION.md",
     "runtime/../../x", ""],
)
def test_safe_staged_target_rejects_bad_paths(tmp_path, rel):
    d = _bare_staged(tmp_path)
    with pytest.raises(svc.FdeWorkbenchError):
        svc._safe_staged_target(d, rel)


def _full_staged(root: Path) -> Path:
    d = root / "demo"
    (d / "runtime").mkdir(parents=True)
    d_md = (
        "---\nname: demo\ncategory: ops\ntags: [a]\n"
        "triggers: [告警]\ndescription: 旧\n---\n\n# Demo\n"
    )
    (d / "SKILL.md").write_text(d_md, "utf-8")
    (d / ".env.example").write_text("CMDB_TOKEN=\nCMDB_BASE_URL=\n", "utf-8")
    (d / "runtime" / "tool_adapters.py").write_text("X = 1\n", "utf-8")
    (d / "_fde_meta.json").write_text(
        json.dumps({"skill_name": "demo", "target_workspace": "query"}),
        "utf-8",
    )
    return d


@pytest.fixture
def staged_only(monkeypatch, tmp_path):
    """Point the staged dir at tmp_path and stub the subprocess calls so the
    edit logic is tested in isolation (no fde_tools / scanner / LLM)."""
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setenv("QWENPAW_FDE_STAGED_DIR", str(staged))
    monkeypatch.setattr(
        svc, "show_staged_skill",
        lambda name, **k: {"skill_name": name, "files": []},
    )
    monkeypatch.setattr(
        svc, "selfcheck_staged_skill",
        lambda name: {"ready_for_review": True, "scan": {"findings": []}},
    )
    return staged


def test_edit_fields_rewrites_md_and_env(staged_only):
    _full_staged(staged_only)
    out = svc.edit_staged_fields(
        "demo",
        description="新描述",
        triggers=["应用拓扑"],
        env={"CMDB_TOKEN": "leak", "CMDB_BASE_URL": "http://x:8000"},
    )
    md = (staged_only / "demo" / "SKILL.md").read_text("utf-8")
    assert "新描述" in md and "应用拓扑" in md
    env = (staged_only / "demo" / ".env.example").read_text("utf-8")
    assert "CMDB_TOKEN=\n" in env and "leak" not in env       # secret emptied
    assert "CMDB_BASE_URL=http://x:8000" in env
    # envelope shape: staged(+review) + fresh selfcheck
    assert out["staged"]["review"]["effective"] == "pending"
    assert out["selfcheck"]["ready_for_review"] is True


def test_edit_files_writes_and_rejects_traversal(staged_only):
    _full_staged(staged_only)
    svc.edit_staged_files(
        "demo",
        [{"path": "runtime/tool_adapters.py", "content": "Y = 2\n"}],
    )
    assert (
        staged_only / "demo" / "runtime" / "tool_adapters.py"
    ).read_text("utf-8") == "Y = 2\n"
    with pytest.raises(svc.FdeWorkbenchError):
        svc.edit_staged_files(
            "demo", [{"path": "../evil.py", "content": "x"}],
        )
