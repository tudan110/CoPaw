import type { AlarmWorkorder } from "../types/portal";

const DEFAULT_PORTAL_API_BASE_URL = "/portal-api";
const SAME_ORIGIN_PORTAL_API_BASE_URL = "/api/portal";
const DEFAULT_REQUEST_TIMEOUT_MS = 15000;

// Optional global handler invoked when a portal API call returns 401 — used
// by the SSO layer to clear the session and re-login. SSO endpoints
// (/sso/*) are excluded so login calls handle their own 401s.
let unauthorizedHandler: (() => void) | null = null;

export function setPortalUnauthorizedHandler(
  handler: (() => void) | null,
): void {
  unauthorizedHandler = handler;
}

const PORTAL_API_BASE_URL = (
  import.meta.env.VITE_PORTAL_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.__PORTAL_RUNTIME_CONFIG__?.portalApiBaseUrl
    : "") ||
  DEFAULT_PORTAL_API_BASE_URL
).replace(/\/$/, "");

function shouldRetryWithSameOriginApi(status: number, errorText: string) {
  if (
    import.meta.env.DEV ||
    PORTAL_API_BASE_URL === SAME_ORIGIN_PORTAL_API_BASE_URL ||
    PORTAL_API_BASE_URL !== DEFAULT_PORTAL_API_BASE_URL ||
    ![404, 405].includes(status)
  ) {
    return false;
  }

  try {
    const payload = JSON.parse(errorText);
    return ["Not Found", "Method Not Allowed"].includes(String(payload?.detail || ""));
  } catch {
    return !errorText.trim();
  }
}

function extractPortalApiError(errorText: string) {
  try {
    const payload = JSON.parse(errorText);
    if (payload?.detail) {
      return String(payload.detail);
    }
  } catch {
    // Keep the original server text when it is not JSON.
  }
  return errorText || "Portal 请求失败";
}

async function fetchPortalApi(baseUrl: string, path: string, init: RequestInit, signal: AbortSignal) {
  return fetch(`${baseUrl}${path}`, {
    ...init,
    signal,
  });
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

export interface AlarmWorkorderListResponse {
  total?: number;
  items?: AlarmWorkorder[];
  source?: string;
}

export async function requestPortalApi<T = unknown>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const externalSignal = init.signal;
  const cleanupExternalAbort = bindAbortSignals(controller, externalSignal);
  const requestInit = { ...init };
  delete requestInit.signal;
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    let response = await fetchPortalApi(PORTAL_API_BASE_URL, path, requestInit, controller.signal);
    let errorText = "";

    if (!response.ok) {
      errorText = await response.text().catch(() => "");
      if (shouldRetryWithSameOriginApi(response.status, errorText)) {
        response = await fetchPortalApi(
          SAME_ORIGIN_PORTAL_API_BASE_URL,
          path,
          requestInit,
          controller.signal,
        );
        errorText = "";
      }
    }

    if (!response.ok) {
      errorText = errorText || await response.text().catch(() => "");
      if (response.status === 401 && !path.startsWith("/sso/")) {
        unauthorizedHandler?.();
      }
      const error = new Error(extractPortalApiError(errorText)) as Error & {
        status?: number;
      };
      error.status = response.status;
      throw error;
    }

    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error(externalSignal?.aborted ? "请求已取消" : "请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
    cleanupExternalAbort();
  }
}

export async function listAlarmWorkorders(
  params: { limit?: number } = {},
): Promise<AlarmWorkorderListResponse | AlarmWorkorder[]> {
  const searchParams = new URLSearchParams();
  if (params.limit) {
    searchParams.set("limit", String(params.limit));
  }

  return requestPortalApi<AlarmWorkorderListResponse | AlarmWorkorder[]>(
    `/alarm-workorders${
      searchParams.toString() ? `?${searchParams.toString()}` : ""
    }`,
  );
}

export async function killSlowSqlSession(
  payload: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  return requestPortalApi<Record<string, unknown>>("/mock/kill-slow-sql", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}
