import { requestPortalApi } from "./portalWorkorders";

export type TraceSessionStatus = "ok" | "error";

export interface TraceSessionSummary {
  session_id: string;
  agent_id: string;
  user_id: string;
  channel: string;
  title: string;
  preview: string;
  first_event_at: number;
  last_event_at: number;
  event_count: number;
  tool_call_count: number;
  error_count: number;
  status: TraceSessionStatus;
}

export interface TraceSessionListResponse {
  total: number;
  offset: number;
  limit: number;
  items: TraceSessionSummary[];
}

export type TraceEventType =
  | "user_message"
  | "agent_reply"
  | "tool_call"
  | "skill_trigger"
  | "agent_reasoning"
  | "error"
  | string;

export interface TraceEvent {
  ts: number;
  type: TraceEventType;
  session_id?: string;
  agent_id?: string;
  user_id?: string;
  channel?: string;
  // Tool-call fields
  tool_call_id?: string;
  tool_name?: string;
  args?: unknown;
  result?: unknown;
  outcome?: "ok" | "error" | "denied" | "auto_denied" | "timeout";
  duration_ms?: number;
  guard?: { severity?: string; findings_count?: number };
  // User / assistant text
  text?: string;
  role?: string;
  kind?: string;
  // Skill fields
  name?: string;
  display_name?: string;
  input?: string;
  // Error fields
  exception_type?: string;
  message?: string;
  [key: string]: unknown;
}

export interface TraceSessionDetail {
  session_id: string;
  events: TraceEvent[];
  total: number;
  exists: boolean;
}

export interface TraceStats {
  session_count: number;
  session_count_24h: number;
  event_count: number;
  tool_call_count: number;
  error_count: number;
}

export interface TraceListParams {
  agentId?: string;
  keyword?: string;
  onlyErrors?: boolean;
  sinceTs?: number;
  untilTs?: number;
  offset?: number;
  limit?: number;
}

function buildQuery(params: TraceListParams = {}): string {
  const search = new URLSearchParams();
  if (params.agentId) search.set("agent_id", params.agentId);
  if (params.keyword) search.set("keyword", params.keyword);
  if (params.onlyErrors) search.set("only_errors", "true");
  if (typeof params.sinceTs === "number") search.set("since_ts", String(params.sinceTs));
  if (typeof params.untilTs === "number") search.set("until_ts", String(params.untilTs));
  if (typeof params.offset === "number") search.set("offset", String(params.offset));
  if (typeof params.limit === "number") search.set("limit", String(params.limit));
  const query = search.toString();
  return query ? `?${query}` : "";
}

export const tracesApi = {
  listSessions: (params: TraceListParams = {}, signal?: AbortSignal) =>
    requestPortalApi<TraceSessionListResponse>(`/traces/sessions${buildQuery(params)}`, {
      signal,
    }),

  getSession: (
    sessionId: string,
    options: { offset?: number; limit?: number; signal?: AbortSignal } = {},
  ) => {
    const search = new URLSearchParams();
    if (typeof options.offset === "number") search.set("offset", String(options.offset));
    if (typeof options.limit === "number") search.set("limit", String(options.limit));
    const query = search.toString();
    return requestPortalApi<TraceSessionDetail>(
      `/traces/sessions/${encodeURIComponent(sessionId)}${query ? `?${query}` : ""}`,
      { signal: options.signal },
    );
  },

  stats: (signal?: AbortSignal) =>
    requestPortalApi<TraceStats>("/traces/stats", { signal }),

  clearSession: (sessionId: string) =>
    requestPortalApi<{ deleted: boolean; session_id: string }>(
      `/traces/sessions/${encodeURIComponent(sessionId)}/clear`,
      { method: "POST" },
    ),
};
