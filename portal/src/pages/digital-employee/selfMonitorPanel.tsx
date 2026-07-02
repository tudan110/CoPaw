import { useCallback, useEffect, useMemo, useState } from "react";
import {
  selfMonitorApi,
  toDeltaBuckets,
  type SelfMonitorEvent,
  type SelfMonitorLayer,
  type SelfMonitorMetricSeries,
  type SelfMonitorOverview,
  type SelfMonitorStatus,
} from "../../api/selfMonitor";
import { EChart } from "../../components/big-screen/charts/EChart";
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

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function SelfMonitorPanel() {
  const [windowS, setWindowS] = useState<number>(3600);
  const [overview, setOverview] = useState<SelfMonitorOverview | null>(null);
  const [events, setEvents] = useState<SelfMonitorEvent[]>([]);
  const [reqSeries, setReqSeries] = useState<SelfMonitorMetricSeries[]>([]);
  const [degradeSeries, setDegradeSeries] = useState<SelfMonitorMetricSeries[]>([]);
  const [error, setError] = useState("");
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const load = async () => {
      const since = Date.now() / 1000 - windowS;
      try {
        const [ov, ev, req, deg] = await Promise.all([
          selfMonitorApi.overview(windowS, controller.signal),
          selfMonitorApi.events(60, controller.signal),
          selfMonitorApi.metrics("qwenpaw_llm_requests_total", since, controller.signal),
          selfMonitorApi.metrics("qwenpaw_degrade_events_total", since, controller.signal),
        ]);
        if (cancelled) return;
        setOverview(ov);
        setEvents(ev.items || []);
        setReqSeries(req.series || []);
        setDegradeSeries(deg.series || []);
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

  const state: SelfMonitorStatus = overview?.state ?? "unknown";
  const kpis = overview?.kpis;
  const layers = overview?.layers ?? [];
  const layerOf = (id: string): SelfMonitorLayer | undefined =>
    layers.find((l) => l.layer === id);
  const l3 = layerOf("l3");
  const l4 = layerOf("l4");
  const datasources = (l3?.metrics?.datasources ?? {}) as Record<string, boolean>;
  const rssByWorker = (l4?.metrics?.rssBytesByWorker ?? {}) as Record<string, number>;
  const hasData = state !== "unknown";

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
        textStyle: { color: "#9fb2cc", fontSize: 10 },
        itemWidth: 12,
        itemHeight: 6,
      },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: axis.map((t) => fmtClock(t)),
        axisLine: { lineStyle: { color: "rgba(255,255,255,.18)" } },
        axisLabel: { color: "#9fb2cc", fontSize: 10 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#9fb2cc", fontSize: 10 },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } },
      },
      series: [
        {
          name: "请求成功",
          type: "line",
          smooth: true,
          symbol: "none",
          data: axis.map((t) => at(okBuckets, t)),
          lineStyle: { color: "#22d3ee", width: 2 },
          itemStyle: { color: "#22d3ee" },
          areaStyle: { color: "rgba(34,211,238,.10)" },
        },
        {
          name: "429 限流",
          type: "bar",
          data: axis.map((t) => at(err429Buckets, t)),
          itemStyle: { color: "rgba(251,146,60,.8)", borderRadius: [2, 2, 0, 0] },
          barMaxWidth: 10,
        },
        {
          name: "降级",
          type: "bar",
          data: axis.map((t) => at(degradeBuckets, t)),
          itemStyle: { color: "rgba(248,113,113,.85)", borderRadius: [2, 2, 0, 0] },
          barMaxWidth: 10,
        },
      ],
    };
    return { chartOption: option, chartHasData: axis.length > 0 };
  }, [reqSeries, degradeSeries, windowS]);

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
            QwenPaw <em>自监控</em>
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
        <button className="sm-refresh" onClick={refresh}>
          刷新{loadedAt ? ` · ${fmtTime(loadedAt)}` : ""}
        </button>
      </div>

      {error ? (
        <div className="sm-error-banner">自监控接口不可用:{error}</div>
      ) : null}

      <div className="sm-shell">
        {/* ── layer spine ── */}
        <aside className="sm-spine">
          {(["l1", "l2", "l3", "l4"] as const).map((id) => {
            const layer = layerOf(id);
            const status = layer?.status ?? "unknown";
            const metrics = layer?.metrics ?? {};
            return (
              <div key={id} className={`sm-lnode ${status}`}>
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
                <b>{kpis ? num(kpis.degradeEvents) : "—"}</b>
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
                <b>{kpis ? num(kpis.llm429) : "—"}</b>
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
                <b>{kpis ? num(kpis.workersUp) : "—"}</b>
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
                <b>
                  {kpis?.chatSuccessRate == null
                    ? "—"
                    : (num(kpis.chatSuccessRate) * 100).toFixed(1)}
                </b>
                <small>%</small>
              </div>
              <div className="sm-note">终态 success 占比</div>
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
                  {Object.entries(datasources).map(([source, up]) => (
                    <div key={source} className={`sm-ds ${up ? "up" : "down"}`}>
                      <i />
                      {source}
                      <span style={{ marginLeft: "auto", fontSize: 9, opacity: 0.7 }}>
                        {up ? "ok" : "down"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="sm-empty">暂无数据源探测结果</div>
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
        </main>

        {/* ── events ── */}
        <aside className="sm-events-col">
          <div className="sm-panel" style={{ paddingBottom: 12 }}>
            <div className="sm-ph" style={{ marginBottom: 0 }}>
              <i style={{ background: "var(--sm-red)" }} />
              <h3>事件流</h3>
              <span className="sm-en">Events</span>
              <span className="sm-right">
                24h:{" "}
                {Object.entries(overview?.eventCounts ?? {})
                  .map(([sev, count]) => `${sev} ${count}`)
                  .join(" · ") || "0"}
              </span>
            </div>
          </div>
          <div className="sm-feed">
            {events.length ? (
              events.map((event, index) => (
                <div
                  key={`${event.dedupKey}-${event.ts}-${index}`}
                  className={`sm-evt ${event.severity}`}
                >
                  <div className="sm-rail" />
                  <div>
                    <div className="sm-l1">
                      <span className="sm-type">{event.type}</span>
                      {event.count > 1 ? <span className="sm-cnt">×{event.count}</span> : null}
                      <time>{fmtTime(event.ts)}</time>
                    </div>
                    {event.message ? <p>{event.message}</p> : null}
                    <div className="sm-src">
                      {event.layer.toUpperCase()} · {event.source || "system"}
                    </div>
                  </div>
                </div>
              ))
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
