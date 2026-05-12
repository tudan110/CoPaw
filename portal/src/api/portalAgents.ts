// Thin client for QwenPaw's agent-management endpoints (the same ones the
// console's "create agent" modal uses). Used by the FDE workbench so a
// generated skill can target a brand-new business agent, not just existing
// ones. Not agent-scoped — no X-Agent-Id needed.

import type { ModelSlotConfig } from "./models";

const DEFAULT_API_BASE_URL = "/copaw-api/api";
const REQUEST_TIMEOUT_MS = 45000;

const API_BASE_URL = (
  import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL
).replace(/\/$/, "");

export interface AgentSummary {
  id: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  enabled?: boolean;
  active_model?: ModelSlotConfig | null;
}

export interface CreateAgentPayload {
  id?: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  language?: string;
  skill_names?: string[];
  active_model?: { provider_id: string; model: string };
}

export interface AgentProfileRef {
  id: string;
  workspace_dir: string;
  enabled: boolean;
}

function extractDetail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in (body as object)) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in (d as object)) {
      return String((d as { message: unknown }).message);
    }
    return JSON.stringify(d);
  }
  if (typeof body === "string" && body) return body;
  return `请求失败 (${status})`;
}

async function requestAgents<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS,
  );
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers || {}),
      },
    });
    const text = await response.text();
    let body: unknown;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    if (!response.ok) {
      throw new Error(extractDetail(body, response.status));
    }
    return body as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时");
    }
    throw error instanceof Error ? error : new Error("网络错误");
  } finally {
    window.clearTimeout(timer);
  }
}

export const portalAgentsApi = {
  listAgents: () =>
    requestAgents<{ agents: AgentSummary[] }>("/agents").then(
      (r) => r.agents || [],
    ),

  createAgent: (payload: CreateAgentPayload) =>
    requestAgents<AgentProfileRef>("/agents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
