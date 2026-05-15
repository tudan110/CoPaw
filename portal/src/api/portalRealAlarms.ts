import { requestPortalApi } from "./portalWorkorders";

export interface PortalRealAlarmItem {
  id: string;
  resId: string;
  title: string;
  level: "critical" | "urgent" | "warning" | "info";
  status: "active";
  eventTime: string;
  timeLabel: string;
  deviceName: string;
  manageIp: string;
  employeeId: string;
  dispatchContent: string;
  visibleContent: string;
}

export interface PortalRealAlarmListResponse {
  total: number;
  items: PortalRealAlarmItem[];
  source: "live";
}

export async function listPortalRealAlarms(
  params: { limit?: number } = {},
): Promise<PortalRealAlarmListResponse> {
  const searchParams = new URLSearchParams();
  if (params.limit !== undefined) {
    searchParams.set("limit", String(params.limit));
  }
  return requestPortalApi<PortalRealAlarmListResponse>(
    `/real-alarms${searchParams.toString() ? `?${searchParams.toString()}` : ""}`,
  );
}
