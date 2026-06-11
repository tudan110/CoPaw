import type {
  NlCustomizationActiveResponse,
  NlCustomizationAppListResponse,
  NlCustomizationApplyResponse,
  NlCustomizationDeleteResponse,
  NlCustomizationPreviewResponse,
  NlCustomizationPublishResponse,
  NlCustomizationVersionDetailResponse,
  NlCustomizationVersionListResponse,
} from "../types/naturalLanguageCustomization";

const DEFAULT_PORTAL_API_BASE_URL = "/portal-api";
const PORTAL_API_BASE_URL = (
  import.meta.env.VITE_PORTAL_API_BASE_URL || DEFAULT_PORTAL_API_BASE_URL
).replace(/\/$/, "");
const DEFAULT_REQUEST_TIMEOUT_MS = 30000;
const PREVIEW_REQUEST_TIMEOUT_MS = 90000;

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
        extractErrorMessage(await response.text()) || "轻应用工坊请求失败",
      );
    }
    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("轻应用工坊请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}

export function previewNlCustomization(payload: {
  prompt: string;
  title?: string;
  appId?: string;
}) {
  return requestPortalApi<NlCustomizationPreviewResponse>(
    "/nl-customization/preview",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    PREVIEW_REQUEST_TIMEOUT_MS,
  );
}

export function publishNlCustomization(payload: {
  preview: NlCustomizationPreviewResponse;
  requestedBy?: string;
  title?: string;
}) {
  return requestPortalApi<NlCustomizationPublishResponse>("/nl-customization/publish", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export function applyNlCustomizationVersion(payload: {
  versionId: string;
  requestedBy?: string;
}) {
  return requestPortalApi<NlCustomizationApplyResponse>("/nl-customization/apply", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export function updateNlCustomizationListing(payload: {
  versionId: string;
  listed: boolean;
  requestedBy?: string;
}) {
  return requestPortalApi<{
    versionId: string;
    listed: boolean;
    listedAt: string;
  }>("/nl-customization/listing", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export function listNlCustomizationVersions(limit = 20) {
  return requestPortalApi<NlCustomizationVersionListResponse>(
    `/nl-customization/versions?limit=${encodeURIComponent(String(limit))}`,
  );
}

export function getNlCustomizationVersion(versionId: string) {
  return requestPortalApi<NlCustomizationVersionDetailResponse>(
    `/nl-customization/versions/${encodeURIComponent(versionId)}`,
  );
}

export function deleteNlCustomizationVersion(versionId: string) {
  return requestPortalApi<NlCustomizationDeleteResponse>(
    `/nl-customization/versions/${encodeURIComponent(versionId)}`,
    {
      method: "DELETE",
    },
  );
}

export function getActiveNlCustomization() {
  return requestPortalApi<NlCustomizationActiveResponse>("/nl-customization/active");
}

export function classifyNlCustomizationPrompt(prompt: string) {
  return requestPortalApi<{
    recommendedKind: "page" | "task";
    scenarioType: string;
    triggerType: string;
    confidence: number;
  }>("/nl-customization/classify", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ prompt }),
  });
}

export function listNlCustomizationApps(limit = 50) {
  return requestPortalApi<NlCustomizationAppListResponse>(
    `/nl-customization/apps?limit=${encodeURIComponent(String(limit))}`,
  );
}
