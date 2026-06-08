import assert from "node:assert/strict";
import test from "node:test";
import { computeAutoLayout, type LayoutItem } from "./autoLayout.ts";

const CANVAS = { width: 1920, height: 1080, margin: 24, gutter: 16 };
const EPS = 0.5;

function items(n: number, weights?: number[]): LayoutItem[] {
  return Array.from({ length: n }, (_, i) => ({ id: `c${i}`, weight: weights?.[i] }));
}
const area = (r: { w: number; h: number }) => r.w * r.h;
function overlaps(a: { x: number; y: number; w: number; h: number }, b: typeof a) {
  const ix = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const iy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return ix > EPS && iy > EPS;
}

for (const n of [1, 2, 3, 5, 7, 12, 15, 21]) {
  test(`n=${n}: in-bounds, no overlap, fills canvas, ids preserved`, () => {
    const rects = computeAutoLayout(items(n), CANVAS);
    assert.equal(rects.length, n, "one rect per item");
    assert.deepEqual(
      rects.map((r) => r.id).sort(),
      items(n).map((i) => i.id).sort(),
      "ids preserved",
    );

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
        assert.ok(!overlaps(rects[i], rects[j]), `overlap ${rects[i].id}/${rects[j].id}`);

    const inner = (CANVAS.width - 2 * m) * (CANVAS.height - 2 * m);
    const used = rects.reduce((s, r) => s + area(r), 0);
    assert.ok(used / inner > 0.7, `coverage ${(used / inner).toFixed(2)} too low`);

    const minX = Math.min(...rects.map((r) => r.x));
    const minY = Math.min(...rects.map((r) => r.y));
    const maxX = Math.max(...rects.map((r) => r.x + r.w));
    const maxY = Math.max(...rects.map((r) => r.y + r.h));
    assert.ok(minX <= m + EPS, `bbox left ${minX}`);
    assert.ok(minY <= m + EPS, `bbox top ${minY}`);
    assert.ok(maxX >= CANVAS.width - m - EPS, `bbox right ${maxX}`);
    assert.ok(maxY >= CANVAS.height - m - EPS, `bbox bottom ${maxY}`);
  });
}

test("higher weight → wider + larger area within a row", () => {
  const rects = computeAutoLayout([{ id: "big", weight: 3 }, { id: "small", weight: 1 }], CANVAS);
  const big = rects.find((r) => r.id === "big")!;
  const small = rects.find((r) => r.id === "small")!;
  assert.ok(big.w > small.w, "heavier is wider");
  assert.ok(area(big) > area(small), "heavier has more area");
});

test("deterministic: same input → identical output", () => {
  assert.deepEqual(computeAutoLayout(items(9), CANVAS), computeAutoLayout(items(9), CANVAS));
});

test("empty input → empty output", () => {
  assert.deepEqual(computeAutoLayout([], CANVAS), []);
});

test("missing / zero / negative weights stay finite and positive-sized", () => {
  const rects = computeAutoLayout([{ id: "a" }, { id: "b", weight: 0 }, { id: "c", weight: -5 }], CANVAS);
  for (const r of rects) {
    assert.ok(Number.isFinite(r.x) && Number.isFinite(r.w), `${r.id} finite`);
    assert.ok(r.w > 0 && r.h > 0, `${r.id} positive`);
  }
});
