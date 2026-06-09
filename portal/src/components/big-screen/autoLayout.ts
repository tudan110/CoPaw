/**
 * Auto-layout engine — turns N weighted components into gap-free positions on
 * the design canvas. This is the geometric half of L3: the LLM decides *what*
 * and *how important* (weights); this code decides *where*, and guarantees the
 * result fills the canvas with no overlaps and nothing out of bounds — for any
 * component count. Pure + dependency-free so it is unit-testable in isolation.
 *
 * Strategy: weighted justified rows. Pick a column count that keeps cells
 * roughly `targetAspect` wide:tall (so few items → big cards, many items →
 * auto-dense grid), split items into rows in reading order, size each item's
 * width by its weight, and normalize every row to fill the width and all rows
 * to fill the height.
 */

export interface LayoutItem {
  id: string;
  /** Relative importance → relative size. Default 1. <=0 / non-finite coerced. */
  weight?: number;
}

export interface AutoLayoutCanvas {
  width: number;
  height: number;
  /** Outer margin in design px. Default 24. */
  margin?: number;
  /** Gap between panels in design px. Default 16. */
  gutter?: number;
  /** Desired cell width:height ratio used to pick the column count. Default 1.5. */
  targetAspect?: number;
}

export interface LayoutRect {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

function weightOf(it: LayoutItem): number {
  const w = it.weight ?? 1;
  return Number.isFinite(w) && w > 0 ? w : 0.0001;
}

export function computeAutoLayout(
  items: LayoutItem[],
  canvas: AutoLayoutCanvas,
): LayoutRect[] {
  const n = items.length;
  if (n === 0) return [];

  const margin = canvas.margin ?? 24;
  const gutter = canvas.gutter ?? 16;
  const targetAspect = canvas.targetAspect ?? 1.5;
  const innerW = canvas.width - 2 * margin;
  const innerH = canvas.height - 2 * margin;

  // Column count that makes cells ~targetAspect; derive rows from it.
  let cols = Math.round(Math.sqrt((n * innerW) / (innerH * targetAspect)));
  cols = Math.max(1, Math.min(cols, n));
  const rows = Math.ceil(n / cols);

  // Split into rows in reading order; earlier rows absorb the remainder.
  const perRow = Math.floor(n / rows);
  const rem = n % rows;

  // Even row heights that exactly fill innerH including inter-row gutters.
  const rowH = (innerH - gutter * (rows - 1)) / rows;

  const rects: LayoutRect[] = [];
  let idx = 0;
  for (let r = 0; r < rows; r++) {
    const count = perRow + (r < rem ? 1 : 0);
    const row = items.slice(idx, idx + count);
    idx += count;

    const y = margin + r * (rowH + gutter);
    const availW = innerW - gutter * (row.length - 1);
    const totalW = row.reduce((s, it) => s + weightOf(it), 0);

    let x = margin;
    for (const it of row) {
      const w = availW * (weightOf(it) / totalW);
      rects.push({ id: it.id, x, y, w, h: rowH });
      x += w + gutter;
    }
  }
  return rects;
}
