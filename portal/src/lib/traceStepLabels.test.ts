import assert from "node:assert/strict";
import test from "node:test";
import { traceStepDisplay } from "./traceStepLabels.ts";

test("thinking blocks show a generic analysis label (no raw reasoning)", () => {
  assert.deepEqual(traceStepDisplay({ kind: "thinking", content: "secret chain of thought" } as never), {
    icon: "fa-brain",
    text: "思考分析",
  });
});

test("skill invocations are generalized to 调用技能 (name hidden)", () => {
  assert.equal(traceStepDisplay({ kind: "tool", title: "Skill" }).text, "调用技能");
  assert.equal(traceStepDisplay({ kind: "tool", title: "real-alarm-skill" }).text, "调用技能");
  assert.equal(traceStepDisplay({ kind: "tool", title: "" }).text, "调用技能");
});

test("shell/script tools are generalized to 执行脚本 (command hidden)", () => {
  assert.equal(traceStepDisplay({ kind: "tool", title: "execute_shell_command" }).text, "执行脚本");
  assert.equal(traceStepDisplay({ kind: "tool", title: "run_python" }).text, "执行脚本");
});

test("search / read / write tools map to their coarse categories", () => {
  assert.equal(traceStepDisplay({ kind: "tool", title: "web_search" }).text, "检索数据");
  assert.equal(traceStepDisplay({ kind: "tool", title: "query_alarms" }).text, "检索数据");
  assert.equal(traceStepDisplay({ kind: "tool", title: "list_hosts" }).text, "读取数据");
  assert.equal(traceStepDisplay({ kind: "tool", title: "generate_report" }).text, "生成内容");
});

test("unknown tools never leak the raw name — fall back to 调用工具", () => {
  const out = traceStepDisplay({ kind: "tool", title: "frobnicate_widget_v2" });
  assert.equal(out.text, "调用工具");
  assert.doesNotMatch(out.text, /frobnicate|widget/);
});

test("unknown block kinds are a neutral 处理中", () => {
  assert.equal(traceStepDisplay({ kind: "misc" }).text, "处理中");
  assert.equal(traceStepDisplay(null).text, "处理中");
});
