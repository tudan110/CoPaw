import assert from "node:assert/strict";
import test from "node:test";
import { intrinsicSize, UNIT_PX } from "./intrinsicSize.ts";
import type { ScreenComponent, VisualSpec } from "./types.ts";

function comp(
  type: string,
  data?: ScreenComponent["data"],
  visualSpec: VisualSpec = {},
): ScreenComponent {
  return { id: "c", type, title: "", visualSpec, data };
}

test("empty / failed panels are small regardless of type", () => {
  const empty = intrinsicSize(
    comp("alarm-stream", { capabilityId: "x", sourceStatus: "empty" }),
  );
  const failed = intrinsicSize(
    comp("graph", { capabilityId: "x", sourceStatus: "failed" }),
  );
  assert.equal(empty.naturalHeight, 150);
  assert.equal(failed.naturalHeight, 150);
  assert.ok(empty.widthUnits <= 1.01);
});

test("single-value panels are small (≈1 unit, short)", () => {
  for (const type of ["metric-kpi", "flip-number", "gauge", "risk-pulse"]) {
    const size = intrinsicSize(comp(type));
    assert.equal(size.naturalHeight, 190, `${type} height`);
    assert.ok(Math.abs(size.widthUnits - 1) < 0.01, `${type} width`);
  }
});

test("lists grow taller with more rows", () => {
  const few = intrinsicSize(
    comp("alarm-stream", {
      capabilityId: "x",
      sourceStatus: "live",
      rows: [{}, {}],
    }),
  );
  const many = intrinsicSize(
    comp("alarm-stream", {
      capabilityId: "x",
      sourceStatus: "live",
      rows: Array.from({ length: 12 }, () => ({})),
    }),
  );
  assert.ok(many.naturalHeight > few.naturalHeight, "more rows → taller");
  assert.ok(many.widthUnits >= few.widthUnits, "many rows widen too");
  assert.ok(many.naturalHeight <= 460 + 0.01, "clamped to max");
});

test("fill charts are wide (≈2 units)", () => {
  const line = intrinsicSize(comp("line-chart"));
  assert.ok(line.widthUnits >= 1.9, "line chart ~2 units");
  assert.equal(line.naturalHeight, 320);
});

test("graph shrinks when it has few nodes", () => {
  const sparse = intrinsicSize(
    comp("graph", {
      capabilityId: "x",
      sourceStatus: "live",
      nodes: [{}, {}],
    }),
  );
  const dense = intrinsicSize(
    comp("graph", {
      capabilityId: "x",
      sourceStatus: "live",
      nodes: Array.from({ length: 9 }, () => ({})),
    }),
  );
  assert.ok(dense.naturalHeight > sparse.naturalHeight, "dense graph taller");
  assert.ok(dense.widthUnits > sparse.widthUnits, "dense graph wider");
});

test("composed grows with blueprint cell count", () => {
  const few = intrinsicSize(
    comp("composed", undefined, { blueprint: { cells: [{}, {}] } }),
  );
  const many = intrinsicSize(
    comp("composed", undefined, {
      blueprint: { cells: Array.from({ length: 8 }, () => ({})) },
    }),
  );
  assert.ok(many.naturalHeight > few.naturalHeight, "more cells → taller");
});

test("composition: primary enlarges, supporting shrinks", () => {
  const base = intrinsicSize(comp("donut"));
  const primary = intrinsicSize(
    comp("donut", undefined, { composition: "primary" }),
  );
  const supporting = intrinsicSize(
    comp("donut", undefined, { composition: "supporting" }),
  );
  assert.ok(primary.naturalHeight > base.naturalHeight, "primary taller");
  assert.ok(primary.widthUnits > base.widthUnits, "primary wider");
  assert.ok(
    supporting.naturalHeight < base.naturalHeight,
    "supporting shorter",
  );
});

test("sizes stay within sane card bounds", () => {
  const huge = intrinsicSize(
    comp("line-chart", undefined, { composition: "primary" }),
  );
  assert.ok(huge.widthUnits * UNIT_PX <= 1100 + 0.01, "width capped");
  assert.ok(huge.naturalHeight <= 520 + 0.01, "height capped");
  const tiny = intrinsicSize(
    comp("text", undefined, { composition: "supporting" }),
  );
  assert.ok(tiny.widthUnits * UNIT_PX >= 260 - 0.01, "width floored");
  assert.ok(tiny.naturalHeight >= 140 - 0.01, "height floored");
});
