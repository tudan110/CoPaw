import type {
  NlCustomizationPreviewResponse,
  NlCustomizationPublishResponse,
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
        extractErrorMessage(await response.text()) || "自然语言定制请求失败",
      );
    }
    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("自然语言定制请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}

export function previewNlCustomization(payload: {
  prompt: string;
  title?: string;
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

export function listNlCustomizationVersions(limit = 20) {
  return requestPortalApi<NlCustomizationVersionListResponse>(
    `/nl-customization/versions?limit=${encodeURIComponent(String(limit))}`,
  );
}
