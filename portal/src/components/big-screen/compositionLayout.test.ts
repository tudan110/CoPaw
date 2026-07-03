import assert from "node:assert/strict";
import test from "node:test";
import { computePatternLayout } from "./compositionLayout.ts";
import { LAYOUT_MARGIN } from "./gridGeometry.ts";

const DESIGN = { designWidth: 1920, designHeight: 1080 };
const BAND = { y: 96, height: 960 };
const CONTENT_W = DESIGN.designWidth - 2 * LAYOUT_MARGIN;

function item(id: string, role: string, widthUnits = 1, naturalHeight = 300) {
  return { id, role, widthUnits, naturalHeight };
}

test("focus-left: hero owns the left 58%, rail stacks right, edges aligned", () => {
  const out = computePatternLayout(
    "focus-left",
    [item("hero", "hero", 2), item("a", "support"), item("b", "context")],
    DESIGN,
    BAND,
  );
  assert.ok(out);
  const hero = out.get("hero")!;
  const a = out.get("a")!;
  const b = out.get("b")!;
  assert.equal(hero.x, LAYOUT_MARGIN);
  assert.equal(hero.y, BAND.y);
  assert.equal(hero.h, BAND.height);
  assert.ok(Math.abs(hero.w - (CONTENT_W - 24) * 0.58) < 1e-6);
  // rail column right of the hero, right edge on the margin line
  assert.ok(a.x > hero.x + hero.w);
  assert.ok(Math.abs(a.x + a.w - (DESIGN.designWidth - LAYOUT_MARGIN)) < 1e-6);
  assert.equal(a.x, b.x);
  assert.equal(a.w, b.w);
  // rail cells share the band height with one gutter between
  assert.ok(Math.abs(a.h + b.h + 24 - BAND.height) < 1e-6);
  assert.ok(b.y > a.y);
});

test("focus-right mirrors the hero to the right edge", () => {
  const out = computePatternLayout(
    "focus-right",
    [item("hero", "hero"), item("a", "support")],
    DESIGN,
    BAND,
  );
  assert.ok(out);
  const hero = out.get("hero")!;
  const a = out.get("a")!;
  assert.ok(
    Math.abs(hero.x + hero.w - (DESIGN.designWidth - LAYOUT_MARGIN)) < 1e-6,
  );
  assert.equal(a.x, LAYOUT_MARGIN);
});

test("focus without exactly one hero → null (fallback to auto layout)", () => {
  assert.equal(
    computePatternLayout(
      "focus-left",
      [item("a", "support"), item("b", "support")],
      DESIGN,
      BAND,
    ),
    null,
  );
  assert.equal(
    computePatternLayout(
      "focus-left",
      [item("a", "hero"), item("b", "hero")],
      DESIGN,
      BAND,
    ),
    null,
  );
});

test("focus hero alone stretches the full content width", () => {
  const out = computePatternLayout(
    "focus-left",
    [item("hero", "hero")],
    DESIGN,
    BAND,
  );
  assert.ok(out);
  assert.equal(out.get("hero")!.w, CONTENT_W);
});

test("kpi-top: context strip on top, body row below, all inside the band", () => {
  const out = computePatternLayout(
    "kpi-top",
    [
      item("k1", "context"),
      item("k2", "context"),
      item("k3", "context"),
      item("main", "hero", 2),
      item("side", "support", 1),
    ],
    DESIGN,
    BAND,
  );
  assert.ok(out);
  const k1 = out.get("k1")!;
  const main = out.get("main")!;
  const side = out.get("side")!;
  assert.equal(k1.y, BAND.y);
  assert.ok(main.y > k1.y + k1.h);
  // hero gets proportionally more width than the support in the body row
  assert.ok(main.w > side.w);
  for (const rect of out.values()) {
    assert.ok(rect.y >= BAND.y);
    assert.ok(rect.y + rect.h <= BAND.y + BAND.height + 1e-6);
  }
});

test("kpi-top without any context items → null", () => {
  assert.equal(
    computePatternLayout(
      "kpi-top",
      [item("a", "hero"), item("b", "support")],
      DESIGN,
      BAND,
    ),
    null,
  );
});

test("balanced and unknown patterns → null (auto layout owns geometry)", () => {
  const items = [item("a", "hero")];
  assert.equal(computePatternLayout("balanced", items, DESIGN, BAND), null);
  assert.equal(computePatternLayout("weird", items, DESIGN, BAND), null);
});

test("too many rail items → null instead of unreadable slivers", () => {
  const rail = ["a", "b", "c", "d", "e", "f"].map((id) => item(id, "support"));
  assert.equal(
    computePatternLayout(
      "focus-left",
      [item("hero", "hero"), ...rail],
      DESIGN,
      BAND,
    ),
    null,
  );
});
