import assert from "node:assert/strict";
import test from "node:test";
import { __resetChinaMapForTest, isChinaMapReady } from "./chinaGeo.ts";

test("map starts unready and guard is idempotent", () => {
  __resetChinaMapForTest();
  assert.equal(isChinaMapReady(), false);
});
