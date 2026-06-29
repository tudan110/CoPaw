# -*- coding: utf-8 -*-
"""Installed skills → big-screen data capabilities (M3 Phase C).

A skill opts into the big-screen catalog by adding a ``bigscreen``
block to its ``SKILL.md`` front matter::

    bigscreen:
      domain: inspection
      script: scripts/get_metrics.py
      args: ["--output", "json"]
      rowsPath: data.items
      valuePath: data.total
      unit: 项
      fields: [{key: metric, label: 指标}, {key: value, label: 值}]
      params: [{name: resId, required: true}]
      examplePrompts: ["巡检 7953 的指标"]

Discovery scans the working-dir workspaces, and each declaring skill
becomes a capability ``skill:<workspace>:<skill>``. A generic fetcher
runs the declared script via :mod:`skill_bridge` (declared static args
plus ``--<param> <value>`` for declared params the LLM filled), then
maps the JSON output onto rows/columns — the same mapping the proxy
connector uses. So a newly installed skill appears on the big-screen
with no code change, showing the same real data the chat path gets.

Safety: only operator-installed skills with a declared block are run,
the script is sandboxed to the skill dir, and the LLM only selects the
capability + fills declared params (never the script or path).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator, Mapping

from qwenpaw.extensions.ai_big_screen import skill_bridge
from qwenpaw.extensions.ai_big_screen.capabilities.proxy_capabilities import (
    _coerce_rows,
    _dotted_get,
)

_LOGGER = logging.getLogger(__name__)

CAPABILITY_PREFIX = "skill:"

_DEFAULT_VISUALS = [
    "table",
    "alarm-stream",
    "metric-card",
    "metric-kpi",
    "flip-number",
    "donut",
    "bar-chart",
    "line-chart",
    "composed",
]


def _workspaces_root() -> Path:
    from qwenpaw import constant

    return constant.WORKING_DIR / "workspaces"


def _read_bigscreen_block(skill_md: Path) -> dict[str, Any] | None:
    try:
        import frontmatter

        post = frontmatter.loads(skill_md.read_text(encoding="utf-8"))
    except Exception:  # unreadable / no frontmatter → not a candidate
        return None
    block = post.metadata.get("bigscreen") if post.metadata else None
    if not isinstance(block, dict):
        return None
    if block.get("enabled", True) is False:
        return None
    if not str(block.get("script") or "").strip():
        return None
    return block


def _iter_skill_specs() -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield ``(workspace, skill, bigscreen_block)`` for declaring skills."""
    root = _workspaces_root()
    if not root.exists():
        return
    for workspace_dir in sorted(root.iterdir()):
        skills_dir = workspace_dir / "skills"
        if not (workspace_dir.is_dir() and skills_dir.is_dir()):
            continue
        for skill_dir in sorted(skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not (skill_dir.is_dir() and skill_md.is_file()):
                continue
            block = _read_bigscreen_block(skill_md)
            if block is not None:
                yield workspace_dir.name, skill_dir.name, block


def _capability_id(workspace: str, skill: str) -> str:
    return f"{CAPABILITY_PREFIX}{workspace}:{skill}"


def _split_capability_id(capability_id: str) -> tuple[str, str] | None:
    parts = capability_id.split(":")
    if len(parts) != 3 or parts[0] != "skill":
        return None
    return parts[1], parts[2]


def _fields(block: Mapping[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for field in block.get("fields") or []:
        if isinstance(field, Mapping) and field.get("key"):
            key = str(field["key"])
            out.append({"key": key, "label": str(field.get("label") or key)})
    return out


def _params(block: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for param in block.get("params") or []:
        if isinstance(param, Mapping) and param.get("name"):
            out.append(dict(param))
    return out


def _metadata(workspace: str, skill: str, block: Mapping[str, Any]) -> dict:
    capability_id = _capability_id(workspace, skill)
    params = _params(block)
    input_schema = {
        str(param["name"]): param.get("default") for param in params
    }
    return {
        "id": capability_id,
        "name": str(block.get("name") or skill),
        "domain": str(block.get("domain") or "skill"),
        "category": str(block.get("domain") or "skill"),
        "connection": str(block.get("connection") or "inoe"),
        "description": str(
            block.get("description") or f"技能「{skill}」提供的大屏数据能力",
        ),
        "inputSchema": input_schema,
        "outputSchema": {"columns": "array", "rows": "array"},
        "availableFields": _fields(block),
        "supportedVisuals": list(_DEFAULT_VISUALS),
        "permissionScope": "skill:read",
        "cachePolicy": {"ttlSeconds": 30},
        "refreshPolicy": {"intervalSeconds": 60},
        "dataSource": capability_id,
        "skillName": skill,
        "examplePrompts": list(block.get("examplePrompts") or []),
        "_skillWorkspace": workspace,
        "_skillName": skill,
        "_skillBlock": dict(block),
    }


def discover_skill_capabilities() -> list[dict[str, Any]]:
    """Capability metadata for every skill that declared a bigscreen block."""
    try:
        return [
            _metadata(workspace, skill, block)
            for workspace, skill, block in _iter_skill_specs()
        ]
    except Exception:  # discovery must never break the catalog
        _LOGGER.warning("skill capability discovery failed", exc_info=True)
        return []


def get_skill_metadata(capability_id: str) -> dict[str, Any] | None:
    split = _split_capability_id(capability_id)
    if split is None:
        return None
    workspace, skill = split
    skill_md = _workspaces_root() / workspace / "skills" / skill / "SKILL.md"
    if not skill_md.is_file():
        return None
    block = _read_bigscreen_block(skill_md)
    if block is None:
        return None
    return _metadata(workspace, skill, block)


def metadata_for_registry() -> list[dict[str, Any]]:
    """Catalog metadata with the private ``_skill*`` keys stripped."""
    cleaned: list[dict[str, Any]] = []
    for meta in discover_skill_capabilities():
        cleaned.append(
            {
                key: value
                for key, value in meta.items()
                if not key.startswith("_")
            },
        )
    return cleaned


def _build_args(
    block: Mapping[str, Any],
    query_params: Mapping[str, Any],
) -> list[str]:
    args = [str(item) for item in (block.get("args") or [])]
    allowed = {
        str(param["name"]) for param in _params(block) if param.get("name")
    }
    for name in allowed:
        if name in query_params and query_params[name] not in (None, ""):
            args.extend([f"--{name}", str(query_params[name])])
    return args


def fetch_skill_capability(
    capability_id: str,
    query_params: Mapping[str, Any],
) -> dict[str, Any]:
    """Fetcher for a ``skill:<ws>:<skill>`` capability."""
    meta = get_skill_metadata(capability_id)
    if meta is None:
        return {
            "source": capability_id,
            "sourceStatus": "failed",
            "message": "技能未安装或未声明大屏能力。",
        }
    workspace = meta["_skillWorkspace"]
    skill = meta["_skillName"]
    block = meta["_skillBlock"]

    try:
        payload = skill_bridge.run_skill_query(
            workspace=workspace,
            skill=skill,
            script=str(block.get("script") or ""),
            args=_build_args(block, query_params),
            timeout=float(block.get("timeout") or 30.0),
        )
    except Exception as exc:
        return {
            "source": capability_id,
            "sourceStatus": "failed",
            "message": str(exc).strip() or "技能查询失败",
        }

    rows = _coerce_rows(_dotted_get(payload, str(block.get("rowsPath") or "")))
    columns = _fields(block)
    if not columns and rows:
        columns = [{"key": key, "label": key} for key in rows[0].keys()]

    value: Any = None
    if block.get("valuePath"):
        value = _dotted_get(payload, str(block["valuePath"]))
    if value is None:
        value = len(rows)
    total = _dotted_get(payload, str(block.get("totalPath") or ""))
    if not isinstance(total, int):
        total = len(rows)

    return {
        "source": capability_id,
        "sourceStatus": "live" if rows else "empty",
        "value": value,
        "unit": str(block.get("unit") or ""),
        "total": total,
        "columns": columns,
        "rows": rows,
    }
