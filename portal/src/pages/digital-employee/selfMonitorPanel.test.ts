import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

const source = readFileSync(
  fileURLToPath(new URL("./selfMonitorPanel.tsx", import.meta.url)),
  "utf8",
);

test("self-monitor exposes the full seven-day retention window", () => {
  assert.match(source, /\{ label: "7d", seconds: 7 \* 86400 \}/);
});
