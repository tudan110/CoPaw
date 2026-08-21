"""Tests for the environment-independent qwenpaw image seed builder."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


BUILDER_PATH = (
    Path(__file__).parents[3]
    / "deploy-all/qwenpaw/scripts/build_universal_seed.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_universal_seed",
    BUILDER_PATH,
)
assert SPEC and SPEC.loader
seed_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_builder)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def build_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "working"
    workspace = source / "workspaces/demo"
    builtin_root = tmp_path / "builtins"
    output = tmp_path / "seed"

    write_json(
        source / "config.json",
        {
            "channels": {"discord": {"bot_token": "do-not-package"}},
            "last_api": {"host": "10.0.0.1", "port": 8088},
            "active_model": {"provider_id": "environment-provider"},
            "tools": {
                "builtin_tools": {
                    "get_token_usage": {
                        "name": "get_token_usage",
                        "enabled": True,
                    },
                },
            },
            "agents": {
                "active_agent": "demo",
                "profiles": {
                    "demo": {
                        "id": "wrong-id",
                        "workspace_dir": "~/.qwenpaw/workspaces/demo",
                    },
                },
            },
        },
    )
    write_json(
        workspace / "agent.json",
        {
            "id": "wrong-id",
            "name": "Demo",
            "workspace_dir": "~/.qwenpaw/workspaces/demo",
            "api_key": "do-not-package",
            "active_model": {"provider_id": "environment-provider"},
        },
    )
    write_json(
        workspace / "jobs.json",
        {"version": 1, "jobs": [{"id": "old"}]},
    )
    write_json(
        workspace / "skill.json",
        {
            "schema_version": "workspace-skill-manifest.v1",
            "skills": {
                "custom": {"enabled": True, "channels": ["all"]},
                "docx": {"enabled": True, "channels": ["all"]},
                "retired": {"enabled": True, "channels": ["all"]},
            },
        },
    )
    write_skill(workspace / "skills/custom", "custom")
    (workspace / "skills/custom/.env").write_text(
        "TOKEN=secret\n",
        encoding="utf-8",
    )
    (workspace / "skills/custom/.env.example").write_text(
        "TOKEN=\n",
        encoding="utf-8",
    )
    (workspace / "skills/custom/cache.db").write_text(
        "runtime\n",
        encoding="utf-8",
    )
    (workspace / "skills/custom/__pycache__").mkdir()
    (workspace / "skills/custom/__pycache__/cache.pyc").write_bytes(b"cache")
    write_skill(builtin_root / "docx-zh", "docx")
    write_json(
        source / "universal-seed.json",
        {
            "schema_version": 1,
            "builtin_language": "zh",
            "default_builtin_skills": ["docx"],
            "retired_skills": ["retired"],
            "shared_skill_sources": {},
        },
    )
    return source, builtin_root, output


def test_builds_sanitized_seed_with_builtin_and_retired_skill_handling(
    tmp_path: Path,
) -> None:
    source, builtin_root, output = build_fixture(tmp_path)
    args = seed_builder.argparse.Namespace(
        source=source,
        builtin_root=builtin_root,
        output=output,
        runtime_working_dir="/app/working",
        manifest=None,
    )

    seed_builder.build_seed(args)

    config = json.loads((output / "config.json").read_text(encoding="utf-8"))
    assert config["agents"]["profiles"] == {
        "demo": {
            "id": "demo",
            "workspace_dir": "/app/working/workspaces/demo",
            "enabled": True,
        },
    }
    assert config["agents"]["agent_order"] == ["default", "demo"]
    assert config["agents"]["active_agent"] == "default"
    assert config["channels"]["discord"]["bot_token"] == ""
    assert config["last_api"] is None
    assert "active_model" not in config
    default_manifest = json.loads(
        (output / "workspaces/default/skill.json").read_text(encoding="utf-8"),
    )
    assert default_manifest["skills"]["docx"]["enabled"] is True
    assert (output / "workspaces/default/skills/docx/SKILL.md").is_file()
    assert config["tools"]["builtin_tools"]["get_token_usage"] == {
        "name": "get_token_usage",
        "enabled": True,
    }

    agent = json.loads(
        (output / "workspaces/demo/agent.json").read_text(encoding="utf-8"),
    )
    assert agent["id"] == "demo"
    assert agent["workspace_dir"] == "/app/working/workspaces/demo"
    assert agent["api_key"] == ""
    assert "active_model" not in agent
    assert json.loads(
        (output / "workspaces/demo/jobs.json").read_text(encoding="utf-8"),
    ) == {"version": 1, "jobs": []}

    skill_manifest = json.loads(
        (output / "workspaces/demo/skill.json").read_text(encoding="utf-8"),
    )
    assert set(skill_manifest["skills"]) == {"custom", "docx"}
    assert skill_manifest["skills"]["docx"]["enabled"] is True
    assert (output / "workspaces/demo/skills/docx/SKILL.md").is_file()
    assert not (output / "workspaces/demo/skills/retired").exists()
    assert not (output / "workspaces/demo/skills/custom/.env").exists()
    assert (output / "workspaces/demo/skills/custom/.env.example").is_file()
    assert (output / "workspaces/demo/skills/custom/cache.db").is_file()
    assert not (output / "workspaces/demo/skills/custom/__pycache__").exists()
    assert (output / "seed-manifest.json").is_file()


def test_rejects_manifest_skill_without_a_managed_source(
    tmp_path: Path,
) -> None:
    source, builtin_root, output = build_fixture(tmp_path)
    manifest = json.loads(
        (source / "workspaces/demo/skill.json").read_text(encoding="utf-8"),
    )
    manifest["skills"]["missing"] = {"enabled": True}
    write_json(source / "workspaces/demo/skill.json", manifest)
    args = seed_builder.argparse.Namespace(
        source=source,
        builtin_root=builtin_root,
        output=output,
        runtime_working_dir="/app/working",
        manifest=None,
    )

    with pytest.raises(seed_builder.SeedError, match="No source exists"):
        seed_builder.build_seed(args)
