import assert from "node:assert/strict";
import test from "node:test";
import { bindingField, coerceNumber } from "./binding.ts";

test("bindingField resolves via visualSpec.bindings then fallback keys", () => {
  const row = { riskScore: 88, value: 12 };
  assert.equal(bindingField(row, { value: "riskScore" }, "value", "count"), 88); // binding wins
  assert.equal(bindingField({ count: 5 }, undefined, "value", "count"), 5);      // fallback chain
  assert.equal(bindingField({}, undefined, "value"), undefined);
});

test("coerceNumber tolerates strings and units", () => {
  assert.equal(coerceNumber("96%"), 96);
  assert.equal(coerceNumber("1,284"), 1284);
  assert.equal(coerceNumber(null), 0);
});
