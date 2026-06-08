import type { DashboardSpec } from "./types.ts";

/**
 * DMAX_OPS_FIXTURE — a realistic "运维指挥中心" ops board that reproduces the
 * locked D-max mockup. Used by the preview route to eyeball the full visual
 * stack: glass panels, aurora, map flying-lines, flip numbers, water ball,
 * gauge/radar, marquee alarm stream, and the honest live/empty/failed/gap
 * status badges. Data is inlined per component (P1; dataRef wiring lands in P2).
 *
 * Canvas 1920×1080. Bands: header(18..68) · KPI(80..176) · main(188..658) ·
 * lower-A(670..846) · lower-B(858..1056). 24px side margins, 16px gutters.
 */
export const DMAX_OPS_FIXTURE: DashboardSpec = {
  schemaVersion: 1,
  id: "dmax-ops-demo",
  name: "智能运维指挥中心",
  status: "published",
  layout: { designWidth: 1920, designHeight: 1080 },
  theme: {},
  components: [
    // ── Header ────────────────────────────────────────────────
    {
      id: "hdr",
      type: "text",
      title: "智能运维指挥中心",
      layoutPosition: { x: 24, y: 18, w: 1872, h: 50 },
      visualSpec: { composition: "primary", bindings: { text: "text" } },
      data: {
        capabilityId: "static",
        sourceStatus: "live",
        metrics: { text: "实时态势感知 · 全域设备监控 · 智能告警分析" },
      },
    },

    // ── KPI strip (4 tiles) ───────────────────────────────────
    {
      id: "kpi-alarms",
      type: "flip-number",
      title: "实时告警总数",
      layoutPosition: { x: 24, y: 80, w: 456, h: 96 },
      visualSpec: { density: "showcase", bindings: { value: "value", unit: "件" } },
      data: { capabilityId: "alarm.count", sourceStatus: "live", metrics: { value: 1284 } },
    },
    {
      id: "kpi-online",
      type: "metric-kpi",
      title: "在线设备",
      layoutPosition: { x: 496, y: 80, w: 456, h: 96 },
      visualSpec: { density: "showcase", bindings: { value: "value", y: "v", color: "#34d399" } },
      data: {
        capabilityId: "device.online",
        sourceStatus: "live",
        metrics: { value: 8642 },
        rows: [{ v: 40 }, { v: 55 }, { v: 48 }, { v: 70 }, { v: 62 }, { v: 88 }],
      },
    },
    {
      id: "kpi-tickets",
      type: "metric-kpi",
      title: "今日工单",
      layoutPosition: { x: 968, y: 80, w: 456, h: 96 },
      visualSpec: { density: "showcase", bindings: { value: "value", y: "v", color: "#a78bfa" } },
      data: {
        capabilityId: "ticket.today",
        sourceStatus: "live",
        metrics: { value: 327 },
        rows: [{ v: 12 }, { v: 18 }, { v: 25 }, { v: 22 }, { v: 31 }, { v: 27 }],
      },
    },
    {
      id: "kpi-recovered",
      type: "flip-number",
      title: "今日恢复",
      layoutPosition: { x: 1440, y: 80, w: 456, h: 96 },
      visualSpec: { density: "showcase", bindings: { value: "value", unit: "件", color: "#34d399" } },
      data: { capabilityId: "alarm.recovered", sourceStatus: "live", metrics: { value: 298 } },
    },

    // ── Main row ──────────────────────────────────────────────
    {
      id: "donut-severity",
      type: "donut",
      title: "告警分级占比",
      layoutPosition: { x: 24, y: 188, w: 360, h: 227 },
      visualSpec: { bindings: { name: "name", value: "value" } },
      data: {
        capabilityId: "alarm.bySeverity",
        sourceStatus: "live",
        rows: [
          { name: "严重", value: 18 },
          { name: "高", value: 42 },
          { name: "中", value: 67 },
          { name: "低", value: 124 },
        ],
      },
    },
    {
      id: "topn-source",
      type: "top-n",
      title: "TOP 告警源",
      layoutPosition: { x: 24, y: 431, w: 360, h: 227 },
      visualSpec: { bindings: { name: "name", value: "value" } },
      data: {
        capabilityId: "alarm.topSource",
        sourceStatus: "live",
        rows: [
          { name: "核心交换机-01", value: 128 },
          { name: "DB-主库", value: 96 },
          { name: "API-网关", value: 72 },
          { name: "缓存集群", value: 54 },
          { name: "消息队列", value: 38 },
        ],
      },
    },
    {
      id: "map-fly",
      type: "map-fly",
      title: "全国设备告警分布",
      layoutPosition: { x: 400, y: 188, w: 744, h: 470 },
      visualSpec: { composition: "primary", motion: "scan" },
      data: {
        capabilityId: "alarm.geo",
        sourceStatus: "live",
        nodes: [
          { name: "北京", coord: [116.4, 39.9] },
          { name: "上海", coord: [121.47, 31.23] },
          { name: "广州", coord: [113.26, 23.13] },
          { name: "成都", coord: [104.07, 30.57] },
          { name: "武汉", coord: [114.3, 30.59] },
          { name: "西安", coord: [108.95, 34.27] },
          { name: "沈阳", coord: [123.43, 41.8] },
          { name: "乌鲁木齐", coord: [87.62, 43.82] },
          { name: "拉萨", coord: [91.11, 29.97] },
          { name: "哈尔滨", coord: [126.53, 45.8] },
        ],
        rows: [
          { from: "北京", to: "上海" },
          { from: "北京", to: "广州" },
          { from: "北京", to: "成都" },
          { from: "上海", to: "武汉" },
          { from: "广州", to: "西安" },
          { from: "成都", to: "乌鲁木齐" },
          { from: "北京", to: "沈阳" },
          { from: "北京", to: "哈尔滨" },
          { from: "上海", to: "拉萨" },
        ],
      },
    },
    {
      id: "liquid-sla",
      type: "liquid-ball",
      title: "SLA 达成率",
      layoutPosition: { x: 1160, y: 188, w: 320, h: 227 },
      visualSpec: { layoutPattern: "focus", bindings: { value: "value" } },
      data: { capabilityId: "sla.rate", sourceStatus: "live", metrics: { value: 92 } },
    },
    {
      id: "gauge-health",
      type: "gauge",
      title: "系统健康度",
      layoutPosition: { x: 1160, y: 431, w: 320, h: 227 },
      visualSpec: { layoutPattern: "focus", bindings: { value: "health" } },
      data: { capabilityId: "system.health", sourceStatus: "live", metrics: { health: 86 } },
    },
    {
      id: "alarm-stream",
      type: "alarm-stream",
      title: "实时告警流",
      layoutPosition: { x: 1496, y: 188, w: 400, h: 470 },
      visualSpec: {
        bindings: { message: "msg", time: "time", tone: "severity" },
        highlightRules: [
          { field: "severity", operator: "=", value: "critical", tone: "critical" },
          { field: "severity", operator: "=", value: "high", tone: "high" },
          { field: "severity", operator: "=", value: "medium", tone: "medium" },
          { field: "severity", operator: "=", value: "normal", tone: "normal" },
        ],
      },
      data: {
        capabilityId: "alarm.stream",
        sourceStatus: "live",
        rows: [
          { time: "09:42:18", msg: "核心交换机 CPU 利用率 95%", severity: "critical" },
          { time: "09:41:50", msg: "数据库主从延迟 12s", severity: "high" },
          { time: "09:40:33", msg: "API 网关 5xx 错误率上升", severity: "high" },
          { time: "09:39:07", msg: "机房 B 温度告警 32℃", severity: "medium" },
          { time: "09:37:55", msg: "磁盘使用率 88% (node-17)", severity: "medium" },
          { time: "09:36:20", msg: "定时备份任务执行成功", severity: "normal" },
          { time: "09:35:01", msg: "边缘节点心跳恢复", severity: "normal" },
        ],
      },
    },

    // ── Lower-A (charts) ──────────────────────────────────────
    {
      id: "area-trend",
      type: "area-chart",
      title: "24 小时告警趋势",
      layoutPosition: { x: 24, y: 670, w: 456, h: 176 },
      visualSpec: { bindings: { x: "x", y: "y" } },
      data: {
        capabilityId: "alarm.trend24h",
        sourceStatus: "live",
        rows: [
          { x: "00:00", y: 42 },
          { x: "03:00", y: 28 },
          { x: "06:00", y: 35 },
          { x: "09:00", y: 88 },
          { x: "12:00", y: 67 },
          { x: "15:00", y: 120 },
          { x: "18:00", y: 95 },
          { x: "21:00", y: 58 },
        ],
      },
    },
    {
      id: "line-latency",
      type: "line-chart",
      title: "平均响应时延 (ms)",
      layoutPosition: { x: 496, y: 670, w: 456, h: 176 },
      visualSpec: { bindings: { x: "x", y: "y" } },
      data: {
        capabilityId: "perf.latency",
        sourceStatus: "live",
        rows: [
          { x: "00:00", y: 120 },
          { x: "04:00", y: 98 },
          { x: "08:00", y: 210 },
          { x: "12:00", y: 175 },
          { x: "16:00", y: 240 },
          { x: "20:00", y: 130 },
        ],
      },
    },
    {
      id: "bar-room",
      type: "bar-chart",
      title: "各机房告警量",
      layoutPosition: { x: 968, y: 670, w: 456, h: 176 },
      visualSpec: { bindings: { x: "x", y: "y" } },
      data: {
        capabilityId: "alarm.byRoom",
        sourceStatus: "gap",
        message: "部分采集点数据缺失",
        rows: [
          { x: "机房A", y: 62 },
          { x: "机房B", y: 88 },
          { x: "机房C", y: 45 },
          { x: "机房D", y: 73 },
          { x: "边缘", y: 30 },
        ],
      },
    },
    {
      id: "radar-ability",
      type: "radar",
      title: "服务能力评估",
      layoutPosition: { x: 1440, y: 670, w: 456, h: 176 },
      visualSpec: {},
      data: {
        capabilityId: "service.ability",
        sourceStatus: "empty",
        message: "暂无评估数据",
        metrics: {},
      },
    },

    // ── Lower-B (mixed widgets) ───────────────────────────────
    {
      id: "funnel-converge",
      type: "funnel",
      title: "故障收敛漏斗",
      layoutPosition: { x: 24, y: 858, w: 298, h: 198 },
      visualSpec: { bindings: { name: "name", value: "value" } },
      data: {
        capabilityId: "fault.funnel",
        sourceStatus: "live",
        rows: [
          { name: "触发", value: 1000 },
          { name: "确认", value: 680 },
          { name: "派单", value: 420 },
          { name: "处置", value: 260 },
          { name: "关闭", value: 180 },
        ],
      },
    },
    {
      id: "timeline-handle",
      type: "timeline",
      title: "处置时间线",
      layoutPosition: { x: 338, y: 858, w: 298, h: 198 },
      visualSpec: {
        bindings: { message: "msg", time: "time" },
        highlightRules: [
          { field: "level", operator: "=", value: "critical", tone: "critical" },
          { field: "level", operator: "=", value: "high", tone: "high" },
          { field: "level", operator: "=", value: "medium", tone: "medium" },
        ],
      },
      data: {
        capabilityId: "fault.timeline",
        sourceStatus: "live",
        rows: [
          { time: "09:20", msg: "告警触发", level: "critical" },
          { time: "09:24", msg: "自动确认", level: "high" },
          { time: "09:31", msg: "工单派发", level: "medium" },
          { time: "09:48", msg: "现场处置", level: "normal" },
          { time: "10:02", msg: "恢复关闭", level: "normal" },
        ],
      },
    },
    {
      id: "bar3d-week",
      type: "bar3d",
      title: "本周告警分布",
      layoutPosition: { x: 652, y: 858, w: 298, h: 198 },
      visualSpec: {
        bindings: { name: "name", value: "value" },
        highlightRules: [{ field: "value", operator: ">=", value: 85, tone: "critical" }],
      },
      data: {
        capabilityId: "alarm.byWeekday",
        sourceStatus: "live",
        rows: [
          { name: "周一", value: 42 },
          { name: "周二", value: 68 },
          { name: "周三", value: 55 },
          { name: "周四", value: 91 },
          { name: "周五", value: 73 },
          { name: "周六", value: 38 },
          { name: "周日", value: 29 },
        ],
      },
    },
    {
      id: "risk-pulse",
      type: "risk-pulse",
      title: "风险脉搏",
      layoutPosition: { x: 966, y: 858, w: 298, h: 198 },
      visualSpec: {
        motion: "pulse",
        bindings: { description: "description" },
        highlightRules: [
          { field: "severity", operator: "=", value: "critical", tone: "critical" },
          { field: "severity", operator: "=", value: "high", tone: "high" },
        ],
      },
      data: {
        capabilityId: "risk.pulse",
        sourceStatus: "live",
        rows: [{ severity: "critical", description: "核心链路存在拥塞风险，建议扩容" }],
        metrics: { 链路: 3, 时延: 2, 容量: 1 },
      },
    },
    {
      id: "heatmap-period",
      type: "heatmap",
      title: "时段 × 区域热力",
      layoutPosition: { x: 1280, y: 858, w: 298, h: 198 },
      visualSpec: { bindings: { x: "x", y: "y", value: "value" } },
      data: {
        capabilityId: "alarm.heatmap",
        sourceStatus: "failed",
        message: "数据源连接超时 (gateway:30080)",
        rows: [],
      },
    },
    {
      id: "graph-topology",
      type: "graph",
      title: "应用依赖拓扑",
      layoutPosition: { x: 1594, y: 858, w: 302, h: 198 },
      visualSpec: {},
      data: {
        capabilityId: "app.topology",
        sourceStatus: "live",
        nodes: [
          { id: "gw", name: "网关", size: 30 },
          { id: "svc", name: "订单服务", size: 24 },
          { id: "db", name: "数据库", size: 22 },
          { id: "cache", name: "缓存", size: 18 },
          { id: "mq", name: "消息队列", size: 18 },
        ],
        links: [
          { source: "gw", target: "svc" },
          { source: "svc", target: "db" },
          { source: "svc", target: "cache" },
          { source: "svc", target: "mq" },
        ],
      },
    },
  ],
};
