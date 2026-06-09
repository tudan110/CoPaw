import assert from "node:assert/strict";
import test from "node:test";
import { computeStageTransform } from "./layout.ts";

test("contain: scales to fit and centers, never overflows", () => {
  const t = computeStageTransform({ designWidth: 1920, designHeight: 1080 }, { width: 960, height: 540 }, "contain");
  assert.equal(t.scale, 0.5);
  assert.equal(t.offsetX, 0);
  assert.equal(t.offsetY, 0);
});

test("contain: letterboxes the shorter axis (centered)", () => {
  const t = computeStageTransform({ designWidth: 1920, designHeight: 1080 }, { width: 1920, height: 1080 + 200 }, "contain");
  assert.equal(t.scale, 1);
  assert.equal(t.offsetY, 100); // (1280-1080)/2
});

test("cover: fills viewport (may crop), scale uses max ratio", () => {
  const t = computeStageTransform({ designWidth: 1920, designHeight: 1080 }, { width: 1920, height: 1280 }, "cover");
  assert.equal(Math.round(t.scale * 1000), Math.round((1280 / 1080) * 1000));
});
