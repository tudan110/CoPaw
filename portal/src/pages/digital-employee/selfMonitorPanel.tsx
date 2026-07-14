import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  selfMonitorApi,
  toDeltaBuckets,
  type SelfMonitorAlert,
  type SelfMonitorCost,
  type SelfMonitorDiagnosis,
  type SelfMonitorEvent,
  type SelfMonitorLayer,
  type SelfMonitorMetricSeries,
  type SelfMonitorModels,
  type SelfMonitorOverview,
  type SelfMonitorSessions,
  type SelfMonitorStatus,
  type SelfMonitorTokenLedger,
  type SelfMonitorTokens,
  type SelfMonitorTools,
  type SelfMonitorTopology,
} from "../../api/selfMonitor";
import { EChart } from "../../components/big-screen/charts/EChart";
import { TracesCenterPanel } from "./tracesCenterPanel";
import { workspaceDisplayName } from "./workspaceDisplay";
import "../self-monitor.css";

const REFRESH_INTERVAL_MS = 15000;

const WINDOW_OPTIONS = [
  { label: "15m", seconds: 900 },
  { label: "1h", seconds: 3600 },
  { label: "6h", seconds: 21600 },
  { label: "24h", seconds: 86400 },
] as const;

const STATE_META: Record<SelfMonitorStatus, { text: string; en: string }> = {
  ok: { text: "正常运行", en: "NOMINAL" },
  warn: { text: "受损运行", en: "DEGRADED" },
  crit: { text: "严重异常", en: "CRITICAL" },
  unknown: { text: "等待数据", en: "STANDBY" },
};

const LAYER_META: Record<string, { name: string; en: string }> = {
  l1: { name: "体验层", en: "UX" },
  l2: { name: "应用层", en: "Agent" },
  l3: { name: "依赖层", en: "Deps" },
  l4: { name: "资源层", en: "Host" },
};

function fmtTime(ts: number) {
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtClock(ts: number) {
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes >= 1 << 30) return `${(bytes / (1 << 30)).toFixed(1)}G`;
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(0)}M`;
  return `${Math.round(bytes / 1024)}K`;
}

function fmtBig(value: number | null | undefined): string {
  const v = Number(value ?? 0);
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}Mil`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

function fmtSeconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value < 0.001) return `${(value * 1e6).toFixed(0)} µs`;
  if (value < 1) return `${(value * 1000).toFixed(0)} ms`;
  return `${value.toFixed(2)} s`;
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function SelfMonitorPanel() {
  const [windowS, setWindowS] = useState<number>(3600);
  const [overview, setOverview] = useState<SelfMonitorOverview | null>(null);
  const [events, setEvents] = useState<SelfMonitorEvent[]>([]);
  const [reqSeries, setReqSeries] = useState<SelfMonitorMetricSeries[]>([]);
  const [degradeSeries, setDegradeSeries] = useState<SelfMonitorMetricSeries[]>([]);
  const [alerts, setAlerts] = useState<{ active: SelfMonitorAlert[]; recent: SelfMonitorAlert[] }>({
    active: [],
    recent: [],
  });
  const [cost, setCost] = useState<SelfMonitorCost | null>(null);
  const [topology, setTopology] = useState<SelfMonitorTopology | null>(null);
  const [diagnosis, setDiagnosis] = useState<SelfMonitorDiagnosis | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [error, setError] = useState("");
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const load = async () => {
      const since = Date.now() / 1000 - windowS;
      try {
        const [ov, ev, req, deg, al, co, topo] = await Promise.all([
          selfMonitorApi.overview(windowS, controller.signal),
          selfMonitorApi.events(60, controller.signal),
          selfMonitorApi.metrics("qwenpaw_llm_requests_total", since, controller.signal),
          selfMonitorApi.metrics("qwenpaw_degrade_events_total", since, controller.signal),
          selfMonitorApi.alerts(30, controller.signal),
          selfMonitorApi.cost(controller.signal),
          selfMonitorApi.topology(windowS, controller.signal),
        ]);
        if (cancelled) return;
        setOverview(ov);
        setEvents(ev.items || []);
        setReqSeries(req.series || []);
        setDegradeSeries(deg.series || []);
        setAlerts({ active: al.active || [], recent: al.recent || [] });
        setCost(co);
        setTopology(topo);
        setError("");
        setLoadedAt(Date.now() / 1000);
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    };
    void load();
    const timerId = window.setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timerId);
    };
  }, [windowS, reloadNonce]);

  const refresh = useCallback(() => setReloadNonce((n) => n + 1), []);

  const runDiagnose = useCallback(() => {
    setDiagLoading(true);
    selfMonitorApi
      .diagnose(windowS)
      .then((verdict) => setDiagnosis(verdict))
      .catch((err) =>
        setDiagnosis({
          summary: "诊断请求失败",
          rootCause: err instanceof Error ? err.message : String(err),
          confidence: "low",
          evidence: [],
          recommendations: ["检查后端 /self-monitor/diagnose 接口"],
          engine: "rule-based",
          degraded: true,
          generatedAt: Date.now() / 1000,
        }),
      )
      .finally(() => setDiagLoading(false));
  }, [windowS]);

  const state: SelfMonitorStatus = overview?.state ?? "unknown";
  const kpis = overview?.kpis;
  const layers = overview?.layers ?? [];
  const layerOf = (id: string): SelfMonitorLayer | undefined =>
    layers.find((l) => l.layer === id);
  const l3 = layerOf("l3");
  const l4 = layerOf("l4");
  const datasources = (l3?.metrics?.datasources ?? {}) as Record<
    string,
    { configured: boolean; up: boolean | null }
  >;
  const rssByWorker = (l4?.metrics?.rssBytesByWorker ?? {}) as Record<string, number>;
  const hasData = state !== "unknown";

  // AI Agent observability IA (对标阿里云):
  // 总览 | 链路追踪(内嵌追溯中心) | 会话分析 | 场景化分析(四个子维度)
  const navigate = useNavigate();
  type TopTab = "overview" | "traces" | "sessions" | "scenario";
  type ScenarioTab = "tokens" | "model-perf" | "tools" | "users";
  const [activeTab, setActiveTab] = useState<TopTab>(() => {
    // deep-links from the folded-in standalone pages keep working
    if (window.location.pathname === "/traces") return "traces";
    if (window.location.pathname === "/token-usage") return "scenario";
    const wanted = new URLSearchParams(window.location.search).get("tab");
    return wanted === "traces" || wanted === "sessions" || wanted === "scenario"
      ? wanted
      : "overview";
  });
  const [scenarioTab, setScenarioTab] = useState<ScenarioTab>("tokens");
  const [models, setModels] = useState<SelfMonitorModels | null>(null);
  const [tokensData, setTokensData] = useState<SelfMonitorTokens | null>(null);
  const [ledger, setLedger] = useState<SelfMonitorTokenLedger | null>(null);
  const [toolsData, setToolsData] = useState<SelfMonitorTools | null>(null);
  const [sessions, setSessions] = useState<SelfMonitorSessions | null>(null);

  useEffect(() => {
    const wantModels = activeTab === "scenario" && scenarioTab === "model-perf";
    const wantTokens = activeTab === "scenario" && scenarioTab === "tokens";
    const wantTools = activeTab === "scenario" && scenarioTab === "tools";
    const wantSessions =
      activeTab === "sessions" ||
      (activeTab === "scenario" && scenarioTab === "users");
    if (!wantModels && !wantTokens && !wantTools && !wantSessions) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        if (wantModels) {
          setModels(await selfMonitorApi.models(windowS, controller.signal));
        }
        if (wantTokens) {
          setTokensData(await selfMonitorApi.tokens(windowS, controller.signal));
          setLedger(await selfMonitorApi.tokenLedger(30, controller.signal));
        }
        if (wantTools) {
          setToolsData(await selfMonitorApi.tools(windowS, controller.signal));
        }
        if (wantSessions) {
          setSessions(await selfMonitorApi.sessions(7, controller.signal));
        }
      } catch {
        /* keep the last good payload; overview banner reports API errors */
      }
    };
    void load();
    // tools/sessions aggregate over files server-side (60s cache) —
    // polling faster than the cache would just replay stale payloads
    const timerId = window.setInterval(
      () => void load(),
      wantSessions || wantTools ? 60000 : REFRESH_INTERVAL_MS,
    );
    return () => {
      controller.abort();
      window.clearInterval(timerId);
    };
  }, [activeTab, scenarioTab, windowS, reloadNonce]);

  // click a layer node to focus the event stream on that layer
  const [layerFilter, setLayerFilter] = useState<string | null>(null);
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);
  const [refreshSpin, setRefreshSpin] = useState(false);
  const filteredEvents = useMemo(
    () => (layerFilter ? events.filter((event) => event.layer === layerFilter) : events),
    [events, layerFilter],
  );
  const spinRefresh = useCallback(() => {
    setRefreshSpin(true);
    refresh();
    window.setTimeout(() => setRefreshSpin(false), 900);
  }, [refresh]);

  const { chartOption, chartHasData } = useMemo(() => {
    const bucketS = windowS <= 3600 ? 60 : windowS <= 21600 ? 300 : 900;
    const okBuckets = toDeltaBuckets(
      reqSeries.filter((s) => s.labels.status === "ok"),
      bucketS,
    );
    const err429Buckets = toDeltaBuckets(
      reqSeries.filter((s) => s.labels.status === "429"),
      bucketS,
    );
    const degradeBuckets = toDeltaBuckets(degradeSeries, bucketS);
    const axis = [
      ...new Set([
        ...okBuckets.map(([t]) => t),
        ...err429Buckets.map(([t]) => t),
        ...degradeBuckets.map(([t]) => t),
      ]),
    ].sort((a, b) => a - b);
    const at = (buckets: [number, number][], t: number) =>
      buckets.find(([bt]) => bt === t)?.[1] ?? 0;
    const option = {
      backgroundColor: "transparent",
      // Deterministic paint: the panel refreshes every 15s anyway, and
      // entry animation depends on rAF ticks that throttled/embedded
      // contexts may withhold, leaving the first frame unpainted.
      animation: false,
      grid: { containLabel: true, left: 10, right: 10, top: 30, bottom: 6 },
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: "#64748b", fontSize: 10 },
        itemWidth: 12,
        itemHeight: 6,
      },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: axis.map((t) => fmtClock(t)),
        axisLine: { lineStyle: { color: "rgba(15,23,42,.18)" } },
        axisLabel: { color: "#64748b", fontSize: 10 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#64748b", fontSize: 10 },
        splitLine: { lineStyle: { color: "rgba(15,23,42,.07)" } },
      },
      series: [
        {
          name: "请求成功",
          type: "line",
          smooth: true,
          symbol: "none",
          data: axis.map((t) => at(okBuckets, t)),
          lineStyle: { color: "#0891b2", width: 2 },
          itemStyle: { color: "#0891b2" },
          areaStyle: { color: "rgba(8,145,178,.10)" },
        },
        {
          name: "429 限流",
          type: "bar",
          data: axis.map((t) => at(err429Buckets, t)),
          itemStyle: { color: "rgba(217,119,6,.8)", borderRadius: [2, 2, 0, 0] },
          barMaxWidth: 10,
        },
        {
          name: "降级",
          type: "bar",
          data: axis.map((t) => at(degradeBuckets, t)),
          itemStyle: { color: "rgba(220,38,38,.85)", borderRadius: [2, 2, 0, 0] },
          barMaxWidth: 10,
        },
      ],
    };
    return { chartOption: option, chartHasData: axis.length > 0 };
  }, [reqSeries, degradeSeries, windowS]);

  const topoOption = useMemo(() => {
    const nodes = topology?.nodes ?? [];
    const edges = topology?.edges ?? [];
    const statusColor: Record<string, string> = {
      ok: "#059669",
      warn: "#d97706",
      crit: "#dc2626",
      unknown: "#64748b",
    };
    const typeSize: Record<string, number> = {
      core: 34,
      worker: 22,
      model: 18,
      datasource: 16,
    };
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: {},
      series: [
        {
          type: "graph",
          layout: "force",
          roam: false,
          force: { repulsion: 220, edgeLength: [60, 130], gravity: 0.12 },
          label: { show: true, color: "#334155", fontSize: 10, position: "bottom" },
          lineStyle: { color: "rgba(100,116,139,.35)", curveness: 0.1 },
          emphasis: { focus: "adjacency" },
          data: nodes.map((node) => ({
            id: node.id,
            name: node.label,
            symbolSize: typeSize[node.type] ?? 16,
            itemStyle: {
              color: node.type === "core" ? "#0891b2" : statusColor[node.status] ?? "#64748b",
              shadowBlur: node.status === "crit" ? 14 : 6,
              shadowColor:
                node.status === "crit" ? "rgba(220,38,38,.8)" : "rgba(8,145,178,.35)",
            },
          })),
          links: edges.map((edge) => ({
            source: edge.source,
            target: edge.target,
            lineStyle: { width: Math.min(4, 1 + Math.log10(1 + (edge.value || 1))) },
          })),
        },
      ],
    };
  }, [topology]);

  const AXIS = {
    axisLabel: { color: "#64748b", fontSize: 10 },
    axisLine: { lineStyle: { color: "rgba(15,23,42,.16)" } },
    splitLine: { lineStyle: { color: "rgba(15,23,42,.07)" } },
  };

  const tokenDonutOption = useMemo(() => {
    const entries = Object.entries(tokensData?.byModel ?? {});
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["58%", "82%"],
          center: ["50%", "52%"],
          label: { color: "#334155", fontSize: 10 },
          itemStyle: { borderColor: "#ffffff", borderWidth: 2 },
          data: entries.map(([model, kinds]) => ({
            name: model,
            value: kinds.prompt + kinds.completion,
          })),
          color: ["#0891b2", "#059669", "#7c3aed", "#d97706", "#dc2626"],
        },
      ],
    };
  }, [tokensData]);

  const tokenTrendOption = useMemo(() => {
    const rows = tokensData?.series ?? [];
    const axis = rows.map((row) =>
      new Date(row.ts * 1000).toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      legend: {
        data: ["输入 token", "输出 token"],
        textStyle: { color: "#64748b", fontSize: 10 },
        top: 0,
      },
      grid: { left: 54, right: 12, top: 28, bottom: 22 },
      xAxis: { type: "category", data: axis, ...AXIS },
      yAxis: { type: "value", ...AXIS },
      series: [
        {
          name: "输入 token",
          type: "bar",
          stack: "t",
          data: rows.map((row) => row.prompt),
          itemStyle: { color: "rgba(8,145,178,.75)" },
          barMaxWidth: 14,
        },
        {
          name: "输出 token",
          type: "bar",
          stack: "t",
          data: rows.map((row) => row.completion),
          itemStyle: { color: "rgba(5,150,105,.8)" },
          barMaxWidth: 14,
        },
      ],
    };
  }, [tokensData]);

  const perRequestOption = useMemo(() => {
    const rows = tokensData?.perRequest ?? [];
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      grid: { left: 54, right: 12, top: 14, bottom: 22 },
      xAxis: {
        type: "category",
        data: rows.map((row) =>
          new Date(row.ts * 1000).toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          }),
        ),
        ...AXIS,
      },
      yAxis: { type: "value", name: "token/req", ...AXIS },
      series: [
        {
          type: "line",
          smooth: true,
          symbol: "none",
          data: rows.map((row) => row.avgTokens),
          lineStyle: { color: "#7c3aed", width: 2 },
          areaStyle: { color: "rgba(124,58,237,.12)" },
        },
      ],
    };
  }, [tokensData]);

  const tokenTopOption = useMemo(() => {
    const entries = Object.entries(tokensData?.byModel ?? {})
      .map(([model, kinds]) => [model, kinds.prompt + kinds.completion] as const)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .reverse();
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: {},
      grid: { left: 120, right: 30, top: 8, bottom: 22 },
      xAxis: { type: "value", ...AXIS },
      yAxis: {
        type: "category",
        data: entries.map(([model]) => model),
        ...AXIS,
      },
      series: [
        {
          type: "bar",
          data: entries.map(([, total]) => total),
          barMaxWidth: 16,
          itemStyle: { color: "#0891b2", borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: "right",
            color: "#334155",
            fontSize: 10,
            formatter: (p: { value: number }) => fmtBig(p.value),
          },
        },
      ],
    };
  }, [tokensData]);

  const ledgerTrendOption = useMemo(() => {
    const rows = ledger?.byDate ?? [];
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      legend: {
        data: ["输入 token", "输出 token"],
        textStyle: { color: "#64748b", fontSize: 10 },
        top: 0,
      },
      grid: { left: 58, right: 12, top: 28, bottom: 22 },
      xAxis: {
        type: "category",
        data: rows.map((row) => row.date.slice(5)),
        ...AXIS,
      },
      yAxis: { type: "value", ...AXIS },
      series: [
        {
          name: "输入 token",
          type: "bar",
          stack: "ledger",
          data: rows.map((row) => row.promptTokens),
          itemStyle: { color: "rgba(8,145,178,.75)" },
          barMaxWidth: 16,
        },
        {
          name: "输出 token",
          type: "bar",
          stack: "ledger",
          data: rows.map((row) => row.completionTokens),
          itemStyle: { color: "rgba(5,150,105,.8)" },
          barMaxWidth: 16,
        },
      ],
    };
  }, [ledger]);

  const sessionTrendOption = useMemo(() => {
    const rows = sessions?.byDate ?? [];
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      legend: {
        data: ["消息数", "活跃会话"],
        textStyle: { color: "#64748b", fontSize: 10 },
        top: 0,
      },
      grid: { left: 46, right: 40, top: 28, bottom: 22 },
      xAxis: {
        type: "category",
        data: rows.map((row) => row.date.slice(5)),
        ...AXIS,
      },
      yAxis: [
        { type: "value", ...AXIS },
        { type: "value", ...AXIS, splitLine: { show: false } },
      ],
      series: [
        {
          name: "消息数",
          type: "bar",
          data: rows.map((row) => row.messages),
          itemStyle: { color: "rgba(8,145,178,.7)" },
          barMaxWidth: 18,
        },
        {
          name: "活跃会话",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          data: rows.map((row) => row.activeSessions),
          lineStyle: { color: "#d97706", width: 2 },
          itemStyle: { color: "#d97706" },
        },
      ],
    };
  }, [sessions]);

  const hhmm = (ts: number) =>
    new Date(ts * 1000).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    });

  const callTrendOption = useMemo(() => {
    const rows = models?.callTrend ?? [];
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      legend: {
        data: ["调用量", "错误率"],
        textStyle: { color: "#64748b", fontSize: 10 },
        top: 0,
      },
      grid: { left: 44, right: 44, top: 28, bottom: 22 },
      xAxis: { type: "category", data: rows.map((r) => hhmm(r.ts)), ...AXIS },
      yAxis: [
        { type: "value", ...AXIS },
        {
          type: "value",
          ...AXIS,
          splitLine: { show: false },
          axisLabel: { ...AXIS.axisLabel, formatter: "{value}%" },
        },
      ],
      series: [
        {
          name: "调用量",
          type: "bar",
          data: rows.map((r) => r.calls),
          itemStyle: { color: "rgba(8,145,178,.75)" },
          barMaxWidth: 14,
        },
        {
          name: "错误率",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          symbol: "none",
          data: rows.map((r) => Math.round(r.errRate * 1000) / 10),
          lineStyle: { color: "#dc2626", width: 2 },
        },
      ],
    };
  }, [models]);

  const errorTypesOption = useMemo(() => {
    const entries = Object.entries(models?.errorTypes ?? {});
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["55%", "80%"],
          center: ["50%", "52%"],
          label: { color: "#334155", fontSize: 10 },
          itemStyle: { borderColor: "#ffffff", borderWidth: 2 },
          data: entries.map(([status, count]) => ({
            name: status,
            value: count,
          })),
          color: ["#d97706", "#dc2626", "#7c3aed", "#64748b"],
        },
      ],
    };
  }, [models]);

  const avgTrendOption = useCallback(
    (rows: { ts: number; avgS: number }[], color: string) => ({
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 12, top: 14, bottom: 22 },
      xAxis: {
        type: "category",
        data: rows.map((r) => hhmm(r.ts)),
        ...AXIS,
      },
      yAxis: { type: "value", name: "s", ...AXIS },
      series: [
        {
          type: "line",
          smooth: true,
          symbol: "none",
          data: rows.map((r) => r.avgS),
          lineStyle: { color, width: 2 },
          areaStyle: { color: `${color}1f` },
        },
      ],
    }),
    [],
  );

  const toolsTrendOption = useMemo(() => {
    const rows = toolsData?.trend ?? [];
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      legend: {
        data: ["调用次数", "错误"],
        textStyle: { color: "#64748b", fontSize: 10 },
        top: 0,
      },
      grid: { left: 44, right: 12, top: 28, bottom: 22 },
      xAxis: { type: "category", data: rows.map((r) => hhmm(r.ts)), ...AXIS },
      yAxis: { type: "value", ...AXIS },
      series: [
        {
          name: "调用次数",
          type: "bar",
          data: rows.map((r) => r.calls),
          itemStyle: { color: "rgba(8,145,178,.75)" },
          barMaxWidth: 14,
        },
        {
          name: "错误",
          type: "bar",
          data: rows.map((r) => r.errors),
          itemStyle: { color: "rgba(220,38,38,.8)" },
          barMaxWidth: 14,
        },
      ],
    };
  }, [toolsData]);

  const toolsTopOption = useMemo(() => {
    const rows = (toolsData?.byTool ?? []).slice(0, 8).reverse();
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: {},
      grid: { left: 130, right: 40, top: 8, bottom: 22 },
      xAxis: { type: "value", ...AXIS },
      yAxis: { type: "category", data: rows.map((r) => r.tool), ...AXIS },
      series: [
        {
          type: "bar",
          data: rows.map((r) => r.calls),
          barMaxWidth: 14,
          itemStyle: { color: "#0891b2", borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: "right",
            color: "#334155",
            fontSize: 10,
          },
        },
      ],
    };
  }, [toolsData]);

  const stateMeta = STATE_META[state];
  const windowLabel =
    WINDOW_OPTIONS.find((o) => o.seconds === windowS)?.label ?? `${windowS}s`;

  return (
    <div className="sm-root">
      <div className="sm-aurora sm-aurora--cyan" />
      <div className="sm-aurora sm-aurora--violet" />

      <div className="sm-cmd">
        <div>
          <div className="sm-cmd-title">
            智观AI <em>自监控</em>
          </div>
          <div className="sm-cmd-sub">Self Monitor · Mission Console</div>
        </div>
        <div className={`sm-state ${state}`}>
          <i />
          {stateMeta.text} {stateMeta.en}
          {hasData && state !== "ok" ? (
            <small>
              {layers
                .filter((l) => l.status === "crit" || l.status === "warn")
                .map((l) => l.layer.toUpperCase())
                .join("/")}{" "}
              异常
            </small>
          ) : null}
        </div>
        {alerts.active.length > 0 ? (
          <div className="sm-state crit">
            <i />
            {alerts.active.length} 条告警触发中
          </div>
        ) : null}
        <div className="sm-cmd-spacer" />
        <div className="sm-rangebar">
          {WINDOW_OPTIONS.map((option) => (
            <button
              key={option.seconds}
              className={windowS === option.seconds ? "on" : ""}
              onClick={() => setWindowS(option.seconds)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <button
          className={`sm-refresh${refreshSpin ? " spinning" : ""}`}
          onClick={spinRefresh}
        >
          刷新{loadedAt ? ` · ${fmtTime(loadedAt)}` : ""}
        </button>
      </div>

      {error ? (
        <div className="sm-error-banner">自监控接口不可用:{error}</div>
      ) : null}

      <nav className="sm-tabs">
        {(
          [
            ["overview", "总览"],
            ["traces", "链路追踪"],
            ["sessions", "会话分析"],
            ["scenario", "场景化分析"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            className={activeTab === id ? "on" : ""}
            onClick={() => setActiveTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {activeTab === "traces" ? (
        <div className="sm-view sm-traces-embed">
          <TracesCenterPanel />
        </div>
      ) : null}

      {activeTab === "scenario" ? (
        <nav className="sm-tabs sm-subtabs">
          {(
            [
              ["tokens", "Token 用量分析"],
              ["model-perf", "模型性能分析"],
              ["tools", "工具调用分析"],
              ["users", "工作空间分析"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              className={scenarioTab === id ? "on" : ""}
              onClick={() => setScenarioTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
      ) : null}

      {activeTab === "scenario" && scenarioTab === "model-perf" ? (
        <div className="sm-view">
          <section className="sm-kpis">
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>调用量</span>
                <i className="sm-lyr">{windowLabel}</i>
              </div>
              <div className="sm-val">
                <b>{models ? fmtBig(models.totals.calls) : "—"}</b>
                <small>次</small>
              </div>
              <div className="sm-note">窗口内 LLM 请求终态样本数</div>
            </div>
            <div
              className={`sm-panel sm-kpi ${
                models && models.totals.errors > 0 ? "warned" : "good"
              }`}
            >
              <div className="sm-tag">
                <span>错误数</span>
                <i className="sm-lyr">429/error</i>
              </div>
              <div className="sm-val">
                <b>{models ? fmtBig(models.totals.errors) : "—"}</b>
                <small>
                  {models ? `${(models.totals.errRate * 100).toFixed(1)}%` : ""}
                </small>
              </div>
              <div className="sm-note">非 ok 终态(含限流/超时)</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>平均耗时</span>
                <i className="sm-lyr">E2E</i>
              </div>
              <div className="sm-val">
                <b>{models ? fmtSeconds(models.totals.avgDurationS) : "—"}</b>
              </div>
              <div className="sm-note">Δsum/Δcount(直方图窗口增量)</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>平均 TTFT</span>
                <i className="sm-lyr">首token</i>
              </div>
              <div className="sm-val">
                <b>{models ? fmtSeconds(models.totals.avgTtftS) : "—"}</b>
              </div>
              <div className="sm-note">取号→首个流式 chunk(含限流等待)</div>
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i />
                <h3>调用量趋势</h3>
                <span className="sm-en">calls · err rate</span>
              </div>
              {models?.callTrend.length ? (
                <div className="sm-chart-body" style={{ height: 200 }}>
                  <EChart option={callTrendOption} />
                </div>
              ) : (
                <div className="sm-empty">窗口内暂无调用</div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-red)" }} />
                <h3>错误类型分布</h3>
                <span className="sm-en">by status</span>
              </div>
              {Object.keys(models?.errorTypes ?? {}).length ? (
                <div className="sm-chart-body" style={{ height: 200 }}>
                  <EChart option={errorTypesOption} />
                </div>
              ) : (
                <div className="sm-empty">
                  <b>窗口内零错误</b>
                  <br />
                  429/error/timeout 终态会在这里按类型分布。
                </div>
              )}
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-violet)" }} />
                <h3>平均耗时趋势</h3>
                <span className="sm-en">avg duration</span>
              </div>
              {models?.durationTrend.length ? (
                <div className="sm-chart-body" style={{ height: 170 }}>
                  <EChart option={avgTrendOption(models.durationTrend, "#7c3aed")} />
                </div>
              ) : (
                <div className="sm-empty">窗口内暂无耗时样本</div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-green)" }} />
                <h3>平均 TTFT 趋势</h3>
                <span className="sm-en">first token</span>
              </div>
              {models?.ttftTrend.length ? (
                <div className="sm-chart-body" style={{ height: 170 }}>
                  <EChart option={avgTrendOption(models.ttftTrend, "#059669")} />
                </div>
              ) : (
                <div className="sm-empty">
                  <b>暂无 TTFT 样本</b>
                  <br />
                  流式调用的首 chunk 延迟会在这里成线。
                </div>
              )}
            </div>
          </section>

          <section className="sm-panel">
            <div className="sm-ph">
              <i />
              <h3>模型调用统计</h3>
              <span className="sm-en">Model Calls · {windowLabel}</span>
              <span className="sm-right">共 {models?.rows.length ?? 0} 个模型</span>
            </div>
            {models && models.rows.length ? (
              <div className="sm-table-wrap">
                <table className="sm-table">
                  <thead>
                    <tr>
                      <th>模型名称</th>
                      <th>调用量</th>
                      <th>错误数</th>
                      <th>错误率</th>
                      <th>平均耗时</th>
                      <th>平均TTFT</th>
                      <th>平均TPOT</th>
                      <th>输入token</th>
                      <th>输出token</th>
                      <th>Token消耗</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.rows.map((row) => (
                      <tr key={row.model}>
                        <td className="sm-td-model">{row.model}</td>
                        <td>{fmtBig(row.calls)}</td>
                        <td className={row.errors > 0 ? "bad" : ""}>
                          {fmtBig(row.errors)}
                        </td>
                        <td className={row.errRate > 0.05 ? "bad" : ""}>
                          {(row.errRate * 100).toFixed(1)}%
                        </td>
                        <td>{fmtSeconds(row.avgDurationS)}</td>
                        <td>{fmtSeconds(row.avgTtftS)}</td>
                        <td>
                          {row.tpotS == null ? "—" : `${row.tpotS} s/token`}
                        </td>
                        <td>{fmtBig(row.promptTokens)}</td>
                        <td>{fmtBig(row.completionTokens)}</td>
                        <td>{fmtBig(row.totalTokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="sm-empty">
                <b>窗口内暂无模型调用</b>
                <br />
                发起一次对话或大屏生成后,此表按 provider:model 维度聚合。
              </div>
            )}
          </section>
        </div>
      ) : null}

      {activeTab === "scenario" && scenarioTab === "tokens" ? (
        <div className="sm-view">
          <section className="sm-kpis">
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>Token 消耗</span>
                <i className="sm-lyr">{windowLabel}</i>
              </div>
              <div className="sm-val">
                <b>{tokensData ? fmtBig(tokensData.totals.total) : "—"}</b>
              </div>
              <div className="sm-note">输入 + 输出合计</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>输入 Token</span>
                <i className="sm-lyr">prompt</i>
              </div>
              <div className="sm-val">
                <b>{tokensData ? fmtBig(tokensData.totals.prompt) : "—"}</b>
              </div>
              <div className="sm-note">上下文/提示词侧</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>输出 Token</span>
                <i className="sm-lyr">completion</i>
              </div>
              <div className="sm-val">
                <b>{tokensData ? fmtBig(tokensData.totals.completion) : "—"}</b>
              </div>
              <div className="sm-note">模型生成侧</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>单请求均值</span>
                <i className="sm-lyr">token/req</i>
              </div>
              <div className="sm-val">
                <b>
                  {tokensData?.perRequest.length
                    ? fmtBig(
                        tokensData.perRequest[tokensData.perRequest.length - 1]
                          .avgTokens,
                      )
                    : "—"}
                </b>
              </div>
              <div className="sm-note">最近一个分桶的平均</div>
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-violet)" }} />
                <h3>Token 消耗分布</h3>
                <span className="sm-en">by model</span>
              </div>
              {Object.keys(tokensData?.byModel ?? {}).length ? (
                <div className="sm-chart-body" style={{ height: 220 }}>
                  <EChart option={tokenDonutOption} />
                </div>
              ) : (
                <div className="sm-empty">窗口内暂无 token 记录</div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i />
                <h3>Token 消耗趋势</h3>
                <span className="sm-en">stacked · {windowLabel}</span>
              </div>
              {tokensData?.series.length ? (
                <div className="sm-chart-body" style={{ height: 220 }}>
                  <EChart option={tokenTrendOption} />
                </div>
              ) : (
                <div className="sm-empty">窗口内暂无 token 记录</div>
              )}
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-green)" }} />
                <h3>平均单请求 Token 趋势</h3>
                <span className="sm-en">tokens / request</span>
              </div>
              {tokensData?.perRequest.length ? (
                <div className="sm-chart-body" style={{ height: 190 }}>
                  <EChart option={perRequestOption} />
                </div>
              ) : (
                <div className="sm-empty">窗口内暂无可计算的请求</div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-orange)" }} />
                <h3>模型 Token 消耗 Top5</h3>
                <span className="sm-en">Top models</span>
              </div>
              {Object.keys(tokensData?.byModel ?? {}).length ? (
                <div className="sm-chart-body" style={{ height: 190 }}>
                  <EChart option={tokenTopOption} />
                </div>
              ) : (
                <div className="sm-empty">窗口内暂无 token 记录</div>
              )}
            </div>
          </section>

          <div className="sm-note-banner">
            以上为<b>近窗高精度观测</b>(自监控采样,保留期约 7
            天);以下为<b>按日持久账本</b>(token_usage.json,长期留存)——
            原独立「Token 明细」页已并入此处。
          </div>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i />
                <h3>按日 Token 账本</h3>
                <span className="sm-en">last {ledger?.days ?? 30}d</span>
                <span className="sm-right">
                  {ledger
                    ? `合计 ${fmtBig(ledger.totals.totalTokens)} · ${fmtBig(
                        ledger.totals.calls,
                      )} 次调用`
                    : ""}
                </span>
              </div>
              {ledger?.byDate.length ? (
                <div className="sm-chart-body" style={{ height: 210 }}>
                  <EChart option={ledgerTrendOption} />
                </div>
              ) : (
                <div className="sm-empty">
                  {ledger && !ledger.available
                    ? ledger.reason || "账本不可用"
                    : "账本暂无记录"}
                </div>
              )}
            </div>

            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-green)" }} />
                <h3>按模型明细</h3>
                <span className="sm-en">durable ledger</span>
              </div>
              {ledger?.byModel.length ? (
                <div className="sm-table-wrap">
                  <table className="sm-table">
                    <thead>
                      <tr>
                        <th>模型</th>
                        <th>调用次数</th>
                        <th>输入token</th>
                        <th>输出token</th>
                        <th>合计</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ledger.byModel.map((row) => (
                        <tr key={row.model}>
                          <td className="sm-td-model">{row.model}</td>
                          <td>{fmtBig(row.calls)}</td>
                          <td>{fmtBig(row.promptTokens)}</td>
                          <td>{fmtBig(row.completionTokens)}</td>
                          <td>{fmtBig(row.totalTokens)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="sm-empty">最近 30 天暂无模型调用记录</div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {activeTab === "scenario" && scenarioTab === "tools" ? (
        <div className="sm-view">
          <section className="sm-kpis">
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>工具调用次数</span>
                <i className="sm-lyr">{windowLabel}</i>
              </div>
              <div className="sm-val">
                <b>{toolsData ? fmtBig(toolsData.totals.calls) : "—"}</b>
              </div>
              <div className="sm-note">来自链路追踪的 tool_call 事件</div>
            </div>
            <div
              className={`sm-panel sm-kpi ${
                toolsData && toolsData.totals.errors > 0 ? "warned" : "good"
              }`}
            >
              <div className="sm-tag">
                <span>调用错误</span>
                <i className="sm-lyr">errors</i>
              </div>
              <div className="sm-val">
                <b>{toolsData ? fmtBig(toolsData.totals.errors) : "—"}</b>
                <small>
                  {toolsData
                    ? `${(toolsData.totals.errRate * 100).toFixed(1)}%`
                    : ""}
                </small>
              </div>
              <div className="sm-note">outcome 非 ok 的调用</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>平均耗时</span>
                <i className="sm-lyr">avg</i>
              </div>
              <div className="sm-val">
                <b>
                  {toolsData?.totals.avgDurationMs == null
                    ? "—"
                    : toolsData.totals.avgDurationMs >= 1000
                      ? `${(toolsData.totals.avgDurationMs / 1000).toFixed(2)} s`
                      : `${toolsData.totals.avgDurationMs.toFixed(0)} ms`}
                </b>
              </div>
              <div className="sm-note">工具执行 duration_ms 均值</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>覆盖工具数</span>
                <i className="sm-lyr">tools</i>
              </div>
              <div className="sm-val">
                <b>{toolsData ? toolsData.byTool.length : "—"}</b>
              </div>
              <div className="sm-note">窗口内被调用过的工具种类</div>
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i />
                <h3>工具调用趋势</h3>
                <span className="sm-en">calls · errors</span>
              </div>
              {toolsData?.trend.length ? (
                <div className="sm-chart-body" style={{ height: 210 }}>
                  <EChart option={toolsTrendOption} />
                </div>
              ) : (
                <div className="sm-empty">
                  <b>窗口内暂无工具调用</b>
                  <br />
                  Agent 执行任意工具后,这里按时间分桶展示次数与错误。
                </div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-violet)" }} />
                <h3>工具调用 Top</h3>
                <span className="sm-en">by tool</span>
              </div>
              {toolsData?.byTool.length ? (
                <div className="sm-chart-body" style={{ height: 210 }}>
                  <EChart option={toolsTopOption} />
                </div>
              ) : (
                <div className="sm-empty">暂无数据</div>
              )}
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-green)" }} />
                <h3>工具明细</h3>
                <span className="sm-en">calls · errors · avg</span>
              </div>
              {toolsData?.byTool.length ? (
                <div className="sm-table-wrap">
                  <table className="sm-table">
                    <thead>
                      <tr>
                        <th>工具</th>
                        <th>调用</th>
                        <th>错误</th>
                        <th>错误率</th>
                        <th>平均耗时</th>
                      </tr>
                    </thead>
                    <tbody>
                      {toolsData.byTool.map((row) => (
                        <tr key={row.tool}>
                          <td className="sm-td-model">{row.tool}</td>
                          <td>{fmtBig(row.calls)}</td>
                          <td className={row.errors > 0 ? "bad" : ""}>
                            {fmtBig(row.errors)}
                          </td>
                          <td className={row.errRate > 0.05 ? "bad" : ""}>
                            {(row.errRate * 100).toFixed(1)}%
                          </td>
                          <td>
                            {row.avgDurationMs == null
                              ? "—"
                              : row.avgDurationMs >= 1000
                                ? `${(row.avgDurationMs / 1000).toFixed(2)} s`
                                : `${row.avgDurationMs.toFixed(0)} ms`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="sm-empty">暂无数据</div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-orange)" }} />
                <h3>按数字员工分布</h3>
                <span className="sm-en">by workspace</span>
              </div>
              {toolsData?.byAgent.length ? (
                <div className="sm-table-wrap">
                  <table className="sm-table">
                    <thead>
                      <tr>
                        <th>数字员工</th>
                        <th>工具调用</th>
                      </tr>
                    </thead>
                    <tbody>
                      {toolsData.byAgent.map((row) => (
                        <tr key={row.agent}>
                          <td className="sm-td-model">{workspaceDisplayName(row.agent)}</td>
                          <td>{fmtBig(row.calls)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="sm-empty">暂无数据</div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {activeTab === "scenario" && scenarioTab === "users" ? (
        <div className="sm-view">
          <div className="sm-note-banner">
            当前统计按 <b>数字员工工作空间 / 渠道</b> 聚合，不包含终端用户账号维度。
          </div>
          <section className="sm-kpis">
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>活跃工作空间</span>
                <i className="sm-lyr">{sessions?.days ?? 7}d</i>
              </div>
              <div className="sm-val">
                <b>{sessions?.workspaces ? sessions.workspaces.length : "—"}</b>
              </div>
              <div className="sm-note">窗口内有会话活动的数字员工工作空间</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>活跃渠道</span>
                <i className="sm-lyr">channels</i>
              </div>
              <div className="sm-val">
                <b>{sessions?.byChannel ? sessions.byChannel.length : "—"}</b>
              </div>
              <div className="sm-note">portal / dingtalk / console …</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>均会话数</span>
                <i className="sm-lyr">/工作空间</i>
              </div>
              <div className="sm-val">
                <b>
                  {sessions?.workspaces?.length
                    ? (
                        (sessions.totals?.activeSessions ?? 0) /
                        sessions.workspaces.length
                      ).toFixed(1)
                    : "—"}
                </b>
              </div>
              <div className="sm-note">活跃会话 ÷ 活跃工作空间</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>均消息数</span>
                <i className="sm-lyr">/session</i>
              </div>
              <div className="sm-val">
                <b>
                  {sessions?.totals?.activeSessions
                    ? (
                        sessions.totals.messages /
                        sessions.totals.activeSessions
                      ).toFixed(1)
                    : "—"}
                </b>
              </div>
              <div className="sm-note">消息数 ÷ 会话数(≈对话轮次×2)</div>
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i />
                <h3>数字员工 Token 消耗 Top</h3>
                <span className="sm-en">prompt + completion</span>
              </div>
              {sessions?.workspaces?.length ? (
                <div className="sm-table-wrap">
                  <table className="sm-table">
                    <thead>
                      <tr>
                        <th>数字员工</th>
                        <th>输入token</th>
                        <th>输出token</th>
                        <th>合计</th>
                        <th>LLM 调用</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...sessions.workspaces]
                        .sort(
                          (a, b) =>
                            b.promptTokens +
                            b.completionTokens -
                            (a.promptTokens + a.completionTokens),
                        )
                        .map((row) => (
                          <tr key={row.workspace}>
                            <td className="sm-td-model">{workspaceDisplayName(row.workspace)}</td>
                            <td>{fmtBig(row.promptTokens)}</td>
                            <td>{fmtBig(row.completionTokens)}</td>
                            <td>
                              {fmtBig(row.promptTokens + row.completionTokens)}
                            </td>
                            <td>{fmtBig(row.llmCalls)}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="sm-empty">窗口内暂无数字员工活动</div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-green)" }} />
                <h3>渠道会话 Top</h3>
                <span className="sm-en">sessions by channel</span>
              </div>
              {sessions?.byChannel?.length ? (
                <div className="sm-table-wrap">
                  <table className="sm-table">
                    <thead>
                      <tr>
                        <th>渠道</th>
                        <th>会话数</th>
                        <th>用户消息</th>
                        <th>助手消息</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sessions.byChannel.map((row) => (
                        <tr key={row.channel}>
                          <td className="sm-td-model">{row.channel}</td>
                          <td>{fmtBig(row.sessions)}</td>
                          <td>{fmtBig(row.userMessages)}</td>
                          <td>{fmtBig(row.assistantMessages)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="sm-empty">暂无渠道数据</div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {activeTab === "sessions" ? (
        <div className="sm-view">
          {sessions && !sessions.available ? (
            <div className="sm-error-banner">
              会话统计不可用:{sessions.reason || "agent_stats 未就绪"}
            </div>
          ) : null}
          <section className="sm-kpis">
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>活跃会话</span>
                <i className="sm-lyr">{sessions?.days ?? 7}d</i>
              </div>
              <div className="sm-val">
                <b>{fmtBig(sessions?.totals?.activeSessions)}</b>
              </div>
              <div className="sm-note">全数字员工工作空间汇总</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>消息数</span>
                <i className="sm-lyr">user+ai</i>
              </div>
              <div className="sm-val">
                <b>{fmtBig(sessions?.totals?.messages)}</b>
              </div>
              <div className="sm-note">
                用户 {fmtBig(sessions?.totals?.userMessages)} · 助手{" "}
                {fmtBig(sessions?.totals?.assistantMessages)}
              </div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>LLM 调用</span>
                <i className="sm-lyr">calls</i>
              </div>
              <div className="sm-val">
                <b>{fmtBig(sessions?.totals?.llmCalls)}</b>
              </div>
              <div className="sm-note">
                tokens {fmtBig(
                  (sessions?.totals?.promptTokens ?? 0) +
                    (sessions?.totals?.completionTokens ?? 0),
                )}
              </div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>工具调用</span>
                <i className="sm-lyr">tools</i>
              </div>
              <div className="sm-val">
                <b>{fmtBig(sessions?.totals?.toolCalls)}</b>
              </div>
              <div className="sm-note">Agent 执行的工具次数</div>
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i />
                <h3>会话趋势</h3>
                <span className="sm-en">by day</span>
              </div>
              {sessions?.byDate?.length ? (
                <div className="sm-chart-body" style={{ height: 210 }}>
                  <EChart option={sessionTrendOption} />
                </div>
              ) : (
                <div className="sm-empty">最近 {sessions?.days ?? 7} 天暂无会话</div>
              )}
            </div>
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-green)" }} />
                <h3>渠道分布</h3>
                <span className="sm-en">by channel</span>
              </div>
              {sessions?.byChannel?.length ? (
                <div className="sm-table-wrap">
                  <table className="sm-table">
                    <thead>
                      <tr>
                        <th>渠道</th>
                        <th>会话数</th>
                        <th>用户消息</th>
                        <th>助手消息</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sessions.byChannel.map((row) => (
                        <tr key={row.channel}>
                          <td className="sm-td-model">{row.channel}</td>
                          <td>{fmtBig(row.sessions)}</td>
                          <td>{fmtBig(row.userMessages)}</td>
                          <td>{fmtBig(row.assistantMessages)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="sm-empty">暂无渠道数据</div>
              )}
            </div>
          </section>

          <section className="sm-panel">
            <div className="sm-ph">
              <i style={{ background: "var(--sm-violet)" }} />
              <h3>数字员工调用统计</h3>
              <span className="sm-en">by digital employee</span>
              <button className="sm-refresh sm-right" onClick={() => navigate("/traces")}>
                单会话明细 → 链路追踪
              </button>
            </div>
            {sessions?.workspaces?.length ? (
              <div className="sm-table-wrap">
                <table className="sm-table">
                  <thead>
                    <tr>
                      <th>数字员工</th>
                      <th>活跃会话</th>
                      <th>消息数</th>
                      <th>LLM 调用</th>
                      <th>工具调用</th>
                      <th>输入token</th>
                      <th>输出token</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.workspaces.map((row) => (
                      <tr key={row.workspace}>
                        <td className="sm-td-model">{workspaceDisplayName(row.workspace)}</td>
                        <td>{fmtBig(row.activeSessions)}</td>
                        <td>{fmtBig(row.messages)}</td>
                        <td>{fmtBig(row.llmCalls)}</td>
                        <td>{fmtBig(row.toolCalls)}</td>
                        <td>{fmtBig(row.promptTokens)}</td>
                        <td>{fmtBig(row.completionTokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="sm-empty">
                <b>最近 {sessions?.days ?? 7} 天暂无 Agent 活动</b>
                <br />
                会话/消息由 agent_stats 从各数字员工工作空间的会话归档聚合。
              </div>
            )}
          </section>
        </div>
      ) : null}

      <div className="sm-shell" hidden={activeTab !== "overview"}>
        {/* ── layer spine ── */}
        <aside className="sm-spine">
          {(["l1", "l2", "l3", "l4"] as const).map((id) => {
            const layer = layerOf(id);
            const status = layer?.status ?? "unknown";
            const metrics = layer?.metrics ?? {};
            return (
              <div
                key={id}
                className={`sm-lnode ${status}${layerFilter === id ? " selected" : ""}`}
                title={`点击${layerFilter === id ? "取消" : ""}按 ${id.toUpperCase()} 层过滤事件流`}
                onClick={() => setLayerFilter((prev) => (prev === id ? null : id))}
              >
                <div className="sm-ring">{id.toUpperCase()}</div>
                <div>
                  <h4>
                    {LAYER_META[id].name} <span>{LAYER_META[id].en}</span>
                  </h4>
                  <div className="sm-kv">
                    {id === "l1" && (
                      <>
                        <div>
                          <span>会话成功率</span>
                          <b className={num(metrics.chatSuccessRate) >= 0.98 ? "up" : "mid"}>
                            {metrics.chatSuccessRate == null
                              ? "—"
                              : `${(num(metrics.chatSuccessRate) * 100).toFixed(1)}%`}
                          </b>
                        </div>
                        <div>
                          <span>会话轮次</span>
                          <b>{num(metrics.chatTurns)}</b>
                        </div>
                        <div>
                          <span>拨测</span>
                          <b
                            className={
                              Object.values(
                                (metrics.probes ?? {}) as Record<string, boolean>,
                              ).some((up) => !up)
                                ? "bad"
                                : "up"
                            }
                          >
                            {(() => {
                              const probeMap = (metrics.probes ?? {}) as Record<string, boolean>;
                              const total = Object.keys(probeMap).length;
                              if (!total) return "—";
                              const ok = Object.values(probeMap).filter(Boolean).length;
                              return `${ok} / ${total}`;
                            })()}
                          </b>
                        </div>
                      </>
                    )}
                    {id === "l2" && (
                      <>
                        <div>
                          <span>治理超时</span>
                          <b className={num(metrics.governanceTimeouts) > 0 ? "mid" : ""}>
                            {num(metrics.governanceTimeouts)} 次
                          </b>
                        </div>
                        <div>
                          <span>治理拒绝</span>
                          <b>{num(metrics.governanceDenies)} 次</b>
                        </div>
                      </>
                    )}
                    {id === "l3" && (
                      <>
                        <div>
                          <span>LLM 429</span>
                          <b className={num(metrics.llm429) > 0 ? "bad" : ""}>
                            {num(metrics.llm429)} 次
                          </b>
                        </div>
                        <div>
                          <span>降级事件</span>
                          <b className={num(metrics.degradeEvents) > 0 ? "bad" : ""}>
                            {num(metrics.degradeEvents)} 起
                          </b>
                        </div>
                      </>
                    )}
                    {id === "l4" && (
                      <>
                        <div>
                          <span>Worker 存活</span>
                          <b className={num(metrics.workersUp) > 0 ? "up" : "bad"}>
                            {num(metrics.workersUp)}
                          </b>
                        </div>
                        <div>
                          <span>日志 ERROR</span>
                          <b className={num(metrics.logErrors) > 20 ? "mid" : ""}>
                            {num(metrics.logErrors)} 条
                          </b>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          <div className="sm-spine-foot">
            <div>
              <span>统计窗口</span>
              <b>{windowLabel}</b>
            </div>
            <div>
              <span>自动刷新</span>
              <b>15s</b>
            </div>
            <div>
              <span>采集状态</span>
              <b>{overview?.enabled === false ? "已关闭" : hasData ? "运行中" : "待数据"}</b>
            </div>
          </div>
        </aside>

        {/* ── main column ── */}
        <main className="sm-main">
          <section className="sm-kpis">
            <div className={`sm-panel sm-kpi ${num(kpis?.degradeEvents) > 0 ? "alarm" : "good"}`}>
              <div className="sm-tag">
                <span>降级事件</span>
                <i className="sm-lyr">L3</i>
              </div>
              <div className="sm-val">
                <b key={`degrade-${kpis ? num(kpis.degradeEvents) : "-"}`}>
                  {kpis ? num(kpis.degradeEvents) : "—"}
                </b>
                <small>起 / {windowLabel}</small>
              </div>
              <div className="sm-note">任何组件退回模版/降级路径</div>
            </div>
            <div className={`sm-panel sm-kpi ${num(kpis?.llm429) > 0 ? "warned" : "good"}`}>
              <div className="sm-tag">
                <span>LLM 限流 429</span>
                <i className="sm-lyr">L3</i>
              </div>
              <div className="sm-val">
                <b key={`llm429-${kpis ? num(kpis.llm429) : "-"}`}>
                  {kpis ? num(kpis.llm429) : "—"}
                </b>
                <small>次 / {windowLabel}</small>
              </div>
              <div className="sm-note">上游 TPM 限流命中</div>
            </div>
            <div className={`sm-panel sm-kpi ${num(kpis?.workersUp) > 0 ? "good" : "alarm"}`}>
              <div className="sm-tag">
                <span>Worker 存活</span>
                <i className="sm-lyr">L4</i>
              </div>
              <div className="sm-val">
                <b key={`workers-${kpis ? num(kpis.workersUp) : "-"}`}>
                  {kpis ? num(kpis.workersUp) : "—"}
                </b>
                <small>UP</small>
              </div>
              <div className="sm-note">心跳 &lt; 60s 的进程数</div>
            </div>
            <div className="sm-panel sm-kpi good">
              <div className="sm-tag">
                <span>会话成功率</span>
                <i className="sm-lyr">L1</i>
              </div>
              <div className="sm-val">
                <b key={`chat-${kpis?.chatSuccessRate ?? "-"}`}>
                  {kpis?.chatSuccessRate == null
                    ? "—"
                    : (num(kpis.chatSuccessRate) * 100).toFixed(1)}
                </b>
                <small>%</small>
              </div>
              <div className="sm-note">终态 success 占比</div>
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-red)" }} />
                <h3>告警</h3>
                <span className="sm-en">Alerts</span>
                <span className="sm-right">
                  触发中 {alerts.active.length} · 历史 {alerts.recent.length}
                </span>
              </div>
              {alerts.active.length || alerts.recent.length ? (
                <div className="sm-alert-list">
                  {(alerts.active.length ? alerts.active : alerts.recent.slice(0, 5)).map(
                    (alert) => (
                      <div
                        key={alert.id}
                        className={`sm-alert ${alert.state} ${alert.severity}`}
                      >
                        <div className="sm-alert-head">
                          <b>{alert.name}</b>
                          <span className="sm-alert-state">
                            {alert.state === "firing" ? "FIRING" : "已恢复"}
                          </span>
                          <time>{fmtTime(alert.startedAt)}</time>
                        </div>
                        <p>{alert.message}</p>
                      </div>
                    ),
                  )}
                </div>
              ) : (
                <div className="sm-empty">
                  <b>无告警</b>
                  <br />
                  规则引擎随采集循环每 15s 评估;规则可经 self_monitor_rules.json 扩展。
                </div>
              )}
            </div>

            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-violet)" }} />
                <h3>AI 根因诊断</h3>
                <span className="sm-en">Diagnose</span>
                <button className="sm-refresh sm-right" onClick={runDiagnose} disabled={diagLoading}>
                  {diagLoading ? "诊断中…" : "运行诊断"}
                </button>
              </div>
              {diagnosis ? (
                <div className="sm-diag">
                  <div className="sm-diag-head">
                    <b>{diagnosis.summary}</b>
                    <span className={`sm-diag-engine ${diagnosis.engine}`}>
                      {diagnosis.engine === "llm" ? "LLM" : "规则引擎"} ·{" "}
                      {diagnosis.confidence}
                    </span>
                  </div>
                  <p className="sm-diag-cause">{diagnosis.rootCause}</p>
                  {diagnosis.evidence.length ? (
                    <ul>
                      {diagnosis.evidence.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  ) : null}
                  {diagnosis.recommendations.length ? (
                    <div className="sm-diag-reco">
                      建议:{diagnosis.recommendations.join(";")}
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="sm-empty">
                  <b>点击「运行诊断」</b>
                  <br />
                  汇总四层快照交给 LLM 出根因;未配置模型时由规则引擎兜底。
                </div>
              )}
            </div>
          </section>

          <section className="sm-panel">
            <div className="sm-ph">
              <i />
              <h3>依赖层脉搏</h3>
              <span className="sm-en">LLM Requests · {windowLabel}</span>
              <span className="sm-right">成功 / 429 / 降级(每分钟增量)</span>
            </div>
            {hasData && chartHasData ? (
              <div className="sm-chart-body">
                <EChart option={chartOption} />
              </div>
            ) : (
              <div className="sm-empty">
                <b>暂无时序数据</b>
                <br />
                自监控随后端运行自动累积;产生 LLM 调用后这里会出现脉搏曲线。
              </div>
            )}
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-violet)" }} />
                <h3>数据源连通</h3>
                <span className="sm-en">connection_status</span>
              </div>
              {Object.keys(datasources).length ? (
                <div className="sm-dsgrid">
                  {Object.entries(datasources).map(([source, ds]) => {
                    const cls = !ds.configured
                      ? "unconfigured"
                      : ds.up === null
                        ? "probing"
                        : ds.up
                          ? "up"
                          : "down";
                    const label = !ds.configured
                      ? "未配置"
                      : ds.up === null
                        ? "探测中"
                        : ds.up
                          ? "可达"
                          : "断连";
                    const title = !ds.configured
                      ? `${source}: 连接参数未配置(去 设置 页配置后重启后端)`
                      : `${source}: 对配置的 base URL 做真实 HTTP 探活(60s 周期)· 当前${label}`;
                    return (
                      <div key={source} className={`sm-ds ${cls}`} title={title}>
                        <i />
                        {source}
                        <small>{label}</small>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="sm-empty">
                  <b>等待首轮探活</b>
                  <br />
                  数据源可达性由后端每 60s 真实 HTTP 探测,非配置检查。
                </div>
              )}
            </div>

            <div className="sm-panel">
              <div className="sm-ph">
                <i />
                <h3>L4 资源</h3>
                <span className="sm-en">psutil · 15s</span>
              </div>
              <div className="sm-gauges">
                {Object.entries(rssByWorker).map(([worker, rss]) => (
                  <div key={worker} className={`sm-gauge ${rss > 1.5 * (1 << 30) ? "hot" : ""}`}>
                    <div className="sm-top">
                      <span>RSS · {worker.split(":").pop()}</span>
                      <b>{fmtBytes(rss)}</b>
                    </div>
                    <div className="sm-bar">
                      <i style={{ width: `${Math.min(100, (rss / (2 * (1 << 30))) * 100)}%` }} />
                    </div>
                  </div>
                ))}
                <div className={`sm-gauge ${num(l4?.metrics?.diskUsagePercent) >= 85 ? "hot" : ""}`}>
                  <div className="sm-top">
                    <span>磁盘 · working</span>
                    <b>
                      {l4?.metrics?.diskUsagePercent == null
                        ? "—"
                        : `${num(l4?.metrics?.diskUsagePercent).toFixed(0)}%`}
                    </b>
                  </div>
                  <div className="sm-bar">
                    <i style={{ width: `${Math.min(100, num(l4?.metrics?.diskUsagePercent))}%` }} />
                  </div>
                </div>
                <div className={`sm-gauge ${num(l4?.metrics?.logErrors) > 20 ? "hot" : ""}`}>
                  <div className="sm-top">
                    <span>日志 ERROR / {windowLabel}</span>
                    <b>{num(l4?.metrics?.logErrors)} 条</b>
                  </div>
                  <div className="sm-bar">
                    <i style={{ width: `${Math.min(100, num(l4?.metrics?.logErrors) * 2)}%` }} />
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="sm-subrow">
            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-green)" }} />
                <h3>依赖图谱</h3>
                <span className="sm-en">Topology</span>
                <span className="sm-right">
                  {topology ? `${topology.nodes.length} 节点` : ""}
                </span>
              </div>
              {topology && topology.nodes.length > 1 ? (
                <div className="sm-chart-body" style={{ height: 220 }}>
                  <EChart option={topoOption} />
                </div>
              ) : (
                <div className="sm-empty">
                  <b>图谱待数据</b>
                  <br />
                  worker / 模型 / 数据源关系由指标标签自动派生。
                </div>
              )}
            </div>

            <div className="sm-panel">
              <div className="sm-ph">
                <i style={{ background: "var(--sm-orange)" }} />
                <h3>LLM 成本(今日)</h3>
                <span className="sm-en">Cost</span>
              </div>
              {cost?.configured ? (
                <div>
                  <div className="sm-cost-total">
                    <b>{cost.total == null ? "—" : cost.total.toFixed(2)}</b>
                    <small>{cost.currency}</small>
                    {cost.budgetDaily != null ? (
                      <span className="sm-cost-budget">
                        预算 {cost.budgetDaily.toFixed(0)} {cost.currency}
                      </span>
                    ) : null}
                  </div>
                  {cost.budgetDaily != null && cost.total != null ? (
                    <div className={`sm-gauge ${cost.total > cost.budgetDaily ? "hot" : ""}`}>
                      <div className="sm-bar">
                        <i
                          style={{
                            width: `${Math.min(100, (cost.total / cost.budgetDaily) * 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  ) : null}
                  <div className="sm-cost-models">
                    {Object.entries(cost.byModel)
                      .slice(0, 4)
                      .map(([model, amount]) => (
                        <div key={model}>
                          <span>{model}</span>
                          <b>
                            {amount.toFixed(2)} {cost.currency}
                          </b>
                        </div>
                      ))}
                    {cost.unpricedModels.length ? (
                      <div className="sm-cost-unpriced">
                        未配置单价: {cost.unpricedModels.join(", ")}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="sm-empty">
                  <b>未配置模型单价</b>
                  <br />
                  在 self_monitor_costs.json 配置 prices/budgetDaily 后此卡与预算告警生效。
                </div>
              )}
            </div>
          </section>
        </main>

        {/* ── events ── */}
        <aside className="sm-events-col">
          <div className="sm-panel" style={{ paddingBottom: 12 }}>
            <div className="sm-ph" style={{ marginBottom: 0 }}>
              <i style={{ background: "var(--sm-red)" }} />
              <h3>事件流</h3>
              <span className="sm-en">Events</span>
              <span className="sm-right">
                {layerFilter ? (
                  <span
                    className="sm-filter-chip"
                    onClick={() => setLayerFilter(null)}
                    title="点击清除层过滤"
                  >
                    {layerFilter.toUpperCase()} 层 ✕
                  </span>
                ) : (
                  <>
                    24h:{" "}
                    {Object.entries(overview?.eventCounts ?? {})
                      .map(([sev, count]) => `${sev} ${count}`)
                      .join(" · ") || "0"}
                  </>
                )}
              </span>
            </div>
          </div>
          <div className="sm-feed">
            {filteredEvents.length ? (
              filteredEvents.map((event, index) => (
                <div
                  key={`${event.dedupKey}-${event.ts}-${index}`}
                  className={`sm-evt ${event.severity}${
                    expandedEvent === `${event.dedupKey}-${event.ts}` ? " expanded" : ""
                  }`}
                  onClick={() =>
                    setExpandedEvent((prev) =>
                      prev === `${event.dedupKey}-${event.ts}`
                        ? null
                        : `${event.dedupKey}-${event.ts}`,
                    )
                  }
                >
                  <div className="sm-rail" />
                  <div>
                    <div className="sm-l1">
                      <span className="sm-type">{event.type}</span>
                      {event.count > 1 ? <span className="sm-cnt">×{event.count}</span> : null}
                      <time>{fmtTime(event.ts)}</time>
                    </div>
                    {event.message ? <p>{event.message}</p> : null}
                    {event.message && event.message.length > 64 ? (
                      <div className="sm-expand-hint">
                        {expandedEvent === `${event.dedupKey}-${event.ts}`
                          ? "点击收起"
                          : "点击展开全文"}
                      </div>
                    ) : null}
                    <div className="sm-src">
                      {event.layer.toUpperCase()} · {event.source || "system"}
                    </div>
                  </div>
                </div>
              ))
            ) : layerFilter ? (
              <div className="sm-empty">
                <b>{layerFilter.toUpperCase()} 层暂无事件</b>
                <br />
                点击左侧选中的层节点(或上方过滤标签)可取消过滤。
              </div>
            ) : (
              <div className="sm-empty">
                <b>暂无事件</b>
                <br />
                worker 重启、429 风暴、组件降级、治理超时等信号会在这里出现。
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
