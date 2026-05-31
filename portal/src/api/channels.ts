// Channels API client for Portal.
// Backend route: /api/agents/{agentId}/config/channels
// Portal accesses via /copaw-api/api/config/channels with X-Agent-Id header.

const DEFAULT_API_BASE_URL = "/copaw-api/api";
const DEFAULT_FALLBACK_AGENT_ID = "default";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

export interface ChannelInfo {
  enabled: boolean;
  bot_prefix?: string;
  isBuiltin?: boolean;
  [key: string]: unknown;
}

export type ChannelListResponse = Record<string, ChannelInfo>;

interface RequestOptions {
  agentId?: string;
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

function getAgentId(agentId?: string) {
  return agentId || import.meta.env.VITE_COPAW_FALLBACK_AGENT_ID || DEFAULT_FALLBACK_AGENT_ID;
}

async function requestChannelsApi<T>(
  path: string,
  { agentId, method = "GET", body, signal }: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/config${path}`, {
    method,
    signal,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      "X-Agent-Id": getAgentId(agentId),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let detail = "";
    try {
      const payload = JSON.parse(text);
      detail = payload?.detail || payload?.message || "";
    } catch {
      detail = text;
    }
    throw new Error(detail || `频道请求失败：${response.status}`);
  }

  if (response.status === 204) {
    return null as T;
  }
  return response.json() as Promise<T>;
}

export const channelsApi = {
  listChannels: (agentId?: string, signal?: AbortSignal) =>
    requestChannelsApi<ChannelListResponse>("/channels", { agentId, signal }),

  listChannelTypes: (agentId?: string, signal?: AbortSignal) =>
    requestChannelsApi<string[]>("/channels/types", { agentId, signal }),

  getChannel: (channelName: string, agentId?: string, signal?: AbortSignal) =>
    requestChannelsApi<ChannelInfo>(`/channels/${encodeURIComponent(channelName)}`, {
      agentId,
      signal,
    }),

  updateChannel: (channelName: string, config: Record<string, unknown>, agentId?: string) =>
    requestChannelsApi<ChannelInfo>(`/channels/${encodeURIComponent(channelName)}`, {
      agentId,
      method: "PUT",
      body: config,
    }),

  getChannelHealth: (channelName: string, agentId?: string, signal?: AbortSignal) =>
    requestChannelsApi<Record<string, unknown>>(`/channels/${encodeURIComponent(channelName)}/health`, {
      agentId,
      signal,
    }),

  restartChannel: (channelName: string, agentId?: string) =>
    requestChannelsApi<Record<string, unknown>>(`/channels/${encodeURIComponent(channelName)}/restart`, {
      agentId,
      method: "POST",
    }),
};
