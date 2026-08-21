#!/usr/bin/env python3
"""Build a minimal, environment-independent QwenPaw working-directory seed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

SOURCE_CACHE_DIRECTORY_NAMES = {"__pycache__"}
SOURCE_CACHE_FILE_NAMES = {".DS_Store", ".skill.json.lock"}
SOURCE_CACHE_FILE_SUFFIXES = {".pyc"}
SENSITIVE_EXACT_KEYS = {
    "access_token",
    "ak",
    "api_key",
    "app_id",
    "app_secret",
    "authorization",
    "client_id",
    "client_secret",
    "encrypt_key",
    "password",
    "phone_number",
    "private_key",
    "secret",
    "sk",
    "token",
    "username",
    "verification_token",
}
SENSITIVE_KEY_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_authorization",
    "_password",
    "_private_key",
    "_secret",
    "_token",
)
NETWORK_KEY_PARTS = (
    "base_url",
    "endpoint",
    "homeserver",
    "host",
    "http_proxy",
    "url",
    "ws_host",
    "ws_url",
)
SYNC_WORKSPACE_FILES = {
    "AGENTS.md",
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
    "MEMORY.md",
    "PROFILE.md",
    "SOUL.md",
}
SYNC_SKILL_EXCLUDED_PARTS = {"builtin_kb", "data"}


class SeedError(ValueError):
    """Raised when managed source cannot form a valid universal seed."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--builtin-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--runtime-working-dir",
        default="/app/working",
        help="Container path assigned to every generated workspace.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Defaults to <source>/universal-seed.json.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SeedError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def is_ignored_source_path(path: Path) -> bool:
    """Exclude generated caches and real .env credentials only."""
    if path.name in SOURCE_CACHE_DIRECTORY_NAMES:
        return True
    if path.name in SOURCE_CACHE_FILE_NAMES:
        return True
    if path.name == ".env":
        return True
    return path.suffix.lower() in SOURCE_CACHE_FILE_SUFFIXES


def copy_managed_tree(source: Path, destination: Path) -> None:
    """Copy every maintained source file except generated caches and .env."""
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if is_ignored_source_path(relative):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def scrub_for_universal_image(value: Any, key: str = "") -> Any:
    """Drop credentials and endpoint values while preserving config shape."""
    lower_key = key.lower()
    if (
        lower_key in SENSITIVE_EXACT_KEYS
        or lower_key.endswith(SENSITIVE_KEY_SUFFIXES)
    ):
        if isinstance(value, list):
            return []
        if isinstance(value, dict):
            return {}
        return ""
    if any(part in lower_key for part in NETWORK_KEY_PARTS):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return 0
        return ""
    if isinstance(value, dict):
        return {
            child_key: scrub_for_universal_image(child_value, child_key)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [scrub_for_universal_image(item, key) for item in value]
    return value


def builtin_sources(root: Path, language: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    suffix = f"-{language}"
    for path in root.iterdir():
        if path.is_dir() and path.name.endswith(suffix):
            result[path.name[: -len(suffix)]] = path
    if not result:
        raise SeedError(
            f"No packaged builtin Skills found in {root} for {language}",
        )
    return result


def skill_directories(skills_dir: Path) -> set[str]:
    if not skills_dir.exists():
        return set()
    return {
        path.name
        for path in skills_dir.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }


def materialize_missing_skills(
    workspace_id: str,
    skills: dict[str, Any],
    skills_dir: Path,
    source_workspaces: Path,
    builtin_by_name: dict[str, Path],
    shared_sources: dict[str, str],
    retired_skills: set[str],
) -> dict[str, Any]:
    expected = set(skills) - retired_skills
    existing = skill_directories(skills_dir)

    for skill_name in sorted(expected - existing):
        builtin_source = builtin_by_name.get(skill_name)
        shared_workspace = shared_sources.get(skill_name)
        if builtin_source is not None:
            copy_managed_tree(builtin_source, skills_dir / skill_name)
        elif shared_workspace is not None:
            shared_skill = (
                source_workspaces
                / shared_workspace
                / "skills"
                / skill_name
            )
            if not (shared_skill / "SKILL.md").is_file():
                raise SeedError(
                    "Shared source for "
                    f"{workspace_id}/{skill_name} is invalid: {shared_skill}",
                )
            copy_managed_tree(shared_skill, skills_dir / skill_name)
        else:
            raise SeedError(
                "No source exists for managed Skill "
                f"{workspace_id}/{skill_name}. Add it to working/workspaces "
                "or declare a shared_skill_sources mapping."
            )

    existing = skill_directories(skills_dir)
    unexpected = existing - expected
    if unexpected:
        raise SeedError(
            f"Workspace {workspace_id} contains Skills absent from "
            f"skill.json: {', '.join(sorted(unexpected))}",
        )
    missing = expected - existing
    if missing:
        raise SeedError(
            f"Workspace {workspace_id} still lacks Skills: "
            f"{', '.join(sorted(missing))}",
        )

    return {name: entry for name, entry in skills.items() if name in expected}


def seed_default_workspace(
    output: Path,
    builtin_by_name: dict[str, Path],
    default_skill_names: list[str],
) -> None:
    """Seed builtin skills for the default agent created at app startup."""
    workspace = output / "workspaces" / "default"
    skills_dir = workspace / "skills"
    entries: dict[str, dict[str, Any]] = {}
    for skill_name in default_skill_names:
        builtin_source = builtin_by_name.get(skill_name)
        if builtin_source is None:
            raise SeedError(
                f"No builtin source exists for default Skill {skill_name}",
            )
        copy_managed_tree(builtin_source, skills_dir / skill_name)
        entries[skill_name] = {
            "enabled": True,
            "channels": ["all"],
            "source": "builtin",
        }
    write_json(
        workspace / "skill.json",
        {
            "schema_version": "workspace-skill-manifest.v1",
            "skills": entries,
        },
    )
    write_json(workspace / "jobs.json", {"version": 1, "jobs": []})


def normalize_agent_config(
    source: Path,
    workspace_id: str,
    workspace_dir: str,
) -> dict[str, Any]:
    agent = scrub_for_universal_image(load_json(source))
    agent.pop("active_model", None)
    agent["id"] = workspace_id
    agent["workspace_dir"] = workspace_dir
    return agent


def normalize_root_config(
    source: Path,
    workspace_ids: list[str],
    runtime_working_dir: str,
) -> dict[str, Any]:
    config = scrub_for_universal_image(load_json(source))
    agents = config.setdefault("agents", {})
    if not isinstance(agents, dict):
        raise SeedError("config.json agents must be an object")

    agents["profiles"] = {
        workspace_id: {
            "id": workspace_id,
            "workspace_dir": (
                f"{runtime_working_dir}/workspaces/{workspace_id}"
            ),
            "enabled": True,
        }
        for workspace_id in workspace_ids
    }
    agents["agent_order"] = ["default", *workspace_ids]
    agents["active_agent"] = "default"
    config["last_api"] = None
    config.pop("active_model", None)
    return config


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(files.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_sync_manifest(output: Path) -> dict[str, Any]:
    """Describe static seed files safe to reconcile into an existing PVC."""
    managed_files: dict[str, dict[str, str]] = {}
    managed_skills: dict[str, dict[str, Any]] = {}
    workspaces_dir = output / "workspaces"

    for workspace in sorted(
        path for path in workspaces_dir.iterdir() if path.is_dir()
    ):
        workspace_relative = Path("workspaces") / workspace.name
        for name in SYNC_WORKSPACE_FILES:
            candidate = workspace / name
            if candidate.is_file():
                relative = str(workspace_relative / name)
                managed_files[relative] = {
                    "kind": "workspace_file",
                    "sha256": sha256(candidate),
                }

        agent_path = workspace / "agent.json"
        if agent_path.is_file():
            relative = str(workspace_relative / "agent.json")
            managed_files[relative] = {
                "kind": "agent_config",
                "sha256": sha256(agent_path),
            }

        skill_manifest = workspace / "skill.json"
        if skill_manifest.is_file():
            relative = str(workspace_relative / "skill.json")
            managed_files[relative] = {
                "kind": "skill_manifest",
                "sha256": sha256(skill_manifest),
            }

        skills_dir = workspace / "skills"
        for skill_dir in sorted(
            path for path in skills_dir.iterdir() if path.is_dir()
        ):
            if not (skill_dir / "SKILL.md").is_file():
                continue
            skill_relative = workspace_relative / "skills" / skill_dir.name
            files: dict[str, str] = {}
            tree_files: dict[str, str] = {}
            for skill_file in sorted(
                path for path in skill_dir.rglob("*") if path.is_file()
            ):
                relative_in_skill = skill_file.relative_to(skill_dir)
                if (
                    skill_file.name == ".env"
                    or SYNC_SKILL_EXCLUDED_PARTS.intersection(
                        relative_in_skill.parts
                    )
                ):
                    continue
                relative = str(skill_relative / relative_in_skill)
                file_hash = sha256(skill_file)
                files[relative] = file_hash
                tree_files[str(relative_in_skill)] = file_hash
                managed_files[relative] = {
                    "kind": "skill_file",
                    "sha256": file_hash,
                }
            managed_skills[str(skill_relative)] = {
                "tree_sha256": _tree_hash(tree_files),
                "files": files,
            }

    managed_hashes = {
        relative: item["sha256"]
        for relative, item in managed_files.items()
    }
    return {
        "schema_version": "qwenpaw-seed.v2",
        "seed_id": _tree_hash(managed_hashes),
        "managed_files": managed_files,
        "managed_skills": managed_skills,
    }


def assert_universal_output(output: Path) -> None:
    forbidden = []
    for path in output.rglob("*"):
        relative = path.relative_to(output)
        if path.is_dir():
            continue
        if path.name == ".env":
            forbidden.append(str(relative))
        if relative.parts and relative.parts[0] == "providers":
            forbidden.append(str(relative))
        if path.name == ".master_key":
            forbidden.append(str(relative))
    if forbidden:
        raise SeedError(
            "Universal seed contains forbidden runtime data: "
            + ", ".join(sorted(set(forbidden)))
        )


def build_seed(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    workspaces = source / "workspaces"
    config_path = source / "config.json"
    manifest_path = args.manifest or source / "universal-seed.json"
    manifest = load_json(manifest_path)

    if not workspaces.is_dir() or not config_path.is_file():
        raise SeedError("Source must contain config.json and workspaces/")

    language = manifest.get("builtin_language", "zh")
    if language not in {"zh", "en"}:
        raise SeedError("builtin_language must be zh or en")
    retired_skills = set(manifest.get("retired_skills", []))
    default_skill_names = manifest.get("default_builtin_skills", [])
    if (
        not isinstance(default_skill_names, list)
        or not all(isinstance(name, str) for name in default_skill_names)
    ):
        raise SeedError("default_builtin_skills must be a list of skill names")
    shared_sources = manifest.get("shared_skill_sources", {})
    if not isinstance(shared_sources, dict):
        raise SeedError("shared_skill_sources must be an object")
    builtin_by_name = builtin_sources(args.builtin_root.resolve(), language)

    workspace_dirs = sorted(
        path
        for path in workspaces.iterdir()
        if path.is_dir() and (path / "agent.json").is_file()
    )
    workspace_ids = [path.name for path in workspace_dirs]
    if not workspace_ids:
        raise SeedError("No managed workspaces found")

    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    normalized_config = normalize_root_config(
        config_path,
        workspace_ids,
        args.runtime_working_dir.rstrip("/"),
    )
    write_json(output / "config.json", normalized_config)
    seed_default_workspace(output, builtin_by_name, default_skill_names)

    for source_workspace in workspace_dirs:
        workspace_id = source_workspace.name
        destination = output / "workspaces" / workspace_id
        copy_managed_tree(source_workspace, destination)

        runtime_workspace = (
            f"{args.runtime_working_dir.rstrip('/')}/workspaces/{workspace_id}"
        )
        write_json(
            destination / "agent.json",
            normalize_agent_config(
                source_workspace / "agent.json",
                workspace_id,
                runtime_workspace,
            ),
        )
        write_json(destination / "jobs.json", {"version": 1, "jobs": []})

        workspace_manifest = load_json(source_workspace / "skill.json")
        skills = workspace_manifest.get("skills")
        if not isinstance(skills, dict):
            raise SeedError(
                f"Invalid skills object for workspace {workspace_id}",
            )
        workspace_manifest["skills"] = materialize_missing_skills(
            workspace_id,
            skills,
            destination / "skills",
            workspaces,
            builtin_by_name,
            shared_sources,
            retired_skills,
        )
        write_json(destination / "skill.json", workspace_manifest)

    assert_universal_output(output)
    file_hashes = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    seed_manifest = {
        **build_sync_manifest(output),
        "source_commit": os.environ.get("SOURCE_COMMIT", "unknown"),
        "managed_workspaces": ["default", *workspace_ids],
        "retired_skills": sorted(retired_skills),
        "file_hashes": file_hashes,
    }
    write_json(output / "seed-manifest.json", seed_manifest)


def main() -> int:
    try:
        build_seed(parse_args())
    except SeedError as exc:
        print(f"universal seed error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
