import { portalGatewayAgentId } from "../config/portalBranding";

const DEFAULT_API_BASE_URL = "/copaw-api/api";
const DEFAULT_REQUEST_TIMEOUT_MS = 15000;

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

export interface InboxEvent {
  id: string;
  agent_id: string;
  source_type: string;
  source_id: string;
  event_type: string;
  status: string;
  severity: string;
  title: string;
  body: string;
  payload?: Record<string, unknown>;
  read: boolean;
  created_at: string | number;
}

export interface InboxTraceEvent {
  at: number;
  event: Record<string, unknown>;
}

export interface InboxTrace {
  run_id: string;
  created_at: number;
  completed_at: number | null;
  status: string;
  meta: Record<string, unknown>;
  events: InboxTraceEvent[];
  error?: string;
}

export interface ListInboxEventsParams {
  limit?: number;
  offset?: number;
  source_type?: string;
  status?: string;
  agent_id?: string;
  unread_only?: boolean;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

function bindAbortSignals(controller: AbortController, externalSignal?: AbortSignal | null) {
  if (!externalSignal) {
    return () => {};
  }
  if (externalSignal.aborted) {
    controller.abort();
    return () => {};
  }
  const abort = () => controller.abort();
  externalSignal.addEventListener("abort", abort, { once: true });
  return () => externalSignal.removeEventListener("abort", abort);
}

function buildInboxQuery(params: ListInboxEventsParams = {}) {
  const query = new URLSearchParams();
  if (typeof params.limit === "number") query.set("limit", String(params.limit));
  if (typeof params.offset === "number") query.set("offset", String(params.offset));
  if (params.source_type) query.set("source_type", params.source_type);
  if (params.status) query.set("status", params.status);
  if (params.agent_id) query.set("agent_id", params.agent_id);
  if (typeof params.unread_only === "boolean") query.set("unread_only", String(params.unread_only));
  const suffix = query.toString();
  return suffix ? `?${suffix}` : "";
}

async function requestInboxApi<T>(
  path: string,
  { method = "GET", body, signal, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS }: RequestOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const cleanupExternalAbort = bindAbortSignals(controller, signal);
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/console/inbox${path}`, {
      method,
      signal: controller.signal,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        "X-Agent-Id": portalGatewayAgentId,
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
      throw new Error(detail || `收件箱请求失败：${response.status}`);
    }

    if (response.status === 204) {
      return null as T;
    }

    return response.json() as Promise<T>;
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error(signal?.aborted ? "请求已取消" : "请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
    cleanupExternalAbort();
  }
}

export const inboxApi = {
  listInboxEvents: (params: ListInboxEventsParams = {}, signal?: AbortSignal) =>
    requestInboxApi<{ events: InboxEvent[] }>(`/events${buildInboxQuery(params)}`, { signal }),

  markRead: (eventIds: string[]) =>
    requestInboxApi<{ updated: number }>("/read", {
      method: "POST",
      body: { event_ids: eventIds },
    }),

  markAllRead: () =>
    requestInboxApi<{ updated: number }>("/read", {
      method: "POST",
      body: { all: true },
    }),

  deleteEvent: (eventId: string) =>
    requestInboxApi<{ deleted: boolean; trace_deleted?: boolean; run_id?: string | null }>(
      `/events/${encodeURIComponent(eventId)}`,
      { method: "DELETE" },
    ),

  getTrace: (runId: string, signal?: AbortSignal) =>
    requestInboxApi<InboxTrace>(`/traces/${encodeURIComponent(runId)}`, { signal }),
};
