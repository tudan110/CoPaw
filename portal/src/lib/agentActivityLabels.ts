// Turn raw tool/skill invocations into a single friendly, human-readable
// activity line (e.g. "🔧 正在查询告警数据…"). We deliberately expose only a
// short verb phrase — never the raw arguments or output, which stay available
// in the Traces Center ("追溯中心") for those who need them.
//
// The verb-prefix rules cover the vast majority of tool names without needing
// to enumerate every skill; the CURATED map is only for cases where a nicer
// phrasing is worth hand-writing.

import type { IAgentScopeRuntimeMessage } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";

const RUNNING_ICON = "🔧";
const DONE_ICON = "✅";

type VerbRule = { test: RegExp; running: string; done: string };

// Ordered: the first matching prefix wins, so keep more specific rules first.
const VERB_RULES: VerbRule[] = [
  { test: /^(search|web|google|bing|browse|crawl|fetch_url)/, running: "正在联网搜索", done: "已完成联网搜索" },
  { test: /^(query|select|find|lookup|q_)/, running: "正在查询", done: "已完成查询" },
  { test: /^(analy|diagnos|assess|evaluat|inspect|review|summar|reason)/, running: "正在分析", done: "已完成分析" },
  { test: /^(list|ls|get|read|load|show|describe|fetch|retriev|count|stat)/, running: "正在获取", done: "已获取" },
  { test: /^(create|make|generat|build|render|draw|compose|plot|chart)/, running: "正在生成", done: "已生成" },
  { test: /^(update|patch|modif|edit|set|apply|config|save|write)/, running: "正在更新", done: "已更新" },
  { test: /^(delete|remove|drop|clear|clean)/, running: "正在清理", done: "已清理" },
  { test: /^(send|post|notify|push|publish|email|alert)/, running: "正在发送", done: "已发送" },
  { test: /^(run|exec|execute|invoke|call|dispatch|trigger|start|perform|do_)/, running: "正在执行", done: "已执行" },
];

// Optional hand-written overrides keyed by exact (lower-cased) tool name.
const CURATED: Record<string, { running: string; done: string }> = {
  // e.g. "query_alarms": { running: "正在查询告警数据", done: "已获取告警数据" },
};

/** Pull the bare tool/function name from a merged tool message. */
export function extractToolName(item: IAgentScopeRuntimeMessage): string {
  const content = Array.isArray(item?.content) ? item.content : [];
  for (const part of content) {
    const data = (part as { data?: Record<string, unknown> } | undefined)?.data;
    const name = data && typeof data === "object" ? data.name : undefined;
    if (typeof name === "string" && name.trim()) {
      return name.trim();
    }
  }
  return "";
}

/** Humanize a snake_case / camelCase tool name for the fallback phrasing. */
function prettifyToolName(name: string): string {
  return name
    .replace(/[._-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/**
 * Friendly one-line label for a tool step. `done` selects the completed vs.
 * in-progress phrasing. Never includes arguments or output.
 */
export function toolActivityLabel(
  rawName: string | undefined,
  opts: { done: boolean },
): string {
  const done = opts.done;
  const name = (rawName || "").trim();
  if (!name) {
    return done ? `${DONE_ICON} 已完成一个步骤` : `${RUNNING_ICON} 正在处理…`;
  }

  const key = name.toLowerCase();
  const curated = CURATED[key];
  if (curated) {
    return done ? `${DONE_ICON} ${curated.done}` : `${RUNNING_ICON} ${curated.running}…`;
  }

  for (const rule of VERB_RULES) {
    if (rule.test.test(key)) {
      return done ? `${DONE_ICON} ${rule.done}` : `${RUNNING_ICON} ${rule.running}…`;
    }
  }

  const pretty = prettifyToolName(name);
  return done
    ? `${DONE_ICON} 已完成「${pretty}」`
    : `${RUNNING_ICON} 正在调用「${pretty}」…`;
}
