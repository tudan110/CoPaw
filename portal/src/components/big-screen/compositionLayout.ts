/**
 * Screen-level composition patterns — the deterministic half of the
 * "构图语法". The planner (LLM) picks a pattern and assigns component
 * roles (hero / support / context); this module turns that decision into
 * aligned, gutter-consistent rects. Design intelligence lives in the
 * choice, visual discipline lives here — auto box-packing never produces
 * a hero, which is exactly why screens read as "stacked blocks".
 *
 * Every function returns ``null`` when the pattern's preconditions don't
 * hold (no hero, too many rail items, …) — callers fall back to the
 * content-packing auto layout, so a bad plan degrades to the old look
 * instead of a broken one.
 *
 * JSX-free and pure so node:test can import it directly.
 */

import type { Band } from "./autoLayoutBands.ts";
import { LAYOUT_MARGIN, type DesignSize, type Rect } from "./gridGeometry.ts";

export interface PatternItem {
  id: string;
  /** hero / support / context / "" (unassigned) */
  role: string;
  /** Relative width appetite from intrinsicSize (used for proportions). */
  widthUnits: number;
  naturalHeight: number;
}

const GUTTER = LAYOUT_MARGIN;
/** Rail/strip cells thinner than this stop being readable. */
const MIN_CELL_HEIGHT = 120;
const KPI_STRIP_HEIGHT = 176;

export const PATTERNS = [
  "focus-left",
  "focus-right",
  "kpi-top",
  "balanced",
] as const;

function contentBox(design: DesignSize, band: Band) {
  return {
    x: LAYOUT_MARGIN,
    y: band.y,
    w: design.designWidth - 2 * LAYOUT_MARGIN,
    h: band.height,
  };
}

/** Stack ``items`` vertically inside the column, equal heights. */
function stackColumn(
  items: PatternItem[],
  x: number,
  y: number,
  w: number,
  h: number,
  out: Map<string, Rect>,
): boolean {
  const n = items.length;
  if (n === 0) return true;
  const cell = (h - (n - 1) * GUTTER) / n;
  if (cell < MIN_CELL_HEIGHT) return false;
  items.forEach((item, i) => {
    out.set(item.id, { x, y: y + i * (cell + GUTTER), w, h: cell });
  });
  return true;
}

/** Lay ``items`` in one row, widths proportional to widthUnits. */
function spreadRow(
  items: PatternItem[],
  x: number,
  y: number,
  w: number,
  h: number,
  out: Map<string, Rect>,
): void {
  const totalUnits = items.reduce(
    (sum, item) => sum + Math.max(0.5, item.widthUnits),
    0,
  );
  const usable = w - (items.length - 1) * GUTTER;
  let cursor = x;
  items.forEach((item, i) => {
    const cellW =
      i === items.length - 1
        ? x + w - cursor // absorb rounding, right edge stays aligned
        : (usable * Math.max(0.5, item.widthUnits)) / totalUnits;
    out.set(item.id, { x: cursor, y, w: cellW, h });
    cursor += cellW + GUTTER;
  });
}

function focusLayout(
  items: PatternItem[],
  design: DesignSize,
  band: Band,
  side: "left" | "right",
): Map<string, Rect> | null {
  const heroes = items.filter((item) => item.role === "hero");
  if (heroes.length !== 1) return null;
  const rail = items.filter((item) => item.role !== "hero");
  if (rail.length > 5) return null;
  const box = contentBox(design, band);
  const out = new Map<string, Rect>();
  const heroW = rail.length === 0 ? box.w : (box.w - GUTTER) * 0.58;
  const railW = box.w - GUTTER - heroW;
  const heroX = side === "left" ? box.x : box.x + box.w - heroW;
  const railX = side === "left" ? box.x + heroW + GUTTER : box.x;
  out.set(heroes[0].id, { x: heroX, y: box.y, w: heroW, h: box.h });
  if (!stackColumn(rail, railX, box.y, railW, box.h, out)) return null;
  return out;
}

function kpiTopLayout(
  items: PatternItem[],
  design: DesignSize,
  band: Band,
): Map<string, Rect> | null {
  const strip = items.filter((item) => item.role === "context");
  const body = items.filter((item) => item.role !== "context");
  if (strip.length < 1 || strip.length > 4) return null;
  if (body.length < 1 || body.length > 3) return null;
  const box = contentBox(design, band);
  const bodyH = box.h - KPI_STRIP_HEIGHT - GUTTER;
  if (bodyH < MIN_CELL_HEIGHT) return null;
  const out = new Map<string, Rect>();
  // equal-width strip cells keep the top row reading as one band
  const stripItems = strip.map((item) => ({ ...item, widthUnits: 1 }));
  spreadRow(stripItems, box.x, box.y, box.w, KPI_STRIP_HEIGHT, out);
  spreadRow(body, box.x, box.y + KPI_STRIP_HEIGHT + GUTTER, box.w, bodyH, out);
  return out;
}

/**
 * Compute rects for ``items`` under ``pattern`` within the free band.
 * ``null`` = pattern not applicable — caller falls back to auto layout.
 */
export function computePatternLayout(
  pattern: string,
  items: PatternItem[],
  design: DesignSize,
  band: Band,
): Map<string, Rect> | null {
  if (items.length === 0) return null;
  switch (pattern) {
    case "focus-left":
      return focusLayout(items, design, band, "left");
    case "focus-right":
      return focusLayout(items, design, band, "right");
    case "kpi-top":
      return kpiTopLayout(items, design, band);
    default:
      return null; // "balanced" and unknown → content-packing auto layout
  }
}
