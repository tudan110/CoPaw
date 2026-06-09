import assert from "node:assert/strict";
import test from "node:test";
import { evaluateRules, toneRank } from "./rules.ts";

const rows = [
  { host: "db-07", cpu: 96 },
  { host: "web-1", cpu: 40 },
];

test("returns strongest matching tone per row", () => {
  const tones = evaluateRules(rows, [
    { field: "cpu", operator: ">=", value: 90, tone: "critical" },
    { field: "cpu", operator: ">=", value: 30, tone: "normal" },
  ]);
  assert.equal(tones[0], "critical"); // 96 >= 90 wins over normal
  assert.equal(tones[1], "normal");
});

test("contains operator + no-match -> null tone", () => {
  const tones = evaluateRules([{ msg: "OOM killed" }, { msg: "ok" }], [
    { field: "msg", operator: "contains", value: "OOM", tone: "critical" },
  ]);
  assert.equal(tones[0], "critical");
  assert.equal(tones[1], null);
});

test("toneRank orders severity", () => {
  assert.ok(toneRank("critical") > toneRank("high"));
  assert.ok(toneRank("high") > toneRank("normal"));
});
