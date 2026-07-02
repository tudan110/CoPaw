/**
 * Conversions between the backend's 12-col grid units (layoutPosition,
 * renderedPosition) and design-pixel rects. JSX-free and pure so node:test
 * can parse it without transformation — see registry.ts for the same
 * pattern.
 */

export const LAYOUT_MARGIN = 24;
export const GRID_COLS = 12;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DesignSize {
  designWidth: number;
  designHeight: number;
}

/** Convert a pinned 12-col grid position (backend units) to design pixels. */
export function gridToPx(
  lp: { x: number; y: number; w: number; h: number },
  design: DesignSize,
): Rect {
  const colW = (design.designWidth - 2 * LAYOUT_MARGIN) / GRID_COLS;
  const rowH = (design.designHeight - 2 * LAYOUT_MARGIN) / GRID_COLS;
  return {
    x: LAYOUT_MARGIN + Math.max(0, lp.x) * colW,
    y: LAYOUT_MARGIN + Math.max(0, lp.y) * rowH,
    w: Math.max(1, lp.w) * colW,
    h: Math.max(1, lp.h) * rowH,
  };
}

/**
 * Inverse of gridToPx — converts a design-pixel rect (however it was
 * produced: pinned grid coords, an auto-laid-out box, or an authored
 * fixture) back into 12-col grid-unit equivalents. Unlike stored
 * layoutPosition, this reflects what's actually on screen right now, so
 * results are intentionally fractional rather than clamped to integers.
 */
export function pxToGrid(
  rect: Rect,
  design: DesignSize,
): { x: number; y: number; w: number; h: number } {
  const colW = (design.designWidth - 2 * LAYOUT_MARGIN) / GRID_COLS;
  const rowH = (design.designHeight - 2 * LAYOUT_MARGIN) / GRID_COLS;
  return {
    x: (rect.x - LAYOUT_MARGIN) / colW,
    y: (rect.y - LAYOUT_MARGIN) / rowH,
    w: rect.w / colW,
    h: rect.h / rowH,
  };
}
