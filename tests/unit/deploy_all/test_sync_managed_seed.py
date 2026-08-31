# -*- coding: utf-8 -*-
"""Unit tests for the deploy-all managed seed synchronizer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = (
    Path(__file__).parents[3]
    / "deploy-all/qwenpaw/scripts/sync_managed_seed.py"
)
SPEC = importlib.util.spec_from_file_location("sync_managed_seed", SCRIPT)
assert SPEC and SPEC.loader
sync_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_module
SPEC.loader.exec_module(sync_module)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def build_seed(seed: Path) -> None:
    write_json(seed / "config.json", {"runtime": "seed"})
    write(seed / "workspaces/demo/AGENTS.md", "new instructions\n")
    write(seed / "workspaces/demo/skills/example/SKILL.md", "# new\n")
    write(
        seed / "workspaces/demo/skills/example/scripts/run.py",
        "print('new')\n",
    )
    write_json(
        seed / "workspaces/demo/agent.json",
        {
            "id": "demo",
            "name": "New Demo",
            "description": "new description",
            "workspace_dir": "/app/working/workspaces/demo",
            "channels": {"discord": {"bot_token": ""}},
        },
    )
    write_json(
        seed / "workspaces/demo/skill.json",
        {
            "schema_version": "workspace-skill-manifest.v1",
            "skills": {
                "example": {
                    "enabled": True,
                    "channels": ["all"],
                    "source": "customized",
                },
            },
        },
    )

    files = {}
    for path in sorted(seed.rglob("*")):
        if path.is_file() and path.name != "seed-manifest.json":
            relative = str(path.relative_to(seed))
            kind = "skill_file"
            if relative.endswith("AGENTS.md"):
                kind = "workspace_file"
            elif relative.endswith("agent.json"):
                kind = "agent_config"
            elif relative.endswith("skill.json"):
                kind = "skill_manifest"
            files[relative] = {"kind": kind, "sha256": sha256(path)}
    write_json(
        seed / "seed-manifest.json",
        {
            "schema_version": "qwenpaw-seed.v2",
            "seed_id": "test-seed",
            "managed_files": files,
            "managed_skills": {
                "workspaces/demo/skills/example": {
                    "tree_sha256": "unused-in-test",
                    "files": {
                        name: data["sha256"]
                        for name, data in files.items()
                        if "/skills/example/" in name
                    },
                },
            },
        },
    )


def build_target(target: Path) -> None:
    write_json(target / "config.json", {"runtime": "target"})
    write(target / "workspaces/demo/AGENTS.md", "old instructions\n")
    write(target / "workspaces/demo/skills/example/SKILL.md", "# old\n")
    write(
        target / "workspaces/demo/skills/example/scripts/run.py",
        "print('old')\n",
    )
    write(
        target / "workspaces/demo/skills/example/data/knowledge.db",
        "keep\n",
    )
    write(target / "workspaces/demo/skills/example/.env", "TOKEN=keep\n")
    write(target / "workspaces/demo/skills/user/SKILL.md", "# user\n")
    write_json(
        target / "workspaces/demo/agent.json",
        {
            "id": "demo",
            "name": "Old Demo",
            "description": "old description",
            "workspace_dir": "/old/demo",
            "channels": {"discord": {"bot_token": "keep-me"}},
            "active_model": {"provider_id": "keep"},
        },
    )
    write_json(
        target / "workspaces/demo/jobs.json",
        {"jobs": [{"id": "keep"}]},
    )
    write_json(
        target / "workspaces/demo/skill.json",
        {
            "schema_version": "workspace-skill-manifest.v1",
            "version": 5,
            "skills": {
                "example": {
                    "enabled": False,
                    "config": {"local": True},
                    "tags": ["keep"],
                },
                "user": {"enabled": True},
            },
        },
    )


def test_empty_target_bootstraps_full_seed(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    target = tmp_path / "target"
    target.mkdir()
    build_seed(seed)

    result = sync_module.sync_managed_seed(seed, target, apply=True)

    assert result.summary() == {"bootstrap": 1}
    assert (target / "config.json").is_file()
    assert (target / "workspaces/demo/agent.json").is_file()


def test_existing_target_overwrites_managed_files_only(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    target = tmp_path / "target"
    build_seed(seed)
    build_target(target)

    result = sync_module.sync_managed_seed(seed, target, apply=True)

    assert result.summary()["update"] >= 1
    assert (
        target / "workspaces/demo/AGENTS.md"
    ).read_text() == "new instructions\n"
    assert (
        target / "workspaces/demo/skills/example/SKILL.md"
    ).read_text() == "# new\n"
    assert (
        target / "workspaces/demo/skills/example/data/knowledge.db"
    ).read_text() == "keep\n"
    assert (
        target / "workspaces/demo/skills/example/.env"
    ).read_text() == "TOKEN=keep\n"
    assert (target / "workspaces/demo/skills/user/SKILL.md").is_file()
    assert json.loads((target / "workspaces/demo/jobs.json").read_text())[
        "jobs"
    ] == [{"id": "keep"}]

    agent = json.loads((target / "workspaces/demo/agent.json").read_text())
    assert agent["name"] == "New Demo"
    assert agent["channels"]["discord"]["bot_token"] == "keep-me"
    assert agent["active_model"] == {"provider_id": "keep"}

    manifest = json.loads((target / "workspaces/demo/skill.json").read_text())
    assert manifest["skills"]["example"]["enabled"] is True
    assert manifest["skills"]["example"]["config"] == {"local": True}
    assert "user" in manifest["skills"]

    second = sync_module.sync_managed_seed(seed, target)
    assert second.summary()["unchanged"] >= 1
