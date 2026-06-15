# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from typing import Any

from qwenpaw.extensions.ai_big_screen.rebalance import (
    rebalance_screen_by_data,
)


def _comp(
    cid: str,
    ctype: str,
    *,
    rows: int = 0,
    status: str = "live",
    composition: str = "primary",
    metrics: dict | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"sourceStatus": status}
    if rows:
        data["rows"] = [{"i": i} for i in range(rows)]
    if metrics is not None:
        data["metrics"] = metrics
    return {
        "id": cid,
        "type": ctype,
        "visualSpec": {"composition": composition},
        "queryParams": {"limit": 50},
        "data": data,
    }


def _screen(components: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": "s1", "components": components}


def _composition(component: dict[str, Any]) -> str:
    return component["visualSpec"]["composition"]


class TestRebalanceRules:
    def test_empty_and_failed_become_supporting(self) -> None:
        screen = _screen(
            [
                _comp("a", "alarm-stream", rows=0, status="empty"),
                _comp("b", "table", rows=5, status="failed"),
            ],
        )
        rebalance_screen_by_data(screen)
        assert _composition(screen["components"][0]) == "supporting"
        assert _composition(screen["components"][1]) == "supporting"

    def test_dense_list_becomes_primary(self) -> None:
        screen = _screen([_comp("a", "alarm-stream", rows=12)])
        rebalance_screen_by_data(screen)
        assert _composition(screen["components"][0]) == "primary"

    def test_sparse_list_downgraded(self) -> None:
        # a dense component already holds the primary slot, so the anchor
        # guarantee does not fire and the raw row-count rules are visible
        screen = _screen(
            [
                _comp("anchor", "alarm-stream", rows=15),  # → primary
                _comp("a", "alarm-stream", rows=2),  # 1-2 → supporting
                _comp("b", "table", rows=4),  # 3-6 → secondary
            ],
        )
        rebalance_screen_by_data(screen)
        by_id = {c["id"]: c for c in screen["components"]}
        assert _composition(by_id["anchor"]) == "primary"
        assert _composition(by_id["a"]) == "supporting"
        assert _composition(by_id["b"]) == "secondary"

    def test_single_value_is_secondary(self) -> None:
        screen = _screen(
            [_comp("a", "flip-number", rows=0, metrics={"value": 42})],
        )
        rebalance_screen_by_data(screen)
        assert _composition(screen["components"][0]) == "secondary"

    def test_anchor_promotes_richest_when_all_sparse(self) -> None:
        # no component qualifies for primary; the richest live one is
        # promoted so the screen still has a focal point
        screen = _screen(
            [
                _comp("a", "alarm-stream", rows=2),
                _comp("b", "table", rows=4),
                _comp("c", "alarm-stream", rows=1),
            ],
        )
        summary = rebalance_screen_by_data(screen)
        assert summary["anchorId"] == "b"
        by_id = {c["id"]: c for c in screen["components"]}
        assert _composition(by_id["b"]) == "primary"

    def test_no_anchor_when_everything_empty(self) -> None:
        screen = _screen(
            [
                _comp("a", "alarm-stream", rows=0, status="empty"),
                _comp("b", "table", rows=0, status="failed"),
            ],
        )
        summary = rebalance_screen_by_data(screen)
        assert summary["anchorId"] == ""
        for component in screen["components"]:
            assert _composition(component) == "supporting"

    def test_creates_visualspec_when_absent(self) -> None:
        component = {
            "id": "a",
            "type": "alarm-stream",
            "data": {"sourceStatus": "live", "rows": [{"i": 0}] * 9},
        }
        screen = _screen([component])
        rebalance_screen_by_data(screen)
        assert screen["components"][0]["visualSpec"]["composition"] == (
            "primary"
        )

    def test_never_touches_data_or_query_params(self) -> None:
        component = _comp("a", "alarm-stream", rows=2)
        before_data = copy.deepcopy(component["data"])
        before_qp = copy.deepcopy(component["queryParams"])
        screen = _screen([component])
        rebalance_screen_by_data(screen)
        assert screen["components"][0]["data"] == before_data
        assert screen["components"][0]["queryParams"] == before_qp

    def test_summary_reports_adjustments_and_volumes(self) -> None:
        screen = _screen(
            [
                _comp("a", "alarm-stream", rows=12, composition="supporting"),
                _comp("b", "flip-number", rows=0, metrics={"value": 1}),
            ],
        )
        summary = rebalance_screen_by_data(screen)
        assert summary["volumes"]["a"] == 12
        adjusted_ids = {entry["id"] for entry in summary["adjusted"]}
        assert "a" in adjusted_ids  # supporting → primary

    def test_empty_screen_safe(self) -> None:
        assert rebalance_screen_by_data({"components": []}) == {
            "adjusted": [],
            "anchorId": "",
            "volumes": {},
        }
