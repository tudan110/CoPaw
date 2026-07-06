import assert from "node:assert/strict";
import test from "node:test";
import {
  safeToken,
  screenTitleCss,
  visualSpecClassTokens,
} from "./visualSpec.ts";

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

test("screenTitleCss: explicit color disables the gradient fill", () => {
  const css = screenTitleCss({ color: "#ef4444" });
  assert.equal(css.color, "#ef4444");
  assert.equal(css.WebkitTextFillColor, "#ef4444");
  assert.equal(css.background, "none");
});

test("screenTitleCss: sizeScale clamps to 0.5–2 of the 34px base", () => {
  assert.equal(screenTitleCss({ sizeScale: 1.5 }).fontSize, 51);
  assert.equal(screenTitleCss({ sizeScale: 99 }).fontSize, 68);
  assert.equal(screenTitleCss({ sizeScale: 0.1 }).fontSize, 17);
});

test("screenTitleCss: strong emphasis glows in the chosen color", () => {
  const css = screenTitleCss({ color: "#ef4444", emphasis: "strong" });
  assert.ok(String(css.textShadow).includes("#ef4444"));
});

test("screenTitleCss: garbage color is ignored (defence in depth)", () => {
  const css = screenTitleCss({ color: "javascript:alert(1)" });
  assert.equal(css.color, undefined);
  assert.equal(css.background, undefined);
});

test("screenTitleCss: empty style yields no overrides", () => {
  assert.deepEqual(screenTitleCss(undefined), {});
  assert.deepEqual(screenTitleCss({}), {});
});
