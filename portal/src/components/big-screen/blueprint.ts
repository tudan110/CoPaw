/**
 * Blueprint — the generative composition grammar for `composed` widgets.
 *
 * Frontend mirror of the backend whitelist in
 * src/qwenpaw/extensions/ai_big_screen/sanitizer.py (sanitize_blueprint).
 * The LLM declares a panel as controlled atoms; this module validates the
 * declaration into typed structures and the ComposedWidget interprets it.
 * Defense in depth: even though the backend sanitizes, the renderer never
 * trusts incoming specs.
 */

export type BlueprintLayout =
  | "rows"
  | "columns"
  | "grid"
  | "overlay"
  | "radial";
export type BlueprintGap = "s" | "m" | "l";

export interface ValueElement {
  kind: "value";
  bind: Record<string, string>;
  style?: "plain" | "flip" | "glow";
  size?: "m" | "l" | "xl";
}
export interface ChartElement {
  kind: "chart";
  chart: "line" | "area" | "bar" | "donut" | "gauge" | "radar" | "heatmap";
  bind?: Record<string, string>;
}
export interface ListElement {
  kind: "list";
  bind?: Record<string, string>;
  style?: "stream" | "rank" | "plain";
  limit: number;
}
export interface BadgeElement {
  kind: "badge" | "label";
  text?: string;
  tone?: string;
  bind?: Record<string, string>;
}
export interface ProgressElement {
  kind: "progress";
  bind: Record<string, string>;
  style?: "bar" | "ring" | "liquid";
  max?: number;
}
export interface SparklineElement {
  kind: "sparkline";
  bind: Record<string, string>;
}
export interface GroupElement {
  kind: "group";
  layout: BlueprintLayout;
  gap?: BlueprintGap;
  cells: BlueprintCell[];
}

export type BlueprintElement =
  | ValueElement
  | ChartElement
  | ListElement
  | BadgeElement
  | ProgressElement
  | SparklineElement
  | GroupElement;

export interface BlueprintCell {
  span: number;
  element: BlueprintElement;
}

export interface Blueprint {
  layout: BlueprintLayout;
  gap?: BlueprintGap;
  cells: BlueprintCell[];
}

const LAYOUTS = new Set(["rows", "columns", "grid", "overlay", "radial"]);
const GAPS = new Set(["s", "m", "l"]);
const VALUE_STYLES = new Set(["plain", "flip", "glow"]);
const VALUE_SIZES = new Set(["m", "l", "xl"]);
const CHARTS = new Set([
  "line",
  "area",
  "bar",
  "donut",
  "gauge",
  "radar",
  "heatmap",
]);
const LIST_STYLES = new Set(["stream", "rank", "plain"]);
const PROGRESS_STYLES = new Set(["bar", "ring", "liquid"]);
const TONES = new Set(["critical", "high", "medium", "normal", "cool", "warm"]);
const BIND_KEYS: Record<string, Set<string>> = {
  value: new Set(["value", "unit", "label", "prefix"]),
  chart: new Set(["x", "y", "name", "value"]),
  list: new Set(["title", "message", "time", "tone", "value", "name"]),
  badge: new Set(["text"]),
  progress: new Set(["value", "max"]),
  sparkline: new Set(["x", "y"]),
};
const MAX_CELLS = 12;
const MAX_DEPTH = 2;
const MAX_LIST_LIMIT = 20;
const BAD_FRAGMENTS = [
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
];

function safeText(raw: unknown, maxLength: number): string {
  const token = String(raw ?? "")
    .trim()
    .slice(0, maxLength);
  if (!token) return "";
  const lowered = token.toLowerCase();
  if (BAD_FRAGMENTS.some((b) => lowered.includes(b))) return "";
  return token;
}

function clampInt(raw: unknown, fallback: number, lo: number, hi: number) {
  const n = Number(raw);
  const v = Number.isFinite(n) ? Math.trunc(n) : fallback;
  return Math.max(lo, Math.min(hi, v));
}

function normalizeBind(
  kind: string,
  raw: unknown,
): Record<string, string> {
  const allowed = BIND_KEYS[kind];
  if (!allowed || typeof raw !== "object" || raw === null) return {};
  const bind: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!allowed.has(key)) continue;
    const field = safeText(value, 80);
    if (field) bind[key] = field;
  }
  return bind;
}

function normalizeElement(
  raw: unknown,
  depth: number,
): BlueprintElement | null {
  if (typeof raw !== "object" || raw === null) return null;
  const obj = raw as Record<string, unknown>;
  const kind = String(obj["kind"] ?? "").trim();

  if (kind === "group") {
    if (depth >= MAX_DEPTH) return null;
    const nested = normalizeBlueprint(obj, depth + 1);
    if (!nested) return null;
    return { kind: "group", ...nested };
  }

  const bind = normalizeBind(kind, obj["bind"]);
  const style = String(obj["style"] ?? "").trim();

  switch (kind) {
    case "value": {
      if (!bind["value"]) return null;
      const el: ValueElement = { kind, bind };
      if (VALUE_STYLES.has(style)) el.style = style as ValueElement["style"];
      const size = String(obj["size"] ?? "").trim();
      if (VALUE_SIZES.has(size)) el.size = size as ValueElement["size"];
      return el;
    }
    case "chart": {
      const chart = String(obj["chart"] ?? "").trim();
      if (!CHARTS.has(chart)) return null;
      return {
        kind,
        chart: chart as ChartElement["chart"],
        bind,
      };
    }
    case "list": {
      const el: ListElement = {
        kind,
        bind,
        limit: clampInt(obj["limit"], 6, 1, MAX_LIST_LIMIT),
      };
      if (LIST_STYLES.has(style)) el.style = style as ListElement["style"];
      return el;
    }
    case "progress": {
      if (!bind["value"]) return null;
      const el: ProgressElement = { kind, bind };
      if (PROGRESS_STYLES.has(style)) {
        el.style = style as ProgressElement["style"];
      }
      const max = Number(obj["max"]);
      if (Number.isFinite(max) && max > 0) el.max = max;
      return el;
    }
    case "sparkline": {
      if (!bind["y"]) return null;
      return { kind, bind };
    }
    case "badge":
    case "label": {
      const text = safeText(obj["text"], 60);
      const tone = String(obj["tone"] ?? "").trim();
      if (!text && Object.keys(bind).length === 0) return null;
      const el: BadgeElement = { kind };
      if (text) el.text = text;
      if (TONES.has(tone)) el.tone = tone;
      if (Object.keys(bind).length > 0) el.bind = bind;
      return el;
    }
    default:
      return null;
  }
}

export function normalizeBlueprint(
  raw: unknown,
  depth = 0,
): Blueprint | null {
  if (typeof raw !== "object" || raw === null) return null;
  const obj = raw as Record<string, unknown>;
  const layoutRaw = String(obj["layout"] ?? "").trim();
  const layout = (
    LAYOUTS.has(layoutRaw) ? layoutRaw : "rows"
  ) as BlueprintLayout;
  const cellsRaw = obj["cells"];
  if (!Array.isArray(cellsRaw)) return null;
  const cells: BlueprintCell[] = [];
  for (const cellRaw of cellsRaw.slice(0, MAX_CELLS)) {
    if (typeof cellRaw !== "object" || cellRaw === null) continue;
    const cellObj = cellRaw as Record<string, unknown>;
    const element = normalizeElement(cellObj["element"], depth);
    if (!element) continue;
    cells.push({
      span: clampInt(cellObj["span"], 1, 1, 4),
      element,
    });
  }
  if (cells.length === 0) return null;
  const blueprint: Blueprint = { layout, cells };
  const gap = String(obj["gap"] ?? "").trim();
  if (GAPS.has(gap)) blueprint.gap = gap as BlueprintGap;
  return blueprint;
}
