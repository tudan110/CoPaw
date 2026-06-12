import type { LightAppListResponse } from "../types/lightApps";

const DEFAULT_PORTAL_API_BASE_URL = "/portal-api";
const PORTAL_API_BASE_URL = (
  import.meta.env.VITE_PORTAL_API_BASE_URL || DEFAULT_PORTAL_API_BASE_URL
).replace(/\/$/, "");
const DEFAULT_REQUEST_TIMEOUT_MS = 30000;

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

async function requestPortalApi<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${PORTAL_API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(
        extractErrorMessage(await response.text()) || "应用中心请求失败",
      );
    }
    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("应用中心请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}

export function listLightApps(limit = 100) {
  return requestPortalApi<LightAppListResponse>(
    `/light-apps?limit=${encodeURIComponent(String(limit))}`,
  );
}

export function setAppArtifactListing(appId: string, listed: boolean) {
  return requestPortalApi<{ id: string; listed_at: string }>(
    `/app-artifacts/${encodeURIComponent(appId)}/listing`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ listed }),
    },
  );
}
