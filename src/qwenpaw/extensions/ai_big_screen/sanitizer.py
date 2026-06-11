# -*- coding: utf-8 -*-
"""visualSpec whitelist sanitizer (backend mirror of the frontend one).

Ported from the legacy monolith with one deliberate fix: sanitization
is **field-independent**. The legacy version returned ``{}`` whenever
``kind`` was missing or invalid, silently dropping ``composition`` (the
auto-layout weight) and ``bindings`` that the D-max renderer depends
on — even though the L1 prompt's own output example omits ``kind``.
Token whitelists are unchanged and stay aligned with
``portal/src/components/big-screen/visualSpec.ts``.
"""
from __future__ import annotations

from typing import Any

from qwenpaw.extensions.ai_big_screen.capabilities.fields import safe_int

ALLOWED_KINDS = {
    "risk-field",
    "signal-stream",
    "timeline",
    "heatmap-matrix",
    "metric-cluster",
}
ALLOWED_MOTIONS = {"none", "pulse", "scan", "flow", "stagger"}
ALLOWED_DENSITIES = {"compact", "balanced", "showcase"}
ALLOWED_LAYOUT_PATTERNS = {
    "grid",
    "focus",
    "split",
    "timeline",
    "matrix",
    "flow",
}
ALLOWED_COMPOSITIONS = {"primary", "secondary", "supporting"}
ALLOWED_BINDING_KEYS = {
    "time",
    "title",
    "message",
    "severity",
    "status",
    "value",
    "group",
    "riskScore",
    "riskLevel",
    "name",
    "x",
    "y",
    "unit",
    "prefix",
    "color",
    "label",
    "description",
    "text",
    "tone",
}
ALLOWED_LAYER_TYPES = {
    "score",
    "list",
    "stream",
    "timeline",
    "matrix",
    "metrics",
}
ALLOWED_LAYER_SOURCES = {"rows", "riskItems", "series", "categories"}
ALLOWED_RULE_OPERATORS = {">", ">=", "<", "<=", "=", "contains"}
ALLOWED_RULE_TONES = {"critical", "high", "medium", "normal", "cool", "warm"}

MAX_HIGHLIGHT_RULES = 8
MAX_LAYERS = 6

_BLOCKED_FRAGMENTS = (
    "<",
    ">",
    "script",
    "javascript:",
    "data:",
    "onerror",
    "onclick",
    "style=",
    "http://",
    "https://",
)


def safe_visual_token(value: Any, *, max_length: int = 80) -> str:
    """Sanitize a free-form token (field name / rule value)."""
    token = str(value or "").strip()[:max_length]
    if not token:
        return ""
    lowered = token.lower()
    if any(fragment in lowered for fragment in _BLOCKED_FRAGMENTS):
        return ""
    return token


def _sanitize_bindings(raw_bindings: Any) -> dict[str, str]:
    if not isinstance(raw_bindings, dict):
        return {}
    bindings: dict[str, str] = {}
    for key, value in raw_bindings.items():
        normalized_key = str(key or "").strip()
        if normalized_key not in ALLOWED_BINDING_KEYS:
            continue
        field = safe_visual_token(value, max_length=80)
        if field:
            bindings[normalized_key] = field
    return bindings


def _sanitize_rules(raw_rules: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rules, list):
        return []
    rules: list[dict[str, Any]] = []
    for raw_rule in raw_rules[:MAX_HIGHLIGHT_RULES]:
        if not isinstance(raw_rule, dict):
            continue
        field = safe_visual_token(raw_rule.get("field"), max_length=80)
        operator = str(raw_rule.get("operator") or "").strip()
        tone = str(raw_rule.get("tone") or "").strip()
        if (
            not field
            or operator not in ALLOWED_RULE_OPERATORS
            or tone not in ALLOWED_RULE_TONES
        ):
            continue
        value = raw_rule.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            safe_value: Any = value
        else:
            safe_value = safe_visual_token(value, max_length=80)
        if safe_value == "":
            continue
        rules.append(
            {
                "field": field,
                "operator": operator,
                "value": safe_value,
                "tone": tone,
            },
        )
    return rules


def _sanitize_layers(raw_layers: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_layers, list):
        return []
    layers: list[dict[str, Any]] = []
    for raw_layer in raw_layers[:MAX_LAYERS]:
        if not isinstance(raw_layer, dict):
            continue
        layer_type = str(raw_layer.get("type") or "").strip()
        source = str(raw_layer.get("source") or "rows").strip()
        if (
            layer_type not in ALLOWED_LAYER_TYPES
            or source not in ALLOWED_LAYER_SOURCES
        ):
            continue
        layer: dict[str, Any] = {"type": layer_type, "source": source}
        if "limit" in raw_layer:
            layer["limit"] = max(
                1,
                min(20, safe_int(raw_layer.get("limit"), 6)),
            )
        if "field" in raw_layer:
            field = safe_visual_token(raw_layer.get("field"), max_length=80)
            if field:
                layer["field"] = field
        layers.append(layer)
    return layers


def sanitize_visual_spec(raw_visual_spec: Any) -> dict[str, Any]:
    """Whitelist-sanitize an AI-supplied ``visualSpec``.

    Every field is validated independently; invalid tokens are dropped
    without nuking the rest of the spec.
    """
    if not isinstance(raw_visual_spec, dict):
        return {}
    visual_spec: dict[str, Any] = {}

    kind = str(raw_visual_spec.get("kind") or "").strip()
    if kind in ALLOWED_KINDS:
        visual_spec["kind"] = kind
        motion = str(raw_visual_spec.get("motion") or "none").strip()
        density = str(raw_visual_spec.get("density") or "balanced").strip()
        visual_spec["motion"] = motion if motion in ALLOWED_MOTIONS else "none"
        visual_spec["density"] = (
            density if density in ALLOWED_DENSITIES else "balanced"
        )
    else:
        motion = str(raw_visual_spec.get("motion") or "").strip()
        if motion in ALLOWED_MOTIONS:
            visual_spec["motion"] = motion
        density = str(raw_visual_spec.get("density") or "").strip()
        if density in ALLOWED_DENSITIES:
            visual_spec["density"] = density

    layout_pattern = str(raw_visual_spec.get("layoutPattern") or "").strip()
    if layout_pattern in ALLOWED_LAYOUT_PATTERNS:
        visual_spec["layoutPattern"] = layout_pattern

    composition = str(raw_visual_spec.get("composition") or "").strip()
    if composition in ALLOWED_COMPOSITIONS:
        visual_spec["composition"] = composition

    bindings = _sanitize_bindings(raw_visual_spec.get("bindings"))
    if bindings:
        visual_spec["bindings"] = bindings

    highlight_rules = _sanitize_rules(raw_visual_spec.get("highlightRules"))
    if highlight_rules:
        visual_spec["highlightRules"] = highlight_rules

    emphasis_rules = _sanitize_rules(raw_visual_spec.get("emphasisRules"))
    if emphasis_rules:
        visual_spec["emphasisRules"] = emphasis_rules

    layers = _sanitize_layers(raw_visual_spec.get("layers"))
    if layers:
        visual_spec["layers"] = layers

    return visual_spec
