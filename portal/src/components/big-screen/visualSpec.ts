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
