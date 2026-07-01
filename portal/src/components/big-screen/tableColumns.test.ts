import assert from "node:assert/strict";
import test from "node:test";
import { cell, deriveColumns } from "./widgets/tableColumns.ts";

test("deriveColumns prefers declared fields (workorder columns)", () => {
  const cols = deriveColumns({
    data: {
      capabilityId: "workorders",
      sourceStatus: "live",
      fields: [
        { key: "workorderNo", label: "工单号" },
        { key: "title", label: "标题" },
      ],
      rows: [{ workorderNo: "WO-1", title: "工单A" }],
    },
  });
  assert.deepEqual(cols, [
    { key: "workorderNo", label: "工单号" },
    { key: "title", label: "标题" },
  ]);
});

test("deriveColumns falls back to the union of row keys", () => {
  const cols = deriveColumns({
    data: {
      capabilityId: "x",
      sourceStatus: "live",
      rows: [
        { a: 1, b: 2 },
        { a: 3, c: 4 },
      ],
    },
  });
  assert.deepEqual(
    cols.map((c) => c.key),
    ["a", "b", "c"],
  );
});

test("deriveColumns caps at 8 columns", () => {
  const row: Record<string, number> = {};
  for (let i = 0; i < 20; i++) row["k" + i] = i;
  const cols = deriveColumns({
    data: { capabilityId: "x", sourceStatus: "live", rows: [row] },
  });
  assert.equal(cols.length, 8);
});

test("cell: empty→em-dash, scalars→string, objects→json", () => {
  assert.equal(cell(null), "—");
  assert.equal(cell(undefined), "—");
  assert.equal(cell(""), "—");
  assert.equal(cell(0), "0");
  assert.equal(cell("处理中"), "处理中");
  assert.equal(cell({ a: 1 }), '{"a":1}');
});
