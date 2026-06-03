import { requestPortalApi } from "./portalWorkorders";
import type {
  AiBigScreenApp,
  AiBigScreenDeleteResponse,
  AiBigScreenListResponse,
  AiBigScreenPatchResponse,
  AiBigScreenPluginsResponse,
  AiBigScreenPublishResponse,
  AiBigScreenResponse,
} from "../types/aiBigScreen";

const AI_BIG_SCREEN_TIMEOUT_MS = 45000;
const AI_BIG_SCREEN_GENERATION_TIMEOUT_MS = 600000;

export function listAiBigScreenPlugins() {
  return requestPortalApi<AiBigScreenPluginsResponse>(
    "/ai-big-screens/plugins",
    {},
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}

export function listAiBigScreens(limit = 50) {
  return requestPortalApi<AiBigScreenListResponse>(
    `/ai-big-screens?limit=${encodeURIComponent(String(limit))}`,
    {},
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}

export function generateAiBigScreenDraft(payload: {
  prompt: string;
  title?: string;
  requestedBy?: string;
}) {
  return requestPortalApi<AiBigScreenResponse>(
    "/ai-big-screens/draft",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    AI_BIG_SCREEN_GENERATION_TIMEOUT_MS,
  );
}

export function saveAiBigScreen(screen: AiBigScreenApp, requestedBy = "portal") {
  return requestPortalApi<AiBigScreenResponse>(
    "/ai-big-screens",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ screen, requestedBy }),
    },
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}

export function getAiBigScreen(screenId: string) {
  return requestPortalApi<AiBigScreenResponse>(
    `/ai-big-screens/${encodeURIComponent(screenId)}`,
    {},
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}

export function deleteAiBigScreen(screenId: string) {
  return requestPortalApi<AiBigScreenDeleteResponse>(
    `/ai-big-screens/${encodeURIComponent(screenId)}`,
    {
      method: "DELETE",
    },
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}

export function patchAiBigScreen(
  screenId: string,
  payload: {
    baseVersionId?: string;
    selectedComponentId?: string;
    instruction: string;
    requestedBy?: string;
  },
) {
  return requestPortalApi<AiBigScreenPatchResponse>(
    `/ai-big-screens/${encodeURIComponent(screenId)}/patch`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    AI_BIG_SCREEN_GENERATION_TIMEOUT_MS,
  );
}

export function publishAiBigScreen(
  screenId: string,
  payload: {
    requestedBy?: string;
    visibility?: string;
  } = {},
) {
  return requestPortalApi<AiBigScreenPublishResponse>(
    `/ai-big-screens/${encodeURIComponent(screenId)}/publish`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}
