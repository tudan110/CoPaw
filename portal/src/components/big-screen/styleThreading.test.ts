import assert from "node:assert/strict";
import test from "node:test";
import { intrinsicSize } from "./intrinsicSize.ts";
import { buildGraphOption, buildLineOption } from "./charts/options.ts";
import { resolveChartStyle } from "./charts/chartStyle.ts";
import { PALETTES } from "./charts/palettes.ts";
import type { ScreenComponent, VisualSpec } from "./types.ts";

function comp(type: string, visualSpec: VisualSpec = {}): ScreenComponent {
  return { id: "c", type, title: "", visualSpec };
}

test("style.sizeScale enlarges a component's intrinsic size", () => {
  const base = intrinsicSize(comp("graph"));
  const bigger = intrinsicSize(comp("graph", { style: { sizeScale: 1.5 } }));
  assert.ok(bigger.widthUnits > base.widthUnits, "width grows");
  assert.ok(bigger.naturalHeight > base.naturalHeight, "height grows");
  const smaller = intrinsicSize(comp("graph", { style: { sizeScale: 0.6 } }));
  assert.ok(smaller.widthUnits < base.widthUnits, "width shrinks");
});

test("buildGraphOption honours node size / link opacity / palette", () => {
  const style = resolveChartStyle({
    sizeScale: 2,
    lineOpacity: 90,
    palette: "warm",
  });
  const opt: any = buildGraphOption(
    { nodes: [{ name: "a" }, { name: "b" }] },
    style,
  );
  const series = opt.series[0];
  assert.equal(series.nodes[0].symbolSize, 40, "20 * sizeScale 2");
  assert.ok(
    String(series.lineStyle.color).includes("0.9"),
    "link opacity from lineOpacity",
  );
  assert.equal(series.nodes[0].itemStyle.color, PALETTES.warm[0]);
});

test("buildGraphOption default raises the link-opacity floor to .35", () => {
  const opt: any = buildGraphOption({ nodes: [{ name: "a" }] });
  assert.equal(opt.series[0].nodes[0].symbolSize, 20, "default scale 1");
  assert.ok(
    String(opt.series[0].lineStyle.color).includes("0.35"),
    "brighter default than the old .2",
  );
});

test("buildLineOption applies a selected palette", () => {
  const opt: any = buildLineOption(
    { rows: [{ x: 1, y: 2 }] },
    { x: "x", y: "y" },
    resolveChartStyle({ palette: "cool" }),
  );
  assert.deepEqual(opt.color, PALETTES.cool);
  assert.equal(opt.series[0].lineStyle.color, PALETTES.cool[0]);
});

test("builders stay JSON-serializable (no function literals)", () => {
  const opt = buildGraphOption(
    { nodes: [{ name: "a" }] },
    resolveChartStyle({ accentColor: "#ff0000" }),
  );
  assert.ok(!JSON.stringify(opt).includes("function"));
});
