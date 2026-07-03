import assert from "node:assert/strict";
import test from "node:test";
import {
  buildBarOption,
  buildLineOption,
  buildMapFlyOption,
  buildRadarOption,
  inferAxisKeys,
} from "./options.ts";

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

test("inferAxisKeys: name/value rows chart without explicit bindings", () => {
  // The reported bug: metric-card rows converted to bar-chart rendered
  // every x label as the literal "undefined" (default keys x/y missing).
  const rows = [
    { name: "硬件设备", value: 1 },
    { name: "软件服务-虚拟机", value: 3 },
  ];
  const { xKey, yKey } = inferAxisKeys(rows);
  assert.equal(xKey, "name");
  assert.equal(yKey, "value");
  const option = buildBarOption({ rows }) as {
    xAxis: { data: unknown[] };
    series: Array<{ data: unknown[] }>;
  };
  assert.deepEqual(option.xAxis.data, ["硬件设备", "软件服务-虚拟机"]);
  assert.deepEqual(option.series[0].data, [1, 3]);
});

test("inferAxisKeys: explicit bindings still win when present in rows", () => {
  const rows = [{ host: "a", cpu: 90, name: "x", value: 1 }];
  const { xKey, yKey } = inferAxisKeys(rows, "host", "cpu");
  assert.equal(xKey, "host");
  assert.equal(yKey, "cpu");
});

test("inferAxisKeys: falls back to first string/number columns", () => {
  const rows = [{ region: "华东", latency: 42 }];
  const { xKey, yKey } = inferAxisKeys(rows);
  assert.equal(xKey, "region");
  assert.equal(yKey, "latency");
});

test("inferAxisKeys: empty rows keep the requested/default keys", () => {
  const { xKey, yKey } = inferAxisKeys([]);
  assert.equal(xKey, "x");
  assert.equal(yKey, "y");
});
