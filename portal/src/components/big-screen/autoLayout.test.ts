import assert from "node:assert/strict";
import test from "node:test";
import { computeAutoLayout, type LayoutItem } from "./autoLayout.ts";

const CANVAS = { width: 1920, height: 1080, margin: 24, gutter: 16 };
const EPS = 0.5;

/** Sparse cards: small width units, short natural height. */
function smallItems(n: number): LayoutItem[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `c${i}`,
    widthUnits: 1,
    naturalHeight: 180,
  }));
}
/** Big cards: wide + tall, enough of them to overflow the canvas. */
function bigItems(n: number): LayoutItem[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `c${i}`,
    widthUnits: 2,
    naturalHeight: 360,
  }));
}

const area = (r: { w: number; h: number }) => r.w * r.h;
function overlaps(
  a: { x: number; y: number; w: number; h: number },
  b: typeof a,
) {
  const ix = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const iy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return ix > EPS && iy > EPS;
}
function assertInBoundsNoOverlap(rects: ReturnType<typeof computeAutoLayout>) {
  const m = CANVAS.margin;
  for (const r of rects) {
    assert.ok(r.w > 0 && r.h > 0, `${r.id} positive size`);
    assert.ok(r.x >= m - EPS, `${r.id} left`);
    assert.ok(r.y >= m - EPS, `${r.id} top`);
    assert.ok(r.x + r.w <= CANVAS.width - m + EPS, `${r.id} right`);
    assert.ok(r.y + r.h <= CANVAS.height - m + EPS, `${r.id} bottom`);
  }
  for (let i = 0; i < rects.length; i++)
    for (let j = i + 1; j < rects.length; j++)
      assert.ok(
        !overlaps(rects[i], rects[j]),
        `overlap ${rects[i].id}/${rects[j].id}`,
      );
}

// Core invariants hold for any count and either density.
for (const n of [1, 2, 3, 5, 7, 12, 15, 21]) {
  test(`n=${n}: in-bounds, no overlap, ids preserved (small + big)`, () => {
    for (const set of [smallItems(n), bigItems(n)]) {
      const rects = computeAutoLayout(set, CANVAS);
      assert.equal(rects.length, n, "one rect per item");
      assert.deepEqual(
        rects.map((r) => r.id).sort(),
        set.map((i) => i.id).sort(),
        "ids preserved",
      );
      assertInBoundsNoOverlap(rects);
    }
  });
}

test("sparse: cards stay compact and the block leaves vertical whitespace", () => {
  // 3 small cards (the user's screenshot scenario) must NOT fill the canvas.
  const rects = computeAutoLayout(smallItems(3), CANVAS);
  const m = CANVAS.margin;
  const innerH = CANVAS.height - 2 * m;

  // every card is capped near its natural height — no half-screen voids
  for (const r of rects) assert.ok(r.h <= 200 + EPS, `${r.id} height ${r.h}`);

  // used vertical extent is well short of the canvas → honest whitespace
  const top = Math.min(...rects.map((r) => r.y));
  const bottom = Math.max(...rects.map((r) => r.y + r.h));
  assert.ok(bottom - top < innerH * 0.6, "sparse block is short");

  // and the block is vertically centered (roughly equal margins)
  const above = top - m;
  const below = CANVAS.height - m - bottom;
  assert.ok(Math.abs(above - below) < EPS + 1, "block vertically centered");
});

test("sparse single row is horizontally centered, not stretched", () => {
  const rects = computeAutoLayout(smallItems(3), CANVAS);
  const m = CANVAS.margin;
  const left = Math.min(...rects.map((r) => r.x));
  const right = Math.max(...rects.map((r) => r.x + r.w));
  // not pinned to the full width (centered with side whitespace)
  assert.ok(left > m + EPS, "left whitespace present");
  assert.ok(right < CANVAS.width - m - EPS, "right whitespace present");
  const leftGap = left - m;
  const rightGap = CANVAS.width - m - right;
  assert.ok(Math.abs(leftGap - rightGap) < EPS + 1, "row centered");
});

test("rich/overflow: many big cards scale to fit, never overflow the canvas", () => {
  const rects = computeAutoLayout(bigItems(12), CANVAS);
  assertInBoundsNoOverlap(rects);
  // overflow path must actually use most of the canvas (no giant gaps)
  const m = CANVAS.margin;
  const innerH = CANVAS.height - 2 * m;
  const top = Math.min(...rects.map((r) => r.y));
  const bottom = Math.max(...rects.map((r) => r.y + r.h));
  assert.ok(bottom - top > innerH * 0.85, "overflow block fills height");
});

test("taller naturalHeight → taller rect", () => {
  const [shortR] = computeAutoLayout(
    [{ id: "x", widthUnits: 1, naturalHeight: 160 }],
    CANVAS,
  );
  const [tallR] = computeAutoLayout(
    [{ id: "x", widthUnits: 1, naturalHeight: 400 }],
    CANVAS,
  );
  assert.ok(tallR.h > shortR.h, "bigger naturalHeight is taller");
});

test("wider widthUnits → wider rect within a shared row", () => {
  const rects = computeAutoLayout(
    [
      { id: "big", widthUnits: 2, naturalHeight: 200 },
      { id: "small", widthUnits: 1, naturalHeight: 200 },
    ],
    CANVAS,
  );
  const big = rects.find((r) => r.id === "big")!;
  const small = rects.find((r) => r.id === "small")!;
  assert.equal(big.y, small.y, "same row");
  assert.ok(big.w > small.w, "more units is wider");
});

test("legacy weight alias still drives width", () => {
  const rects = computeAutoLayout(
    [
      { id: "big", weight: 2, naturalHeight: 200 },
      { id: "small", weight: 1, naturalHeight: 200 },
    ],
    CANVAS,
  );
  const big = rects.find((r) => r.id === "big")!;
  const small = rects.find((r) => r.id === "small")!;
  assert.ok(big.w > small.w, "weight alias respected");
});

test("deterministic: same input → identical output", () => {
  assert.deepEqual(
    computeAutoLayout(smallItems(9), CANVAS),
    computeAutoLayout(smallItems(9), CANVAS),
  );
});

test("empty input → empty output", () => {
  assert.deepEqual(computeAutoLayout([], CANVAS), []);
});

test("missing / zero / negative sizes stay finite and positive", () => {
  const rects = computeAutoLayout(
    [
      { id: "a" },
      { id: "b", widthUnits: 0, naturalHeight: 0 },
      { id: "c", widthUnits: -5, naturalHeight: -10 },
    ],
    CANVAS,
  );
  for (const r of rects) {
    assert.ok(Number.isFinite(r.x) && Number.isFinite(r.w), `${r.id} finite`);
    assert.ok(r.w > 0 && r.h > 0, `${r.id} positive`);
  }
});
