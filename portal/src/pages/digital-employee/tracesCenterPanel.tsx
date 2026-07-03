import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  tracesApi,
  type TraceEvent,
  type TraceSessionDetail,
  type TraceSessionSummary,
  type TraceSpan,
  type TraceStats,
  type TraceTrends,
} from "../../api/traces";
import { EChart } from "../../components/big-screen/charts/EChart";
import "./tracesCenterPanel.css";

const REFRESH_INTERVAL_MS = 15000;
const DEFAULT_LIST_LIMIT = 50;

type Filter = {
  keyword: string;
  onlyErrors: boolean;
};

function formatTs(ts: number | undefined | null) {
  if (!ts) return "—";
  const ms = ts * 1000;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

function formatRelative(ts: number | undefined | null): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.max(1, Math.round(diff))} 秒前`;
  if (diff < 3600) return `${Math.round(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.round(diff / 3600)} 小时前`;
  return `${Math.round(diff / 86400)} 天前`;
}

function formatDuration(ms: number | undefined | null) {
  if (ms === undefined || ms === null) return "";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function truncate(text: string, max = 160): string {
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function jsonPretty(value: unknown): string {
  if (value === undefined) return "";
  try {
    return typeof value === "string"
      ? value
      : JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const EVENT_LABEL: Record<string, string> = {
  user_message: "用户输入",
  agent_reply: "助手回复",
  tool_call: "工具调用",
  skill_trigger: "技能触发",
  agent_reasoning: "推理过程",
  error: "异常",
  cancelled: "已中断",
};

const EVENT_ICON: Record<string, string> = {
  user_message: "fa-user",
  agent_reply: "fa-robot",
  tool_call: "fa-screwdriver-wrench",
  skill_trigger: "fa-bolt",
  agent_reasoning: "fa-brain",
  error: "fa-triangle-exclamation",
  cancelled: "fa-ban",
};

function eventLabel(type: string) {
  return EVENT_LABEL[type] || type;
}

function eventIcon(type: string) {
  return EVENT_ICON[type] || "fa-circle-info";
}

function outcomeClass(outcome: string | undefined) {
  switch (outcome) {
    case "ok":
      return "trace-outcome ok";
    case "error":
      return "trace-outcome err";
    case "denied":
    case "auto_denied":
      return "trace-outcome denied";
    case "timeout":
      return "trace-outcome timeout";
    default:
      return "trace-outcome";
  }
}

function outcomeLabel(outcome: string | undefined) {
  switch (outcome) {
    case "ok":
      return "成功";
    case "error":
      return "失败";
    case "denied":
      return "用户拒绝";
    case "auto_denied":
      return "自动拒绝";
    case "timeout":
      return "审批超时";
    default:
      return outcome || "";
  }
}

function StatTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "default" | "warn" | "err";
}) {
  return (
    <div className={`trace-stat ${tone || "default"}`}>
      <div className="trace-stat-value">{value.toLocaleString()}</div>
      <div className="trace-stat-label">{label}</div>
    </div>
  );
}

function EventCard({
  event,
  index,
  open,
  onToggle,
}: {
  event: TraceEvent;
  index: number;
  open: boolean;
  onToggle: () => void;
}) {
  const isTool = event.type === "tool_call";
  const isError = event.type === "error";
  const title = useMemo(() => {
    if (isTool) return event.tool_name || "tool_call";
    if (event.type === "skill_trigger") return event.display_name || event.name || "skill";
    if (event.type === "user_message" || event.type === "agent_reply") {
      return truncate(String(event.text || ""), 120) || eventLabel(event.type);
    }
    if (isError) return event.exception_type || "Error";
    return eventLabel(event.type);
  }, [event, isTool, isError]);

  const previewBody = useMemo(() => {
    if (event.type === "user_message" || event.type === "agent_reply") {
      return event.text || "";
    }
    if (isError || event.type === "cancelled") {
      return event.message || "";
    }
    if (isTool) {
      const out: string[] = [];
      if (event.args !== undefined) out.push(`参数:\n${jsonPretty(event.args)}`);
      if (event.result !== undefined && event.result !== null) {
        out.push(`返回:\n${jsonPretty(event.result)}`);
      }
      if (event.error) out.push(`错误:\n${event.error}`);
      return out.join("\n\n");
    }
    if (event.type === "skill_trigger") {
      const out: string[] = [];
      if (event.input) out.push(`输入: ${event.input}`);
      return out.join("\n");
    }
    return "";
  }, [event, isError, isTool]);

  // Whether collapsing actually hides anything. When the body fits inside
  // the preview budget there is nothing to reveal, so we render it in full
  // (no 3-line clamp) — otherwise expanding a short reply feels like a no-op.
  const PREVIEW_CHARS = 200;
  const previewTruncated =
    previewBody.length > PREVIEW_CHARS || previewBody.split("\n").length > 3;

  const cardClass = `trace-event ${event.type}${
    isError ? " err" : event.outcome === "error" ? " err" : ""
  }`;

  return (
    <div className={cardClass}>
      <button
        type="button"
        className="trace-event-head"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="trace-event-index">{index + 1}</span>
        <span className="trace-event-icon">
          <i className={`fas ${eventIcon(event.type)}`} />
        </span>
        <span className="trace-event-type">{eventLabel(event.type)}</span>
        <span className="trace-event-title" title={title}>
          {title}
        </span>
        {isTool && event.outcome ? (
          <span className={outcomeClass(event.outcome)}>
            {outcomeLabel(event.outcome)}
          </span>
        ) : null}
        {isTool && event.duration_ms !== undefined ? (
          <span className="trace-event-duration">{formatDuration(event.duration_ms)}</span>
        ) : null}
        <span className="trace-event-ts">{formatTs(event.ts)}</span>
        <span className="trace-event-chevron">
          <i className={`fas fa-chevron-${open ? "up" : "down"}`} />
        </span>
      </button>
      {open ? (
        <div className="trace-event-body">
          {previewBody ? <pre className="trace-event-text">{previewBody}</pre> : null}
          <details className="trace-event-raw">
            <summary>原始事件 JSON</summary>
            <pre>{jsonPretty(event)}</pre>
          </details>
        </div>
      ) : previewBody ? (
        <div
          className={`trace-event-preview${previewTruncated ? "" : " full"}`}
        >
          {previewTruncated ? truncate(previewBody, PREVIEW_CHARS) : previewBody}
        </div>
      ) : null}
    </div>
  );
}

const TC_AXIS = {
  axisLabel: { color: "#64748b", fontSize: 10 },
  axisLine: { lineStyle: { color: "#e2e8f0" } },
  splitLine: { lineStyle: { color: "#eef2f7" } },
};

function fmtTokens(n: number | null | undefined): string {
  const v = Number(n ?? 0);
  if (!Number.isFinite(v) || v <= 0) return "—";
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}Mil`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

/** span-ish events (llm_call / tool_call) of one trace */
function spanEvents(events: TraceEvent[]): TraceEvent[] {
  return events.filter(
    (e) => e.type === "llm_call" || e.type === "tool_call",
  );
}

interface TraceRound {
  user: TraceEvent | null;
  children: TraceEvent[];
}

/** group a trace into conversation rounds: each user_message opens one */
function groupRounds(events: TraceEvent[]): TraceRound[] {
  const rounds: TraceRound[] = [];
  let current: TraceRound = { user: null, children: [] };
  for (const event of events) {
    if (event.type === "user_message") {
      if (current.user || current.children.length) rounds.push(current);
      current = { user: event, children: [] };
    } else {
      current.children.push(event);
    }
  }
  if (current.user || current.children.length) rounds.push(current);
  return rounds;
}

function spanName(event: TraceEvent): string {
  if (event.type === "llm_call") {
    const model = String(event.model || "llm");
    return `chat ${model.split(":").pop()}`;
  }
  return String(event.tool_name || "tool");
}

function spanOk(event: TraceEvent): boolean {
  const state = String(event.status || event.outcome || "ok");
  return state === "ok" || state === "success";
}

/** ── 调用树(轮次分组 + 甘特条)────────────────────────────── */
function CallTreeView({ detail }: { detail: TraceSessionDetail }) {
  const events = detail.events;
  const start = events.length ? events[0].ts : 0;
  const end = events.length
    ? Math.max(
        ...events.map(
          (e) => e.ts + (Number(e.duration_ms) || 0) / 1000,
        ),
      )
    : 1;
  const span = Math.max(0.001, end - start);
  const rounds = groupRounds(events);
  if (!spanEvents(events).length) {
    return (
      <div className="traces-detail-empty">
        <p>该会话暂无 LLM/工具 span。</p>
        <p className="hint">
          后端升级后的新会话会自动记录每次 LLM 调用(模型/tokens/TTFT)。
        </p>
      </div>
    );
  }
  return (
    <div className="tc2-tree">
      {rounds.map((round, roundIdx) => (
        <div key={roundIdx} className="tc2-round">
          {round.user ? (
            <div className="tc2-round-head">
              <i className="fas fa-user" />
              <span className="tc2-round-title">
                {truncate(String(round.user.text || "用户输入"), 90)}
              </span>
              <time>{formatTs(round.user.ts)}</time>
            </div>
          ) : null}
          {round.children
            .filter((e) => e.type === "llm_call" || e.type === "tool_call")
            .map((event, idx) => {
              const dur = Number(event.duration_ms) || 0;
              const left = Math.min(
                99,
                Math.max(0, ((event.ts - start) / span) * 100),
              );
              const width = Math.max(0.6, (dur / 1000 / span) * 100);
              const isLlm = event.type === "llm_call";
              return (
                <div
                  key={idx}
                  className={`tc2-span-row${spanOk(event) ? "" : " err"}`}
                >
                  <span className={`tc2-badge ${isLlm ? "llm" : "tool"}`}>
                    {isLlm ? "LLM" : "TOOL"}
                  </span>
                  <div className="tc2-span-main">
                    <div className="tc2-span-name">{spanName(event)}</div>
                    <div className="tc2-span-sub">
                      {isLlm ? (
                        <>
                          <span>model: {String(event.model || "—")}</span>
                          <span className="hl">
                            total tokens:{" "}
                            {fmtTokens(
                              (Number(event.prompt_tokens) || 0) +
                                (Number(event.completion_tokens) || 0),
                            )}
                          </span>
                          <span>
                            TTFT:{" "}
                            {event.ttft_ms != null
                              ? formatDuration(Number(event.ttft_ms))
                              : "—"}
                          </span>
                        </>
                      ) : (
                        <>
                          <span>outcome: {String(event.outcome || "ok")}</span>
                          <span>agent: {String(event.agent_id || "—")}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="tc2-gantt">
                    <i
                      style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}
                      className={spanOk(event) ? "" : "err"}
                    />
                  </div>
                  <span className="tc2-span-dur">{formatDuration(dur)}</span>
                </div>
              );
            })}
        </div>
      ))}
    </div>
  );
}

/** ── 时序线(左 span 列表 + 右字段详情)──────────────────── */
function TimelineView({ detail }: { detail: TraceSessionDetail }) {
  const spans = useMemo(() => spanEvents(detail.events), [detail]);
  const [picked, setPicked] = useState(0);
  const maxDur = Math.max(1, ...spans.map((e) => Number(e.duration_ms) || 0));
  const current = spans[picked];
  if (!spans.length) {
    return (
      <div className="traces-detail-empty">
        <p>该会话暂无 LLM/工具 span。</p>
      </div>
    );
  }
  return (
    <div className="tc2-timeline">
      <div className="tc2-timeline-list">
        {spans.map((event, idx) => {
          const dur = Number(event.duration_ms) || 0;
          const isLlm = event.type === "llm_call";
          return (
            <button
              key={idx}
              type="button"
              className={`tc2-timeline-row${idx === picked ? " on" : ""}${
                spanOk(event) ? "" : " err"
              }`}
              onClick={() => setPicked(idx)}
            >
              <span className={`tc2-badge ${isLlm ? "llm" : "tool"}`}>
                {isLlm ? "LLM" : "TOOL"}
              </span>
              <span className="tc2-timeline-name">{spanName(event)}</span>
              <span className="tc2-timeline-dur">{formatDuration(dur)}</span>
              <span className="tc2-timeline-bar">
                <i style={{ width: `${Math.max(3, (dur / maxDur) * 100)}%` }} />
              </span>
            </button>
          );
        })}
      </div>
      <div className="tc2-timeline-detail">
        {current ? (
          <>
            <div className="tc2-detail-title">
              <span className={`tc2-badge ${current.type === "llm_call" ? "llm" : "tool"}`}>
                {current.type === "llm_call" ? "LLM" : "TOOL"}
              </span>
              <b>{spanName(current)}</b>
              <span className={`trace-outcome ${spanOk(current) ? "ok" : "err"}`}>
                {spanOk(current) ? "成功" : String(current.status || current.outcome)}
              </span>
            </div>
            <table className="tc2-kv">
              <tbody>
                <tr><th>开始时间</th><td>{formatTs(current.ts)}</td></tr>
                <tr><th>耗时</th><td>{formatDuration(Number(current.duration_ms) || 0)}</td></tr>
                {current.type === "llm_call" ? (
                  <>
                    <tr><th>Model</th><td>{String(current.model || "—")}</td></tr>
                    <tr>
                      <th>Input Tokens</th>
                      <td>{fmtTokens(current.prompt_tokens)}</td>
                    </tr>
                    <tr>
                      <th>Output Tokens</th>
                      <td>{fmtTokens(current.completion_tokens)}</td>
                    </tr>
                    <tr>
                      <th>Total Tokens</th>
                      <td>
                        {fmtTokens(
                          (Number(current.prompt_tokens) || 0) +
                            (Number(current.completion_tokens) || 0),
                        )}
                      </td>
                    </tr>
                    <tr>
                      <th>TTFT</th>
                      <td>
                        {current.ttft_ms != null
                          ? formatDuration(Number(current.ttft_ms))
                          : "—(非流式或旧数据)"}
                      </td>
                    </tr>
                  </>
                ) : (
                  <>
                    <tr><th>工具</th><td>{String(current.tool_name || "—")}</td></tr>
                    <tr><th>Agent</th><td>{String(current.agent_id || "—")}</td></tr>
                    <tr><th>结果</th><td>{outcomeLabel(current.outcome)}</td></tr>
                  </>
                )}
              </tbody>
            </table>
            {current.args !== undefined ? (
              <details className="trace-event-raw" open>
                <summary>入参 args</summary>
                <pre>{jsonPretty(current.args)}</pre>
              </details>
            ) : null}
            {current.result !== undefined && current.result !== null ? (
              <details className="trace-event-raw">
                <summary>返回 result</summary>
                <pre>{jsonPretty(current.result)}</pre>
              </details>
            ) : null}
            <details className="trace-event-raw">
              <summary>原始事件 JSON</summary>
              <pre>{jsonPretty(current)}</pre>
            </details>
          </>
        ) : null}
      </div>
    </div>
  );
}

/** ── 推理轨迹(导航彩块 + 消息时间线)────────────────────── */
const TRAJ_COLOR: Record<string, string> = {
  user_message: "#d9679b",
  agent_reply: "#e8923c",
  agent_reasoning: "#8b5cf6",
  tool_call: "#0891b2",
  llm_call: "#64748b",
  error: "#dc2626",
};

function TrajectoryView({
  detail,
  expandedKeys,
  onToggle,
}: {
  detail: TraceSessionDetail;
  expandedKeys: Set<string>;
  onToggle: (key: string) => void;
}) {
  const events = detail.events.filter((e) => e.type !== "llm_call");
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  return (
    <div className="tc2-traj">
      <div className="tc2-traj-nav">
        <span className="tc2-traj-label">导航图({events.length} 条消息)</span>
        <div className="tc2-traj-legend">
          {[["User", "#d9679b"], ["Assistant", "#e8923c"], ["Reasoning", "#8b5cf6"], ["Tool", "#0891b2"], ["Error", "#dc2626"]].map(
            ([label, color]) => (
              <span key={label}>
                <i style={{ background: color }} /> {label}
              </span>
            ),
          )}
        </div>
        <div className="tc2-traj-blocks">
          {events.map((event, idx) => (
            <button
              key={idx}
              type="button"
              title={`${eventLabel(event.type)} · ${formatTs(event.ts)}`}
              style={{ background: TRAJ_COLOR[event.type] || "#94a3b8" }}
              onClick={() =>
                refs.current[idx]?.scrollIntoView({ behavior: "smooth", block: "center" })
              }
            />
          ))}
        </div>
      </div>
      <div className="traces-events">
        {events.map((evt, idx) => {
          const key = `${evt.ts}-${evt.type}-${idx}`;
          return (
            <div key={key} ref={(el) => (refs.current[idx] = el)}>
              <EventCard
                event={evt}
                index={idx}
                open={expandedKeys.has(key)}
                onToggle={() => onToggle(key)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** ── 链路分析(KPI + 占比 + TOP 表 + 单轮趋势)───────────── */
function AnalysisView({ detail }: { detail: TraceSessionDetail }) {
  const events = detail.events;
  const llmSpans = events.filter((e) => e.type === "llm_call");
  const toolSpans = events.filter((e) => e.type === "tool_call");
  const llmDur = llmSpans.reduce((acc, e) => acc + (Number(e.duration_ms) || 0), 0);
  const toolDur = toolSpans.reduce((acc, e) => acc + (Number(e.duration_ms) || 0), 0);
  const totalTokens = llmSpans.reduce(
    (acc, e) =>
      acc + (Number(e.prompt_tokens) || 0) + (Number(e.completion_tokens) || 0),
    0,
  );
  const errors = events.filter(
    (e) => e.type === "error" || !spanOk(e),
  ).length;
  const wall = events.length
    ? Math.max(0, events[events.length - 1].ts - events[0].ts)
    : 0;

  const shareOption = {
    backgroundColor: "transparent",
    animation: false,
    tooltip: { trigger: "item" },
    series: [
      {
        type: "pie",
        radius: ["52%", "78%"],
        label: { color: "#334155", fontSize: 10 },
        itemStyle: { borderColor: "#fff", borderWidth: 2 },
        data: [
          { name: "LLM 耗时", value: Math.round(llmDur) },
          { name: "工具耗时", value: Math.round(toolDur) },
        ],
        color: ["#7c8ff0", "#0891b2"],
      },
    ],
  };
  const roundTrendOption = (
    values: number[],
    color: string,
    unit: string,
  ) => ({
    backgroundColor: "transparent",
    animation: false,
    tooltip: { trigger: "axis" },
    grid: { left: 52, right: 10, top: 12, bottom: 22 },
    xAxis: {
      type: "category",
      data: values.map((_, i) => `#${i + 1}`),
      ...TC_AXIS,
    },
    yAxis: { type: "value", name: unit, ...TC_AXIS },
    series: [
      {
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 5,
        data: values,
        lineStyle: { color, width: 2 },
        areaStyle: { color: `${color}1a` },
        itemStyle: { color },
      },
    ],
  });
  const topRows = (spans: TraceEvent[], nameOf: (e: TraceEvent) => string) =>
    [...spans]
      .sort((a, b) => (Number(b.duration_ms) || 0) - (Number(a.duration_ms) || 0))
      .slice(0, 6);

  return (
    <div className="tc2-analysis">
      <div className="tc2-ana-kpis">
        {[
          ["总耗时", `${wall.toFixed(1)} s`],
          ["Token 消耗", fmtTokens(totalTokens)],
          ["LLM 调用", String(llmSpans.length)],
          ["TOOL 调用", String(toolSpans.length)],
          ["异常", String(errors)],
        ].map(([label, value]) => (
          <div key={label} className={`trace-stat${label === "异常" && errors > 0 ? " err" : ""}`}>
            <div className="trace-stat-value">{value}</div>
            <div className="trace-stat-label">{label}</div>
          </div>
        ))}
      </div>
      <div className="tc2-ana-grid">
        <div className="tc2-ana-card">
          <h4>LLM 与工具调用耗时占比</h4>
          <div style={{ height: 200 }}>
            <EChart option={shareOption} />
          </div>
        </div>
        <div className="tc2-ana-card">
          <h4>LLM 调用耗时 TOP</h4>
          <table className="tc2-kv tc2-top">
            <thead>
              <tr><th>span</th><th>耗时</th><th>输入</th><th>输出</th></tr>
            </thead>
            <tbody>
              {topRows(llmSpans, spanName).map((event, idx) => (
                <tr key={idx}>
                  <td>{spanName(event)}</td>
                  <td>{formatDuration(Number(event.duration_ms) || 0)}</td>
                  <td>{fmtTokens(event.prompt_tokens)}</td>
                  <td>{fmtTokens(event.completion_tokens)}</td>
                </tr>
              ))}
              {!llmSpans.length ? (
                <tr><td colSpan={4}>暂无 LLM span(旧会话无此数据)</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className="tc2-ana-card">
          <h4>TOOL 调用耗时 TOP</h4>
          <table className="tc2-kv tc2-top">
            <thead>
              <tr><th>工具</th><th>耗时</th><th>结果</th></tr>
            </thead>
            <tbody>
              {topRows(toolSpans, spanName).map((event, idx) => (
                <tr key={idx}>
                  <td>{String(event.tool_name || "—")}</td>
                  <td>{formatDuration(Number(event.duration_ms) || 0)}</td>
                  <td>{outcomeLabel(event.outcome)}</td>
                </tr>
              ))}
              {!toolSpans.length ? (
                <tr><td colSpan={3}>该会话没有工具调用</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
      {llmSpans.length >= 2 ? (
        <div className="tc2-ana-grid two">
          <div className="tc2-ana-card">
            <h4>LLM 单轮耗时趋势</h4>
            <div style={{ height: 180 }}>
              <EChart
                option={roundTrendOption(
                  llmSpans.map((e) => Math.round((Number(e.duration_ms) || 0) / 100) / 10),
                  "#7c8ff0",
                  "s",
                )}
              />
            </div>
          </div>
          <div className="tc2-ana-card">
            <h4>LLM 单轮 Token 趋势</h4>
            <div style={{ height: 180 }}>
              <EChart
                option={roundTrendOption(
                  llmSpans.map(
                    (e) =>
                      (Number(e.prompt_tokens) || 0) +
                      (Number(e.completion_tokens) || 0),
                  ),
                  "#0891b2",
                  "tokens",
                )}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function TracesCenterPanel() {
  const [stats, setStats] = useState<TraceStats | null>(null);
  const [sessions, setSessions] = useState<TraceSessionSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>({ keyword: "", onlyErrors: false });
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const refreshTimerRef = useRef<number | null>(null);
  // 对标阿里云链路追踪:列表页三趋势图 + Trace/Span 双视图 + 详情四 tab
  const [trends, setTrends] = useState<TraceTrends | null>(null);
  const [viewMode, setViewMode] = useState<"traces" | "spans">("traces");
  const [spanRows, setSpanRows] = useState<TraceSpan[]>([]);
  const [spanType, setSpanType] = useState<"all" | "llm_call" | "tool_call">("all");
  const [detailTab, setDetailTab] = useState<
    "tree" | "timeline" | "trajectory" | "analysis"
  >("tree");

  const loadTrends = useCallback(async (signal?: AbortSignal) => {
    try {
      setTrends(await tracesApi.trends(30 * 86400, signal));
    } catch {
      /* trends are decoration; the list is the source of truth */
    }
  }, []);

  const loadSpans = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await tracesApi.listSpans(
          {
            spanType,
            keyword: filter.keyword.trim() || undefined,
            limit: 100,
          },
          signal,
        );
        setSpanRows(data.items || []);
      } catch {
        /* keep last rows */
      }
    },
    [spanType, filter.keyword],
  );

  useEffect(() => {
    if (viewMode !== "spans") return;
    const controller = new AbortController();
    void loadSpans(controller.signal);
    return () => controller.abort();
  }, [viewMode, loadSpans]);

  const trendOptions = useMemo(() => {
    const points = trends?.points ?? [];
    const axis = points.map((p) =>
      new Date(p.ts * 1000).toLocaleDateString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
      }),
    );
    const base = (data: number[], color: string, name: string) => ({
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis" },
      grid: { left: 56, right: 10, top: 12, bottom: 20 },
      xAxis: { type: "category", data: axis, ...TC_AXIS },
      yAxis: { type: "value", ...TC_AXIS },
      series: [
        {
          name,
          type: "line",
          smooth: true,
          symbol: "none",
          data,
          lineStyle: { color, width: 2 },
          areaStyle: { color: `${color}1a` },
        },
      ],
    });
    return {
      traces: base(points.map((p) => p.traces), "#2ec7c9", "Trace 数"),
      duration: base(points.map((p) => p.avgDurationS), "#7c8ff0", "平均耗时(s)"),
      tokens: base(points.map((p) => p.tokens), "#8b5cf6", "Token 消耗"),
    };
  }, [trends]);

  const toggleEvent = useCallback((key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const loadStats = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await tracesApi.stats(signal);
      setStats(data);
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      // Don't block UI on stats errors
    }
  }, []);

  const loadList = useCallback(
    async (signal?: AbortSignal) => {
      setListLoading(true);
      setListError(null);
      try {
        const data = await tracesApi.listSessions(
          {
            keyword: filter.keyword.trim() || undefined,
            onlyErrors: filter.onlyErrors,
            limit: DEFAULT_LIST_LIMIT,
          },
          signal,
        );
        setSessions(data.items || []);
        setTotal(data.total || 0);
      } catch (err: any) {
        if (err?.name === "AbortError") return;
        setListError(err?.message || "加载失败");
      } finally {
        setListLoading(false);
      }
    },
    [filter],
  );

  const loadDetail = useCallback(
    async (
      sessionId: string,
      signal?: AbortSignal,
      opts?: { background?: boolean },
    ) => {
      const background = !!opts?.background;
      if (!background) setDetailLoading(true);
      setDetailError(null);
      try {
        const data = await tracesApi.getSession(sessionId, { signal });
        setDetail(data);
      } catch (err: any) {
        if (err?.name === "AbortError") return;
        if (!background) {
          setDetail(null);
          setDetailError(err?.message || "加载失败");
        }
      } finally {
        if (!background) setDetailLoading(false);
      }
    },
    [],
  );

  // Initial + filter-change reload
  useEffect(() => {
    const controller = new AbortController();
    loadStats(controller.signal);
    loadList(controller.signal);
    loadTrends(controller.signal);
    return () => controller.abort();
  }, [loadStats, loadList, loadTrends]);

  // Auto-refresh
  useEffect(() => {
    if (refreshTimerRef.current) {
      window.clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    if (!autoRefresh) return;
    refreshTimerRef.current = window.setInterval(() => {
      const controller = new AbortController();
      loadStats(controller.signal);
      loadList(controller.signal);
      if (selectedId) {
        loadDetail(selectedId, controller.signal, { background: true });
      }
    }, REFRESH_INTERVAL_MS);
    return () => {
      if (refreshTimerRef.current) {
        window.clearInterval(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, [autoRefresh, loadList, loadStats, loadDetail, selectedId]);

  // Pull detail when selection changes
  useEffect(() => {
    setExpandedKeys(new Set());
    setDetailTab("tree");
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    loadDetail(selectedId, controller.signal);
    return () => controller.abort();
  }, [selectedId, loadDetail]);

  const handleManualRefresh = useCallback(() => {
    const controller = new AbortController();
    loadStats(controller.signal);
    loadList(controller.signal);
    if (selectedId) {
      loadDetail(selectedId, controller.signal);
    }
  }, [loadStats, loadList, loadDetail, selectedId]);

  const handleClear = useCallback(
    async (sessionId: string) => {
      if (!window.confirm("清除该会话的全部追溯记录？该操作不可撤销。")) return;
      try {
        await tracesApi.clearSession(sessionId);
        if (selectedId === sessionId) {
          setSelectedId(null);
          setDetail(null);
        }
        handleManualRefresh();
      } catch (err: any) {
        window.alert(err?.message || "清除失败");
      }
    },
    [selectedId, handleManualRefresh],
  );

  const selectedSummary = useMemo(
    () => sessions.find((s) => s.session_id === selectedId) || null,
    [sessions, selectedId],
  );

  return (
    <div className="traces-center">
      <header className="traces-header">
        <div className="traces-header-titles">
          <h2>追溯中心</h2>
          <p>每一次会话、每一次工具调用、每一次推理与回复，全部留痕可溯源。</p>
        </div>
        <div className="traces-header-stats">
          <StatTile label="会话总数" value={stats?.session_count ?? 0} />
          <StatTile label="24h 会话" value={stats?.session_count_24h ?? 0} />
          <StatTile label="事件总数" value={stats?.event_count ?? 0} />
          <StatTile label="工具调用" value={stats?.tool_call_count ?? 0} />
          <StatTile
            label="异常计数"
            value={stats?.error_count ?? 0}
            tone={(stats?.error_count ?? 0) > 0 ? "err" : "default"}
          />
        </div>
      </header>

      {!selectedId ? (
        <>
          <div className="tc2-trends">
            {[
              { title: "Trace 数", option: trendOptions.traces },
              { title: "平均耗时", option: trendOptions.duration },
              { title: "Token 消耗", option: trendOptions.tokens },
            ].map(({ title, option }) => (
              <div key={title} className="tc2-trend-card">
                <h4>{title}</h4>
                {trends?.points.length ? (
                  <div style={{ height: 150 }}>
                    <EChart option={option} />
                  </div>
                ) : (
                  <div className="tc2-trend-empty">最近 30 天暂无 trace</div>
                )}
              </div>
            ))}
          </div>

          <div className="tc2-viewbar">
            <div className="tc2-viewswitch">
              <button
                className={viewMode === "traces" ? "on" : ""}
                onClick={() => setViewMode("traces")}
              >
                <i className="fas fa-list" /> Trace 列表
              </button>
              <button
                className={viewMode === "spans" ? "on" : ""}
                onClick={() => setViewMode("spans")}
              >
                <i className="fas fa-bars-staggered" /> Span 列表
              </button>
            </div>
            {viewMode === "spans" ? (
              <div className="tc2-viewswitch sub">
                {(
                  [
                    ["all", "全部"],
                    ["llm_call", "LLM"],
                    ["tool_call", "工具"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    className={spanType === id ? "on" : ""}
                    onClick={() => setSpanType(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      {!selectedId && viewMode === "spans" ? (
        <div className="tc2-span-table-wrap">
          <table className="tc2-span-table">
            <thead>
              <tr>
                <th>开始时间</th>
                <th>类型</th>
                <th>名称</th>
                <th>耗时</th>
                <th>TTFT</th>
                <th>输入 tokens</th>
                <th>输出 tokens</th>
                <th>状态</th>
                <th>Agent</th>
                <th>所属 Trace</th>
              </tr>
            </thead>
            <tbody>
              {spanRows.map((row, idx) => (
                <tr key={idx} className={row.status === "ok" ? "" : "err"}>
                  <td>{formatTs(row.ts)}</td>
                  <td>
                    <span className={`tc2-badge ${row.type === "llm_call" ? "llm" : "tool"}`}>
                      {row.type === "llm_call" ? "LLM" : "TOOL"}
                    </span>
                  </td>
                  <td className="tc2-td-name">{row.name || "—"}</td>
                  <td>{row.durationMs != null ? formatDuration(row.durationMs) : "—"}</td>
                  <td>{row.ttftMs != null ? formatDuration(row.ttftMs) : "—"}</td>
                  <td>{fmtTokens(row.promptTokens)}</td>
                  <td>{fmtTokens(row.completionTokens)}</td>
                  <td>{row.status}</td>
                  <td>{row.agentId || "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="tc2-link"
                      onClick={() => setSelectedId(row.sessionId)}
                      title={row.sessionId}
                    >
                      {row.sessionId.slice(0, 12)}…
                    </button>
                  </td>
                </tr>
              ))}
              {!spanRows.length ? (
                <tr>
                  <td colSpan={10} className="tc2-span-empty">
                    暂无 span——后端升级后的新会话会记录每次 LLM/工具调用。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}

      <div
        className="traces-body"
        style={!selectedId && viewMode === "spans" ? { display: "none" } : undefined}
      >
        <aside className="traces-sidebar">
          <div className="traces-filter">
            <input
              type="text"
              placeholder="按会话/用户/标题搜索…"
              value={filter.keyword}
              onChange={(e) => setFilter((f) => ({ ...f, keyword: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleManualRefresh();
              }}
            />
            <label className="traces-checkbox">
              <input
                type="checkbox"
                checked={filter.onlyErrors}
                onChange={(e) =>
                  setFilter((f) => ({ ...f, onlyErrors: e.target.checked }))
                }
              />
              仅看异常
            </label>
            <label className="traces-checkbox">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              自动刷新 (15s)
            </label>
            <button type="button" onClick={handleManualRefresh} className="traces-refresh">
              <i className="fas fa-rotate" /> 刷新
            </button>
          </div>
          <div className="traces-list-meta">
            共 {total} 个会话{listLoading ? " · 加载中…" : ""}
          </div>
          {listError ? <div className="traces-error">{listError}</div> : null}
          <div className="traces-list">
            {sessions.length === 0 && !listLoading ? (
              <div className="traces-empty">
                <i className="fas fa-clipboard-list" />
                <p>暂无追溯记录</p>
                <p className="hint">完成一次对话或工具调用后会自动出现在这里。</p>
              </div>
            ) : null}
            {sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                className={`traces-list-item${
                  s.session_id === selectedId ? " active" : ""
                }${s.status === "error" ? " err" : ""}`}
                onClick={() => setSelectedId(s.session_id)}
              >
                <div className="traces-list-title">
                  {s.title || s.session_id.slice(0, 16) + "…"}
                </div>
                <div className="traces-list-preview">{s.preview || "—"}</div>
                <div className="traces-list-row">
                  <span className="traces-list-id" title={s.session_id}>
                    <i className="fas fa-hashtag" /> {s.session_id.slice(0, 10)}
                  </span>
                  <span className="traces-list-channel">
                    <i className="fas fa-plug" /> {s.channel || "—"}
                  </span>
                </div>
                <div className="traces-list-row meta">
                  <span title="LLM 调用数">
                    <i className="fas fa-microchip" /> {s.llm_call_count ?? 0}
                  </span>
                  <span title="工具调用数">
                    <i className="fas fa-screwdriver-wrench" /> {s.tool_call_count}
                  </span>
                  {s.total_tokens ? (
                    <span title="Total tokens">
                      <i className="fas fa-coins" /> {fmtTokens(s.total_tokens)}
                    </span>
                  ) : null}
                  {s.error_count > 0 ? (
                    <span title="异常计数" className="err">
                      <i className="fas fa-triangle-exclamation" /> {s.error_count}
                    </span>
                  ) : null}
                  <span className="traces-list-time">{formatRelative(s.last_event_at)}</span>
                </div>
              </button>
            ))}
          </div>
        </aside>

        <main className="traces-detail">
          {!selectedId ? (
            <div className="traces-detail-empty">
              <i className="fas fa-arrow-left" />
              <p>从左侧选择一个会话查看完整时间线</p>
            </div>
          ) : detailLoading ? (
            <div className="traces-detail-empty">
              <i className="fas fa-spinner fa-spin" />
              <p>加载时间线…</p>
            </div>
          ) : detailError ? (
            <div className="traces-detail-empty err">
              <i className="fas fa-triangle-exclamation" />
              <p>{detailError}</p>
            </div>
          ) : detail ? (
            <>
              <div className="traces-detail-header">
                <div>
                  <h3>{selectedSummary?.title || selectedId}</h3>
                  <div className="traces-detail-meta">
                    <span><i className="fas fa-hashtag" /> {selectedId}</span>
                    {selectedSummary?.agent_id ? (
                      <span><i className="fas fa-robot" /> {selectedSummary.agent_id}</span>
                    ) : null}
                    {selectedSummary?.user_id ? (
                      <span><i className="fas fa-user" /> {selectedSummary.user_id}</span>
                    ) : null}
                    {selectedSummary?.channel ? (
                      <span><i className="fas fa-plug" /> {selectedSummary.channel}</span>
                    ) : null}
                    <span>
                      <i className="fas fa-clock" />{" "}
                      {formatTs(selectedSummary?.first_event_at)} —{" "}
                      {formatTs(selectedSummary?.last_event_at)}
                    </span>
                  </div>
                </div>
                <div className="traces-detail-actions">
                  <button type="button" onClick={() => loadDetail(selectedId)}>
                    <i className="fas fa-rotate" /> 重新加载
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => handleClear(selectedId)}
                  >
                    <i className="fas fa-trash" /> 清除该会话追溯
                  </button>
                </div>
              </div>
              {detail.events.length ? (
                <div className="tc2-detail-kpis">
                  {(() => {
                    const llm = detail.events.filter((e) => e.type === "llm_call");
                    const tools = detail.events.filter((e) => e.type === "tool_call");
                    const tokens = llm.reduce(
                      (acc, e) =>
                        acc +
                        (Number(e.prompt_tokens) || 0) +
                        (Number(e.completion_tokens) || 0),
                      0,
                    );
                    const wall =
                      detail.events[detail.events.length - 1].ts -
                      detail.events[0].ts;
                    return [
                      ["耗时", `${Math.max(0, wall).toFixed(1)} s`],
                      ["总Token消耗", fmtTokens(tokens)],
                      ["LLM 调用", String(llm.length)],
                      ["工具调用", String(tools.length)],
                      [
                        "事件数",
                        String(detail.total || detail.events.length),
                      ],
                    ].map(([label, value]) => (
                      <span key={label} className="tc2-chip">
                        {label} <b>{value}</b>
                      </span>
                    ));
                  })()}
                </div>
              ) : null}

              <nav className="tc2-detail-tabs">
                {(
                  [
                    ["tree", "调用树"],
                    ["timeline", "时序线"],
                    ["trajectory", "推理轨迹"],
                    ["analysis", "链路分析"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    className={detailTab === id ? "on" : ""}
                    onClick={() => setDetailTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </nav>

              {detail.events.length === 0 ? (
                <div className="traces-detail-empty">
                  <p>该会话尚未产生事件。</p>
                </div>
              ) : detailTab === "tree" ? (
                <CallTreeView detail={detail} />
              ) : detailTab === "timeline" ? (
                <TimelineView detail={detail} />
              ) : detailTab === "analysis" ? (
                <AnalysisView detail={detail} />
              ) : (
                <TrajectoryView
                  detail={detail}
                  expandedKeys={expandedKeys}
                  onToggle={toggleEvent}
                />
              )}
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}

export default TracesCenterPanel;
