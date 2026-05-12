const DEFAULT_API_BASE_URL = "/copaw-api/api";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

interface SkillsRequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  agentId?: string;
}

export interface PoolSkillInfo {
  name: string;
  description: string;
  emoji: string;
  version_text: string;
  content: string;
  references: Record<string, unknown>;
  scripts: Record<string, unknown>;
  source: string;
  protected: boolean;
  commit_text: string;
  sync_status: string;
  latest_version_text: string;
  builtin_language?: string;
  available_builtin_languages?: string[];
  tags: string[];
  config: Record<string, unknown>;
  last_updated: string;
}

export interface WorkspaceSkillInfo {
  name: string;
  description: string;
  emoji: string;
  version_text: string;
  content: string;
  references: Record<string, unknown>;
  scripts: Record<string, unknown>;
  source: string;
  tags: string[];
  config: Record<string, unknown>;
  last_updated: string;
  enabled: boolean;
  channels: string[];
}

export interface WorkspaceSkillSummary {
  agent_id: string;
  agent_name: string;
  workspace_dir: string;
  skills: WorkspaceSkillInfo[];
}

export interface CreatePoolSkillRequest {
  name: string;
  content: string;
  config?: Record<string, unknown>;
}

export interface SavePoolSkillRequest {
  name: string;
  content: string;
  sourceName?: string;
  config?: Record<string, unknown>;
}

export interface SavePoolSkillResult {
  success: boolean;
  mode?: "edit" | "rename";
  name?: string;
  reason?: string;
  suggested_name?: string;
}

export interface BuiltinImportSpec {
  name: string;
  description: string;
  version_text: string;
  current_version_text: string;
  current_source: string;
  current_language: string;
  available_languages: string[];
  languages: Record<string, Record<string, unknown>>;
  status: string;
}

export interface SkillScanFinding {
  severity: string;
  title: string;
  description: string;
  file_path: string;
  line_number: number | null;
  rule_id: string;
}

export interface SkillScanErrorPayload {
  type: "security_scan_failed";
  detail: string;
  skill_name: string;
  max_severity: string;
  findings: SkillScanFinding[];
}

/** Thrown when the backend skill scanner blocks an import/enable. */
export class SkillScanError extends Error {
  readonly payload: SkillScanErrorPayload;

  constructor(payload: SkillScanErrorPayload) {
    super(payload.detail || `技能安全扫描未通过：${payload.skill_name}`);
    this.name = "SkillScanError";
    this.payload = payload;
  }
}

/** Thrown when an import would overwrite existing skills (HTTP 409). */
export class SkillConflictError extends Error {
  readonly conflicts: string[];
  readonly detail: unknown;

  constructor(conflicts: string[], detail: unknown, message?: string) {
    super(message || `技能名冲突：${conflicts.join(", ") || "已存在同名技能"}`);
    this.name = "SkillConflictError";
    this.conflicts = conflicts;
    this.detail = detail;
  }
}

function isScanErrorPayload(value: unknown): value is SkillScanErrorPayload {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    (value as { type?: unknown }).type === "security_scan_failed"
  );
}

function extractConflicts(detail: unknown): string[] {
  if (!detail || typeof detail !== "object") {
    return [];
  }
  const raw = (detail as { conflicts?: unknown }).conflicts;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      if (item && typeof item === "object") {
        const obj = item as { name?: unknown; skill_name?: unknown; reason?: unknown };
        return String(obj.name ?? obj.skill_name ?? obj.reason ?? "");
      }
      return "";
    })
    .filter(Boolean);
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

    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail as {
        reason?: unknown;
        suggested_name?: unknown;
      };
      if (typeof detail.suggested_name === "string" && detail.suggested_name) {
        return `技能名冲突，建议改用：${detail.suggested_name}`;
      }
      if (typeof detail.reason === "string" && detail.reason) {
        return `技能保存失败：${detail.reason}`;
      }
      return JSON.stringify(detail);
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

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => "");
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function throwForErrorBody(status: number, body: unknown): never {
  // The scan blocker is served as 422 with a structured payload; it may be the
  // body directly or nested under `detail` depending on the route.
  if (isScanErrorPayload(body)) {
    throw new SkillScanError(body);
  }
  if (body && typeof body === "object" && isScanErrorPayload((body as { detail?: unknown }).detail)) {
    throw new SkillScanError((body as { detail: SkillScanErrorPayload }).detail);
  }
  if (status === 409) {
    const detail =
      body && typeof body === "object" && "detail" in (body as object)
        ? (body as { detail: unknown }).detail
        : body;
    const conflicts = extractConflicts(detail) || extractConflicts(body);
    throw new SkillConflictError(conflicts, detail);
  }
  const text = typeof body === "string" ? body : body === undefined ? "" : JSON.stringify(body);
  throw new Error(extractErrorMessage(text) || `技能池请求失败：${status}`);
}

async function requestSkills<T>(
  path: string,
  { method = "GET", body, signal, agentId }: SkillsRequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  if (agentId) {
    headers["X-Agent-Id"] = agentId;
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    signal,
    headers: Object.keys(headers).length ? headers : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.ok) {
    if (response.status === 204) {
      return null as T;
    }
    return response.json() as Promise<T>;
  }

  throwForErrorBody(response.status, await parseBody(response));
}

async function requestSkillsForm<T>(
  path: string,
  formData: FormData,
  { method = "POST", agentId, signal }: { method?: string; agentId?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (agentId) {
    headers["X-Agent-Id"] = agentId;
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    signal,
    headers: Object.keys(headers).length ? headers : undefined,
    body: formData,
  });

  if (response.ok) {
    if (response.status === 204) {
      return null as T;
    }
    return response.json() as Promise<T>;
  }

  throwForErrorBody(response.status, await parseBody(response));
}

export interface SkillImportResult {
  count: number;
  conflicts: string[];
}

export interface HubImportResult {
  installed: boolean;
  name: string;
  enabled: boolean;
  source_url: string;
}

export interface BuiltinImportResult {
  added: string[];
  skipped: string[];
  conflicts: string[];
}

export interface PoolDownloadResult {
  downloaded: { workspace_id: string; workspace_name: string; name: string }[];
}

export type HubInstallTaskStatus =
  | "pending"
  | "importing"
  | "completed"
  | "failed"
  | "cancelled";

export interface HubInstallTask {
  task_id: string;
  bundle_url: string;
  version: string;
  enable: boolean;
  status: HubInstallTaskStatus;
  error: string | null;
  result:
    | { installed?: boolean; name?: string; enabled?: boolean; source_url?: string }
    | SkillScanErrorPayload
    | Record<string, unknown>
    | null;
  created_at: number;
  updated_at: number;
}

export const skillsApi = {
  listPoolSkills: (signal?: AbortSignal) =>
    requestSkills<PoolSkillInfo[]>("/skills/pool", { signal }),

  refreshPoolSkills: () =>
    requestSkills<PoolSkillInfo[]>("/skills/pool/refresh", { method: "POST" }),

  listWorkspaceSkills: (signal?: AbortSignal) =>
    requestSkills<WorkspaceSkillSummary[]>("/skills/workspaces", { signal }),

  createPoolSkill: (payload: CreatePoolSkillRequest) =>
    requestSkills<{ created: boolean; name: string }>("/skills/pool/create", {
      method: "POST",
      body: payload,
    }),

  savePoolSkill: (payload: SavePoolSkillRequest) =>
    requestSkills<SavePoolSkillResult>("/skills/pool/save", {
      method: "PUT",
      body: {
        name: payload.name,
        content: payload.content,
        source_name: payload.sourceName,
        config: payload.config || {},
      },
    }),

  updatePoolSkillTags: (skillName: string, tags: string[]) =>
    requestSkills<{ updated: boolean; tags: string[] }>(
      `/skills/pool/${encodeURIComponent(skillName)}/tags`,
      // FastAPI parses `tags: list[str]` (no Query()) as a JSON body, not a
      // query string — send the array as the request body. An empty array is
      // still truthy in JS, so `[]` is sent verbatim (= clear all tags).
      { method: "PUT", body: tags },
    ),

  deletePoolSkill: (skillName: string) =>
    requestSkills<{ deleted: boolean }>(`/skills/pool/${encodeURIComponent(skillName)}`, {
      method: "DELETE",
    }),

  uploadSkillZipToPool: (
    file: File,
    options: { targetName?: string; renameMap?: Record<string, string> } = {},
  ) => {
    const params = new URLSearchParams();
    if (options.targetName?.trim()) {
      params.set("target_name", options.targetName.trim());
    }
    if (options.renameMap && Object.keys(options.renameMap).length) {
      params.set("rename_map", JSON.stringify(options.renameMap));
    }
    const query = params.toString();
    const formData = new FormData();
    formData.append("file", file);
    return requestSkillsForm<SkillImportResult>(
      `/skills/pool/upload-zip${query ? `?${query}` : ""}`,
      formData,
    );
  },

  importSkillFromHub: (payload: { bundleUrl: string; version?: string; targetName?: string }) =>
    requestSkills<HubImportResult>("/skills/pool/import", {
      method: "POST",
      body: {
        bundle_url: payload.bundleUrl.trim(),
        version: payload.version?.trim() || "",
        target_name: payload.targetName?.trim() || "",
      },
    }),

  listBuiltinSources: (signal?: AbortSignal) =>
    requestSkills<BuiltinImportSpec[]>("/skills/pool/builtin-sources", { signal }),

  importBuiltinSkills: (payload: {
    imports: { skill_name: string; language?: string }[];
    overwriteConflicts?: boolean;
  }) =>
    requestSkills<BuiltinImportResult>("/skills/pool/import-builtin", {
      method: "POST",
      body: {
        imports: payload.imports.map((item) => ({
          skill_name: item.skill_name,
          language: item.language || "",
        })),
        overwrite_conflicts: Boolean(payload.overwriteConflicts),
      },
    }),

  downloadPoolSkill: (payload: {
    skillName: string;
    workspaceId: string;
    overwrite?: boolean;
    previewOnly?: boolean;
  }) =>
    requestSkills<PoolDownloadResult>("/skills/pool/download", {
      method: "POST",
      body: {
        skill_name: payload.skillName,
        targets: [{ workspace_id: payload.workspaceId }],
        overwrite: Boolean(payload.overwrite),
        preview_only: Boolean(payload.previewOnly),
      },
    }),

  enableWorkspaceSkill: (skillName: string, agentId: string) =>
    requestSkills<{ enabled: boolean }>(`/skills/${encodeURIComponent(skillName)}/enable`, {
      method: "POST",
      agentId,
    }),

  disableWorkspaceSkill: (skillName: string, agentId: string) =>
    requestSkills<{ disabled: boolean }>(`/skills/${encodeURIComponent(skillName)}/disable`, {
      method: "POST",
      agentId,
    }),

  // --- Agent-scoped (X-Agent-Id) workspace skill APIs ---

  listAgentSkills: (agentId: string, signal?: AbortSignal) =>
    requestSkills<WorkspaceSkillInfo[]>("/skills", { agentId, signal }),

  refreshAgentSkills: (agentId: string) =>
    requestSkills<WorkspaceSkillInfo[]>("/skills/refresh", {
      method: "POST",
      agentId,
    }),

  createAgentSkill: (
    agentId: string,
    payload: { name: string; content: string; config?: Record<string, unknown> },
  ) =>
    requestSkills<{ created: boolean; name: string }>("/skills", {
      method: "POST",
      agentId,
      body: {
        name: payload.name,
        content: payload.content,
        config: payload.config || {},
        enable: true,
      },
    }),

  saveAgentSkill: (
    agentId: string,
    payload: {
      name: string;
      sourceName?: string;
      content: string;
      config?: Record<string, unknown>;
      overwrite?: boolean;
    },
  ) =>
    requestSkills<SavePoolSkillResult>("/skills/save", {
      method: "PUT",
      agentId,
      body: {
        name: payload.name,
        source_name: payload.sourceName,
        content: payload.content,
        config: payload.config || {},
        overwrite: Boolean(payload.overwrite),
      },
    }),

  uploadSkillZipToAgent: (
    agentId: string,
    file: File,
    options: { targetName?: string; renameMap?: Record<string, string> } = {},
  ) => {
    const params = new URLSearchParams();
    params.set("enable", "true");
    if (options.targetName?.trim()) {
      params.set("target_name", options.targetName.trim());
    }
    if (options.renameMap && Object.keys(options.renameMap).length) {
      params.set("rename_map", JSON.stringify(options.renameMap));
    }
    const formData = new FormData();
    formData.append("file", file);
    return requestSkillsForm<SkillImportResult>(
      `/skills/upload?${params.toString()}`,
      formData,
      { agentId },
    );
  },

  updateAgentSkillTags: (agentId: string, skillName: string, tags: string[]) =>
    requestSkills<{ updated: boolean; tags: string[] }>(
      `/skills/${encodeURIComponent(skillName)}/tags`,
      // FastAPI parses `tags: list[str]` (no Query()) as a JSON body, not a
      // query string — send the array as the request body. An empty array is
      // still truthy in JS, so `[]` is sent verbatim (= clear all tags).
      { method: "PUT", agentId, body: tags },
    ),

  deleteAgentSkill: (agentId: string, skillName: string) =>
    requestSkills<{ deleted: boolean }>(`/skills/${encodeURIComponent(skillName)}`, {
      method: "DELETE",
      agentId,
    }),

  startHubInstallToAgent: (
    agentId: string,
    payload: { bundleUrl: string; version?: string; targetName?: string },
  ) =>
    requestSkills<HubInstallTask>("/skills/hub/install/start", {
      method: "POST",
      agentId,
      body: {
        bundle_url: payload.bundleUrl.trim(),
        version: payload.version?.trim() || "",
        target_name: payload.targetName?.trim() || "",
        enable: true,
      },
    }),

  getHubInstallStatus: (taskId: string, signal?: AbortSignal) =>
    requestSkills<HubInstallTask>(
      `/skills/hub/install/status/${encodeURIComponent(taskId)}`,
      { signal },
    ),
};
