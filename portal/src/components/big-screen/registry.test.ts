import assert from "node:assert/strict";
import test from "node:test";
import { isKnownComponentType, KNOWN_COMPONENT_TYPES } from "./registry.ts";

test("registry advertises the D-max widget whitelist", () => {
  for (const t of ["metric-kpi","flip-number","liquid-ball","line-chart","bar-chart","area-chart","donut","gauge","radar","heatmap","graph","map-fly","alarm-stream","top-n","risk-pulse","funnel","timeline","bar3d"]) {
    assert.ok(KNOWN_COMPONENT_TYPES.includes(t), `${t} should be registered`);
  }
});

test("unknown type is not known", () => {
  assert.equal(isKnownComponentType("totally-made-up"), false);
});
