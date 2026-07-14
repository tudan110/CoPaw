import assert from "node:assert/strict";
import test from "node:test";

import { workspaceDisplayName } from "./workspaceDisplay.ts";

test("uses the configured Chinese digital-employee name for known workspaces", () => {
  assert.equal(workspaceDisplayName("fault"), "故障分析专家");
  assert.equal(workspaceDisplayName("knowledge"), "知识库助手");
  assert.equal(workspaceDisplayName("query"), "数据分析专家");
});

test("keeps an unknown workspace identifier visible", () => {
  assert.equal(workspaceDisplayName("custom-ops"), "custom-ops");
});
