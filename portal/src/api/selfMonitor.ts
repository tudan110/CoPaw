import { requestPortalApi } from "./portalWorkorders";

/** Layer/overall status vocabulary from the self-monitor backend. */
export type SelfMonitorStatus = "ok" | "warn" | "crit" | "unknown";

export interface SelfMonitorLayer {
  layer: "l1" | "l2" | "l3" | "l4";
  status: SelfMonitorStatus;
  metrics: Record<string, unknown>;
}

export interface SelfMonitorOverview {
  generatedAt: number;
  windowS: number;
  enabled: boolean;
  state: SelfMonitorStatus;
  layers: SelfMonitorLayer[];
  kpis: {
    degradeEvents: number;
    llm429: number;
    workersUp: number;
    chatSuccessRate: number | null;
  };
  alertsFiring: number;
  eventCounts: Record<string, number>;
}

export interface SelfMonitorAlert {
  id: number;
  ruleId: string;
  name: string;
  layer: string;
  severity: "warn" | "critical";
  state: "firing" | "resolved";
  value: number;
  threshold: number;
  message: string;
  startedAt: number;
  resolvedAt: number | null;
}

export interface SelfMonitorTopology {
  generatedAt: number;
  windowS: number;
  nodes: {
    id: string;
    type: "core" | "worker" | "model" | "datasource";
    label: string;
    status: string;
    requests?: number;
    errorRatio?: number;
  }[];
  edges: { source: string; target: string; value: number }[];
}

export interface SelfMonitorCost {
  total: number | null;
  currency: string;
  byModel: Record<string, number>;
  unpricedModels: string[];
  tokensByModel: Record<string, { prompt: number; completion: number }>;
  budgetDaily: number | null;
  configured: boolean;
  since: number;
  generatedAt: number;
}

export interface SelfMonitorModelRow {
  model: string;
  calls: number;
  errors: number;
  errRate: number;
  byStatus: Record<string, number>;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  avgDurationS: number | null;
  avgTtftS: number | null;
  tpotS: number | null;
}

export interface SelfMonitorModels {
  generatedAt: number;
  windowS: number;
  bucketS: number;
  rows: SelfMonitorModelRow[];
  totals: {
    calls: number;
    errors: number;
    errRate: number;
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
    avgDurationS: number | null;
    avgTtftS: number | null;
  };
  callTrend: { ts: number; calls: number; errors: number; errRate: number }[];
  durationTrend: { ts: number; avgS: number }[];
  ttftTrend: { ts: number; avgS: number }[];
  errorTypes: Record<string, number>;
}

export interface SelfMonitorTools {
  generatedAt: number;
  windowS: number;
  bucketS: number;
  totals: {
    calls: number;
    errors: number;
    errRate: number;
    avgDurationMs: number | null;
  };
  byTool: {
    tool: string;
    calls: number;
    errors: number;
    errRate: number;
    avgDurationMs: number | null;
  }[];
  byAgent: { agent: string; calls: number }[];
  trend: { ts: number; calls: number; errors: number }[];
}

export interface SelfMonitorTokens {
  generatedAt: number;
  windowS: number;
  bucketS: number;
  totals: { prompt: number; completion: number; total: number };
  byModel: Record<string, { prompt: number; completion: number }>;
  series: { ts: number; prompt: number; completion: number }[];
  perRequest: { ts: number; avgTokens: number }[];
}

export interface SelfMonitorSessions {
  available: boolean;
  reason?: string;
  generatedAt?: number;
  days?: number;
  totals?: {
    activeSessions: number;
    messages: number;
    userMessages: number;
    assistantMessages: number;
    llmCalls: number;
    toolCalls: number;
    promptTokens: number;
    completionTokens: number;
  };
  workspaces?: {
    workspace: string;
    activeSessions: number;
    messages: number;
    userMessages: number;
    assistantMessages: number;
    llmCalls: number;
    toolCalls: number;
    promptTokens: number;
    completionTokens: number;
  }[];
  byDate?: {
    date: string;
    chats: number;
    activeSessions: number;
    messages: number;
    llmCalls: number;
    toolCalls: number;
  }[];
  byChannel?: {
    channel: string;
    sessions: number;
    userMessages: number;
    assistantMessages: number;
  }[];
}

export interface SelfMonitorDiagnosis {
  summary: string;
  rootCause: string;
  confidence: "high" | "medium" | "low";
  evidence: string[];
  recommendations: string[];
  engine: "llm" | "rule-based";
  degraded: boolean;
  generatedAt: number;
}

export interface SelfMonitorMetricSeries {
  name: string;
  labels: Record<string, string>;
  worker: string;
  kind: string;
  layer: string;
  points: [number, number][];
}

export interface SelfMonitorEvent {
  ts: number;
  type: string;
  severity: "info" | "warn" | "error" | "critical";
  layer: string;
  source: string;
  labels: Record<string, string>;
  message: string;
  dedupKey: string;
  count: number;
}

function buildQuery(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export const selfMonitorApi = {
  overview: (windowS: number, signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorOverview>(
      `/self-monitor/overview${buildQuery({ window_s: windowS })}`,
      { signal },
    ),

  metrics: (name: string, since: number, signal?: AbortSignal) =>
    requestPortalApi<{ name: string; series: SelfMonitorMetricSeries[] }>(
      `/self-monitor/metrics${buildQuery({ name, since })}`,
      { signal },
    ),

  events: (limit = 60, signal?: AbortSignal) =>
    requestPortalApi<{ items: SelfMonitorEvent[] }>(
      `/self-monitor/events${buildQuery({ limit })}`,
      { signal },
    ),

  alerts: (limit = 50, signal?: AbortSignal) =>
    requestPortalApi<{ active: SelfMonitorAlert[]; recent: SelfMonitorAlert[] }>(
      `/self-monitor/alerts${buildQuery({ limit })}`,
      { signal },
    ),

  topology: (windowS = 3600, signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorTopology>(
      `/self-monitor/topology${buildQuery({ window_s: windowS })}`,
      { signal },
    ),

  cost: (signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorCost>("/self-monitor/cost", { signal }),

  models: (windowS = 86400, signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorModels>(
      `/self-monitor/models${buildQuery({ window_s: windowS })}`,
      { signal },
    ),

  tokens: (windowS = 86400, signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorTokens>(
      `/self-monitor/tokens${buildQuery({ window_s: windowS })}`,
      { signal },
    ),

  tools: (windowS = 86400, signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorTools>(
      `/self-monitor/tools${buildQuery({ window_s: windowS })}`,
      { signal },
    ),

  sessions: (days = 7, signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorSessions>(
      `/self-monitor/sessions${buildQuery({ days })}`,
      { signal },
    ),

  diagnose: (windowS = 3600, signal?: AbortSignal) =>
    requestPortalApi<SelfMonitorDiagnosis>("/self-monitor/diagnose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ windowS }),
      signal,
    }),
};

/**
 * Turn cumulative-counter rollup series into per-bucket increases,
 * summed across all (labels, worker) series.  Mirrors the backend's
 * counter_delta semantics: drops between samples are counter resets.
 */
export function toDeltaBuckets(
  series: SelfMonitorMetricSeries[],
  bucketS = 60,
): [number, number][] {
  const buckets = new Map<number, number>();
  for (const one of series) {
    let prev: number | null = null;
    for (const [ts, value] of one.points) {
      if (prev !== null) {
        const delta = value >= prev ? value - prev : value;
        const bucket = Math.floor(ts / bucketS) * bucketS;
        buckets.set(bucket, (buckets.get(bucket) || 0) + delta);
      }
      prev = value;
    }
  }
  return [...buckets.entries()].sort((a, b) => a[0] - b[0]);
}
