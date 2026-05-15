import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import DigitalEmployeeAvatar from "../../components/DigitalEmployeeAvatar";
import { digitalEmployees } from "../../data/portalData";

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
  uptime: string;
  latency: string;
  latencyClass: "" | "warn" | "bad";
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

const ASSET_OVERVIEW_STATS: OverviewKpi[] = [
  {
    label: "纳管总资产",
    value: "19,540",
    trend: "flat",
    trendValue: "资产",
    color: "#3b82f6",
    barPct: 100,
    iconClass: "fa-server",
  },
  {
    label: "云主机",
    value: "12,450",
    trend: "flat",
    trendValue: "IaaS",
    color: "#6366f1",
    barPct: 64,
    iconClass: "fa-cloud",
  },
  {
    label: "网络设备",
    value: "5,200",
    trend: "flat",
    trendValue: "LAN",
    color: "#22c55e",
    barPct: 27,
    iconClass: "fa-network-wired",
  },
  {
    label: "在线率",
    value: "99.1%",
    trend: "flat",
    trendValue: "稳定",
    color: "#22d3ee",
    barPct: 99.1,
    iconClass: "fa-signal",
  },
];

const KPI_CARDS: OverviewKpi[] = [
  {
    label: "业务可用率",
    value: "99.97%",
    trend: "up",
    trendValue: "+0.12%",
    color: "#22c55e",
    barPct: 99.97,
    iconClass: "fa-heart-pulse",
  },
  {
    label: "活跃告警",
    value: "7",
    trend: "down",
    trendValue: "-3",
    color: "#ef4444",
    barPct: 14,
    iconClass: "fa-triangle-exclamation",
  },
  {
    label: "今日工单",
    value: "23",
    trend: "up",
    trendValue: "+5",
    color: "#6366f1",
    barPct: 46,
    iconClass: "fa-square-check",
  },
  {
    label: "数字员工在线",
    value: "5/6",
    trend: "flat",
    trendValue: "稳定",
    color: "#22d3ee",
    barPct: 83,
    iconClass: "fa-users",
  },
  ...ASSET_OVERVIEW_STATS,
];

const ALERTS: OverviewAlert[] = [
  { level: "紧急", color: "#ef4444", count: 1, pct: 14 },
  { level: "严重", color: "#f97316", count: 2, pct: 28 },
  { level: "警告", color: "#f59e0b", count: 4, pct: 57 },
  { level: "通知", color: "#22d3ee", count: 12, pct: 100 },
];

const TICKETS: OverviewTicket[] = [
  { label: "待处理", value: 8, color: "#f59e0b" },
  { label: "进行中", value: 6, color: "#3b82f6" },
  { label: "已完成", value: 18, color: "#22c55e" },
  { label: "完成率", value: "75%", color: "#6366f1" },
];

const SERVICES: OverviewService[] = [
  { name: "核心交换网络", status: "healthy", uptime: "99.99%", latency: "2ms", latencyClass: "" },
  { name: "Web应用集群", status: "healthy", uptime: "99.98%", latency: "45ms", latencyClass: "" },
  {
    name: "数据库集群(MySQL)",
    status: "warning",
    uptime: "99.92%",
    latency: "128ms",
    latencyClass: "warn",
  },
  { name: "K8s容器平台", status: "healthy", uptime: "99.95%", latency: "12ms", latencyClass: "" },
  { name: "对象存储(OSS)", status: "healthy", uptime: "100%", latency: "8ms", latencyClass: "" },
  { name: "支付服务", status: "critical", uptime: "98.7%", latency: "892ms", latencyClass: "bad" },
  { name: "CDN加速节点", status: "healthy", uptime: "99.99%", latency: "5ms", latencyClass: "" },
  {
    name: "消息队列(Kafka)",
    status: "warning",
    uptime: "99.88%",
    latency: "67ms",
    latencyClass: "warn",
  },
];

const EVENTS: OverviewEvent[] = [
  {
    title: "支付服务连接池耗尽",
    time: "2分钟前",
    color: "#ef4444",
    iconClass: "fa-circle-xmark",
    employeeId: "fault",
  },
  {
    title: "K8s Pod自动扩容 → 12副本",
    time: "5分钟前",
    color: "#22d3ee",
    iconClass: "fa-up-right-and-down-left-from-center",
    employeeId: "resource",
  },
  {
    title: "MySQL慢查询告警已触发",
    time: "8分钟前",
    color: "#f59e0b",
    iconClass: "fa-database",
    employeeId: "fault",
  },
  {
    title: "SSL证书续签完成(15个域名)",
    time: "15分钟前",
    color: "#22c55e",
    iconClass: "fa-lock",
    employeeId: "inspection",
  },
  {
    title: "CDN节点华东区域流量激增",
    time: "22分钟前",
    color: "#f97316",
    iconClass: "fa-wave-square",
    employeeId: "query",
  },
  {
    title: "巡检专家完成全量主机巡检",
    time: "30分钟前",
    color: "#22c55e",
    iconClass: "fa-circle-check",
    employeeId: "inspection",
  },
  {
    title: "Kafka消费者组Lag告警",
    time: "45分钟前",
    color: "#f59e0b",
    iconClass: "fa-triangle-exclamation",
    employeeId: "fault",
  },
  {
    title: "自动备份任务完成",
    time: "1小时前",
    color: "#6366f1",
    iconClass: "fa-cloud-arrow-up",
    employeeId: "order",
  },
];

const ALERT_TREND_HOURS = Array.from({ length: 24 }, (_, index) => `${String(index).padStart(2, "0")}:00`);
const ALERT_TREND_SERIES_CRITICAL = [2, 1, 1, 0, 1, 0, 0, 1, 3, 5, 8, 6, 4, 3, 5, 7, 4, 3, 2, 3, 4, 2, 1, 1];
const ALERT_TREND_SERIES_WARNING = [5, 4, 3, 2, 3, 2, 1, 4, 6, 9, 12, 10, 8, 7, 9, 11, 8, 6, 5, 6, 7, 5, 4, 3];

export function OverviewPanel({ pageTheme, onOpenEmployeeChat, employees }: OverviewPanelProps) {
  const isDark = pageTheme === "dark";

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

  const chartOption = useMemo<EChartsOption>(
    () => ({
      grid: { top: 10, right: 10, bottom: 24, left: 32 },
      xAxis: {
        type: "category",
        data: ALERT_TREND_HOURS,
        axisLabel: {
          fontSize: 9,
          color: isDark ? "#64748b" : "#94a3b8",
          interval: 3,
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
      series: [
        {
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { width: 2, color: "#ef4444" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(239,68,68,.25)" },
                { offset: 1, color: "rgba(239,68,68,0)" },
              ],
            },
          },
          data: ALERT_TREND_SERIES_CRITICAL,
        },
        {
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { width: 2, color: "#f59e0b" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(245,158,11,.15)" },
                { offset: 1, color: "rgba(245,158,11,0)" },
              ],
            },
          },
          data: ALERT_TREND_SERIES_WARNING,
        },
      ],
    }),
    [isDark],
  );

  return (
    <div className="portal-overview portal-overview-reference">
      <div className="overview-main-header">
        <div className="overview-main-title">
          <span className="overview-live-dot" />
          数字总览
          <small>全局态势感知</small>
        </div>
      </div>

      <section className="overview-ref-top">
        {KPI_CARDS.map((card) => (
          <article key={card.label} className="overview-ref-kpi">
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
            {TICKETS.map((ticket) => (
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
            24h告警趋势
          </div>
          <div className="overview-ref-chart">
            <ReactECharts
              option={chartOption}
              style={{ height: 186, width: "100%" }}
              notMerge
              lazyUpdate
            />
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
            {ALERTS.map((alert) => (
              <div key={alert.level} className="overview-ref-alert-row">
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
            {SERVICES.map((service) => (
              <div key={service.name} className="overview-ref-service-row">
                <div className={`overview-ref-service-dot ${service.status}`} />
                <div className="overview-ref-service-name">{service.name}</div>
                <div className="overview-ref-service-uptime">{service.uptime}</div>
                <div className={`overview-ref-service-latency ${service.latencyClass}`}>
                  {service.latency}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="overview-ref-card">
          <div className="overview-ref-card-title">
            <i className="fas fa-clock" />
            实时事件流
          </div>
          <div className="overview-ref-event-list">
            {EVENTS.map((event) => {
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
            })}
          </div>
        </article>
      </section>
    </div>
  );
}
