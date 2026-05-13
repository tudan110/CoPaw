// FDE 交付工作台 API 客户端。
// 后端路由前缀 `/api/portal/fde/*`，nginx 把 `/portal-api/*` 反代到那里。

const DEFAULT_PORTAL_API_BASE_URL = "/portal-api";
// Fast endpoints (workspace info, staged list).
const DEFAULT_REQUEST_TIMEOUT_MS = 45000;
// Endpoints whose backend run imports qwenpaw / scans / probes a skill.
const HEAVY_TIMEOUT_MS = 120000;

const PORTAL_API_BASE_URL = (
  import.meta.env.VITE_PORTAL_API_BASE_URL || DEFAULT_PORTAL_API_BASE_URL
).replace(/\/$/, "");

export class FdeWorkbenchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FdeWorkbenchError";
  }
}

async function requestFde<T = unknown>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number | null = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer =
    timeoutMs == null ? null : setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${PORTAL_API_BASE_URL}/fde${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers || {}),
      },
    });
    const text = await response.text();
    let body: unknown = undefined;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    if (!response.ok) {
      const detail =
        body && typeof body === "object" && "detail" in (body as object)
          ? String((body as { detail: unknown }).detail)
          : typeof body === "string"
            ? body
            : `请求失败 (${response.status})`;
      throw new FdeWorkbenchError(detail);
    }
    // 后端用 200 + {reason:"fde_workbench_error", detail} 表达业务错误
    if (
      body &&
      typeof body === "object" &&
      (body as { reason?: string }).reason === "fde_workbench_error"
    ) {
      throw new FdeWorkbenchError(
        String((body as { detail?: unknown }).detail || "FDE 工作台错误"),
      );
    }
    return body as T;
  } catch (error) {
    if (error instanceof FdeWorkbenchError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new FdeWorkbenchError("请求超时");
    }
    throw new FdeWorkbenchError(
      error instanceof Error ? error.message : "网络错误",
    );
  } finally {
    if (timer != null) {
      clearTimeout(timer);
    }
  }
}

// --- 返回类型（与后端 fde_tools.py 的 JSON 输出对齐） ---

export interface FdeWorkbenchInfo {
  available: boolean;
  reason?: string;
  agentId?: string;
  workspaceDir?: string;
  stagedDir?: string;
  onboardingSkill?: string;
}

export interface FdeStagedSummary {
  skill_name: string;
  staged_dir: string;
  target_workspace: string;
  created_at: string;
  open_questions: string[];
}

export interface FdeStagedListResult {
  staged_dir: string;
  skills: FdeStagedSummary[];
}

export interface FdeStagedFile {
  path: string;
  size: number;
  content?: string | null;
  binary?: boolean;
  truncated?: boolean;
}

export interface FdeSelfcheckResult {
  ok: boolean;
  skill_name?: string;
  skill_dir?: string;
  ready_for_review?: boolean;
  blocked_reasons?: string[];
  warnings?: string[];
  scan?: Record<string, unknown>;
  domain?: Record<string, unknown>;
  syntax?: Record<string, unknown>;
  todo?: string[];
  error?: string;
}

export interface FdeStagedDetail {
  skill_name: string;
  staged_dir: string;
  files: FdeStagedFile[];
  selfcheck: FdeSelfcheckResult;
}

export interface FdeGenerateResult {
  skill_name: string;
  target_workspace: string;
  staged_dir: string;
  files: string[];
  meta: Record<string, unknown>;
  selfcheck: FdeSelfcheckResult;
}

export interface FdeProbeResult {
  skill_dir: string;
  returncode?: number;
  stdout?: string;
  stderr?: string;
  ok: boolean;
  error?: string;
}

export interface FdeGatewayMirror {
  mirrored: boolean;
  gateway_agent: string;
  skipped_reason?: string | null;
}

export interface FdeInstallResult {
  installed: boolean;
  name: string;
  target_workspace: string;
  // true when the install path auto-created the target agent because it
  // didn't exist yet (one-click delivery).
  target_created?: boolean;
  // true when the domain_guard verdict cache was pre-warmed because the
  // operator clicked "强制安装(领域审核暂不可用)".
  domain_override_applied?: boolean;
  // .env keys that got written into the installed skill dir.
  env_written?: string[];
  // surfaced when the skill landed but writing .env failed (e.g. perms).
  env_error?: string;
  // 'true' when the skill was also installed into the gateway workspace
  // (so portal entry can trigger it). Skipped silently when target *is*
  // gateway or gateway already has same-named skill.
  gateway_mirror?: FdeGatewayMirror;
  files: string[];
  tag: string;
}

export interface FdeEnvField {
  key: string;
  default: string;
  // multi-line hint pulled from the leading # comments in .env.example
  hint: string;
}

export interface FdeInstalledSkill {
  agent_id: string;
  agent_name: string;
  skill_name: string;
  enabled: boolean;
  description: string;
  updated_at: string;
  tags: string[];
}

export interface FdeInstalledListResult {
  count: number;
  skills: FdeInstalledSkill[];
}

export interface FdeEnvState {
  target_workspace: string;
  skill_name: string;
  skill_dir: string;
  schema: FdeEnvField[];
  values: Record<string, string>;
  has_env: boolean;
  has_example: boolean;
}

export interface FdeBrief {
  description?: string;
  summary?: string;
  category?: string;
  title?: string;
  when_to_use?: string;
  tags?: string[];
  triggers?: string[];
  open_questions?: string[];
}

export const fdeApi = {
  getWorkbenchInfo: () => requestFde<FdeWorkbenchInfo>("/workspace"),

  listStaged: () => requestFde<FdeStagedListResult>("/staged"),

  listInstalled: () => requestFde<FdeInstalledListResult>("/installed"),

  copyInstalled: (
    sourceAgent: string,
    skillName: string,
    targetWorkspace: string,
    opts?: { removeSource?: boolean; skipDomainCheck?: boolean },
  ) =>
    requestFde<{
      copied: boolean;
      name: string;
      source_agent: string;
      target_workspace: string;
      target_created: boolean;
      removed_source: boolean;
      remove_error?: string;
      tag: string;
    }>(
      `/installed/${encodeURIComponent(sourceAgent)}/${encodeURIComponent(skillName)}/copy`,
      {
        method: "POST",
        body: JSON.stringify({
          target_workspace: targetWorkspace,
          remove_source: !!opts?.removeSource,
          skip_domain_check: !!opts?.skipDomainCheck,
        }),
      },
      HEAVY_TIMEOUT_MS,
    ),

  showStaged: (skillName: string) =>
    requestFde<FdeStagedDetail>(
      `/staged/${encodeURIComponent(skillName)}`,
      {},
      HEAVY_TIMEOUT_MS,
    ),

  generate: (payload: {
    name: string;
    targetWorkspace: string;
    brief?: FdeBrief;
  }) =>
    requestFde<FdeGenerateResult>(
      "/generate",
      {
        method: "POST",
        body: JSON.stringify({
          name: payload.name,
          target_workspace: payload.targetWorkspace,
          brief: payload.brief || {},
        }),
      },
      HEAVY_TIMEOUT_MS,
    ),

  selfcheckStaged: (skillName: string) =>
    requestFde<FdeSelfcheckResult>(
      `/staged/${encodeURIComponent(skillName)}/selfcheck`,
      { method: "POST" },
      HEAVY_TIMEOUT_MS,
    ),

  probeStaged: (skillName: string, context?: Record<string, unknown>) =>
    requestFde<FdeProbeResult>(
      `/staged/${encodeURIComponent(skillName)}/probe`,
      {
        method: "POST",
        body: JSON.stringify({ context: context || {} }),
      },
      HEAVY_TIMEOUT_MS,
    ),

  installStaged: (
    skillName: string,
    targetWorkspace?: string,
    opts?: {
      skipDomainCheck?: boolean;
      envValues?: Record<string, string>;
    },
  ) => {
    const body: Record<string, unknown> = {};
    if (targetWorkspace) body.target_workspace = targetWorkspace;
    if (opts?.skipDomainCheck) body.skip_domain_check = true;
    if (opts?.envValues && Object.keys(opts.envValues).length > 0) {
      body.env_values = opts.envValues;
    }
    return requestFde<FdeInstallResult>(
      `/staged/${encodeURIComponent(skillName)}/install`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
      HEAVY_TIMEOUT_MS,
    );
  },

  deleteInstalled: (targetWorkspace: string, skillName: string) =>
    requestFde<{
      deleted: boolean;
      target_workspace: string;
      skill_name: string;
      gateway_mirror_removed: boolean;
      gateway_mirror_skipped_reason: string | null;
    }>(
      `/installed/${encodeURIComponent(targetWorkspace)}/${encodeURIComponent(skillName)}`,
      { method: "DELETE" },
    ),

  readInstalledEnv: (targetWorkspace: string, skillName: string) =>
    requestFde<FdeEnvState>(
      `/installed/${encodeURIComponent(targetWorkspace)}/${encodeURIComponent(skillName)}/env`,
    ),

  writeInstalledEnv: (
    targetWorkspace: string,
    skillName: string,
    values: Record<string, string>,
  ) =>
    requestFde<{
      target_workspace: string;
      skill_name: string;
      skill_dir: string;
      keys: string[];
      wrote_count: number;
    }>(
      `/installed/${encodeURIComponent(targetWorkspace)}/${encodeURIComponent(skillName)}/env`,
      {
        method: "PUT",
        body: JSON.stringify({
          target_workspace: targetWorkspace,
          skill_name: skillName,
          values,
        }),
      },
    ),

  discardStaged: (skillName: string) =>
    requestFde<{ discarded: string }>(
      `/staged/${encodeURIComponent(skillName)}`,
      { method: "DELETE" },
    ),
};
