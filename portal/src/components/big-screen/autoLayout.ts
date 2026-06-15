/**
 * Auto-layout engine — packs N content-sized panels onto the design canvas.
 *
 * This is the geometric half of L3: the LLM decides *what* and *how
 * important*; `intrinsicSize` turns each panel's real content into a desired
 * size; this code decides *where*. The guiding rule (chosen by the product
 * owner): **size to content, don't stretch.** Rich screens fill the canvas;
 * sparse screens cluster compact cards and leave honest whitespace — never a
 * half-screen empty box. Pure + dependency-free so it is unit-testable.
 *
 * Strategy: greedy justified rows over intrinsic sizes.
 *   1. Pack items left→right into rows until the next item's natural width
 *      would overflow (≥1 item per row) — column count adapts to content
 *      (many small cards per row, few wide charts).
 *   2. Each row's height is its tallest item (clamped) — NOT an even split.
 *   3. Per row: if the natural widths fit, place them and center the row;
 *      otherwise scale widths down to fill the row.
 *   4. Vertically: if the rows fit, center the whole block (whitespace top
 *      and bottom); otherwise scale all heights down to fit (never overflow).
 */

import { UNIT_PX } from "./intrinsicSize.ts";

export interface LayoutItem {
  id: string;
  /** Relative width appetite; one unit ≈ UNIT_PX design px. */
  widthUnits?: number;
  /** Desired height in design px. */
  naturalHeight?: number;
  /** Deprecated alias for widthUnits (kept so old callers/tests still work). */
  weight?: number;
}

export interface AutoLayoutCanvas {
  width: number;
  height: number;
  /** Outer margin in design px. Default 24. */
  margin?: number;
  /** Gap between panels in design px. Default 16. */
  gutter?: number;
}

export interface LayoutRect {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

const ROW_H_MIN = 140;
const ROW_H_MAX = 520;

function widthUnitsOf(it: LayoutItem): number {
  const u = it.widthUnits ?? it.weight ?? 1;
  return Number.isFinite(u) && u > 0 ? u : 0.0001;
}

function naturalWidthOf(it: LayoutItem): number {
  return widthUnitsOf(it) * UNIT_PX;
}

function naturalHeightOf(it: LayoutItem): number {
  const h = it.naturalHeight ?? 260;
  return Number.isFinite(h) && h > 0 ? h : 260;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function computeAutoLayout(
  items: LayoutItem[],
  canvas: AutoLayoutCanvas,
): LayoutRect[] {
  const n = items.length;
  if (n === 0) return [];

  const margin = canvas.margin ?? 24;
  const gutter = canvas.gutter ?? 16;
  const innerW = canvas.width - 2 * margin;
  const innerH = canvas.height - 2 * margin;

  // 1) Greedy pack into rows by natural width (≥1 item per row).
  const rows: LayoutItem[][] = [];
  let current: LayoutItem[] = [];
  let rowWidth = 0;
  for (const it of items) {
    const w = Math.min(naturalWidthOf(it), innerW);
    const withItem = current.length === 0 ? w : rowWidth + gutter + w;
    if (current.length > 0 && withItem > innerW) {
      rows.push(current);
      current = [it];
      rowWidth = w;
    } else {
      current.push(it);
      rowWidth = withItem;
    }
  }
  if (current.length > 0) rows.push(current);

  // 2) Row heights = tallest item in the row, clamped.
  const rowHeights = rows.map((row) =>
    clamp(Math.max(...row.map(naturalHeightOf)), ROW_H_MIN, ROW_H_MAX),
  );

  // 4a) Vertical fit: center the block if it fits, else scale row heights
  // (gutters are fixed, so scale against the height available *after* them).
  const vGutters = gutter * (rows.length - 1);
  const totalRowH = rowHeights.reduce((s, h) => s + h, 0);
  const availH = innerH - vGutters;
  const vScale = totalRowH > availH ? availH / totalRowH : 1;
  const scaledRowH = rowHeights.map((h) => h * vScale);
  const scaledTotalH = scaledRowH.reduce((s, h) => s + h, 0) + vGutters;
  let y = margin + Math.max(0, (innerH - scaledTotalH) / 2);

  const rects: LayoutRect[] = [];
  rows.forEach((row, r) => {
    const h = scaledRowH[r];

    // 3) Horizontal: natural widths; center if they fit, else scale to fill.
    const naturalWs = row.map((it) => Math.min(naturalWidthOf(it), innerW));
    const gutters = gutter * (row.length - 1);
    const sumNatural = naturalWs.reduce((s, w) => s + w, 0);
    const availW = innerW - gutters;
    const hScale = sumNatural > availW ? availW / sumNatural : 1;
    const widths = naturalWs.map((w) => w * hScale);
    const usedW = widths.reduce((s, w) => s + w, 0) + gutters;

    let x = margin + Math.max(0, (innerW - usedW) / 2);
    row.forEach((it, i) => {
      rects.push({ id: it.id, x, y, w: widths[i], h });
      x += widths[i] + gutter;
    });

    y += h + gutter;
  });

  return rects;
}
