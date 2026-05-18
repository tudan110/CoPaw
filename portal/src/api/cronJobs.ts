const DEFAULT_API_BASE_URL = "/copaw-api/api";
const DEFAULT_FALLBACK_AGENT_ID = "default";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

export interface CronJobSchedule {
  type: "cron" | "once";
  cron?: string;
  timezone?: string;
  run_at?: string;
  repeat_every_days?: number;
  repeat_end_type?: "never" | "until" | "count";
  repeat_until?: string;
  repeat_count?: number;
}

export interface CronJobTarget {
  user_id: string;
  session_id: string;
}

export interface CronJobDispatch {
  type: "channel";
  channel?: string;
  target: CronJobTarget;
  mode?: "stream" | "final";
  meta?: Record<string, unknown>;
}

export interface CronJobRuntime {
  share_session?: boolean;
  max_concurrency?: number;
  timeout_seconds?: number;
  misfire_grace_seconds?: number;
}

export interface CronJobRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  [key: string]: unknown;
}

export interface CronJobSpec {
  id: string;
  name: string;
  enabled?: boolean;
  save_result_to_inbox?: boolean;
  schedule: CronJobSchedule;
  task_type?: "text" | "agent";
  text?: string;
  request?: CronJobRequest;
  dispatch: CronJobDispatch;
  runtime?: CronJobRuntime;
  meta?: Record<string, unknown>;
}

export interface CronJobState {
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: "success" | "error" | "running" | "skipped" | "cancelled" | null;
  last_error?: string | null;
}

export interface CronJobExecutionRecord {
  run_at: string;
  status: "success" | "error" | "running" | "skipped" | "cancelled";
  error?: string | null;
  trigger?: "scheduled" | "manual";
}

export interface CronDispatchTargetItem {
  channel: string;
  user_id: string;
  session_id: string;
}

export interface CronDispatchTargetsResponse {
  channels: string[];
  items: CronDispatchTargetItem[];
}

interface CopawRequestOptions {
  agentId?: string;
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
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
      throw new Error(lastErrorText || `定时任务请求失败：${response.status}`);
    }
  }

  throw new Error(lastErrorText || `定时任务请求失败：${lastStatus}`);
}

export const cronJobsApi = {
  listCronJobs: (agentId?: string, signal?: AbortSignal) =>
    requestCopaw<CronJobSpec[]>("/cron/jobs", { agentId, signal }),

  getCronJobState: (jobId: string, agentId?: string, signal?: AbortSignal) =>
    requestCopaw<CronJobState>(`/cron/jobs/${encodeURIComponent(jobId)}/state`, {
      agentId,
      signal,
    }),

  createCronJob: (spec: CronJobSpec, agentId?: string) =>
    requestCopaw<CronJobSpec>("/cron/jobs", {
      agentId,
      method: "POST",
      body: spec,
    }),

  replaceCronJob: (jobId: string, spec: CronJobSpec, agentId?: string) =>
    requestCopaw<CronJobSpec>(`/cron/jobs/${encodeURIComponent(jobId)}`, {
      agentId,
      method: "PUT",
      body: spec,
    }),

  deleteCronJob: (jobId: string, agentId?: string) =>
    requestCopaw<{ deleted: boolean }>(`/cron/jobs/${encodeURIComponent(jobId)}`, {
      agentId,
      method: "DELETE",
    }),

  pauseCronJob: (jobId: string, agentId?: string) =>
    requestCopaw<{ paused: boolean }>(`/cron/jobs/${encodeURIComponent(jobId)}/pause`, {
      agentId,
      method: "POST",
    }),

  resumeCronJob: (jobId: string, agentId?: string) =>
    requestCopaw<{ resumed: boolean }>(`/cron/jobs/${encodeURIComponent(jobId)}/resume`, {
      agentId,
      method: "POST",
    }),

  runCronJob: (jobId: string, agentId?: string) =>
    requestCopaw<{ started: boolean }>(`/cron/jobs/${encodeURIComponent(jobId)}/run`, {
      agentId,
      method: "POST",
    }),

  listDispatchTargets: (agentId?: string, params?: { channel?: string; keyword?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.keyword) searchParams.append("keyword", params.keyword);
    const query = searchParams.toString();
    return requestCopaw<CronDispatchTargetsResponse>(
      `/cron/dispatch-targets${query ? `?${query}` : ""}`,
      { agentId },
    );
  },

  getCronJobHistory: (jobId: string, agentId?: string) =>
    requestCopaw<CronJobExecutionRecord[]>(`/cron/jobs/${encodeURIComponent(jobId)}/history`, {
      agentId,
    }),
};