import assert from "node:assert/strict";
import test from "node:test";
import {
  adjustBrightness,
  resolveChartStyle,
  withAlpha,
} from "./chartStyle.ts";
import { BS_PALETTE, PALETTES } from "./palettes.ts";

test("no style → default palette/label, no overrides", () => {
  const s = resolveChartStyle();
  assert.deepEqual(s.palette, BS_PALETTE);
  assert.equal(s.primary, BS_PALETTE[0]);
  assert.equal(s.labelColor, "#9fb2cc");
  assert.equal(s.lineOpacity, null);
  assert.equal(s.nodeSizeScale, 1);
});

test("palette name selects the named series", () => {
  const s = resolveChartStyle({ palette: "warm" });
  assert.deepEqual(s.palette, PALETTES.warm);
  assert.equal(s.primary, PALETTES.warm[0]);
});

test("unknown palette falls back to default", () => {
  const s = resolveChartStyle({ palette: "nope" });
  assert.deepEqual(s.palette, BS_PALETTE);
});

test("valid accentColor leads the palette and becomes primary", () => {
  const hex = resolveChartStyle({ accentColor: "#ff0000" });
  assert.equal(hex.primary, "#ff0000");
  assert.equal(hex.palette[0], "#ff0000");
  const named = resolveChartStyle({ accentColor: "gold" });
  assert.equal(named.primary, "gold");
});

test("malicious accentColor is rejected (no injection)", () => {
  for (const bad of [
    "red;background:url(javascript:alert(1))",
    "<script>",
    "http://evil",
    "rgb(1,2,3)",
    "#xyz",
  ]) {
    const s = resolveChartStyle({ accentColor: bad });
    assert.equal(s.primary, BS_PALETTE[0], `rejected: ${bad}`);
  }
});

test("lineOpacity 0-100 maps to 0..1 and clamps", () => {
  assert.equal(resolveChartStyle({ lineOpacity: 80 }).lineOpacity, 0.8);
  assert.equal(resolveChartStyle({ lineOpacity: 200 }).lineOpacity, 1);
  assert.equal(resolveChartStyle({ lineOpacity: -10 }).lineOpacity, 0);
});

test("labelBrightness lightens/darkens the label colour", () => {
  const bright = resolveChartStyle({ labelBrightness: 60 }).labelColor;
  const dark = resolveChartStyle({ labelBrightness: -60 }).labelColor;
  assert.notEqual(bright, "#9fb2cc");
  assert.notEqual(dark, "#9fb2cc");
  assert.notEqual(bright, dark);
});

test("sizeScale drives nodeSizeScale, clamped to [0.5, 2]", () => {
  assert.equal(resolveChartStyle({ sizeScale: 1.5 }).nodeSizeScale, 1.5);
  assert.equal(resolveChartStyle({ sizeScale: 9 }).nodeSizeScale, 2);
  assert.equal(resolveChartStyle({ sizeScale: 0.1 }).nodeSizeScale, 0.5);
});

test("adjustBrightness mixes toward white / black", () => {
  assert.equal(adjustBrightness("#000000", 100), "#ffffff");
  assert.equal(adjustBrightness("#ffffff", -100), "#000000");
  assert.equal(adjustBrightness("#9fb2cc", 0), "#9fb2cc");
});

test("withAlpha converts hex to rgba; leaves names unchanged", () => {
  assert.equal(withAlpha("#22d3ee", 0.5), "rgba(34,211,238,0.5)");
  assert.equal(withAlpha("#abc", 1), "rgba(170,187,204,1)");
  assert.equal(withAlpha("gold", 0.5), "gold");
});
