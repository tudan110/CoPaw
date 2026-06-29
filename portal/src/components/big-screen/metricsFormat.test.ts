import assert from "node:assert/strict";
import test from "node:test";
import {
  formatPercent,
  formatDurationMs,
  topFailingCapabilities,
  hasMetrics,
  type BigScreenMetrics,
} from "./metricsFormat.ts";

test("formatPercent rounds and clamps", () => {
  assert.equal(formatPercent(0.5), "50%");
  assert.equal(formatPercent(1), "100%");
  assert.equal(formatPercent(0), "0%");
  assert.equal(formatPercent(0.333), "33%");
  assert.equal(formatPercent(1.5), "100%"); // clamp
  assert.equal(formatPercent(Number.NaN), "—");
});

test("formatDurationMs picks the right unit", () => {
  assert.equal(formatDurationMs(820), "820ms");
  assert.equal(formatDurationMs(1500), "1.5s");
  assert.equal(formatDurationMs(123000), "2m03s");
  assert.equal(formatDurationMs(0), "—");
  assert.equal(formatDurationMs(Number.NaN), "—");
});

test("topFailingCapabilities ranks non-zero worst-first", () => {
  const ranked = topFailingCapabilities({
    "real-alarms": 0.1,
    workorders: 0,
    "system-logs": 0.5,
    "cmdb-resources": 0.3,
  });
  assert.deepEqual(
    ranked.map((r) => r.capabilityId),
    ["system-logs", "cmdb-resources", "real-alarms"],
  );
  // zero-rate capability excluded
  assert.ok(!ranked.some((r) => r.capabilityId === "workorders"));
});

test("topFailingCapabilities respects the limit and empty input", () => {
  const rates = { a: 0.9, b: 0.8, c: 0.7, d: 0.6 };
  assert.equal(topFailingCapabilities(rates, 2).length, 2);
  assert.deepEqual(topFailingCapabilities(undefined), []);
  assert.deepEqual(topFailingCapabilities({}), []);
});

test("hasMetrics reflects recorded events", () => {
  const empty: BigScreenMetrics = {
    total: 0,
    successRate: 0,
    degradedRate: 0,
    avgDurationMs: 0,
    capabilityFailureRates: {},
    kinds: {},
  };
  assert.equal(hasMetrics(empty), false);
  assert.equal(hasMetrics(undefined), false);
  assert.equal(hasMetrics({ ...empty, total: 3 }), true);
});
