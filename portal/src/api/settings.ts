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
  inspection: NotificationChannelScopeConfig;
  alarm_analyst: NotificationChannelScopeConfig;
  order_workflow: NotificationChannelScopeConfig;
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
};
