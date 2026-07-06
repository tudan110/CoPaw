# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.extensions.ai_big_screen.capabilities.fields import safe_int
from qwenpaw.extensions.ai_big_screen.sanitizer import (
    safe_visual_token,
    sanitize_component_style,
    sanitize_visual_spec,
)


class TestSafeVisualToken:
    def test_plain_field_names_pass(self) -> None:
        assert safe_visual_token("severity") == "severity"
        assert safe_visual_token("riskScore") == "riskScore"
        assert safe_visual_token("告警级别") == "告警级别"

    def test_injection_payloads_blocked(self) -> None:
        for payload in (
            "<script>alert(1)</script>",
            "javascript:alert(1)",
            "data:text/html;base64,xxx",
            "x onerror=alert(1)",
            "a onclick=do()",
            "style=expression(1)",
            "http://evil.example",
            "https://evil.example",
        ):
            assert safe_visual_token(payload) == ""

    def test_length_cap(self) -> None:
        assert len(safe_visual_token("a" * 500, max_length=80)) == 80

    def test_none_and_empty(self) -> None:
        assert safe_visual_token(None) == ""
        assert safe_visual_token("   ") == ""


class TestSanitizeVisualSpec:
    def test_full_valid_spec_round_trips(self) -> None:
        spec = sanitize_visual_spec(
            {
                "kind": "risk-field",
                "motion": "pulse",
                "density": "showcase",
                "layoutPattern": "focus",
                "composition": "primary",
                "bindings": {"value": "riskScore", "tone": "riskLevel"},
                "highlightRules": [
                    {
                        "field": "cpu",
                        "operator": ">=",
                        "value": 90,
                        "tone": "critical",
                    },
                ],
                "layers": [{"type": "score", "source": "riskItems"}],
            },
        )
        assert spec["kind"] == "risk-field"
        assert spec["motion"] == "pulse"
        assert spec["density"] == "showcase"
        assert spec["layoutPattern"] == "focus"
        assert spec["composition"] == "primary"
        assert spec["bindings"] == {"value": "riskScore", "tone": "riskLevel"}
        assert spec["highlightRules"][0]["value"] == 90
        assert spec["layers"][0]["source"] == "riskItems"

    def test_composition_survives_without_kind(self) -> None:
        """Legacy bug: missing kind nuked the whole spec, dropping the
        composition weight the auto-layout engine depends on."""
        spec = sanitize_visual_spec(
            {
                "composition": "primary",
                "bindings": {"value": "total", "unit": "条"},
            },
        )
        assert spec["composition"] == "primary"
        assert spec["bindings"]["value"] == "total"
        assert "kind" not in spec

    def test_invalid_tokens_dropped_individually(self) -> None:
        spec = sanitize_visual_spec(
            {
                "kind": "explode",
                "motion": "shake",
                "density": "ultra",
                "layoutPattern": "spiral",
                "composition": "hero",
                "bindings": {
                    "value": "total",
                    "evil": "x",
                    "tone": "<script>",
                },
            },
        )
        assert "kind" not in spec
        assert spec.get("motion") in (None, "none")
        assert "layoutPattern" not in spec
        assert "composition" not in spec
        assert spec["bindings"] == {"value": "total"}

    def test_non_dict_returns_empty(self) -> None:
        assert not sanitize_visual_spec(None)
        assert not sanitize_visual_spec("kind: risk-field")
        assert not sanitize_visual_spec(42)

    def test_highlight_rules_validation(self) -> None:
        spec = sanitize_visual_spec(
            {
                "kind": "signal-stream",
                "highlightRules": [
                    {
                        "field": "lvl",
                        "operator": "~=",
                        "value": 1,
                        "tone": "critical",
                    },
                    {
                        "field": "lvl",
                        "operator": ">",
                        "value": 1,
                        "tone": "neon",
                    },
                    {
                        "field": "",
                        "operator": ">",
                        "value": 1,
                        "tone": "critical",
                    },
                    {
                        "field": "msg",
                        "operator": "contains",
                        "value": "OOM",
                        "tone": "critical",
                    },
                ],
            },
        )
        rules = spec.get("highlightRules") or []
        assert len(rules) == 1
        assert rules[0]["field"] == "msg"

    def test_rules_and_layers_length_caps(self) -> None:
        spec = sanitize_visual_spec(
            {
                "kind": "signal-stream",
                "highlightRules": [
                    {
                        "field": f"f{i}",
                        "operator": ">",
                        "value": i,
                        "tone": "high",
                    }
                    for i in range(20)
                ],
                "layers": [
                    {"type": "list", "source": "rows"} for _ in range(20)
                ],
            },
        )
        assert len(spec["highlightRules"]) <= 8
        assert len(spec["layers"]) <= 6

    def test_layer_limit_clamped(self) -> None:
        spec = sanitize_visual_spec(
            {
                "kind": "metric-cluster",
                "layers": [
                    {"type": "metrics", "source": "rows", "limit": 999},
                ],
            },
        )
        assert spec["layers"][0]["limit"] == 20

    def test_blueprint_round_trips(self) -> None:
        spec = sanitize_visual_spec(
            {
                "composition": "primary",
                "blueprint": {
                    "layout": "columns",
                    "gap": "m",
                    "cells": [
                        {
                            "span": 1,
                            "element": {
                                "kind": "value",
                                "style": "flip",
                                "size": "xl",
                                "bind": {"value": "total", "unit": "条"},
                            },
                        },
                        {
                            "span": 2,
                            "element": {
                                "kind": "chart",
                                "chart": "area",
                                "bind": {"x": "eventTime", "y": "value"},
                            },
                        },
                        {
                            "element": {
                                "kind": "group",
                                "layout": "rows",
                                "cells": [
                                    {
                                        "element": {
                                            "kind": "badge",
                                            "text": "实时监控",
                                            "tone": "cool",
                                        },
                                    },
                                    {
                                        "element": {
                                            "kind": "sparkline",
                                            "bind": {"x": "x", "y": "y"},
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            },
        )
        blueprint = spec["blueprint"]
        assert blueprint["layout"] == "columns"
        assert blueprint["gap"] == "m"
        assert len(blueprint["cells"]) == 3
        assert blueprint["cells"][0]["element"]["style"] == "flip"
        assert blueprint["cells"][1]["element"]["chart"] == "area"
        group = blueprint["cells"][2]["element"]
        assert group["kind"] == "group"
        assert len(group["cells"]) == 2

    def test_blueprint_invalid_atoms_dropped(self) -> None:
        spec = sanitize_visual_spec(
            {
                "blueprint": {
                    "layout": "explode",  # invalid → rows
                    "cells": [
                        {"element": {"kind": "iframe", "src": "evil"}},
                        {
                            "element": {
                                "kind": "chart",
                                "chart": "3d-globe",  # invalid chart
                            },
                        },
                        {
                            "element": {
                                "kind": "value",
                                "bind": {
                                    "value": "<script>",  # injected field
                                    "unit": "条",
                                },
                            },
                        },
                        {
                            "element": {
                                "kind": "badge",
                                "text": "javascript:alert(1)",
                            },
                        },
                        {
                            "element": {
                                "kind": "value",
                                "size": "xl",
                                "bind": {"value": "total"},
                            },
                        },
                    ],
                },
            },
        )
        blueprint = spec["blueprint"]
        assert blueprint["layout"] == "rows"
        # only the last valid value cell survives
        assert len(blueprint["cells"]) == 1
        survivor = blueprint["cells"][0]["element"]
        assert survivor["kind"] == "value"
        assert survivor["bind"] == {"value": "total"}

    def test_blueprint_depth_and_caps(self) -> None:
        deep = {
            "kind": "group",
            "layout": "rows",
            "cells": [
                {
                    "element": {
                        "kind": "group",
                        "layout": "rows",
                        "cells": [
                            {
                                "element": {
                                    "kind": "group",  # depth 3 → dropped
                                    "layout": "rows",
                                    "cells": [
                                        {
                                            "element": {
                                                "kind": "label",
                                                "text": "太深了",
                                            },
                                        },
                                    ],
                                },
                            },
                            {"element": {"kind": "label", "text": "ok"}},
                        ],
                    },
                },
            ],
        }
        spec = sanitize_visual_spec(
            {
                "blueprint": {
                    "layout": "grid",
                    "cells": [{"element": deep, "span": 99}]
                    + [
                        {"element": {"kind": "label", "text": f"c{i}"}}
                        for i in range(20)
                    ],
                },
            },
        )
        blueprint = spec["blueprint"]
        assert len(blueprint["cells"]) <= 12
        assert blueprint["cells"][0]["span"] == 4  # clamped 99→4
        level2 = blueprint["cells"][0]["element"]["cells"][0]["element"]
        level2_kinds = [c["element"]["kind"] for c in level2["cells"]]
        assert "group" not in level2_kinds  # depth-3 group dropped
        assert "label" in level2_kinds

    def test_blueprint_empty_when_no_valid_cells(self) -> None:
        spec = sanitize_visual_spec(
            {
                "kind": "metric-cluster",
                "blueprint": {"layout": "rows", "cells": [{"bogus": 1}]},
            },
        )
        assert "blueprint" not in spec

    def test_emphasis_rules_supported(self) -> None:
        spec = sanitize_visual_spec(
            {
                "kind": "signal-stream",
                "emphasisRules": [
                    {
                        "field": "level",
                        "operator": "=",
                        "value": "critical",
                        "tone": "critical",
                    },
                ],
            },
        )
        assert spec["emphasisRules"][0]["field"] == "level"


class TestComponentStyle:
    def test_clamps_and_whitelists(self) -> None:
        style = sanitize_component_style(
            {
                "sizeScale": 9,
                "lineOpacity": 250,
                "labelBrightness": -500,
                "palette": "warm",
                "emphasis": "strong",
                "accentColor": "gold",
                "bogus": "x",
            },
        )
        assert style == {
            "sizeScale": 2.0,
            "lineOpacity": 100,
            "labelBrightness": -100,
            "palette": "warm",
            "emphasis": "strong",
            "accentColor": "gold",
        }

    def test_rejects_bad_palette_emphasis_accent(self) -> None:
        style = sanitize_component_style(
            {
                "palette": "neon",  # not whitelisted
                "emphasis": "loud",  # not whitelisted
                "accentColor": "url(http://x)",  # not a colour
                "sizeScale": "big",  # not a number
            },
        )
        assert style == {}

    def test_accepts_hex_accent(self) -> None:
        style = sanitize_component_style({"accentColor": "#22d3ee"})
        assert style == {"accentColor": "#22d3ee"}

    def test_flows_through_visual_spec(self) -> None:
        spec = sanitize_visual_spec(
            {"composition": "primary", "style": {"sizeScale": 1.5}},
        )
        assert spec["composition"] == "primary"
        assert spec["style"] == {"sizeScale": 1.5}


class TestSafeInt:
    def test_plain_and_string_integers(self) -> None:
        assert safe_int(42, -1) == 42
        assert safe_int("42", -1) == 42
        assert safe_int("  7  ", -1) == 7  # int() strips surrounding space

    def test_large_numbers_pass_through(self) -> None:
        big = 10**30
        assert safe_int(big, -1) == big
        assert safe_int("9" * 40, -1) == int("9" * 40)

    def test_negative_numbers(self) -> None:
        assert safe_int(-7, 0) == -7
        assert safe_int("-7", 0) == -7

    def test_floats_truncate_toward_zero(self) -> None:
        assert safe_int(3.9, -1) == 3
        assert safe_int(-3.9, -1) == -3

    def test_non_numeric_returns_fallback(self) -> None:
        # Numeric-looking strings with a decimal point are NOT valid ints.
        assert safe_int("3.14", -1) == -1
        assert safe_int("abc", 99) == 99
        assert safe_int("", 5) == 5
        assert safe_int(None, 5) == 5
        assert safe_int([], 5) == 5
        assert safe_int({}, 5) == 5


class TestScrollStyleKnob:
    def test_scroll_enum_accepted(self) -> None:
        from qwenpaw.extensions.ai_big_screen.sanitizer import (
            sanitize_component_style,
        )

        assert sanitize_component_style({"scroll": "off"}) == {
            "scroll": "off",
        }
        assert sanitize_component_style({"scroll": "ON"}) == {"scroll": "on"}
        assert sanitize_component_style({"scroll": "marquee-fast"}) == {}
