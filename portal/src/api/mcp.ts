import { requestPortalApi } from "./portalWorkorders";

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

export interface McpImportResult {
  created: boolean;
  key: string;
  name: string;
  domain_category?: string;
}

/**
 * Create an MCP client through the Portal's domain-checked endpoint
 * (POST /portal-api/mcp/import). Off-domain clients are rejected by the
 * backend with a 422 whose message is shown to the operator.
 */
export function importMcpClient(
  clientKey: string,
  client: McpClientCreateRequest,
  agentId?: string,
): Promise<McpImportResult> {
  return requestPortalApi<McpImportResult>("/mcp/import", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(agentId ? { "X-Agent-Id": agentId } : {}),
    },
    body: JSON.stringify({ client_key: clientKey, client }),
  });
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
    requestCopaw<McpToolInfo[]>(`/mcp/${encodeURIComponent(clientKey)}/tools`, {
      agentId,
      signal,
    }),

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
    requestCopaw<McpClientInfo>(`/mcp/${encodeURIComponent(clientKey)}/toggle`, {
      agentId,
      method: "PATCH",
    }),

  deleteClient: (clientKey: string, agentId?: string) =>
    requestCopaw<{ message: string }>(`/mcp/${encodeURIComponent(clientKey)}`, {
      agentId,
      method: "DELETE",
    }),
};
