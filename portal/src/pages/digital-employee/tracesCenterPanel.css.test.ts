import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

const stylesheet = readFileSync(
  fileURLToPath(new URL("./tracesCenterPanel.css", import.meta.url)),
  "utf8",
);

test("trajectory event cards use the same semantic colors as the navigation legend", () => {
  assert.match(stylesheet, /\.trace-event\.user_message\s*\{\s*border-left-color:\s*#d9679b;/);
  assert.match(stylesheet, /\.trace-event\.agent_reply\s*\{\s*border-left-color:\s*#e8923c;/);
  assert.match(stylesheet, /\.trace-event\.tool_call\s*\{\s*border-left-color:\s*#0891b2;/);
  assert.match(stylesheet, /\.trace-event\.agent_reasoning\s*\{\s*border-left-color:\s*#8b5cf6;/);
});
