import assert from "node:assert/strict";
import test from "node:test";
import { extractToolName, toolActivityLabel } from "./agentActivityLabels.ts";

test("toolActivityLabel classifies by verb prefix (running)", () => {
  assert.match(toolActivityLabel("query_alarms", { done: false }), /正在查询/);
  assert.match(toolActivityLabel("web_search", { done: false }), /正在联网搜索/);
  assert.match(toolActivityLabel("list_hosts", { done: false }), /正在获取/);
  assert.match(toolActivityLabel("analyze_root_cause", { done: false }), /正在分析/);
  assert.match(toolActivityLabel("run_playbook", { done: false }), /正在执行/);
});

test("toolActivityLabel running lines carry the tool icon and ellipsis", () => {
  const label = toolActivityLabel("query_alarms", { done: false });
  assert.match(label, /^🔧/);
  assert.match(label, /…$/);
});

test("toolActivityLabel switches to done phrasing with a check icon", () => {
  const label = toolActivityLabel("query_alarms", { done: true });
  assert.match(label, /^✅/);
  assert.match(label, /已完成查询/);
});

test("toolActivityLabel humanizes unknown verbs instead of leaking the raw name", () => {
  assert.match(
    toolActivityLabel("frobnicate_widget", { done: false }),
    /正在调用「frobnicate widget」…/,
  );
});

test("toolActivityLabel handles empty / missing names", () => {
  assert.match(toolActivityLabel("", { done: false }), /正在处理…/);
  assert.match(toolActivityLabel(undefined, { done: true }), /已完成一个步骤/);
});

test("extractToolName digs the name out of merged tool content", () => {
  const msg = {
    id: "m1",
    role: "assistant",
    type: "plugin_call",
    status: "completed",
    content: [
      { type: "data", status: "completed", data: { name: "query_alarms", arguments: "{}" } },
      { type: "data", status: "completed", data: { output: "..." } },
    ],
  };
  assert.equal(extractToolName(msg as never), "query_alarms");
});

test("extractToolName returns empty when no name is present", () => {
  assert.equal(extractToolName({ content: [] } as never), "");
});
