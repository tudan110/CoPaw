import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import DigitalEmployeeAvatar from "../../components/DigitalEmployeeAvatar";
import { digitalEmployees } from "../../data/portalData";
import {
  getMonitoringOverviewDashboard,
  type AlarmTop5Item,
  type AssetOverviewData,
  type BusinessCockpitData,
  type BusinessSystem,
  type CmdbSummaryData,
  type MonitoringOverviewDashboardResponse,
  type ResourceTypeStat,
  type SeverityTrendData,
  type WorkorderStatsData,
} from "../../api/monitoringOverview";

type OverviewEmployee = (typeof digitalEmployees)[number] & {
  statusLabel?: string;
};

type OverviewPanelProps = {
  pageTheme: "light" | "dark";
  onOpenEmployeeChat: (employeeId: string) => void;
  employees: OverviewEmployee[];
};

type OverviewKpi = {
  label: string;
  value: string;
  trend: "up" | "down" | "flat";
  trendValue: string;
  color: string;
  barPct: number;
  iconClass: string;
};

type OverviewAlert = {
  level: string;
  color: string;
  count: number;
  pct: number;
};

type OverviewTicket = {
  label: string;
  value: string | number;
  color: string;
};

type OverviewService = {
  name: string;
  status: "healthy" | "warning" | "critical";
  health: string;
  availability: string;
};

type OverviewEvent = {
  title: string;
  time: string;
  color: string;
  iconClass: string;
  employeeId?: string;
};

const EMPLOYEE_ORDER = [
  "resource",
  "fault",
  "inspection",
  "order",
  "query",
  "knowledge",
] as const;

const STATUS_LABELS: Record<string, string> = {
  running: "运行中",
  urgent: "紧急处理中",
  idle: "待机",
  stopped: "已停止",
  pending: "待执行",
  completed: "已完成",
};

const BUSINESS_STATUS_TO_SERVICE: Record<string, OverviewService["status"]> = {
  "0": "healthy",
  "1": "warning",
  "2": "critical",
};

const RESOURCE_TYPE_ICONS: Array<{ keywords: string[]; icon: string; color: string }> = [
  { keywords: ["云主机", "虚拟机", "vm", "host"], icon: "fa-cloud", color: "#6366f1" },
  { keywords: ["主机", "服务器", "server"], icon: "fa-server", color: "#3b82f6" },
  { keywords: ["网络", "交换", "路由", "switch", "router", "network"], icon: "fa-network-wired", color: "#22c55e" },
  { keywords: ["数据库", "db", "mysql", "oracle", "postgre"], icon: "fa-database", color: "#0ea5e9" },
  { keywords: ["存储", "storage", "oss", "ceph"], icon: "fa-hard-drive", color: "#f59e0b" },
  { keywords: ["中间件", "kafka", "redis", "mq"], icon: "fa-layer-group", color: "#a855f7" },
  { keywords: ["容器", "kubernetes", "k8s", "pod"], icon: "fa-cubes", color: "#14b8a6" },
];

// 今日工单卡配色。中文映射沿用 order-workflow skill 的既有约定:
// 待处理=inProgressCount、进行中=todoCount、已完成=finishedCount。
const TICKET_COLORS = {
  pending: "#f59e0b",
  inProgress: "#3b82f6",
  done: "#22c55e",
  rate: "#6366f1",
} as const;

function buildTickets(stats: WorkorderStatsData | null): OverviewTicket[] {
  const pending = Number(stats?.inProgressCount ?? 0);
  const inProgress = Number(stats?.todoCount ?? 0);
  const done = Number(stats?.finishedCount ?? 0);
  const total = pending + inProgress + done;
  const rate = total > 0 ? Math.round((done / total) * 100) : 0;
  return [
    { label: "待处理", value: pending, color: TICKET_COLORS.pending },
    { label: "进行中", value: inProgress, color: TICKET_COLORS.inProgress },
    { label: "已完成", value: done, color: TICKET_COLORS.done },
    {
      label: "完成率",
      value: total > 0 ? `${rate}%` : "—",
      color: TICKET_COLORS.rate,
    },
  ];
}

// Severity-trend levels, aligned with the gateway's statSeverityTrend keys.
const SEVERITY_TREND_META = [
  { key: "1", name: "紧急", color: "#ef4444" },
  { key: "2", name: "严重", color: "#f97316" },
  { key: "3", name: "普通", color: "#f59e0b" },
  { key: "4", name: "预警", color: "#22d3ee" },
] as const;

type SeverityTrendModel = {
  dates: string[];
  series: Array<{ name: string; color: string; data: number[] }>;
};

function formatTrendDate(raw: string | undefined): string {
  const match = String(raw || "").match(/\d{4}-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}` : String(raw || "");
}

function buildSeverityTrend(trend: SeverityTrendData | null): SeverityTrendModel {
  if (!trend) return { dates: [], series: [] };
  // Date axis from any non-empty level (levels share the same days), ascending.
  const sample =
    SEVERITY_TREND_META.map((meta) => trend[meta.key]).find(
      (arr) => Array.isArray(arr) && arr.length > 0,
    ) || [];
  const dateKeys = [...sample]
    .map((point) => String(point.formatDate || ""))
    .sort((a, b) => a.localeCompare(b));
  if (dateKeys.length === 0) return { dates: [], series: [] };
  const series = SEVERITY_TREND_META.map((meta) => {
    const byDate = new Map(
      (trend[meta.key] || []).map((point) => [
        String(point.formatDate || ""),
        Number(point.data || 0),
      ]),
    );
    return {
      name: meta.name,
      color: meta.color,
      data: dateKeys.map((key) => byDate.get(key) ?? 0),
    };
  });
  return { dates: dateKeys.map(formatTrendDate), series };
}

const EMPTY_KPI: OverviewKpi = {
  label: "—",
  value: "—",
  trend: "flat",
  trendValue: "—",
  color: "#94a3b8",
  barPct: 0,
  iconClass: "fa-circle-notch",
};

function pickResourceTypeIcon(name: string | undefined): { icon: string; color: string } {
  const lowered = String(name || "").toLowerCase();
  for (const entry of RESOURCE_TYPE_ICONS) {
    if (entry.keywords.some((kw) => lowered.includes(kw))) {
      return { icon: entry.icon, color: entry.color };
    }
  }
  return { icon: "fa-cube", color: "#64748b" };
}

function toResourceTypeStats(
  stats: AssetOverviewData["resourceTypeStats"] | undefined,
): ResourceTypeStat[] {
  if (!stats || typeof stats !== "object") return [];
  return Object.values(stats).filter(
    (entry): entry is ResourceTypeStat => Boolean(entry) && typeof entry === "object",
  );
}

function buildKpiCards(
  asset: AssetOverviewData | null,
  employees: OverviewEmployee[],
  activeAlarmTotal: number,
  workorderStats: WorkorderStatsData | null,
  cmdbSummary: CmdbSummaryData | null,
): OverviewKpi[] {
  const totalResources = Number(asset?.totalResources ?? 0);
  // 纳管总资产以 CMDB total_ci_count 为准(对齐 INOE 首页);取不到时降级
  // 回资产总览的 totalResources。
  const cmdbTotal =
    cmdbSummary && cmdbSummary.total_ci_count != null
      ? Number(cmdbSummary.total_ci_count)
      : null;
  const managedTotal = cmdbTotal ?? (asset ? totalResources : null);
  const healthRate = Number(asset?.healthRate ?? 0);
  const stats = toResourceTypeStats(asset?.resourceTypeStats);
  const onlineEmployees = employees.filter(
    (employee) => employee.status === "running" || employee.urgent,
  ).length;
  const workorderTotal = workorderStats
    ? Number(workorderStats.inProgressCount ?? 0) +
      Number(workorderStats.todoCount ?? 0) +
      Number(workorderStats.finishedCount ?? 0)
    : null;
  const workorderDone = Number(workorderStats?.finishedCount ?? 0);
  const workorderRate =
    workorderTotal && workorderTotal > 0
      ? (workorderDone / workorderTotal) * 100
      : 0;

  const baseCards: OverviewKpi[] = [
    {
      label: "业务可用率",
      value: asset ? `${healthRate.toFixed(2)}%` : "—",
      trend: "flat",
      trendValue: asset ? "实时" : "—",
      color: "#22c55e",
      barPct: Math.max(0, Math.min(100, healthRate)),
      iconClass: "fa-heart-pulse",
    },
    {
      label: "活跃告警",
      value: String(activeAlarmTotal),
      trend: "flat",
      trendValue: "实时",
      color: "#ef4444",
      barPct: activeAlarmTotal > 0 ? Math.min(100, activeAlarmTotal) : 0,
      iconClass: "fa-triangle-exclamation",
    },
    {
      label: "今日工单",
      value: workorderTotal !== null ? String(workorderTotal) : "—",
      trend: "flat",
      trendValue: workorderTotal !== null ? "实时" : "待接入",
      color: "#6366f1",
      barPct: Math.max(0, Math.min(100, workorderRate)),
      iconClass: "fa-square-check",
    },
    {
      label: "数字员工在线",
      value: employees.length > 0 ? `${onlineEmployees}/${employees.length}` : "—",
      trend: "flat",
      trendValue: "稳定",
      color: "#22d3ee",
      barPct: employees.length > 0 ? (onlineEmployees / employees.length) * 100 : 0,
      iconClass: "fa-users",
    },
    {
      label: "纳管总资产",
      value: managedTotal != null ? managedTotal.toLocaleString() : "—",
      trend: "flat",
      trendValue: managedTotal != null ? "资产" : "—",
      color: "#3b82f6",
      barPct: 100,
      iconClass: "fa-server",
    },
  ];

  const topResourceTypes = stats
    .slice()
    .sort((a, b) => Number(b.totalCount || 0) - Number(a.totalCount || 0))
    .slice(0, 3);

  const resourceCards: OverviewKpi[] = topResourceTypes.map((stat) => {
    const total = Number(stat.totalCount || 0);
    const pct = totalResources > 0 ? (total / totalResources) * 100 : 0;
    const { icon, color } = pickResourceTypeIcon(stat.resourceTypeName);
    return {
      label: stat.resourceTypeName || "未知类型",
      value: total.toLocaleString(),
      trend: "flat",
      trendValue: stat.alarmCount ? `${stat.alarmCount} 告警` : "正常",
      color,
      barPct: Math.max(0, Math.min(100, pct)),
      iconClass: icon,
    };
  });

  const cards = [...baseCards, ...resourceCards];
  while (cards.length < 8) {
    cards.push({ ...EMPTY_KPI });
  }
  return cards.slice(0, 8);
}

function buildAlerts(top5: AlarmTop5Item[] | null): OverviewAlert[] {
  if (!top5 || top5.length === 0) {
    return [{ level: "暂无告警", color: "#22c55e", count: 0, pct: 0 }];
  }
  const sorted = top5
    .slice()
    .sort((a, b) => Number(b.count || 0) - Number(a.count || 0))
    .slice(0, 5);
  const maxCount = sorted.reduce((max, item) => Math.max(max, Number(item.count || 0)), 1);
  const palette = ["#ef4444", "#f97316", "#f59e0b", "#22d3ee", "#6366f1"];
  return sorted.map((item, index) => ({
    level: item.title || "未命名",
    color: palette[index] || "#64748b",
    count: Number(item.count || 0),
    pct: Math.max(8, (Number(item.count || 0) / maxCount) * 100),
  }));
}

function formatPercent(value: number | string | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(String(value).replace(/%$/, ""));
  return Number.isFinite(numeric) ? `${numeric.toFixed(2)}%` : "—";
}

function buildServices(apps: BusinessSystem[] | undefined): OverviewService[] {
  if (!apps || apps.length === 0) return [];
  return apps.slice(0, 8).map((app) => {
    const status =
      BUSINESS_STATUS_TO_SERVICE[String(app.status ?? "")] || "healthy";
    const errorAssets = Number(app.errorAssets ?? 0);
    const alarmCount = Number(app.alarmCount ?? 0);
    const availability =
      app.rate !== undefined && app.rate !== null && app.rate !== ""
        ? formatPercent(app.rate)
        : errorAssets + alarmCount > 0
          ? `异常 ${errorAssets + alarmCount}`
          : "—";
    return {
      name: app.systemName || "未命名业务系统",
      status,
      health: formatPercent(app.healthPercent),
      availability,
    };
  });
}

function buildEvents(top5: AlarmTop5Item[] | null): OverviewEvent[] {
  if (!top5 || top5.length === 0) return [];
  return top5.slice(0, 8).map((item) => ({
    title: `${item.title || "未命名告警对象"} · ${item.count ?? 0} 次`,
    time: "实时",
    color: "#ef4444",
    iconClass: "fa-triangle-exclamation",
    employeeId: "fault",
  }));
}

function envelopeData<T>(
  envelope: { code?: number; data?: T | null } | null | undefined,
): T | null {
  if (!envelope) return null;
  if (envelope.code !== 200) return null;
  return (envelope.data ?? null) as T | null;
}

export function OverviewPanel({ pageTheme, onOpenEmployeeChat, employees }: OverviewPanelProps) {
  const isDark = pageTheme === "dark";
  const [dashboard, setDashboard] = useState<MonitoringOverviewDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErrorMessage(null);
    getMonitoringOverviewDashboard()
      .then((payload) => {
        if (cancelled) return;
        setDashboard(payload);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setErrorMessage(message || "获取监控总览失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const assetOverview = envelopeData<AssetOverviewData>(dashboard?.assetOverview);
  const businessCockpit = envelopeData<BusinessCockpitData>(dashboard?.businessCockpit);
  const alarmTop5 = envelopeData<AlarmTop5Item[]>(dashboard?.alarmTop5);
  const workorderStats = envelopeData<WorkorderStatsData>(dashboard?.workorderStats);
  const severityTrend = envelopeData<SeverityTrendData>(dashboard?.severityTrend);
  const cmdbSummary = envelopeData<CmdbSummaryData>(dashboard?.cmdbSummary);
  const activeAlarmTotal = Number(dashboard?.activeAlarmTotal ?? 0);

  const assetOverviewError = dashboard?.assetOverview && dashboard.assetOverview.code !== 200
    ? dashboard.assetOverview.msg || null
    : null;

  const orderedEmployees = useMemo(
    () =>
      EMPLOYEE_ORDER
        .map((id) => employees.find((employee) => employee.id === id))
        .filter((employee): employee is OverviewEmployee => Boolean(employee)),
    [employees],
  );
  const orderedEmployeesWithStatus = useMemo(
    () =>
      orderedEmployees.map((employee) => ({
        ...employee,
        statusClass: employee.urgent ? "urgent" : employee.status === "running" ? "running" : "stopped",
        statusText: employee.statusLabel || STATUS_LABELS[employee.status] || employee.status,
      })),
    [orderedEmployees],
  );

  const kpiCards = useMemo(
    () =>
      buildKpiCards(
        assetOverview,
        employees,
        activeAlarmTotal,
        workorderStats,
        cmdbSummary,
      ),
    [assetOverview, employees, activeAlarmTotal, workorderStats, cmdbSummary],
  );
  const tickets = useMemo(() => buildTickets(workorderStats), [workorderStats]);
  const alerts = useMemo(() => buildAlerts(alarmTop5), [alarmTop5]);
  const services = useMemo(
    () => buildServices(businessCockpit?.businessSystems),
    [businessCockpit],
  );
  const events = useMemo(() => buildEvents(alarmTop5), [alarmTop5]);

  const trend = useMemo(
    () => buildSeverityTrend(severityTrend),
    [severityTrend],
  );

  const chartOption = useMemo<EChartsOption>(
    () => ({
      grid: { top: 26, right: 10, bottom: 24, left: 32 },
      legend: {
        top: 0,
        icon: "roundRect",
        itemWidth: 8,
        itemHeight: 8,
        itemGap: 10,
        textStyle: {
          fontSize: 9,
          color: isDark ? "#94a3b8" : "#64748b",
        },
        data: trend.series.map((item) => item.name),
      },
      xAxis: {
        type: "category",
        data: trend.dates,
        axisLabel: {
          fontSize: 9,
          color: isDark ? "#64748b" : "#94a3b8",
          interval: 0,
        },
        axisLine: {
          lineStyle: {
            color: isDark ? "rgba(255,255,255,.07)" : "rgba(0,0,0,.07)",
          },
        },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        splitLine: {
          lineStyle: {
            color: isDark ? "rgba(255,255,255,.05)" : "rgba(0,0,0,.05)",
          },
        },
        axisLabel: {
          fontSize: 9,
          color: isDark ? "#64748b" : "#94a3b8",
        },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: isDark ? "#1c2130" : "#fff",
        borderColor: isDark ? "rgba(255,255,255,.1)" : "rgba(0,0,0,.1)",
        textStyle: {
          fontSize: 11,
          color: isDark ? "#e2e8f0" : "#1e293b",
        },
      },
      series: trend.series.map((item) => ({
        name: item.name,
        type: "line",
        smooth: true,
        symbol: "none",
        lineStyle: { width: 2, color: item.color },
        itemStyle: { color: item.color },
        data: item.data,
      })),
    }),
    [isDark, trend],
  );

  const statusHint = loading
    ? "正在加载实时数据…"
    : errorMessage
      ? `加载失败：${errorMessage}`
      : assetOverviewError
        ? `资产总览接口提示：${assetOverviewError}`
        : null;

  return (
    <div className="portal-overview portal-overview-reference">
      <div className="overview-main-header">
        <div className="overview-main-title">
          <span className="overview-live-dot" />
          数字总览
          <small>{statusHint || "全局态势感知"}</small>
        </div>
      </div>

      <section className="overview-ref-top">
        {kpiCards.map((card, index) => (
          <article key={`${card.label}-${index}`} className="overview-ref-kpi">
            <div className="overview-ref-kpi-head">
              <div className="overview-ref-kpi-icon" style={{ background: card.color }}>
                <i className={`fas ${card.iconClass}`} />
              </div>
              <div className={`overview-ref-kpi-trend ${card.trend}`}>{card.trendValue}</div>
            </div>
            <div className="overview-ref-kpi-value" style={{ color: card.color }}>
              {card.value}
            </div>
            <div className="overview-ref-kpi-label">{card.label}</div>
            <div className="overview-ref-kpi-bar">
              <div
                className="overview-ref-kpi-bar-fill"
                style={{ width: `${card.barPct}%`, background: card.color }}
              />
            </div>
          </article>
        ))}
      </section>

      <section className="overview-ref-mid">
        <article className="overview-ref-card">
          <div className="overview-ref-card-title">
            <i className="fas fa-users" />
            数字员工状态
          </div>
          <div className="overview-ref-employee-grid">
            {orderedEmployeesWithStatus.map((employee) => (
              <button
                key={employee.id}
                type="button"
                className="overview-ref-employee-item"
                onClick={() => onOpenEmployeeChat(employee.id)}
              >
                <DigitalEmployeeAvatar employee={employee} className="overview-ref-employee-avatar" />
                <div className="overview-ref-employee-name">{employee.name}</div>
                <div className={`overview-ref-employee-status ${employee.statusClass}`}>
                  {employee.statusText}
                </div>
              </button>
            ))}
          </div>
        </article>

        <article className="overview-ref-card">
          <div className="overview-ref-card-title">
            <i className="fas fa-square-check" />
            今日工单
          </div>
          <div className="overview-ref-ticket-grid">
            {tickets.map((ticket) => (
              <div key={ticket.label} className="overview-ref-ticket-item">
                <div className="overview-ref-ticket-value" style={{ color: ticket.color }}>
                  {ticket.value}
                </div>
                <div className="overview-ref-ticket-label">{ticket.label}</div>
              </div>
            ))}
          </div>
        </article>

        <article className="overview-ref-card">
          <div className="overview-ref-card-title">
            <i className="fas fa-chart-line" />
            近7天告警趋势
          </div>
          <div className="overview-ref-chart">
            {trend.dates.length === 0 ? (
              <div className="overview-ref-empty">{loading ? "加载中…" : "暂无告警趋势数据"}</div>
            ) : (
              <ReactECharts
                option={chartOption}
                style={{ height: 186, width: "100%" }}
                notMerge
                lazyUpdate
              />
            )}
          </div>
        </article>
      </section>

      <section className="overview-ref-bottom">
        <article className="overview-ref-card">
          <div className="overview-ref-card-title">
            <i className="fas fa-triangle-exclamation" />
            告警分布
          </div>
          <div className="overview-ref-alert-list">
            {alerts.map((alert) => (
              <div
                key={alert.level}
                className={`overview-ref-alert-row${alert.level === "暂无告警" ? " is-empty" : ""}`}
              >
                <div className="overview-ref-alert-dot" style={{ background: alert.color }} />
                <div className="overview-ref-alert-level" style={{ color: alert.color }}>
                  {alert.level}
                </div>
                <div className="overview-ref-alert-bar">
                  <div
                    className="overview-ref-alert-bar-fill"
                    style={{ width: `${alert.pct}%`, background: alert.color }}
                  />
                </div>
                <div className="overview-ref-alert-count" style={{ color: alert.color }}>
                  {alert.count}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="overview-ref-card">
          <div className="overview-ref-card-title">
            <span className="overview-live-dot small" />
            业务服务健康度
          </div>
          <div className="overview-ref-service-list">
            {services.length === 0 ? (
              <div className="overview-ref-empty">{loading ? "加载中…" : "暂无业务服务数据"}</div>
            ) : (
              services.map((service) => (
                <div key={service.name} className="overview-ref-service-row">
                  <div className={`overview-ref-service-dot ${service.status}`} />
                  <div className="overview-ref-service-name">{service.name}</div>
                  <div className="overview-ref-service-health">{service.health}</div>
                  <div className="overview-ref-service-availability">
                    {service.availability}
                  </div>
                </div>
              ))
            )}
          </div>
        </article>

        <article className="overview-ref-card">
          <div className="overview-ref-card-title">
            <i className="fas fa-clock" />
            告警对象 Top5
          </div>
          <div className="overview-ref-event-list">
            {events.length === 0 ? (
              <div className="overview-ref-event">
                <div className="overview-ref-event-icon" style={{ background: "#64748b20", color: "#64748b" }}>
                  <i className="fas fa-circle-info" />
                </div>
                <div className="overview-ref-event-body">
                  <div className="overview-ref-event-title">
                    {loading ? "加载中…" : "暂无告警对象数据"}
                  </div>
                  <div className="overview-ref-event-time">—</div>
                </div>
              </div>
            ) : (
              events.map((event) => {
                const content = (
                  <>
                    <div className="overview-ref-event-icon" style={{ background: `${event.color}20`, color: event.color }}>
                      <i className={`fas ${event.iconClass}`} />
                    </div>
                    <div className="overview-ref-event-body">
                      <div className="overview-ref-event-title">{event.title}</div>
                      <div className="overview-ref-event-time">{event.time}</div>
                    </div>
                  </>
                );

                if (event.employeeId) {
                  return (
                    <button
                      key={event.title}
                      type="button"
                      className="overview-ref-event"
                      onClick={() => onOpenEmployeeChat(event.employeeId!)}
                    >
                      {content}
                    </button>
                  );
                }

                return (
                  <div key={event.title} className="overview-ref-event">
                    {content}
                  </div>
                );
              })
            )}
          </div>
        </article>
      </section>
    </div>
  );
}
