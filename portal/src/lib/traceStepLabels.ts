// Map a conversation "process record" block to a generic activity category.
//
// The live chat (digital-employee) streams process blocks (thinking / tool /
// response). For tool & thinking steps we expose ONLY a coarse "what is it
// doing" category — never the tool/skill name, arguments, script body, or raw
// reasoning text. Those details stay server-side and in the Traces Center.

export type TraceStepBlock = {
  kind?: string;
  title?: string;
  icon?: string;
};

export type TraceStepDisplay = { icon: string; text: string };

// Tool names are conventionally `verb_noun` (query_alarms, list_hosts,
// execute_shell_command). We classify on the *leading verb token* so unrelated
// nouns can't false-match (e.g. "widget" must not read as "get").
const VERB_CATEGORIES: Array<{ icon: string; text: string; verbs: string[] }> = [
  { icon: "fa-terminal", text: "执行脚本", verbs: ["shell", "bash", "cmd", "command", "terminal", "python", "script", "exec", "execute", "run"] },
  { icon: "fa-magnifying-glass", text: "检索数据", verbs: ["search", "web", "browse", "crawl", "http", "fetch", "request", "retrieve", "retriev", "query", "lookup", "grep", "find"] },
  { icon: "fa-database", text: "读取数据", verbs: ["read", "list", "ls", "get", "load", "describe", "count", "stat", "show", "view", "inspect"] },
  { icon: "fa-pen-nib", text: "生成内容", verbs: ["write", "create", "generate", "generat", "render", "report", "export", "draw", "chart", "plot", "compose", "build", "make"] },
];

/** Coarse, non-sensitive category for a process-record step. */
export function traceStepDisplay(block: TraceStepBlock | null | undefined): TraceStepDisplay {
  if (block?.kind === "thinking") {
    return { icon: "fa-brain", text: "思考分析" };
  }
  if (block?.kind === "tool") {
    const raw = String(block?.title || "").trim().toLowerCase();
    const tokens = raw.split(/[^a-z0-9]+/).filter(Boolean);
    const first = tokens[0] || "";

    if (!raw || tokens.includes("skill") || tokens.includes("skills")) {
      return { icon: "fa-puzzle-piece", text: "调用技能" };
    }
    // Standalone shell/script hints anywhere in the name → 执行脚本.
    if (tokens.some((t) => ["shell", "bash", "script"].includes(t))) {
      return { icon: "fa-terminal", text: "执行脚本" };
    }
    for (const cat of VERB_CATEGORIES) {
      if (cat.verbs.some((v) => first === v || first.startsWith(v))) {
        return { icon: cat.icon, text: cat.text };
      }
    }
    return { icon: "fa-screwdriver-wrench", text: "调用工具" };
  }
  return { icon: block?.icon || "fa-gear", text: "处理中" };
}
