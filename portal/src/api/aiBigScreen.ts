import { requestPortalApi } from "./portalWorkorders";
import type {
  AiBigScreenApp,
  AiBigScreenDeleteResponse,
  AiBigScreenListResponse,
  AiBigScreenPatchResponse,
  AiBigScreenPluginsResponse,
  AiBigScreenPublishResponse,
  AiBigScreenResponse,
  AiBigScreenTaskResponse,
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

export function createAiBigScreenDraftTask(payload: {
  prompt: string;
  title?: string;
  requestedBy?: string;
}) {
  return requestPortalApi<AiBigScreenTaskResponse>(
    "/ai-big-screens/draft-tasks",
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

export function getAiBigScreenDraftTask(taskId: string) {
  return requestPortalApi<AiBigScreenTaskResponse>(
    `/ai-big-screens/draft-tasks/${encodeURIComponent(taskId)}`,
    {},
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}

export function saveAiBigScreen(
  screen: AiBigScreenApp,
  requestedBy = "portal",
) {
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

export function renameAiBigScreen(
  screenId: string,
  payload: {
    name: string;
    requestedBy?: string;
  },
) {
  return requestPortalApi<AiBigScreenResponse>(
    `/ai-big-screens/${encodeURIComponent(screenId)}/rename`,
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

export function duplicateAiBigScreen(
  screenId: string,
  payload: {
    name?: string;
    requestedBy?: string;
  } = {},
) {
  return requestPortalApi<AiBigScreenResponse>(
    `/ai-big-screens/${encodeURIComponent(screenId)}/duplicate`,
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

export function refreshAiBigScreen(screenId: string) {
  return requestPortalApi<AiBigScreenResponse>(
    `/ai-big-screens/${encodeURIComponent(screenId)}/refresh`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    },
    AI_BIG_SCREEN_TIMEOUT_MS,
  );
}

export function patchAiBigScreen(
  screenId: string,
  payload: {
    baseVersionId?: string;
    selectedComponentId?: string;
    selectedComponentIds?: string[];
    selectedRegion?: Record<string, unknown>;
    selectionContext?: Record<string, unknown>;
    instruction: string;
    requestedBy?: string;
    /** dry-run: compute the diff on a copy without persisting/versioning. */
    preview?: boolean;
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
