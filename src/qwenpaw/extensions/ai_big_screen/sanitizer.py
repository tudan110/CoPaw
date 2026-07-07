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

import re
from typing import Any, Callable, Mapping

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
#: Canonical palette whitelist. Lives here (the leaf sanitizer) so both
#: ``intent`` (generation) and ``patch`` (editing) import the same set
#: without a circular import; mirrors the frontend ``PALETTES`` keys.
ALLOWED_PALETTES = {
    "professional",
    "warm",
    "cool",
    "executive",
    "industrial",
    "aurora",
    "mono",
}
ALLOWED_EMPHASIS = {"standard", "strong"}
#: component-level presentation style (visualSpec.style) bounds.
STYLE_SIZE_MIN = 0.5
STYLE_SIZE_MAX = 2.0
#: accentColor must be a bare hex colour or a plain colour name — never
#: an arbitrary CSS value (defence in depth on top of safe_visual_token).
_ACCENT_COLOR_RE = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$|^[a-zA-Z]{3,20}$",
)
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

# --- blueprint (composed component) grammar -------------------------------
# The generative layer: the LLM composes a screen panel from controlled
# atoms instead of picking a prefab. Everything is whitelisted data; the
# renderer interprets it — never executes it.
BLUEPRINT_LAYOUTS = {"rows", "columns", "grid", "overlay", "radial"}
BLUEPRINT_GAPS = {"s", "m", "l"}
BLUEPRINT_ELEMENT_KINDS = {
    "value",
    "chart",
    "list",
    "badge",
    "label",
    "progress",
    "sparkline",
    "group",
}
BLUEPRINT_VALUE_STYLES = {"plain", "flip", "glow"}
BLUEPRINT_VALUE_SIZES = {"m", "l", "xl"}
BLUEPRINT_CHARTS = {
    "line",
    "area",
    "bar",
    "donut",
    "gauge",
    "radar",
    "heatmap",
}
BLUEPRINT_LIST_STYLES = {"stream", "rank", "plain"}
BLUEPRINT_PROGRESS_STYLES = {"bar", "ring", "liquid"}
BLUEPRINT_BIND_KEYS = {
    "value": {"value", "unit", "label", "prefix"},
    "chart": {"x", "y", "name", "value"},
    "list": {"title", "message", "time", "tone", "value", "name"},
    "badge": {"text"},
    "progress": {"value", "max"},
    "sparkline": {"x", "y"},
}
MAX_BLUEPRINT_CELLS = 12
MAX_BLUEPRINT_DEPTH = 2
MAX_BLUEPRINT_LIST_LIMIT = 20

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


def _sanitize_bind(kind: str, raw_bind: Any) -> dict[str, str]:
    allowed = BLUEPRINT_BIND_KEYS.get(kind, set())
    if not isinstance(raw_bind, dict) or not allowed:
        return {}
    bind: dict[str, str] = {}
    for key, value in raw_bind.items():
        normalized_key = str(key or "").strip()
        if normalized_key not in allowed:
            continue
        field = safe_visual_token(value, max_length=80)
        if field:
            bind[normalized_key] = field
    return bind


def _sanitize_group(raw: Mapping[str, Any], *, depth: int) -> dict[str, Any]:
    if depth >= MAX_BLUEPRINT_DEPTH:
        return {}
    nested = sanitize_blueprint(raw, depth=depth + 1)
    if not nested:
        return {}
    return {"kind": "group", **nested}


def _raw_style(raw: Mapping[str, Any]) -> str:
    return str(raw.get("style") or "").strip()


def _finish_value(
    element: dict[str, Any],
    raw: Mapping[str, Any],
    bind: dict[str, str],
) -> bool:
    if _raw_style(raw) in BLUEPRINT_VALUE_STYLES:
        element["style"] = _raw_style(raw)
    size = str(raw.get("size") or "").strip()
    if size in BLUEPRINT_VALUE_SIZES:
        element["size"] = size
    return "value" in bind  # core binding survived sanitization?


def _finish_chart(
    element: dict[str, Any],
    raw: Mapping[str, Any],
    _bind: dict[str, str],
) -> bool:
    chart = str(raw.get("chart") or "").strip()
    if chart in BLUEPRINT_CHARTS:
        element["chart"] = chart
        return True
    return False


def _finish_list(
    element: dict[str, Any],
    raw: Mapping[str, Any],
    _bind: dict[str, str],
) -> bool:
    if _raw_style(raw) in BLUEPRINT_LIST_STYLES:
        element["style"] = _raw_style(raw)
    element["limit"] = max(
        1,
        min(MAX_BLUEPRINT_LIST_LIMIT, safe_int(raw.get("limit"), 6)),
    )
    return True


def _finish_progress(
    element: dict[str, Any],
    raw: Mapping[str, Any],
    bind: dict[str, str],
) -> bool:
    if _raw_style(raw) in BLUEPRINT_PROGRESS_STYLES:
        element["style"] = _raw_style(raw)
    if "max" in raw and isinstance(raw.get("max"), (int, float)):
        element["max"] = float(raw["max"])
    return "value" in bind


def _finish_sparkline(
    _element: dict[str, Any],
    _raw: Mapping[str, Any],
    bind: dict[str, str],
) -> bool:
    return "y" in bind


def _finish_text(
    element: dict[str, Any],
    raw: Mapping[str, Any],
    bind: dict[str, str],
) -> bool:
    text = safe_visual_token(raw.get("text"), max_length=60)
    if text:
        element["text"] = text
    tone = str(raw.get("tone") or "").strip()
    if tone in ALLOWED_RULE_TONES:
        element["tone"] = tone
    return bool(text or bind)


_ELEMENT_FINISHERS: dict[
    str,
    Callable[[dict[str, Any], Mapping[str, Any], dict[str, str]], bool],
] = {
    "value": _finish_value,
    "chart": _finish_chart,
    "list": _finish_list,
    "progress": _finish_progress,
    "sparkline": _finish_sparkline,
    "badge": _finish_text,
    "label": _finish_text,
}


def _sanitize_element(raw: Any, *, depth: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    kind = str(raw.get("kind") or "").strip()
    if kind not in BLUEPRINT_ELEMENT_KINDS:
        return {}
    if kind == "group":
        return _sanitize_group(raw, depth=depth)

    element: dict[str, Any] = {"kind": kind}
    bind = _sanitize_bind(kind, raw.get("bind"))
    if bind:
        element["bind"] = bind
    ok = _ELEMENT_FINISHERS[kind](element, raw, bind)
    return element if ok else {}


def sanitize_blueprint(raw: Any, *, depth: int = 0) -> dict[str, Any]:
    """Whitelist-sanitize a composed-component blueprint.

    Returns ``{}`` when nothing valid remains, so a malformed blueprint
    degrades to an ordinary prefab render instead of breaking the
    screen.
    """
    if not isinstance(raw, dict):
        return {}
    layout = str(raw.get("layout") or "").strip()
    if layout not in BLUEPRINT_LAYOUTS:
        layout = "rows"
    cells_raw = raw.get("cells")
    if not isinstance(cells_raw, list):
        return {}
    cells: list[dict[str, Any]] = []
    for cell_raw in cells_raw[:MAX_BLUEPRINT_CELLS]:
        if not isinstance(cell_raw, dict):
            continue
        element = _sanitize_element(cell_raw.get("element"), depth=depth)
        if not element:
            continue
        cell: dict[str, Any] = {"element": element}
        if "span" in cell_raw:
            cell["span"] = max(1, min(4, safe_int(cell_raw.get("span"), 1)))
        cells.append(cell)
    if not cells:
        return {}
    blueprint: dict[str, Any] = {"layout": layout, "cells": cells}
    gap = str(raw.get("gap") or "").strip()
    if gap in BLUEPRINT_GAPS:
        blueprint["gap"] = gap
    return blueprint


def _clamp_number(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(low, min(high, float(value)))


def sanitize_component_style(raw_style: Any) -> dict[str, Any]:
    """Whitelist + clamp a component-level presentation style block.

    Lives on ``visualSpec.style`` — the single controlled vocabulary the
    LLM generator and the natural-language edit loop both use for size /
    colour / brightness / emphasis. Enums and clamped numbers only;
    ``accentColor`` must match a strict colour pattern. No raw CSS, URL or
    code can survive — the renderer interprets these, never executes them.
    """
    if not isinstance(raw_style, dict):
        return {}
    style: dict[str, Any] = {}

    size_scale = _clamp_number(
        raw_style.get("sizeScale"),
        STYLE_SIZE_MIN,
        STYLE_SIZE_MAX,
    )
    if size_scale is not None:
        style["sizeScale"] = size_scale

    palette = str(raw_style.get("palette") or "").strip()
    if palette in ALLOWED_PALETTES:
        style["palette"] = palette

    line_opacity = _clamp_number(raw_style.get("lineOpacity"), 0, 100)
    if line_opacity is not None:
        style["lineOpacity"] = int(line_opacity)

    label_brightness = _clamp_number(
        raw_style.get("labelBrightness"),
        -100,
        100,
    )
    if label_brightness is not None:
        style["labelBrightness"] = int(label_brightness)

    emphasis = str(raw_style.get("emphasis") or "").strip()
    if emphasis in ALLOWED_EMPHASIS:
        style["emphasis"] = emphasis

    accent = safe_visual_token(raw_style.get("accentColor"), max_length=20)
    if accent and _ACCENT_COLOR_RE.match(accent):
        style["accentColor"] = accent

    # In-widget presentation behaviour: list/table auto-marquee control.
    # "off" = static (manual scrollbar), "on" = force marquee, "auto" =
    # row-count threshold (the legacy default). A hardcoded marquee was
    # an uncontrollable element — "不要滚动" must be expressible.
    scroll = str(raw_style.get("scroll") or "").strip().lower()
    # Tolerate the words a model actually reaches for ("static"/"固定"…)
    # — an exact three-token enum turned "设置为静态表格" into a silent
    # no-op. Same forgiveness philosophy as colour names / type aliases.
    scroll = {
        "static": "off",
        "fixed": "off",
        "none": "off",
        "no": "off",
        "false": "off",
        "stop": "off",
        "disabled": "off",
        "静态": "off",
        "固定": "off",
        "关闭": "off",
        "停止": "off",
        "marquee": "on",
        "loop": "on",
        "scrolling": "on",
        "true": "on",
        "yes": "on",
        "滚动": "on",
        "轮播": "on",
    }.get(scroll, scroll)
    if scroll in {"auto", "off", "on"}:
        style["scroll"] = scroll

    return style


#: Common Chinese colour names an instruction like "标题改成红色" reaches us
#: with — mapped to palette-consistent hexes so the banner colour channel is
#: reachable in the user's own words, not just CSS vocabulary.
_CHINESE_COLOR_NAMES = {
    "红": "#ef4444",
    "红色": "#ef4444",
    "橙": "#fb923c",
    "橙色": "#fb923c",
    "黄": "#facc15",
    "黄色": "#facc15",
    "金": "#fbbf24",
    "金色": "#fbbf24",
    "绿": "#34d399",
    "绿色": "#34d399",
    "青": "#22d3ee",
    "青色": "#22d3ee",
    "蓝": "#3b82f6",
    "蓝色": "#3b82f6",
    "紫": "#a78bfa",
    "紫色": "#a78bfa",
    "粉": "#f472b6",
    "粉色": "#f472b6",
    "白": "#ffffff",
    "白色": "#ffffff",
}


def sanitize_screen_title_color(raw: Any) -> str:
    """One colour token for the screen banner: hex / CSS name / 中文色名."""
    text = str(raw or "").strip()
    if not text:
        return ""
    mapped = _CHINESE_COLOR_NAMES.get(text)
    if mapped:
        return mapped
    token = safe_visual_token(text, max_length=20)
    if token and _ACCENT_COLOR_RE.match(token):
        return token
    return ""


def sanitize_screen_title_style(raw_style: Any) -> dict[str, Any]:
    """Whitelist-sanitize the screen banner style (patch op
    ``setScreenTitleStyle``). Same philosophy as component styles: enums,
    clamped numbers and a strict colour token — never raw CSS. Unknown or
    invalid fields are dropped; an empty dict means "nothing usable".
    """
    if not isinstance(raw_style, Mapping):
        # tolerate a bare colour string ("红色" / "#f00")
        color = sanitize_screen_title_color(raw_style)
        return {"color": color} if color else {}
    style: dict[str, Any] = {}
    color = sanitize_screen_title_color(raw_style.get("color"))
    if color:
        style["color"] = color
    size_scale = _clamp_number(raw_style.get("sizeScale"), 0.5, 2.0)
    if size_scale is not None:
        style["sizeScale"] = round(float(size_scale), 2)
    emphasis = str(raw_style.get("emphasis") or "").strip()
    if emphasis in ALLOWED_EMPHASIS:
        style["emphasis"] = emphasis
    return style


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

    blueprint = sanitize_blueprint(raw_visual_spec.get("blueprint"))
    if blueprint:
        visual_spec["blueprint"] = blueprint

    style = sanitize_component_style(raw_visual_spec.get("style"))
    if style:
        visual_spec["style"] = style

    return visual_spec
