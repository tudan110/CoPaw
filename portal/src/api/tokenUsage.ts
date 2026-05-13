const DEFAULT_API_BASE_URL = "/copaw-api/api";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

export interface TokenUsageStats {
  provider_id?: string;
  model?: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

export interface TokenUsageSummary {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_calls: number;
  by_date: Record<string, TokenUsageStats>;
  by_model?: Record<string, TokenUsageStats>;
  by_provider?: Record<string, TokenUsageStats>;
}

export interface TokenUsageDetailRecord extends TokenUsageStats {
  date: string;
  provider_id: string;
  model: string;
}

export interface GetTokenUsageParams {
  start_date: string;
  end_date: string;
  model?: string;
  provider?: string;
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

function buildQuery(params: GetTokenUsageParams) {
  const searchParams = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });
  if (params.model) {
    searchParams.set("model", params.model);
  }
  if (params.provider) {
    searchParams.set("provider", params.provider);
  }
  return `?${searchParams.toString()}`;
}

async function requestTokenUsage<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      extractErrorMessage(text) || `Token 统计请求失败：${response.status}`,
    );
  }

  return response.json();
}

export const tokenUsageApi = {
  getTokenUsageSummary: (params: GetTokenUsageParams) =>
    requestTokenUsage<TokenUsageSummary>(`/token-usage${buildQuery(params)}`),
  getTokenUsageDetails: (params: GetTokenUsageParams) =>
    requestTokenUsage<TokenUsageDetailRecord[]>(`/token-usage/details${buildQuery(params)}`),
  getTokenUsage: (params: GetTokenUsageParams) =>
    requestTokenUsage<TokenUsageSummary>(`/token-usage${buildQuery(params)}`),
};
