import type { VisualSpec } from "./types.ts";

const KINDS = new Set(["risk-field", "signal-stream", "timeline", "heatmap-matrix", "metric-cluster"]);
const MOTIONS = new Set(["none", "pulse", "scan", "flow", "stagger"]);
const DENSITIES = new Set(["compact", "balanced", "showcase"]);
const LAYOUTS = new Set(["grid", "focus", "split", "timeline", "matrix", "flow"]);
const COMPS = new Set(["primary", "secondary", "supporting"]);
const BAD = ["<", ">", "script", "javascript:", "data:", "vbscript:", "onerror", "onclick", "style=", "expression(", "http://", "https://", "&#"];

export function safeToken(raw: unknown, maxLen = 40): string {
  const s = String(raw ?? "").slice(0, maxLen);
  const low = s.toLowerCase();
  if (BAD.some((b) => low.includes(b))) return "";
  return /^[\w一-龥.\- ]*$/.test(s) ? s : "";
}

export function visualSpecClassTokens(vs: VisualSpec | undefined): string[] {
  if (!vs) return [];
  const out: string[] = [];
  if (vs.kind && KINDS.has(vs.kind)) out.push(`bs-kind-${vs.kind}`);
  if (vs.motion && MOTIONS.has(vs.motion)) out.push(`bs-motion-${vs.motion}`);
  if (vs.density && DENSITIES.has(vs.density)) out.push(`bs-density-${vs.density}`);
  if (vs.layoutPattern && LAYOUTS.has(vs.layoutPattern)) out.push(`bs-layout-${vs.layoutPattern}`);
  if (vs.composition && COMPS.has(vs.composition)) out.push(`bs-comp-${vs.composition}`);
  if (vs.style?.emphasis === "strong") out.push("bs-emphasis-strong");
  return out;
}

/** Screen banner style (patch op setScreenTitleStyle) — sanitized upstream,
 *  re-checked here (defence in depth on an adapted payload). */
export interface ScreenTitleStyle {
  color?: string;
  sizeScale?: number;
  emphasis?: string;
}

const TITLE_BASE_FONT = 34;
const TITLE_COLOR_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$|^[a-zA-Z]{3,20}$/;

/**
 * Inline CSS for the screen title banner. The default look is a gradient
 * text (background-clip) — an explicit color must disable the gradient and
 * the transparent fill or it would be invisible.
 */
export function screenTitleCss(
  ts: ScreenTitleStyle | undefined,
): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (!ts) return out;
  const scale = Number(ts.sizeScale);
  if (Number.isFinite(scale) && scale > 0) {
    const clamped = Math.min(2, Math.max(0.5, scale));
    out.fontSize = Math.round(TITLE_BASE_FONT * clamped);
  }
  const color = String(ts.color ?? "").trim();
  if (color && TITLE_COLOR_RE.test(color)) {
    out.background = "none";
    out.WebkitTextFillColor = color;
    out.color = color;
    out.textShadow = `0 0 24px ${color}40`;
  }
  if (ts.emphasis === "strong") {
    const glow = color && TITLE_COLOR_RE.test(color) ? color : "#22d3ee";
    out.textShadow = `0 0 14px ${glow}, 0 0 42px ${glow}66`;
  }
  return out;
}

/**
 * Marquee-or-static decision for row widgets (table / alarm stream).
 * An explicit style wins; "auto" keeps the legacy row-count threshold.
 * A hardcoded marquee was an uncontrollable element — "不要滚动" must be
 * expressible per component.
 */
export function resolveScrollMode(
  style: { scroll?: string } | undefined,
  rowCount: number,
  autoThreshold: number,
): "marquee" | "static" {
  const mode = String(style?.scroll ?? "auto");
  if (mode === "off") return "static";
  if (mode === "on") return rowCount > 0 ? "marquee" : "static";
  return rowCount > autoThreshold ? "marquee" : "static";
}
