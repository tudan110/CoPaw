import assert from "node:assert/strict";
import test from "node:test";
import { normalizeBlueprint } from "./blueprint.ts";

test("valid blueprint round-trips with clamped spans", () => {
  const bp = normalizeBlueprint({
    layout: "columns",
    gap: "m",
    cells: [
      {
        span: 99,
        element: {
          kind: "value",
          style: "flip",
          size: "xl",
          bind: { value: "total", unit: "条" },
        },
      },
      {
        element: {
          kind: "chart",
          chart: "area",
          bind: { x: "eventTime", y: "value" },
        },
      },
      {
        element: {
          kind: "list",
          style: "stream",
          limit: 999,
          bind: { title: "title", tone: "level" },
        },
      },
    ],
  });
  assert.ok(bp);
  assert.equal(bp!.layout, "columns");
  assert.equal(bp!.gap, "m");
  assert.equal(bp!.cells.length, 3);
  assert.equal(bp!.cells[0].span, 4); // 99 → 4
  assert.equal((bp!.cells[2].element as { limit: number }).limit, 20);
});

test("invalid atoms dropped; empty blueprint → null", () => {
  const bp = normalizeBlueprint({
    layout: "explode",
    cells: [
      { element: { kind: "iframe", src: "evil" } },
      { element: { kind: "chart", chart: "3d-globe" } },
      { element: { kind: "value", bind: { value: "<script>" } } },
      { element: { kind: "badge", text: "javascript:alert(1)" } },
    ],
  });
  assert.equal(bp, null);
});

test("layout falls back to rows; injection text stripped", () => {
  const bp = normalizeBlueprint({
    layout: "spiral",
    cells: [
      { element: { kind: "label", text: "正常说明" } },
      { element: { kind: "badge", text: "<img onerror=x>" } },
    ],
  });
  assert.ok(bp);
  assert.equal(bp!.layout, "rows");
  assert.equal(bp!.cells.length, 1); // injected badge dropped
});

test("group nests one level, depth-3 dropped", () => {
  const bp = normalizeBlueprint({
    layout: "rows",
    cells: [
      {
        element: {
          kind: "group",
          layout: "columns",
          cells: [
            {
              element: {
                kind: "group",
                layout: "rows",
                cells: [
                  {
                    element: {
                      kind: "group", // depth 3
                      layout: "rows",
                      cells: [
                        { element: { kind: "label", text: "deep" } },
                      ],
                    },
                  },
                  { element: { kind: "label", text: "ok" } },
                ],
              },
            },
          ],
        },
      },
    ],
  });
  assert.ok(bp);
  const level1 = bp!.cells[0].element as {
    kind: string;
    cells: Array<{ element: { kind: string; cells?: unknown[] } }>;
  };
  assert.equal(level1.kind, "group");
  const level2 = level1.cells[0].element;
  assert.equal(level2.kind, "group");
  const level2Kinds = (level2.cells as Array<{ element: { kind: string } }>)
    .map((c) => c.element.kind);
  assert.ok(!level2Kinds.includes("group"));
  assert.ok(level2Kinds.includes("label"));
});

test("cells capped at 12", () => {
  const bp = normalizeBlueprint({
    layout: "grid",
    cells: Array.from({ length: 30 }, (_, i) => ({
      element: { kind: "label", text: `c${i}` },
    })),
  });
  assert.ok(bp);
  assert.equal(bp!.cells.length, 12);
});

test("core bindings required (value/progress/sparkline)", () => {
  assert.equal(
    normalizeBlueprint({
      layout: "rows",
      cells: [{ element: { kind: "value", bind: { unit: "条" } } }],
    }),
    null,
  );
  assert.equal(
    normalizeBlueprint({
      layout: "rows",
      cells: [{ element: { kind: "sparkline", bind: { x: "t" } } }],
    }),
    null,
  );
  const ok = normalizeBlueprint({
    layout: "rows",
    cells: [
      {
        element: {
          kind: "progress",
          style: "ring",
          bind: { value: "pct" },
          max: 100,
        },
      },
    ],
  });
  assert.ok(ok);
});
