import { requestPortalApi } from "./portalWorkorders";

export interface MonitoringEnvelope<T> {
  code: number;
  msg?: string;
  data: T | null;
}

export interface AlarmTop5Item {
  title?: string;
  count?: number;
}

export interface ResourceTypeStat {
  resourceTypeName?: string;
  totalCount?: number;
  normalCount?: number;
  alarmCount?: number;
}

export type HealthStatus = "green" | "yellow" | "red" | string;

export interface ApplicationHealth {
  platformName?: string;
  healthRate?: number;
  healthStatus?: HealthStatus;
  totalCount?: number;
  alarmCount?: number;
  responseTime?: number | string;
}

export interface HostResourceItem {
  resourceName?: string;
  usageRate?: number;
}

export interface AssetOverviewData {
  totalResources?: number;
  healthRate?: number;
  healthStatus?: HealthStatus;
  resourceTypeStats?: Record<string, ResourceTypeStat>;
  applicationHealthList?: ApplicationHealth[];
  hostResourceTop?: {
    cpuTop5?: HostResourceItem[];
    memoryTop5?: HostResourceItem[];
    storageTop5?: HostResourceItem[];
  };
}

export interface TopologyData {
  nodes?: Array<{
    id?: string;
    type?: string;
    alarmStatus?: string;
    deviceCount?: number;
    data?: { resources?: unknown[] };
  }>;
}

export interface WorkorderStatsData {
  inProgressCount?: number;
  finishedCount?: number;
  todoCount?: number;
}

export interface SeverityTrendPoint {
  formatDate?: string;
  data?: number;
}

// Keyed by severity level ("1"=紧急 / "2"=严重 / "3"=普通 / "4"=预警),
// each value a per-day series (the gateway only offers daily buckets).
export type SeverityTrendData = Record<string, SeverityTrendPoint[]>;

// CMDB CI summary — total_ci_count is the "资产总数" shown on the INOE
// homepage (source of truth for 纳管总资产).
export interface CmdbSummaryData {
  total_ci_count?: number;
  model_count?: number;
}

export interface MonitoringOverviewDashboardResponse {
  assetOverview: MonitoringEnvelope<AssetOverviewData>;
  alarmTop5: MonitoringEnvelope<AlarmTop5Item[]>;
  topology: MonitoringEnvelope<TopologyData>;
  workorderStats: MonitoringEnvelope<WorkorderStatsData>;
  severityTrend: MonitoringEnvelope<SeverityTrendData>;
  cmdbSummary: MonitoringEnvelope<CmdbSummaryData>;
  activeAlarmTotal: number;
}

const DASHBOARD_TIMEOUT_MS = 30000;

export async function getMonitoringOverviewDashboard(): Promise<MonitoringOverviewDashboardResponse> {
  return requestPortalApi<MonitoringOverviewDashboardResponse>(
    "/monitoring-overview/dashboard",
    {},
    DASHBOARD_TIMEOUT_MS,
  );
}

export async function getMonitoringAssetOverview(): Promise<MonitoringEnvelope<AssetOverviewData>> {
  return requestPortalApi<MonitoringEnvelope<AssetOverviewData>>(
    "/monitoring-overview/asset-overview",
    {},
    DASHBOARD_TIMEOUT_MS,
  );
}

export async function getMonitoringAlarmTop5(): Promise<MonitoringEnvelope<AlarmTop5Item[]>> {
  return requestPortalApi<MonitoringEnvelope<AlarmTop5Item[]>>(
    "/monitoring-overview/alarm-top5",
    {},
    DASHBOARD_TIMEOUT_MS,
  );
}

export async function getMonitoringTopology(): Promise<MonitoringEnvelope<TopologyData>> {
  return requestPortalApi<MonitoringEnvelope<TopologyData>>(
    "/monitoring-overview/topology",
    {},
    DASHBOARD_TIMEOUT_MS,
  );
}
