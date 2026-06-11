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
      ...(options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.headers || {}),
    },
  });
}

export const settingsApi = {
  getNotificationChannels: () =>
    requestSettings<NotificationChannelSettings>("/settings/notification-channels"),

  updateNotificationChannels: (body: Partial<NotificationChannelSettings>) =>
    requestSettings<NotificationChannelSettings>("/settings/notification-channels", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

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
}

// Sentinel a PUT sends for the token field to clear its override.
export const DIAGNOSIS_TOKEN_CLEAR = "__CLEAR__";

export const diagnosisSettingsApi = {
  get: () =>
    requestSettings<DiagnosisSettingsPayload>("/diagnosis-settings"),

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
