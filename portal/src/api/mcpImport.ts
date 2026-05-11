import type { McpClientCreateRequest, McpTransport } from "./mcp";

/** A loosely-typed MCP entry as it appears in pasted JSON config. */
export type RawMcpEntry = {
  name?: unknown;
  description?: unknown;
  enabled?: unknown;
  transport?: unknown;
  type?: unknown;
  url?: unknown;
  headers?: unknown;
  command?: unknown;
  args?: unknown;
  env?: unknown;
  cwd?: unknown;
};

export type McpImportEntry = { clientKey: string; payload: McpClientCreateRequest };

function asStringRecord(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const result: Record<string, string> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    result[key] = typeof raw === "string" ? raw : String(raw ?? "");
  }
  return result;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => (typeof item === "string" ? item : String(item ?? "")));
}

export function normalizeMcpImportEntry(key: string, raw: RawMcpEntry): McpImportEntry {
  const clientKey = key.trim();
  if (!clientKey) {
    throw new Error("MCP 配置项的键名不能为空");
  }
  const command = typeof raw.command === "string" ? raw.command.trim() : "";
  const url = typeof raw.url === "string" ? raw.url.trim() : "";
  const declared =
    typeof raw.transport === "string"
      ? raw.transport.trim().toLowerCase()
      : typeof raw.type === "string"
        ? raw.type.trim().toLowerCase()
        : "";

  let transport: McpTransport;
  if (declared === "stdio" || (!declared && command)) {
    transport = "stdio";
  } else if (declared === "sse") {
    transport = "sse";
  } else if (
    declared === "streamable_http" ||
    declared === "streamablehttp" ||
    declared === "http" ||
    (!declared && url)
  ) {
    transport = "streamable_http";
  } else if (command) {
    transport = "stdio";
  } else {
    throw new Error(`「${clientKey}」缺少 command 或 url，无法判断协议类型`);
  }

  if (transport === "stdio" && !command) {
    throw new Error(`「${clientKey}」为 stdio 协议，必须提供 command`);
  }
  if (transport !== "stdio" && !url) {
    throw new Error(`「${clientKey}」为 ${transport} 协议，必须提供 url`);
  }

  return {
    clientKey,
    payload: {
      name: typeof raw.name === "string" && raw.name.trim() ? raw.name.trim() : clientKey,
      description: typeof raw.description === "string" ? raw.description : "",
      enabled: raw.enabled !== false,
      transport,
      url: transport === "stdio" ? "" : url,
      headers: transport === "stdio" ? {} : asStringRecord(raw.headers),
      command: transport === "stdio" ? command : "",
      args: transport === "stdio" ? asStringArray(raw.args) : [],
      env: transport === "stdio" ? asStringRecord(raw.env) : {},
      cwd: transport === "stdio" && typeof raw.cwd === "string" ? raw.cwd.trim() : "",
    },
  };
}

/**
 * Parse a pasted MCP config blob into a list of create requests.
 *
 * Accepted shapes:
 *   { "mcpServers": { "<key>": { ... } } }   — the standard mcp config file
 *   { "<key>": { ... } }                      — a bare key → entry map
 *
 * A single bare entry object (with command/url/transport/type at top level) is
 * rejected with a hint to wrap it, since it has no key.
 */
export function parseMcpImportText(text: string): McpImportEntry[] {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("请粘贴 MCP 配置 JSON");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error("不是合法的 JSON");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("MCP 配置必须是 JSON 对象");
  }
  const obj = parsed as Record<string, unknown>;

  let entriesMap: Record<string, unknown>;
  if (obj.mcpServers && typeof obj.mcpServers === "object" && !Array.isArray(obj.mcpServers)) {
    entriesMap = obj.mcpServers as Record<string, unknown>;
  } else if (["command", "url", "transport", "type"].some((field) => field in obj)) {
    throw new Error('看起来是单个 MCP 配置，请用 {"客户端名": { ... }} 的形式包一层后再导入');
  } else {
    entriesMap = obj;
  }

  const keys = Object.keys(entriesMap);
  if (!keys.length) {
    throw new Error("没有找到任何 MCP 配置项");
  }
  return keys.map((key) => {
    const value = entriesMap[key];
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error(`「${key}」的配置必须是 JSON 对象`);
    }
    return normalizeMcpImportEntry(key, value as RawMcpEntry);
  });
}
