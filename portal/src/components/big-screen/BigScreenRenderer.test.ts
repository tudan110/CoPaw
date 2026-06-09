import assert from "node:assert/strict";
import test from "node:test";
// resolveComponentType is a pure helper that lives in registry.ts (JSX-free)
// so it is importable by the test runner; BigScreenRenderer.tsx imports it too.
import { resolveComponentType } from "./registry.ts";

test("resolveComponentType: known type resolves to itself", () => {
  assert.equal(resolveComponentType("map-fly"), "map-fly");
  assert.equal(resolveComponentType("flip-number"), "flip-number");
  assert.equal(resolveComponentType("text"), "text");
});

test("resolveComponentType: unknown type collapses to 'unknown'", () => {
  assert.equal(resolveComponentType("nope"), "unknown");
  assert.equal(resolveComponentType(""), "unknown");
  assert.equal(resolveComponentType("<script>"), "unknown");
});
