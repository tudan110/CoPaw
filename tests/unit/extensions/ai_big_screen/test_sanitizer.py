# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.extensions.ai_big_screen.sanitizer import (
    safe_visual_token,
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
