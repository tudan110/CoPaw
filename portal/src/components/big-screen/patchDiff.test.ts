import assert from "node:assert/strict";
import test from "node:test";
import {
  summarizePatchDiff,
  hasPatchChanges,
  type PatchDiffEntry,
} from "./patchDiff.ts";

test("empty / missing diff → no lines, no changes", () => {
  assert.deepEqual(summarizePatchDiff(undefined), []);
  assert.deepEqual(summarizePatchDiff([]), []);
  assert.equal(hasPatchChanges(undefined), false);
  assert.equal(hasPatchChanges([]), false);
});

test("scalar field change → before → after line", () => {
  const diff: PatchDiffEntry[] = [
    {
      componentId: "comp-1",
      field: "title",
      before: "告警流",
      after: "实时告警",
    },
  ];
  const lines = summarizePatchDiff(diff);
  assert.equal(lines.length, 1);
  assert.match(lines[0], /comp-1/);
  assert.match(lines[0], /标题/);
  assert.match(lines[0], /告警流/);
  assert.match(lines[0], /实时告警/);
  assert.equal(hasPatchChanges(diff), true);
});

test("theme palette is screen-level (no component prefix)", () => {
  const lines = summarizePatchDiff([
    {
      componentId: "",
      field: "theme.palette",
      before: "industrial",
      after: "executive",
    },
  ]);
  assert.match(lines[0], /主题配色/);
  assert.match(lines[0], /industrial/);
  assert.match(lines[0], /executive/);
});

test("added / removed component", () => {
  const added = summarizePatchDiff([
    {
      componentId: "c-new",
      field: "component",
      before: null,
      after: { type: "donut", title: "级别分布" },
    },
  ]);
  assert.match(added[0], /新增组件/);
  assert.match(added[0], /级别分布/);

  const removed = summarizePatchDiff([
    {
      componentId: "c-old",
      field: "component",
      before: { title: "旧卡" },
      after: null,
    },
  ]);
  assert.match(removed[0], /移除组件/);
  assert.match(removed[0], /旧卡/);
});

test("structured fields read as 'adjusted', not raw object dumps", () => {
  const lines = summarizePatchDiff([
    {
      componentId: "c-1",
      field: "queryParams",
      before: { limit: 20 },
      after: { limit: 50 },
    },
    { componentId: "c-1", field: "layoutPosition", before: {}, after: {} },
    { componentId: "c-1", field: "visualConfig", before: {}, after: {} },
  ]);
  assert.equal(lines.length, 3);
  for (const line of lines) assert.match(line, /已调整/);
  // must not dump the raw object braces
  assert.ok(!lines.join("").includes("{"));
});

test("multiple entries → one line each, order preserved", () => {
  const lines = summarizePatchDiff([
    { componentId: "a", field: "title", before: "x", after: "y" },
    { componentId: "", field: "theme.palette", before: "p", after: "q" },
  ]);
  assert.equal(lines.length, 2);
  assert.match(lines[0], /标题/);
  assert.match(lines[1], /主题配色/);
});

test("unknown field falls back to its raw key", () => {
  const lines = summarizePatchDiff([
    { componentId: "a", field: "mystery", before: "1", after: "2" },
  ]);
  assert.match(lines[0], /mystery/);
});

test("malformed entries are skipped, not thrown", () => {
  // deliberately wrong shapes
  const diff = [
    null,
    42,
    { field: "title", componentId: "a", before: "x", after: "y" },
  ] as unknown as PatchDiffEntry[];
  const lines = summarizePatchDiff(diff);
  assert.equal(lines.length, 1);
});
