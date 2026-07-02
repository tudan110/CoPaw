import assert from "node:assert/strict";
import test from "node:test";
import {
  LAYOUT_MARGIN,
  GRID_COLS,
  gridToPx,
  pxToGrid,
} from "./gridGeometry.ts";

const DESIGN = { designWidth: 1920, designHeight: 1080 };

test("gridToPx: full-width component spans the whole grid minus margins", () => {
  const rect = gridToPx({ x: 0, y: 0, w: GRID_COLS, h: GRID_COLS }, DESIGN);
  assert.equal(rect.x, LAYOUT_MARGIN);
  assert.equal(rect.y, LAYOUT_MARGIN);
  assert.equal(rect.w, DESIGN.designWidth - 2 * LAYOUT_MARGIN);
  assert.equal(rect.h, DESIGN.designHeight - 2 * LAYOUT_MARGIN);
});

test("gridToPx: two components side by side sum to the full content width", () => {
  const left = gridToPx({ x: 0, y: 0, w: 6, h: 4 }, DESIGN);
  const right = gridToPx({ x: 6, y: 0, w: 6, h: 4 }, DESIGN);
  assert.equal(left.x, LAYOUT_MARGIN);
  assert.equal(right.x, left.x + left.w);
  assert.equal(
    right.x + right.w,
    DESIGN.designWidth - LAYOUT_MARGIN,
  );
});

test("gridToPx: clamps negative position and sub-1 size", () => {
  const rect = gridToPx({ x: -5, y: -5, w: 0, h: -2 }, DESIGN);
  assert.equal(rect.x, LAYOUT_MARGIN); // Math.max(0, -5) -> 0
  assert.equal(rect.y, LAYOUT_MARGIN);
  const colW = (DESIGN.designWidth - 2 * LAYOUT_MARGIN) / GRID_COLS;
  const rowH = (DESIGN.designHeight - 2 * LAYOUT_MARGIN) / GRID_COLS;
  assert.equal(rect.w, colW); // Math.max(1, 0) -> 1 col
  assert.equal(rect.h, rowH); // Math.max(1, -2) -> 1 row
});

test("pxToGrid: inverts gridToPx exactly for integer grid coords", () => {
  const original = { x: 3, y: 2, w: 6, h: 4 };
  const rect = gridToPx(original, DESIGN);
  const back = pxToGrid(rect, DESIGN);
  assert.equal(back.x, original.x);
  assert.equal(back.y, original.y);
  assert.equal(back.w, original.w);
  assert.equal(back.h, original.h);
});

test("pxToGrid: round-trips for every corner and a mid-grid position", () => {
  for (const lp of [
    { x: 0, y: 0, w: 1, h: 1 },
    { x: 11, y: 7, w: 1, h: 1 },
    { x: 6, y: 0, w: 6, h: 4 },
    { x: 0, y: 0, w: 12, h: 12 },
  ]) {
    const back = pxToGrid(gridToPx(lp, DESIGN), DESIGN);
    assert.equal(back.x, lp.x, `x for ${JSON.stringify(lp)}`);
    assert.equal(back.y, lp.y, `y for ${JSON.stringify(lp)}`);
    assert.equal(back.w, lp.w, `w for ${JSON.stringify(lp)}`);
    assert.equal(back.h, lp.h, `h for ${JSON.stringify(lp)}`);
  }
});

test("pxToGrid: reports fractional grid units for content-sized (non-grid-aligned) rects", () => {
  // This is the whole point of the fix: an auto-laid-out component that
  // was never pinned to grid coordinates still gets a truthful (possibly
  // fractional) grid-unit equivalent, rather than being forced onto the
  // nearest integer column.
  const colW = (DESIGN.designWidth - 2 * LAYOUT_MARGIN) / GRID_COLS;
  const rect = {
    x: LAYOUT_MARGIN,
    y: LAYOUT_MARGIN,
    w: colW * 5.5, // half a column short of 6 — auto-layout centered it
    h: colW * 3,
  };
  const grid = pxToGrid(rect, DESIGN);
  assert.equal(grid.x, 0);
  assert.ok(Math.abs(grid.w - 5.5) < 1e-9);
});

test("pxToGrid: two components whose rendered widths do NOT sum to 12 columns are reported honestly", () => {
  // Reproduces the reported bug scenario: two auto-laid-out components
  // side by side, each centered with whitespace rather than stretched to
  // fill the row, so their true rendered widths sum to less than the full
  // 12-column grid. The whole point of renderedPosition is that this is
  // now visible to the model instead of assumed away.
  const colW = (DESIGN.designWidth - 2 * LAYOUT_MARGIN) / GRID_COLS;
  const a = pxToGrid(
    { x: LAYOUT_MARGIN + 20, y: LAYOUT_MARGIN, w: colW * 4, h: colW * 3 },
    DESIGN,
  );
  const b = pxToGrid(
    {
      x: LAYOUT_MARGIN + colW * 6 + 20,
      y: LAYOUT_MARGIN,
      w: colW * 4,
      h: colW * 3,
    },
    DESIGN,
  );
  assert.ok(a.w + b.w < 12, "combined width should read as less than a full row");
});
