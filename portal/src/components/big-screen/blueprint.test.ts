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

// --- boundary coverage for normalizeBlueprint guardrails --------------------
// Additive: these lock the exact edges of MAX_CELLS / MAX_DEPTH / clampInt.

// Normalize a lone list element and return its clamped limit.
function listLimit(limit: unknown): number {
  const bp = normalizeBlueprint({
    layout: "rows",
    cells: [{ element: { kind: "list", limit } }],
  });
  assert.ok(bp, "a bare list element should always normalize");
  return (bp!.cells[0].element as { limit: number }).limit;
}

test("list limit clamps to the [1, 20] boundary via clampInt", () => {
  assert.equal(listLimit(0), 1, "0 → lower bound 1");
  assert.equal(listLimit(-5), 1, "negative → lower bound 1");
  assert.equal(listLimit(1), 1, "1 stays on the lower boundary");
  assert.equal(listLimit(20), 20, "20 stays on the upper boundary");
  assert.equal(listLimit(21), 20, "21 → upper bound 20");
  assert.equal(listLimit(1000), 20, "huge → upper bound 20");
});

test("list limit falls back to 6 for non-finite, coerces truthy numerics", () => {
  assert.equal(listLimit(undefined), 6, "missing → fallback 6");
  assert.equal(listLimit("abc"), 6, "non-numeric string → fallback 6");
  assert.equal(listLimit(Infinity), 6, "Infinity is not finite → fallback 6");
  assert.equal(listLimit(NaN), 6, "NaN → fallback 6");
  assert.equal(listLimit("7.9"), 7, "float string truncated toward zero");
  assert.equal(listLimit(9.8), 9, "float truncated toward zero");
  assert.equal(listLimit(null), 1, "null coerces via Number to 0, then clamps to 1");
});

test("cells kept at exactly MAX_CELLS, truncated above", () => {
  const label = (n: number) => ({ element: { kind: "label", text: `c${n}` } });

  const at = normalizeBlueprint({
    layout: "grid",
    cells: Array.from({ length: 12 }, (_, i) => label(i)),
  });
  assert.ok(at);
  assert.equal(at!.cells.length, 12, "exactly 12 → all kept");

  const over = normalizeBlueprint({
    layout: "grid",
    cells: Array.from({ length: 13 }, (_, i) => label(i)),
  });
  assert.ok(over);
  assert.equal(over!.cells.length, 12, "13 → 13th sliced off");
});

test("MAX_CELLS slice is positional: valid cells past index 12 never seen", () => {
  const cells = [
    { element: { kind: "label", text: "keep-0" } },
    { element: { kind: "label", text: "keep-1" } },
    // fill indices 2..11 with invalid atoms
    ...Array.from({ length: 10 }, () => ({ element: { kind: "iframe" } })),
    // index 12: valid, but sliced off before the validity filter runs
    { element: { kind: "label", text: "unreachable" } },
  ];
  const bp = normalizeBlueprint({ layout: "rows", cells });
  assert.ok(bp);
  const texts = bp!.cells.map((c) => (c.element as { text: string }).text);
  assert.deepEqual(texts, ["keep-0", "keep-1"], "only valid cells within first 12");
});

test("cell span clamps to [1, 4] with fallback 1", () => {
  const bp = normalizeBlueprint({
    layout: "grid",
    cells: [
      { span: 0, element: { kind: "label", text: "a" } }, // → 1
      { span: -2, element: { kind: "label", text: "b" } }, // → 1
      { span: 4, element: { kind: "label", text: "c" } }, // → 4 (upper boundary)
      { span: 9, element: { kind: "label", text: "d" } }, // → 4
      { element: { kind: "label", text: "e" } }, // missing → fallback 1
      { span: "2.9", element: { kind: "label", text: "f" } }, // → 2 (truncated)
    ],
  });
  assert.ok(bp);
  assert.deepEqual(bp!.cells.map((c) => c.span), [1, 1, 4, 4, 1, 2]);
});

test("group downgraded to null when its only child exceeds MAX_DEPTH", () => {
  // group(0) → group(1) → group(2). The depth-2 group is rejected, leaving the
  // depth-1 group empty → null → the top group empty → null → whole bp null.
  const bp = normalizeBlueprint({
    layout: "rows",
    cells: [
      {
        element: {
          kind: "group",
          layout: "rows",
          cells: [
            {
              element: {
                kind: "group",
                layout: "rows",
                cells: [
                  {
                    element: {
                      kind: "group", // depth 2 → rejected
                      layout: "rows",
                      cells: [{ element: { kind: "label", text: "deep" } }],
                    },
                  },
                ],
              },
            },
          ],
        },
      },
    ],
  });
  assert.equal(bp, null);
});

test("non-object and structurally-invalid inputs normalize to null", () => {
  assert.equal(normalizeBlueprint(null), null, "null");
  assert.equal(normalizeBlueprint(undefined), null, "undefined");
  assert.equal(normalizeBlueprint("rows"), null, "string");
  assert.equal(normalizeBlueprint(42), null, "number");
  assert.equal(normalizeBlueprint(true), null, "boolean");
  assert.equal(normalizeBlueprint([]), null, "array has no cells field");
  assert.equal(normalizeBlueprint({ layout: "rows" }), null, "missing cells");
  assert.equal(
    normalizeBlueprint({ layout: "rows", cells: "nope" }),
    null,
    "cells is a string",
  );
  assert.equal(
    normalizeBlueprint({ layout: "rows", cells: {} }),
    null,
    "cells is an object",
  );
  assert.equal(
    normalizeBlueprint({ layout: "rows", cells: 5 }),
    null,
    "cells is a number",
  );
  assert.equal(
    normalizeBlueprint({ layout: "rows", cells: [] }),
    null,
    "empty cells array",
  );
});

test("cells with null, missing, or non-object element are skipped", () => {
  const bp = normalizeBlueprint({
    layout: "rows",
    cells: [
      null, // non-object cell
      "cell", // non-object cell
      { span: 2 }, // missing element
      { element: null }, // null element
      { element: "value" }, // non-object element
      { element: { kind: "value", bind: { unit: "只" } } }, // value w/o bind.value
      { element: { kind: "label", text: "survivor" } }, // the only keeper
    ],
  });
  assert.ok(bp);
  assert.equal(bp!.cells.length, 1);
  assert.equal((bp!.cells[0].element as { text: string }).text, "survivor");
});
