/**
 * intrinsicSize — how big a component *wants* to be, from its real content.
 *
 * The old layout sized every panel purely by `visualSpec.composition`
 * (importance) and then stretched it to fill the canvas, so an empty
 * workorder panel and a 2-node topology each got half the screen. This
 * derives a content-aware size instead: a single KPI or an empty/failed
 * note is a small card; a table with many rows is tall; a chart is wide.
 * The auto-layout engine consumes these to pack panels to their content
 * and leave honest whitespace when data is sparse (never a half-screen void).
 *
 * Pure + JSX-free so node:test can import it without transformation.
 * Units are design px on the 1920×1080 canvas; one width unit ≈ UNIT_PX.
 */

import { resolveComponentType } from "./registry.ts";
import type { ScreenComponent, VisualSpec } from "./types.ts";

export interface IntrinsicSize {
  /** Relative width appetite; one unit ≈ UNIT_PX design px. */
  widthUnits: number;
  /** Natural height in design px the content reads well at. */
  naturalHeight: number;
}

export const UNIT_PX = 300;

const WIDTH_MIN = 260;
const WIDTH_MAX = 1100;
const HEIGHT_MIN = 140;
const HEIGHT_MAX = 520;

/** Types that fill their box gracefully at any size (charts, maps, graph). */
const FILL_CHART = new Set([
  "line-chart",
  "bar-chart",
  "area-chart",
  "heatmap",
  "bar3d",
  "map-fly",
]);
const ROUND_CHART = new Set(["donut", "radar"]);
/** Row-based lists whose height tracks item count. */
const LIST_TYPES = new Set(["alarm-stream", "top-n", "funnel", "timeline"]);
/** Intrinsically small, single-value or text panels. */
const SMALL_TYPES = new Set([
  "metric-kpi",
  "flip-number",
  "gauge",
  "liquid-ball",
  "risk-pulse",
  "text",
]);

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function rowCount(component: ScreenComponent): number {
  const data = component.data;
  if (!data) return 0;
  return data.rows?.length ?? data.series?.length ?? data.nodes?.length ?? 0;
}

function blueprintCellCount(vs: VisualSpec | undefined): number {
  const bp = vs?.blueprint as { cells?: unknown[] } | undefined;
  return Array.isArray(bp?.cells) ? bp.cells.length : 0;
}

/** Base (pre-composition) size from type + data volume. */
function baseSize(component: ScreenComponent): IntrinsicSize {
  const type = resolveComponentType(component.type);
  const status = component.data?.sourceStatus;

  // An empty/failed panel only needs room for a one-line note.
  if (status === "empty" || status === "failed") {
    return { widthUnits: 1, naturalHeight: 150 };
  }

  if (LIST_TYPES.has(type)) {
    const rows = rowCount(component);
    return {
      widthUnits: rows >= 8 ? 2 : 1.6,
      naturalHeight: clamp(64 + rows * 30, 180, 460),
    };
  }
  if (type === "graph") {
    const nodes = component.data?.nodes?.length ?? 0;
    return nodes < 5
      ? { widthUnits: 1.4, naturalHeight: 260 }
      : { widthUnits: 2, naturalHeight: 340 };
  }
  if (FILL_CHART.has(type)) {
    return { widthUnits: 2, naturalHeight: 320 };
  }
  if (ROUND_CHART.has(type)) {
    return { widthUnits: 1.4, naturalHeight: 300 };
  }
  if (type === "composed") {
    const cells = blueprintCellCount(component.visualSpec);
    return { widthUnits: 2, naturalHeight: clamp(180 + cells * 36, 220, 420) };
  }
  if (SMALL_TYPES.has(type)) {
    return { widthUnits: 1, naturalHeight: 190 };
  }
  // unknown / fallback — a modest card
  return { widthUnits: 1, naturalHeight: 190 };
}

/** Importance multiplier — primary panels get bigger, supporting smaller. */
function compositionScale(vs: VisualSpec | undefined): {
  w: number;
  h: number;
} {
  switch (vs?.composition) {
    case "primary":
      return { w: 1.3, h: 1.2 };
    case "supporting":
      return { w: 0.85, h: 0.82 };
    default:
      return { w: 1, h: 1 };
  }
}

/** Explicit user/LLM size knob (visualSpec.style.sizeScale), clamped. */
function styleSizeScale(vs: VisualSpec | undefined): number {
  const s = vs?.style?.sizeScale;
  return typeof s === "number" && Number.isFinite(s) ? clamp(s, 0.5, 2) : 1;
}

/**
 * Content-aware size for one component, after folding in its importance and
 * any explicit sizeScale. Always finite and clamped to sane card bounds.
 */
export function intrinsicSize(component: ScreenComponent): IntrinsicSize {
  const base = baseSize(component);
  const scale = compositionScale(component.visualSpec);
  const size = styleSizeScale(component.visualSpec);
  return {
    widthUnits:
      clamp(base.widthUnits * scale.w * size * UNIT_PX, WIDTH_MIN, WIDTH_MAX) /
      UNIT_PX,
    naturalHeight: clamp(
      base.naturalHeight * scale.h * size,
      HEIGHT_MIN,
      HEIGHT_MAX,
    ),
  };
}
