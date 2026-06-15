# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.extensions.ai_big_screen import skill_bridge
from qwenpaw.extensions.ai_big_screen.capabilities import (
    execute_capability,
    get_descriptor,
    list_capability_metadata,
    skill_capabilities,
)

_SKILL_MD = """\
---
name: inspect-demo
description: 演示巡检技能
bigscreen:
  domain: inspection
  script: scripts/query.py
  args: ["--output", "json"]
  rowsPath: data.items
  valuePath: data.total
  unit: 项
  fields:
    - {key: metric, label: 指标}
    - {key: value, label: 值}
  params:
    - {name: resId, required: true}
  examplePrompts: ["巡检 7953"]
---

# Inspect Demo
"""

_SCRIPT = """\
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--output")
p.add_argument("--resId", default="")
a = p.parse_args()
print(json.dumps({
    "data": {
        "total": 2,
        "items": [
            {"metric": "cpu", "value": 88, "resId": a.resId},
            {"metric": "mem", "value": 91, "resId": a.resId},
        ],
    },
}, ensure_ascii=False))
"""


@pytest.fixture(name="skill_ws")
def _skill_ws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A temp WORKING_DIR with one bigscreen-declaring skill installed."""
    skill_dir = tmp_path / "workspaces" / "fault" / "skills" / "inspect-demo"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    (skill_dir / "scripts" / "query.py").write_text(_SCRIPT, encoding="utf-8")

    from qwenpaw import constant

    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
    return tmp_path


class TestDiscovery:
    def test_discovers_declaring_skill(self, skill_ws: Path) -> None:
        metas = skill_capabilities.discover_skill_capabilities()
        ids = {m["id"] for m in metas}
        assert "skill:fault:inspect-demo" in ids
        meta = next(m for m in metas if m["id"] == "skill:fault:inspect-demo")
        assert meta["domain"] == "inspection"
        assert {f["key"] for f in meta["availableFields"]} == {
            "metric",
            "value",
        }

    def test_in_catalog_and_resolvable(self, skill_ws: Path) -> None:
        catalog_ids = {m["id"] for m in list_capability_metadata()}
        assert "skill:fault:inspect-demo" in catalog_ids
        meta = next(
            m
            for m in list_capability_metadata()
            if m["id"] == "skill:fault:inspect-demo"
        )
        assert "_skillBlock" not in meta  # private keys stripped
        assert get_descriptor("skill:fault:inspect-demo") is not None

    def test_skill_without_block_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        plain = tmp_path / "workspaces" / "x" / "skills" / "plain"
        plain.mkdir(parents=True)
        (plain / "SKILL.md").write_text(
            "---\nname: plain\n---\n# Plain\n",
            encoding="utf-8",
        )
        from qwenpaw import constant

        monkeypatch.setattr(constant, "WORKING_DIR", tmp_path)
        assert skill_capabilities.discover_skill_capabilities() == []


class TestBridgeRunner:
    def test_runs_script_and_parses_json(self, skill_ws: Path) -> None:
        out = skill_bridge.run_skill_query(
            workspace="fault",
            skill="inspect-demo",
            script="scripts/query.py",
            args=["--output", "json", "--resId", "7953"],
        )
        assert out["data"]["total"] == 2
        assert out["data"]["items"][0]["resId"] == "7953"

    def test_missing_script_raises(self, skill_ws: Path) -> None:
        with pytest.raises(RuntimeError):
            skill_bridge.run_skill_query(
                workspace="fault",
                skill="inspect-demo",
                script="scripts/nope.py",
            )

    def test_path_traversal_blocked(self, skill_ws: Path) -> None:
        with pytest.raises(RuntimeError):
            skill_bridge.run_skill_query(
                workspace="fault",
                skill="inspect-demo",
                script="../../../../etc/passwd",
            )

    def test_tolerates_leading_log_lines(
        self,
        skill_ws: Path,
    ) -> None:
        skill_dir = (
            skill_ws / "workspaces" / "fault" / "skills" / "inspect-demo"
        )
        (skill_dir / "scripts" / "noisy.py").write_text(
            textwrap.dedent(
                """\
                import json
                print("INFO loading...")
                print(json.dumps({"rows": [{"a": 1}]}))
                """,
            ),
            encoding="utf-8",
        )
        out = skill_bridge.run_skill_query(
            workspace="fault",
            skill="inspect-demo",
            script="scripts/noisy.py",
        )
        assert out == {"rows": [{"a": 1}]}


class TestFetchMapping:
    def test_fetch_maps_rows_via_bridge(self, skill_ws: Path) -> None:
        out = skill_capabilities.fetch_skill_capability(
            "skill:fault:inspect-demo",
            {"resId": "7953"},
        )
        assert out["sourceStatus"] == "live"
        assert out["value"] == 2
        assert out["unit"] == "项"
        assert len(out["rows"]) == 2
        assert {c["key"] for c in out["columns"]} == {"metric", "value"}

    def test_bridge_failure_is_failed_status(
        self,
        skill_ws: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom(**_kw: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(skill_bridge, "run_skill_query", _boom)
        out = skill_capabilities.fetch_skill_capability(
            "skill:fault:inspect-demo",
            {},
        )
        assert out["sourceStatus"] == "failed"
        assert "boom" in out["message"]

    async def test_execute_capability_end_to_end(
        self,
        skill_ws: Path,
    ) -> None:
        result = await execute_capability(
            {"resId": "1"},
            capability_id="skill:fault:inspect-demo",
        )
        assert result.source_status == "live"
        assert result.rows and result.rows[0]["metric"] == "cpu"


def test_python_executable_present() -> None:
    # guards the bridge's reliance on sys.executable in this env
    assert sys.executable
