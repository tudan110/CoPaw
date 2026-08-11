const DEFAULT_API_BASE_URL = "/copaw-api/api";
const DEFAULT_FALLBACK_AGENT_ID = "default";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

interface CopawRequestOptions {
  agentId?: string;
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

export type McpTransport = "stdio" | "streamable_http" | "sse";

export type MCPAccessEffect = "allow" | "ask" | "deny";
export type MCPAccessSourceType = "channel";
export type MCPAccessSubjectType = "all" | "user";

export interface MCPAccessRule {
  source_type: MCPAccessSourceType;
  source_value: string;
  subject_type: MCPAccessSubjectType;
  subject_value: string;
  effect: MCPAccessEffect;
}

export interface MCPAccessPrincipalOption {
  source_type: MCPAccessSourceType;
  source_value: string;
  subject_type: "user";
  subject_value: string;
  label: string;
  chat_id: string;
  chat_name: string;
  session_id: string;
  updated_at: string | null;
}

export interface MCPToolDefaultPolicy {
  tool_name: string;
  effect: MCPAccessEffect;
}

export interface MCPToolAccessOverride extends MCPAccessRule {
  tool_name: string;
}

export interface MCPAccessPolicy {
  default_effect: MCPAccessEffect;
  client_overrides: MCPAccessRule[];
  tool_defaults: MCPToolDefaultPolicy[];
  tool_overrides: MCPToolAccessOverride[];
  unmanaged_rules_count: number;
}

export interface McpClientInfo {
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  transport: McpTransport;
  url: string;
  headers: Record<string, string>;
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
  tools: string[] | null;
}

export interface McpToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface McpClientCreateRequest {
  name: string;
  description?: string;
  enabled?: boolean;
  transport: McpTransport;
  url?: string;
  headers?: Record<string, string>;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
}

export interface McpClientUpdateRequest {
  name?: string;
  description?: string;
  enabled?: boolean;
  transport?: McpTransport;
  url?: string;
  headers?: Record<string, string>;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  tools?: string[] | null;
}

function getAgentCandidates(agentId?: string) {
  const fallbackAgentId =
    import.meta.env.VITE_COPAW_FALLBACK_AGENT_ID || DEFAULT_FALLBACK_AGENT_ID;
  return [...new Set([agentId, fallbackAgentId].filter(Boolean))];
}

function isMissingAgentResponse(status: number, errorText?: string) {
  return status === 404 && /Agent\s+['"].+['"]\s+not\s+found/i.test(errorText || "");
}

function extractErrorMessage(text: string) {
  if (!text) {
    return "";
  }

  try {
    const payload = JSON.parse(text) as {
      detail?: unknown;
      message?: unknown;
      error?: unknown;
    };
    if (typeof payload.detail === "string" && payload.detail) {
      return payload.detail;
    }
    if (typeof payload.message === "string" && payload.message) {
      return payload.message;
    }
    if (typeof payload.error === "string" && payload.error) {
      return payload.error;
    }
  } catch {
    return text;
  }

  return text;
}

async function requestCopaw<T>(
  path: string,
  { agentId, method = "GET", body, signal }: CopawRequestOptions = {},
): Promise<T> {
  const agentCandidates = getAgentCandidates(agentId);
  let lastStatus = 0;
  let lastErrorText = "";

  for (const candidateAgentId of agentCandidates) {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      signal,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(candidateAgentId ? { "X-Agent-Id": candidateAgentId } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    if (response.ok) {
      if (response.status === 204) {
        return null as T;
      }
      return response.json() as Promise<T>;
    }

    lastStatus = response.status;
    const responseText = await response.text().catch(() => "");
    lastErrorText = extractErrorMessage(responseText);
    if (!isMissingAgentResponse(response.status, responseText)) {
      throw new Error(lastErrorText || `MCP 请求失败：${response.status}`);
    }
  }

  throw new Error(lastErrorText || `MCP 请求失败：${lastStatus}`);
}

export const mcpApi = {
  listClients: (agentId?: string, signal?: AbortSignal) =>
    requestCopaw<McpClientInfo[]>("/mcp", { agentId, signal }),

  getClient: (clientKey: string, agentId?: string, signal?: AbortSignal) =>
    requestCopaw<McpClientInfo>(`/mcp/${encodeURIComponent(clientKey)}`, {
      agentId,
      signal,
    }),

  listTools: (clientKey: string, agentId?: string, signal?: AbortSignal) =>
    requestCopaw<McpToolInfo[]>(`/mcp/tools/${encodeURIComponent(clientKey)}`, {
      agentId,
      signal,
    }),

  getPolicy: (clientKey: string, agentId?: string) =>
    requestCopaw<MCPAccessPolicy>(`/mcp/policy/${encodeURIComponent(clientKey)}`, { agentId }),

  updatePolicy: (clientKey: string, policy: MCPAccessPolicy, agentId?: string) =>
    requestCopaw<MCPAccessPolicy>(`/mcp/policy/${encodeURIComponent(clientKey)}`, {
      agentId,
      method: "PUT",
      body: policy,
    }),

  listAccessPrincipals: (agentId?: string) =>
    requestCopaw<MCPAccessPrincipalOption[]>("/mcp/access-principals", { agentId }),

  createClient: (
    clientKey: string,
    client: McpClientCreateRequest,
    agentId?: string,
  ) =>
    requestCopaw<McpClientInfo>("/mcp", {
      agentId,
      method: "POST",
      body: {
        client_key: clientKey,
        client,
      },
    }),

  updateClient: (
    clientKey: string,
    updates: McpClientUpdateRequest,
    agentId?: string,
  ) =>
    requestCopaw<McpClientInfo>(`/mcp/${encodeURIComponent(clientKey)}`, {
      agentId,
      method: "PUT",
      body: updates,
    }),

  toggleClient: (clientKey: string, agentId?: string) =>
    requestCopaw<McpClientInfo>(`/mcp/toggle/${encodeURIComponent(clientKey)}`, {
      agentId,
      method: "PATCH",
    }),

  deleteClient: (clientKey: string, agentId?: string) =>
    requestCopaw<{ message: string }>(`/mcp/${encodeURIComponent(clientKey)}`, {
      agentId,
      method: "DELETE",
    }),
};
