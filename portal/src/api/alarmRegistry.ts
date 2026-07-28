import { requestPortalApi } from "./portalWorkorders";

export interface AlarmRegistryRecord {
  alarmId: string;
  resId: string;
  title: string;
  deviceName: string;
  manageIp: string;
  eventTime: string;
  eventLastTime: string;
  actCount: string;
  visibleContent: string;
  additionalText: string;
  alarmLocation: string;
  status: string;
  sessionId: string;
  chatId: string;
  source: string;
  verificationStatus: string;
  lastError: string;
  createdAt: string;
  updatedAt: string;
  takenOverAt: string;
  handledAt: string;
  lastTriggeredAt: string;
  resolvedAt: string;
}

export interface AlarmRegistryListResponse {
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  items: AlarmRegistryRecord[];
}

export interface AlarmRegistryStatsResponse {
  total: number;
  byStatus: Record<string, number>;
}

export async function listAlarmRegistryRecords(params: {
  status?: string;
  page?: number;
  pageSize?: number;
  search?: string;
} = {}): Promise<AlarmRegistryListResponse> {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set("status", params.status);
  if (params.page) searchParams.set("page", String(params.page));
  if (params.pageSize) searchParams.set("page_size", String(params.pageSize));
  if (params.search) searchParams.set("search", params.search);
  const qs = searchParams.toString();
  return requestPortalApi<AlarmRegistryListResponse>(
    `/alarm-registry/records${qs ? `?${qs}` : ""}`,
  );
}

export async function updateAlarmRegistryStatus(
  alarmId: string,
  status: string,
  chatId?: string,
): Promise<{ ok: boolean; record: AlarmRegistryRecord }> {
  const body: Record<string, string> = { status };
  if (chatId) body.chatId = chatId;
  return requestPortalApi(`/alarm-registry/records/${encodeURIComponent(alarmId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function registerAlarmRecord(alarm: {
  alarmId: string;
  sessionId?: string;
  resId?: string;
  title?: string;
  deviceName?: string;
  manageIp?: string;
  eventTime?: string;
  eventLastTime?: string;
  actCount?: number;
  visibleContent?: string;
  additionalText?: string;
  alarmLocation?: string;
  status?: string;
  source?: string;
}): Promise<{ ok: boolean; record: AlarmRegistryRecord }> {
  return requestPortalApi("/alarm-registry/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(alarm),
  });
}

export async function getAlarmRegistryStats(): Promise<AlarmRegistryStatsResponse> {
  return requestPortalApi<AlarmRegistryStatsResponse>("/alarm-registry/stats");
}

export async function exportAlarmRegistryRecords(params: {
  status?: string;
} = {}): Promise<{ total: number; items: AlarmRegistryRecord[] }> {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set("status", params.status);
  const qs = searchParams.toString();
  return requestPortalApi(`/alarm-registry/export${qs ? `?${qs}` : ""}`);
}
