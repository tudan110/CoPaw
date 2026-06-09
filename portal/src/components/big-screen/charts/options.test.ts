import assert from "node:assert/strict";
import test from "node:test";
import { buildLineOption, buildRadarOption, buildMapFlyOption } from "./options.ts";

test("buildLineOption maps series rows to xAxis+series, dark grid", () => {
  const opt: any = buildLineOption({ rows: [{ t: "10:00", v: 5 }, { t: "11:00", v: 8 }] }, { x: "t", y: "v" });
  assert.deepEqual(opt.xAxis.data, ["10:00", "11:00"]);
  assert.deepEqual(opt.series[0].data, [5, 8]);
  assert.equal(opt.series[0].type, "line");
  assert.equal(typeof opt.backgroundColor, "string"); // transparent/dark
  assert.ok(!JSON.stringify(opt).includes("function")); // no fn literals
});

test("buildRadarOption builds indicators from metrics", () => {
  const opt: any = buildRadarOption({ metrics: { 稳定性: 90, 性能: 80, 容量: 70 } });
  assert.equal(opt.radar.indicator.length, 3);
  assert.deepEqual(opt.series[0].data[0].value, [90, 80, 70]);
});

test("buildMapFlyOption emits geo china + lines series from edges", () => {
  const opt: any = buildMapFlyOption({ nodes: [{ name: "北京", coord: [116, 40] }, { name: "上海", coord: [121, 31] }] }, [{ from: "上海", to: "北京" }]);
  assert.equal(opt.geo.map, "china");
  assert.equal(opt.series.find((s: any) => s.type === "lines").data.length, 1);
});
