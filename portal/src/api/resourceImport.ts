import type {
  ResourceImportMetadata,
  ResourceImportPreviewJob,
  ResourceImportPreview,
  ResourceImportResult,
  ResourceImportStartPayload,
} from "../types/resourceImport";

const DEFAULT_PORTAL_API_BASE_URL = "/portal-api";
const DEFAULT_REQUEST_TIMEOUT_MS = 30000;
const DEFAULT_FALLBACK_AGENT_ID = "default";
const RESOURCE_IMPORT_UPLOAD_TIMEOUT_MS: number | null = null;
// Per-poll fetch timeout. The polling endpoint reads in-memory job state
// plus a progress JSONL file; long progress files can push read time up.
// 120s is generous enough that a transient slow read no longer surfaces as
// a misleading "请求超时" while the LLM preview job is still progressing.
const RESOURCE_IMPORT_POLL_TIMEOUT_MS = 120000;

const PORTAL_API_BASE_URL = (
  import.meta.env.VITE_PORTAL_API_BASE_URL || DEFAULT_PORTAL_API_BASE_URL
).replace(/\/$/, "");

function getAgentCandidates(agentId?: string) {
  const fallbackAgentId =
    import.meta.env.VITE_COPAW_FALLBACK_AGENT_ID || DEFAULT_FALLBACK_AGENT_ID;
  return [...new Set([agentId, fallbackAgentId].filter(Boolean))];
}

function isMissingAgentResponse(status: number, errorText?: string) {
  return status === 404 && /Agent\s+['"].+['"]\s+not\s+found/i.test(errorText || "");
}

async function requestPortalApi<T = unknown>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number | null = DEFAULT_REQUEST_TIMEOUT_MS,
  agentId?: string,
): Promise<T> {
  const agentCandidates = getAgentCandidates(agentId);
  let lastErrorText = "";
  let lastStatus = 0;

  for (const candidateAgentId of agentCandidates) {
    const controller = new AbortController();
    const timerId = timeoutMs && timeoutMs > 0
      ? window.setTimeout(() => controller.abort(), timeoutMs)
      : null;

    try {
      const response = await fetch(`${PORTAL_API_BASE_URL}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          ...(init.headers || {}),
          ...(candidateAgentId ? { "X-Agent-Id": candidateAgentId } : {}),
        },
      });

      if (response.ok) {
        return response.json();
      }

      lastStatus = response.status;
      lastErrorText = await response.text().catch(() => "");
      if (!isMissingAgentResponse(response.status, lastErrorText)) {
        throw new Error(lastErrorText || "资源导入请求失败");
      }
    } catch (error: any) {
      if (error?.name === "AbortError") {
        throw new Error("请求超时，请稍后重试");
      }
      throw error;
    } finally {
      if (timerId !== null) {
        window.clearTimeout(timerId);
      }
    }
  }

  throw new Error(lastErrorText || `资源导入请求失败：${lastStatus}`);
}

export function getResourceImportMetadata(agentId?: string) {
  return requestPortalApi<ResourceImportMetadata>("/resource-import/metadata", {}, undefined, agentId);
}

export function getResourceImportStart(agentId?: string) {
  return requestPortalApi<ResourceImportStartPayload>("/resource-import/start", {}, undefined, agentId);
}

export function startResourceImportPreview(files: File[], agentId?: string) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file, file.name));
  return requestPortalApi<ResourceImportPreviewJob>(
    "/resource-import/preview",
    {
      method: "POST",
      body: formData,
    },
    RESOURCE_IMPORT_UPLOAD_TIMEOUT_MS,
    agentId,
  );
}

export function getResourceImportPreviewJob(jobId: string, agentId?: string) {
  return requestPortalApi<ResourceImportPreviewJob>(
    `/resource-import/preview/${encodeURIComponent(jobId)}`,
    {},
    RESOURCE_IMPORT_POLL_TIMEOUT_MS,
    agentId,
  );
}

export async function previewResourceImport(
  files: File[],
  agentId?: string,
  options?: {
    onProgress?: (job: ResourceImportPreviewJob) => void;
    pollIntervalMs?: number;
    maxWaitMs?: number;
  },
) {
  const pollIntervalMs = options?.pollIntervalMs ?? 1500;
  // Generous backstop only — the backend's bridge subprocess has its own
  // hard timeout (RESOURCE_IMPORT_SCRIPT_TIMEOUT_SECONDS) and will mark the
  // job as `failed` if the underlying skill takes too long. We keep this
  // as a last-resort guard against the backend going completely silent;
  // routine slow LLM preview should never hit it.
  const maxWaitMs = options?.maxWaitMs ?? 60 * 60 * 1000;
  const startedAt = Date.now();
  const initialJob = await startResourceImportPreview(files, agentId);
  options?.onProgress?.(initialJob);

  let currentJob = initialJob;
  while (Date.now() - startedAt <= maxWaitMs) {
    if (currentJob.status === "completed" && currentJob.preview) {
      return currentJob.preview;
    }
    if (currentJob.status === "failed") {
      throw new Error(currentJob.error || "资源解析失败");
    }
    await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs));
    try {
      currentJob = await getResourceImportPreviewJob(initialJob.jobId, agentId);
      options?.onProgress?.(currentJob);
    } catch (error: any) {
      // Polling-side failures (network blip, 60s+ slow read of the
      // growing progress file) are NOT user-visible. The job's authoritative
      // status lives on the backend; we only surface an error when the
      // backend itself reports `status === "failed"`. This avoids the
      // misleading "请求超时" toast that used to appear while the LLM
      // preview was still legitimately working.
      console.warn("[resource-import] preview poll failed, will retry", error);
    }
  }

  throw new Error("资源解析超时，请稍后重试");
}

export function submitResourceImport(payload: Record<string, unknown>, agentId?: string) {
  return requestPortalApi<ResourceImportResult>(
    "/resource-import/import",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    120000,
    agentId,
  );
}
