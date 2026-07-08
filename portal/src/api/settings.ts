import { requestPortalApi } from "./portalWorkorders";

export interface NotificationChannelScopeConfig {
  push_url: string;
  dingtalk_webhook_url: string;
  dingtalk_secret: string;
  feishu_webhook_url: string;
  feishu_secret: string;
  timeout_seconds: number;
  mention_all: boolean;
}

export interface NotificationChannelSettings {
  [scope: string]: NotificationChannelScopeConfig;
}

async function requestSettings<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return requestPortalApi<T>(path, {
    ...options,
    headers: {
      ...(options.method &&
      !["GET", "HEAD"].includes(options.method.toUpperCase())
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.headers || {}),
    },
  });
}

export const settingsApi = {
  getNotificationChannels: () =>
    requestSettings<NotificationChannelSettings>(
      "/settings/notification-channels",
    ),

  updateNotificationChannels: (body: Partial<NotificationChannelSettings>) =>
    requestSettings<NotificationChannelSettings>(
      "/settings/notification-channels",
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  deleteNotificationChannel: (scope: string) =>
    requestSettings<NotificationChannelSettings>(
      `/settings/notification-channels/${encodeURIComponent(scope)}`,
      {
        method: "DELETE",
      },
    ),
};

// --- Alarm diagnosis settings (DB override > env > default) ---

// Masked representation returned for sensitive fields (token).
export interface MaskedSecret {
  is_set: boolean;
  masked: string;
}

// Effective / env layers. Non-sensitive fields are raw scalars; the token
// field is a MaskedSecret. `overrides[key]` is true when the field has a
// page-set value (vs. falling back to env).
export interface DiagnosisSettingsPayload {
  effective: Record<string, number | boolean | string | MaskedSecret>;
  env: Record<string, number | boolean | string | MaskedSecret>;
  overrides: Record<string, boolean>;
  groups: Record<string, string>;
  // Read-only runtime state, e.g. analysis_started_at (ISO time when
  // real-time analysis was last switched on). Never settable via PUT.
  state?: Record<string, string>;
}

// Sentinel a PUT sends for the token field to clear its override.
export const DIAGNOSIS_TOKEN_CLEAR = "__CLEAR__";

export const diagnosisSettingsApi = {
  get: () => requestSettings<DiagnosisSettingsPayload>("/diagnosis-settings"),

  update: (body: Record<string, number | boolean | string>) =>
    requestSettings<DiagnosisSettingsPayload>("/diagnosis-settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  reset: (key: string) =>
    requestSettings<DiagnosisSettingsPayload>("/diagnosis-settings/reset", {
      method: "POST",
      body: JSON.stringify({ key }),
    }),
};

// --- INOE gateway connection (standalone settings concern) ---
//
// The INOE alarm-gateway (base URL / token / timeout) is shared by the
// monitoring overview, real-alarm list and workorder bridge, so it has its
// own namespace + endpoint. The payload shape matches DiagnosisSettingsPayload.

export const inoeSettingsApi = {
  get: () => requestSettings<DiagnosisSettingsPayload>("/inoe-settings"),

  update: (body: Record<string, number | boolean | string>) =>
    requestSettings<DiagnosisSettingsPayload>("/inoe-settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  reset: (key: string) =>
    requestSettings<DiagnosisSettingsPayload>("/inoe-settings/reset", {
      method: "POST",
      body: JSON.stringify({ key }),
    }),
};

// --- Model-provider adapters (Qiming / Xingchen / Kunlun) ---
//
// Connection + credentials + models for the OpenAI-compatible adapters,
// migrated off .env into the settings page. Same payload shape as above.

export interface ProviderSettingsApi {
  get: () => Promise<DiagnosisSettingsPayload>;
  update: (
    body: Record<string, number | boolean | string>,
  ) => Promise<DiagnosisSettingsPayload>;
  reset: (key: string) => Promise<DiagnosisSettingsPayload>;
}

function makeProviderSettingsApi(base: string): ProviderSettingsApi {
  return {
    get: () => requestSettings<DiagnosisSettingsPayload>(base),
    update: (body) =>
      requestSettings<DiagnosisSettingsPayload>(base, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    reset: (key: string) =>
      requestSettings<DiagnosisSettingsPayload>(`${base}/reset`, {
        method: "POST",
        body: JSON.stringify({ key }),
      }),
  };
}

export const qimingSettingsApi = makeProviderSettingsApi("/qiming-settings");
export const xingchenSettingsApi =
  makeProviderSettingsApi("/xingchen-settings");
export const kunlunSettingsApi = makeProviderSettingsApi("/kunlun-settings");
export const zgopsSettingsApi = makeProviderSettingsApi("/zgops-settings");
export const n9eSettingsApi = makeProviderSettingsApi("/n9e-settings");
// INOE OAuth2 single-sign-on credentials. The SSO router mounts under
// /sso within the portal API, so its settings live at /sso/sso-settings.
export const ssoSettingsApi = makeProviderSettingsApi("/sso/sso-settings");

// --- Operator (page-operator) menu connection ---
//
// The 操作 agent's page-operator skill resolves portal routes from an INOE
// menu endpoint via its own OPERATOR_MENU_* env vars, independent of the 平台
// (INOE) tab that drives page-navigator. Same payload shape as the providers.
export const operatorSettingsApi =
  makeProviderSettingsApi("/operator-settings");

// --- Work-order (order-workflow / ferry) connection ---
//
// The 工单 path resolves the ferry work-order API from its own ORDER_* env
// vars, falling back to the shared INOE connection (平台 tab) when left empty.
// Same payload shape as the other providers.
export const orderSettingsApi = makeProviderSettingsApi("/order-settings");

// --- Resource-import LLM pool (zgops-cmdb) ---
//
// Dynamic pool of OpenAI-compatible models (variable count) + 2 scalars.
// api_key is masked on read; empty on write keeps the stored key by row.

export interface ResourceImportLlmModel {
  base_url: string;
  model: string;
  vision_model: string;
  api_key: MaskedSecret;
}

export interface ResourceImportLlmPayload {
  scalars: { sheet_parallelism: number; step_timeout: number };
  models: ResourceImportLlmModel[];
}

// Write shape: api_key is a plain string ("" = keep existing for that row).
export interface ResourceImportLlmModelInput {
  base_url: string;
  model: string;
  vision_model: string;
  api_key: string;
}

export interface ResourceImportLlmUpdate {
  scalars?: { sheet_parallelism: number; step_timeout: number };
  models?: ResourceImportLlmModelInput[];
}

export const resourceImportLlmApi = {
  get: () =>
    requestSettings<ResourceImportLlmPayload>("/resource-import-llm-settings"),

  update: (body: ResourceImportLlmUpdate) =>
    requestSettings<ResourceImportLlmPayload>("/resource-import-llm-settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
