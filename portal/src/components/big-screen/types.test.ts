import assert from "node:assert/strict";
import test from "node:test";
import { normalizeSpec } from "./types.ts";

test("normalizeSpec fills required defaults", () => {
  const spec = normalizeSpec({ id: "s1", name: "运维大屏", components: [{ id: "c1", type: "metric-kpi" }] });
  assert.equal(spec.schemaVersion, 1);
  assert.equal(spec.status, "draft");
  assert.deepEqual(spec.layout, { designWidth: 1920, designHeight: 1080 });
  assert.equal(spec.components[0].title, "");
  assert.deepEqual(spec.components[0].visualSpec, {});
});

test("normalizeSpec drops a component with no id", () => {
  const spec = normalizeSpec({ id: "s1", name: "x", components: [{ type: "table" }] as any });
  assert.equal(spec.components.length, 0);
});
