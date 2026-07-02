#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lint SKILL.md quality against the authoring convention.

Catches the "wrong tool / retry / shell-flail" root causes (pressure-test L2)
by enforcing clear, bounded, routable skill descriptions. See the convention
in ``docs/skills/SKILL_AUTHORING.md``.

Usage:
    python scripts/check_skill_quality.py                # scan all workspaces
    python scripts/check_skill_quality.py --workspace resource
    python scripts/check_skill_quality.py --json         # machine-readable

Checks (per distinct skill):
    ERROR  name missing / != directory name; description missing or too short
    WARN   no ``triggers``; script-based skill without an NL->command mapping;
           SKILL.md copies diverge across workspaces
    INFO   no ``category``; no boundary/disambiguation language

Exit code is non-zero when any ERROR is found (CI-friendly). WARN/INFO never
fail the run.

Only stdlib + the ``frontmatter`` library (already a repo dependency) are used
so this runs standalone without importing the qwenpaw package.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import frontmatter

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = REPO_ROOT / "deploy-all" / "qwenpaw" / "working" / "workspaces"

MIN_DESC_LEN = 40

# Description/body cues that count as a boundary/disambiguation declaration.
BOUNDARY_CUES = (
    "继续使用",
    "而非",
    "不用于",
    "请使用",
    "改用",
    "不要用于",
    "instead of",
    "use `",
)
# Cues that an NL->command mapping exists in a script-based skill.
MAPPING_CUES = ("自然语言映射", "## 用法", "```bash", "```shell", "usage")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _discover() -> dict[str, list[Path]]:
    """Map skill name -> list of its SKILL.md paths across all workspaces."""
    by_name: dict[str, list[Path]] = defaultdict(list)
    if not WORKSPACES.is_dir():
        return by_name
    for md in WORKSPACES.glob("*/skills/*/SKILL.md"):
        by_name[md.parent.name].append(md)
    return by_name


def _has_scripts(skill_dir: Path) -> bool:
    scripts = skill_dir / "scripts"
    if not scripts.is_dir():
        return False
    return any(scripts.rglob("*.py")) or any(scripts.rglob("*.sh"))


def _lint_skill(name: str, paths: list[Path]) -> list[tuple[str, str]]:
    """Return a list of (severity, message) findings for one skill."""
    findings: list[tuple[str, str]] = []
    primary = paths[0]
    skill_dir = primary.parent

    try:
        post = frontmatter.load(str(primary))
        meta = dict(post.metadata)
        body = post.content or ""
    except Exception as exc:  # noqa: BLE001
        return [("ERROR", f"无法解析 frontmatter: {exc}")]

    full_text = (_text(meta.get("description")) + "\n" + body)

    # name
    fm_name = _text(meta.get("name")).strip()
    if not fm_name:
        findings.append(("ERROR", "frontmatter 缺少 name"))
    elif fm_name != name:
        findings.append(
            ("ERROR", f"name='{fm_name}' 与目录名 '{name}' 不一致"),
        )

    # description
    desc = _text(meta.get("description")).strip()
    if not desc:
        findings.append(("ERROR", "frontmatter 缺少 description"))
    elif len(desc) < MIN_DESC_LEN:
        findings.append(
            ("ERROR", f"description 过短({len(desc)}<{MIN_DESC_LEN} 字符)"),
        )

    # triggers
    if not meta.get("triggers"):
        findings.append(("WARN", "缺少 triggers（触发短语），易被路由选错"))

    # category
    if not meta.get("category"):
        findings.append(("INFO", "缺少 category（领域分组）"))

    # boundary / disambiguation
    if not any(cue in full_text for cue in BOUNDARY_CUES):
        findings.append(
            ("INFO", "description/正文未见边界声明（该用/不该用哪个相邻技能）"),
        )

    # NL -> command mapping for script-based skills
    if _has_scripts(skill_dir) and not any(
        cue in full_text for cue in MAPPING_CUES
    ):
        findings.append(
            ("WARN", "脚本类技能缺少自然语言→命令映射（模型会猜命令/瞎试）"),
        )

    # divergent copies across workspaces
    if len(paths) > 1:
        bodies = {p.read_text(encoding="utf-8", errors="ignore") for p in paths}
        if len(bodies) > 1:
            wss = ", ".join(sorted(p.parents[2].name for p in paths))
            findings.append(
                ("WARN", f"{len(paths)} 份副本内容不一致（{wss}），需同步"),
            )

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint SKILL.md quality")
    parser.add_argument("--workspace", help="只检查该 workspace（如 resource）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    by_name = _discover()
    if args.workspace:
        by_name = {
            n: [p for p in ps if p.parents[2].name == args.workspace]
            for n, ps in by_name.items()
        }
        by_name = {n: ps for n, ps in by_name.items() if ps}

    if not by_name:
        print("未发现任何 SKILL.md（检查路径/‑‑workspace）", file=sys.stderr)
        return 2

    results: dict[str, list[tuple[str, str]]] = {}
    for name in sorted(by_name):
        results[name] = _lint_skill(name, by_name[name])

    totals = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for findings in results.values():
        for sev, _ in findings:
            totals[sev] += 1

    if args.json:
        payload = {
            "skills_checked": len(results),
            "totals": totals,
            "findings": {
                n: [{"severity": s, "message": m} for s, m in f]
                for n, f in results.items()
                if f
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if totals["ERROR"] else 0

    # Human-readable, worst-first per skill.
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    clean = 0
    for name in sorted(
        results,
        key=lambda n: min(
            (order[s] for s, _ in results[n]), default=3,
        ),
    ):
        findings = sorted(results[name], key=lambda f: order[f[0]])
        if not findings:
            clean += 1
            continue
        print(f"\n■ {name}")
        for sev, msg in findings:
            mark = {"ERROR": "✗", "WARN": "!", "INFO": "·"}[sev]
            print(f"    {mark} [{sev}] {msg}")

    print(
        f"\n检查 {len(results)} 个技能："
        f"{totals['ERROR']} ERROR / {totals['WARN']} WARN / "
        f"{totals['INFO']} INFO；{clean} 个无问题。",
    )
    return 1 if totals["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
