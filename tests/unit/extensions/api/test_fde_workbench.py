# -*- coding: utf-8 -*-
"""Tests for the Portal FDE delivery workbench service.

The lifecycle test exercises the meta-skill end to end through the service
layer (which shells out to ``skills/fde-onboarding/scripts/fde_tools.py``),
pointing the ``fde`` workspace at the repo's deploy seed and the staged dir at
``tmp_path``. The lighter tests cover the FastAPI-free helpers directly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.extensions.api import fde_workbench_service as svc

REPO_ROOT = Path(__file__).resolve().parents[4]
FDE_WORKSPACE = (
    REPO_ROOT / "deploy-all" / "qwenpaw" / "working" / "workspaces" / "fde"
)


@pytest.fixture
def fde_env(monkeypatch, tmp_path):
    """Point the service at the repo's fde workspace + a temp staged dir."""
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setattr(svc, "fde_workspace_dir", lambda: FDE_WORKSPACE)
    monkeypatch.setenv("QWENPAW_FDE_STAGED_DIR", str(staged))
    return staged


def test_workspace_seed_is_present():
    skill = FDE_WORKSPACE / "skills" / "fde-onboarding"
    skeleton = skill / "references" / "skeleton"
    assert (skill / "scripts" / "fde_tools.py").exists()
    assert (skeleton / "SKILL.md").exists()
    assert (skeleton / "runtime" / "models.py").exists()


def test_workbench_info(fde_env):
    info = svc.workbench_info()
    assert info["available"] is True
    assert info["agentId"] == "fde"
    assert info["onboardingSkill"] == "fde-onboarding"


def test_full_staged_skill_lifecycle(fde_env):
    """generate -> list -> show -> read bundle -> probe -> discard."""
    result = svc.generate_skill(
        name="demo-alarm-stat",
        target_workspace="query",
        brief={
            "description": "演示：按设备分组统计告警并出柱状图",
            "tags": ["alarm", "stat", "monitoring", "network-management"],
            "triggers": ["告警统计", "按设备统计告警"],
            "open_questions": ["确认 realalarm 接口的鉴权方式"],
        },
    )
    assert result["skill_name"] == "demo-alarm-stat"
    assert result["target_workspace"] == "query"
    assert "SKILL.md" in result["files"]
    assert "_fde_meta.json" in result["files"]
    assert result["selfcheck"]["ready_for_review"] is True
    assert any("鉴权" in t for t in result["selfcheck"]["todo"])

    listing = svc.list_staged_skills()
    assert "demo-alarm-stat" in [s["skill_name"] for s in listing["skills"]]

    detail = svc.show_staged_skill("demo-alarm-stat")
    paths = {f["path"] for f in detail["files"]}
    assert "SKILL.md" in paths
    assert "runtime/router.py" in paths
    assert "scripts/chat_skill_bridge.py" in paths
    skill_md = next(f for f in detail["files"] if f["path"] == "SKILL.md")
    assert "name: demo-alarm-stat" in (skill_md["content"] or "")
    assert detail["selfcheck"]["ready_for_review"] is True

    bundle = svc._read_staged_bundle(fde_env / "demo-alarm-stat")
    assert "name: demo-alarm-stat" in bundle["content"]
    assert "chat_skill_bridge.py" in (bundle["scripts"] or {})
    assert "runtime" in (bundle["extra_files"] or {})
    assert "router.py" in bundle["extra_files"]["runtime"]
    # FDE-internal files are excluded from the install payload
    assert "_fde_meta.json" not in (bundle["extra_files"] or {})
    assert "GENERATION.md" not in (bundle["extra_files"] or {})

    # install with a target_override pointing at a non-existent agent must
    # be rejected (resolves the override against config.agents.profiles)
    with pytest.raises(svc.FdeWorkbenchError):
        svc.install_staged_skill(
            "demo-alarm-stat", target_override="no-such-agent-xyz",
        )

    probe = svc.probe_staged_skill("demo-alarm-stat")
    assert probe["ok"] is True
    assert "分析结论" in (probe.get("stdout") or "")

    svc.discard_staged_skill("demo-alarm-stat")
    assert svc.list_staged_skills()["skills"] == []


def test_generate_rejects_bad_name(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.generate_skill(name="Bad Name!", target_workspace="query")


def test_generate_requires_target_workspace(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.generate_skill(name="ok-name", target_workspace="")


def test_tree_insert_builds_nested_dict():
    tree: dict = {}
    svc._tree_insert(tree, ["runtime", "playbooks", "flow.py"], "x = 1")
    assert tree == {"runtime": {"playbooks": {"flow.py": "x = 1"}}}


def test_install_unknown_skill_errors(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.install_staged_skill("nope")


def test_discard_unknown_skill_errors(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.discard_staged_skill("nope")
