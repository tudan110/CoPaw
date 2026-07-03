import assert from "node:assert/strict";
import test from "node:test";
import { MIN_BAND_HEIGHT, pickAutoBand } from "./autoLayoutBands.ts";
import { LAYOUT_MARGIN } from "./gridGeometry.ts";

const DESIGN = { designWidth: 1920, designHeight: 1080 };
const TOP = LAYOUT_MARGIN;
const BOTTOM = DESIGN.designHeight - LAYOUT_MARGIN;

test("no reserved rects → full canvas band", () => {
  const band = pickAutoBand([], DESIGN);
  assert.equal(band.y, TOP);
  assert.equal(band.height, BOTTOM - TOP);
});

test("title band only → content flows right below it", () => {
  const band = pickAutoBand([{ x: TOP, y: 0, w: 1872, h: 96 }], DESIGN);
  assert.equal(band.y, 96);
  assert.equal(band.height, BOTTOM - 96);
});

test("title band + low pinned component → picks the middle gap (the vanish bug)", () => {
  // Reproduces the reported scenario: screen title at the top plus 工单信息
  // pinned at grid y:7 h:5 (≈626..1056px). The old above/below heuristic
  // computed above≈-24 / below≈0 and exiled every auto component to
  // y≥1056 — below the canvas. The middle gap (96..626) is the right band.
  const band = pickAutoBand(
    [
      { x: TOP, y: 0, w: 1872, h: 96 }, // title band
      { x: 356, y: 626, w: 1092, h: 430 }, // pinned near the bottom
    ],
    DESIGN,
  );
  assert.equal(band.y, 96);
  assert.equal(band.height, 626 - 96);
  // The whole point: the band stays on-canvas.
  assert.ok(band.y + band.height <= BOTTOM);
});

test("reserved covering nearly everything → clamped on-canvas, never exiled", () => {
  const band = pickAutoBand(
    [{ x: TOP, y: 0, w: 1872, h: DESIGN.designHeight }],
    DESIGN,
  );
  assert.ok(band.y >= TOP);
  assert.ok(
    band.y <= BOTTOM - MIN_BAND_HEIGHT,
    `band.y=${band.y} must leave ≥${MIN_BAND_HEIGHT}px on canvas`,
  );
  assert.ok(band.height >= MIN_BAND_HEIGHT);
});

test("overlapping reserved rects are merged before gap search", () => {
  const band = pickAutoBand(
    [
      { x: 0, y: 100, w: 500, h: 300 },
      { x: 600, y: 250, w: 500, h: 300 }, // overlaps the first vertically
    ],
    DESIGN,
  );
  // merged interval = 100..550 → gaps are 24..100 (76px) and 550..1056
  assert.equal(band.y, 550);
  assert.equal(band.height, BOTTOM - 550);
});

test("gap between two pinned bands wins when it is the largest", () => {
  const band = pickAutoBand(
    [
      { x: 0, y: TOP, w: 500, h: 200 }, // 24..224
      { x: 0, y: 900, w: 500, h: 156 }, // 900..1056
    ],
    DESIGN,
  );
  assert.equal(band.y, 224);
  assert.equal(band.height, 900 - 224);
});
