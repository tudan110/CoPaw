# -*- coding: utf-8 -*-
"""Parity guard for the alarm capability contract (v0).

The ``real-alarm`` skill runs as an offline subprocess and cannot import
:mod:`qwenpaw.extensions.integrations.alarm_contract`, so it keeps its own
copy of the severity/status/class display maps in
``scripts/utils/alarm_normalizer.py``. Those copies MUST stay identical to
the authoritative contract until M1 folds the skill onto the shared
connector. This test fails on any drift — in the skill copies or the
contract — which is exactly the "change one, forget the other → chat and
big-screen disagree" class of bug this standardization effort exists to
kill.

Maps are read via static ``ast`` parsing (no skill code executed, no skill
sys.path needed).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from qwenpaw.extensions.integrations import alarm_contract

# tests/unit/extensions/integrations/<this file> → repo root is 4 up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SKILL_REL = (
    "deploy-all/qwenpaw/working/workspaces/{ws}/skills/real-alarm/"
    "scripts/utils/alarm_normalizer.py"
)
_WORKSPACES = ("query", "fault", "gateway")

# skill map name -> authoritative contract map it must equal.
_PARITY = {
    "ALARM_SEVERITY_MAP": alarm_contract.SEVERITY_TO_NAME,
    "ALARM_STATUS_MAP": alarm_contract.STATUS_TO_NAME,
    "ALARM_CLASS_MAP": alarm_contract.CLASS_TO_NAME,
}


def _skill_path(ws: str) -> Path:
    return _REPO_ROOT / _SKILL_REL.format(ws=ws)


def _extract_maps(path: Path) -> dict[str, dict]:
    """Statically pull the top-level dict literals we care about."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in _PARITY:
                found[target.id] = ast.literal_eval(node.value)
    return found


@pytest.mark.parametrize("ws", _WORKSPACES)
def test_skill_copy_exists(ws: str) -> None:
    assert _skill_path(ws).is_file(), (
        f"real-alarm skill copy missing for workspace '{ws}'"
    )


@pytest.mark.parametrize("ws", _WORKSPACES)
@pytest.mark.parametrize("map_name", sorted(_PARITY))
def test_skill_map_matches_contract(ws: str, map_name: str) -> None:
    maps = _extract_maps(_skill_path(ws))
    assert map_name in maps, f"{map_name} not found in '{ws}' skill copy"
    assert maps[map_name] == _PARITY[map_name], (
        f"{ws}/{map_name} drifted from alarm_contract — update both, "
        "or fold the skill onto the connector (M1)."
    )


def test_skill_copies_are_identical() -> None:
    per_ws = {ws: _extract_maps(_skill_path(ws)) for ws in _WORKSPACES}
    baseline_ws = _WORKSPACES[0]
    baseline = per_ws[baseline_ws]
    for ws in _WORKSPACES[1:]:
        assert per_ws[ws] == baseline, (
            f"skill maps in '{ws}' differ from '{baseline_ws}'"
        )
