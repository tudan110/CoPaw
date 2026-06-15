# -*- coding: utf-8 -*-
"""Run an installed skill's query script and capture structured JSON.

Generalises the subprocess+JSON pattern already used by
``portal_backend`` (alarm-analyst / fault-disposal bridges) and the
importlib pattern in ``order_workflow`` into one reusable runner the
big-screen pipeline can call to turn *any* declared skill query into
real rows — the basis of skill-backed big-screen capabilities (M3-C).

Safety: the script path is resolved strictly inside the skill's own
directory (no traversal), invoked via the argv list form (no shell),
with a hard timeout and forced UTF-8 stdio. Only operator-installed
skills with a declared ``bigscreen`` block are ever run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_SKILL_QUERY_TIMEOUT = 30.0


def resolve_skill_root(workspace: str, skill: str) -> Path:
    """Working-dir skill dir, falling back to the bundled deploy-all copy."""
    from qwenpaw import constant

    working_root = (
        constant.WORKING_DIR / "workspaces" / workspace / "skills" / skill
    )
    if working_root.exists():
        return working_root
    repo_root = (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / workspace
        / "skills"
        / skill
    )
    return repo_root if repo_root.exists() else working_root


def _skill_subprocess_env() -> dict[str, str]:
    """Force UTF-8 stdio so Chinese skill output never mojibakes."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _extract_json(text: str) -> Any:
    """Parse JSON, tolerating leading log lines before the payload."""
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # some skills print logs then the JSON; take the last {...} / [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise RuntimeError("skill 输出不是合法 JSON")


def run_skill_query(
    *,
    workspace: str,
    skill: str,
    script: str,
    args: list[str] | None = None,
    timeout: float = DEFAULT_SKILL_QUERY_TIMEOUT,
) -> Any:
    """Run ``<skill>/<script> <args>`` and return its parsed JSON output.

    Raises ``RuntimeError`` on a missing/out-of-tree script, non-zero
    exit with no output, empty output, or non-JSON output — the caller
    turns that into an honest ``failed`` capability status.
    """
    root = resolve_skill_root(workspace, skill).resolve()
    script_path = (root / script).resolve()
    # path-traversal guard — the script must live inside the skill dir
    if root not in script_path.parents and script_path != root:
        raise RuntimeError("skill 脚本路径越界,已阻断")
    if not script_path.exists():
        raise RuntimeError(f"skill 脚本不存在: {script}")

    completed = subprocess.run(
        [sys.executable, str(script_path), *(args or [])],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_skill_subprocess_env(),
        timeout=timeout,
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0 and not stdout:
        raise RuntimeError(
            (completed.stderr or "").strip() or "skill 查询失败",
        )
    if not stdout:
        raise RuntimeError("skill 查询返回空输出")
    return _extract_json(stdout)
