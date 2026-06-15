# -*- coding: utf-8 -*-
"""Data-aware visual rebalancing (M3 Phase A).

``intrinsicSize`` on the frontend already sizes each panel's *box* by
its row count, but the panel's importance (``visualSpec.composition``)
is decided by the LLM at generation time, blind to how much data
actually came back. So a screen designed for rich data still reads as
"built for a full template" when the real data is sparse.

This deterministic pass runs right after L2 fetch and rewrites each
component's ``composition`` from its REAL data volume: empty/failed →
supporting (small), sparse → secondary, dense → primary. It also
guarantees one ``primary`` anchor when any component has live data, so
a sparse screen still has a focal point instead of a field of equal
small cards. It only touches ``visualSpec.composition`` — never data,
queryParams or capabilityId — so no-fake-data holds and the LLM
critique can still refine on top.
"""
from __future__ import annotations

from typing import Any, Mapping

# Intrinsically small, single-value panels — meaningful even at volume 1,
# but never the screen's main real-estate earner.
_SINGLE_VALUE_TYPES = {
    "flip-number",
    "metric-card",
    "metric-kpi",
    "gauge",
    "liquid-ball",
}
_LIST_TYPES = {
    "alarm-stream",
    "status-stream",
    "table",
    "timeline",
    "top-n",
    "funnel",
}
_CHART_TYPES = {
    "donut",
    "bar-chart",
    "line-chart",
    "area-chart",
    "radar",
    "heatmap",
    "bar3d",
}
_GRAPH_TYPES = {"graph", "topology"}

# A component must carry at least this many rows to be promoted into the
# hero ``primary`` slot — promoting a 1-2 row panel to primary would just
# stretch sparse content, the very thing this pass exists to avoid.
_ANCHOR_MIN_VOLUME = 3


def _component_volume(data: Mapping[str, Any]) -> int:
    """Rows/series/nodes/categories count, else 1 if any metric value."""
    if not isinstance(data, Mapping):
        return 0
    counts = [
        len(data.get(key) or [])
        for key in ("rows", "series", "nodes", "categories")
        if isinstance(data.get(key), list)
    ]
    volume = max(counts) if counts else 0
    if volume == 0 and isinstance(data.get("metrics"), Mapping):
        if data.get("metrics"):
            return 1
    if volume == 0 and data.get("value") not in (None, "", []):
        return 1
    return volume


def _by_volume(volume: int, primary_at: int, secondary_at: int) -> str:
    if volume >= primary_at:
        return "primary"
    if volume >= secondary_at:
        return "secondary"
    return "supporting"


# (primary_at, secondary_at) row-count thresholds per type family.
_VOLUME_THRESHOLDS: dict[str, tuple[int, int]] = {
    "graph": (5, 1),
    "chart": (8, 1),
    "list": (7, 3),
}


def _target_composition(component: Mapping[str, Any]) -> str:
    data = component.get("data")
    status = (
        str(data.get("sourceStatus") or "")
        if isinstance(data, Mapping)
        else ""
    )
    volume = _component_volume(data if isinstance(data, Mapping) else {})

    # No honest data to show → take the least space.
    if status in ("failed", "empty") or volume == 0:
        return "supporting"

    ctype = str(component.get("type") or "")
    # Single-value / pulse / composed panels are compact-but-meaningful;
    # they never out-rank a data-dense list, hence a flat "secondary".
    if ctype in _SINGLE_VALUE_TYPES or ctype in ("risk-pulse", "composed"):
        return "secondary"
    if ctype in _GRAPH_TYPES:
        return _by_volume(volume, *_VOLUME_THRESHOLDS["graph"])
    if ctype in _CHART_TYPES:
        return _by_volume(volume, *_VOLUME_THRESHOLDS["chart"])
    if ctype in _LIST_TYPES:
        return _by_volume(volume, *_VOLUME_THRESHOLDS["list"])
    # text / unknown
    return "supporting"


def _set_composition(component: dict[str, Any], composition: str) -> None:
    visual_spec = component.get("visualSpec")
    if not isinstance(visual_spec, dict):
        visual_spec = {}
    visual_spec["composition"] = composition
    component["visualSpec"] = visual_spec


def rebalance_screen_by_data(screen: dict[str, Any]) -> dict[str, Any]:
    """Rewrite component ``composition`` from real data volume, in place.

    Returns a summary ``{adjusted, anchorId, volumes}``; never raises on
    a malformed screen (returns an empty summary instead).
    """
    components = [
        component
        for component in (screen.get("components") or [])
        if isinstance(component, dict)
    ]
    if not components:
        return {"adjusted": [], "anchorId": "", "volumes": {}}

    adjusted: list[dict[str, str]] = []
    volumes: dict[str, int] = {}
    has_primary = False
    best_id = ""
    best_volume = -1

    for component in components:
        component_id = str(component.get("id") or "")
        data = component.get("data")
        volume = _component_volume(data if isinstance(data, Mapping) else {})
        volumes[component_id] = volume
        status = (
            str(data.get("sourceStatus") or "")
            if isinstance(data, Mapping)
            else ""
        )

        previous = ""
        visual_spec = component.get("visualSpec")
        if isinstance(visual_spec, Mapping):
            previous = str(visual_spec.get("composition") or "")

        target = _target_composition(component)
        _set_composition(component, target)
        if target != previous:
            adjusted.append(
                {"id": component_id, "from": previous, "to": target},
            )
        if target == "primary":
            has_primary = True

        # track the richest live component as a potential anchor
        if status not in ("failed", "empty") and volume > best_volume:
            best_volume = volume
            best_id = component_id

    # Anchor guarantee: a sparse screen with some live data still gets a
    # focal point instead of a field of equal small cards.
    anchor_id = ""
    if not has_primary and best_id and best_volume >= _ANCHOR_MIN_VOLUME:
        for component in components:
            if str(component.get("id") or "") == best_id:
                _set_composition(component, "primary")
                adjusted.append(
                    {"id": best_id, "from": "anchor", "to": "primary"},
                )
                anchor_id = best_id
                break

    return {"adjusted": adjusted, "anchorId": anchor_id, "volumes": volumes}
