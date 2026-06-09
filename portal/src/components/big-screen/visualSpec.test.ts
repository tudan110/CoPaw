import assert from "node:assert/strict";
import test from "node:test";
import { visualSpecClassTokens, safeToken } from "./visualSpec.ts";

test("emits whitelisted kind/motion/density/layout/composition classes", () => {
  const cls = visualSpecClassTokens({ kind: "risk-field", motion: "pulse", density: "showcase", layoutPattern: "focus", composition: "primary" });
  assert.ok(cls.includes("bs-kind-risk-field"));
  assert.ok(cls.includes("bs-motion-pulse"));
  assert.ok(cls.includes("bs-density-showcase"));
  assert.ok(cls.includes("bs-layout-focus"));
  assert.ok(cls.includes("bs-comp-primary"));
});

test("drops non-whitelisted tokens", () => {
  const cls = visualSpecClassTokens({ motion: "explode" as any, kind: "<script>" as any });
  assert.ok(!cls.join(" ").includes("explode"));
  assert.ok(!cls.join(" ").includes("script"));
});

test("safeToken blocks injection payloads", () => {
  assert.equal(safeToken("javascript:alert(1)"), "");
  assert.equal(safeToken("<img onerror=x>"), "");
  assert.equal(safeToken("severity"), "severity");
});
