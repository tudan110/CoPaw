import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  tracesApi,
  type TraceEvent,
  type TraceSessionDetail,
  type TraceSessionSummary,
  type TraceStats,
} from "../../api/traces";
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
};

const EVENT_ICON: Record<string, string> = {
  user_message: "fa-user",
  agent_reply: "fa-robot",
  tool_call: "fa-screwdriver-wrench",
  skill_trigger: "fa-bolt",
  agent_reasoning: "fa-brain",
  error: "fa-triangle-exclamation",
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

function EventCard({ event, index }: { event: TraceEvent; index: number }) {
  const [open, setOpen] = useState(false);
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
    if (isError) {
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

  const cardClass = `trace-event ${event.type}${
    isError ? " err" : event.outcome === "error" ? " err" : ""
  }`;

  return (
    <div className={cardClass}>
      <div className="trace-event-head" onClick={() => setOpen((v) => !v)}>
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
      </div>
      {open ? (
        <div className="trace-event-body">
          {previewBody ? <pre className="trace-event-text">{previewBody}</pre> : null}
          <details className="trace-event-raw">
            <summary>原始事件 JSON</summary>
            <pre>{jsonPretty(event)}</pre>
          </details>
        </div>
      ) : previewBody ? (
        <div className="trace-event-preview">{truncate(previewBody, 200)}</div>
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
  const refreshTimerRef = useRef<number | null>(null);

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
    async (sessionId: string, signal?: AbortSignal) => {
      setDetailLoading(true);
      setDetailError(null);
      try {
        const data = await tracesApi.getSession(sessionId, { signal });
        setDetail(data);
      } catch (err: any) {
        if (err?.name === "AbortError") return;
        setDetail(null);
        setDetailError(err?.message || "加载失败");
      } finally {
        setDetailLoading(false);
      }
    },
    [],
  );

  // Initial + filter-change reload
  useEffect(() => {
    const controller = new AbortController();
    loadStats(controller.signal);
    loadList(controller.signal);
    return () => controller.abort();
  }, [loadStats, loadList]);

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
        loadDetail(selectedId, controller.signal);
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

      <div className="traces-body">
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
                  <span title="工具调用数">
                    <i className="fas fa-screwdriver-wrench" /> {s.tool_call_count}
                  </span>
                  <span title="事件总数">
                    <i className="fas fa-stream" /> {s.event_count}
                  </span>
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
              <div className="traces-events">
                {detail.events.length === 0 ? (
                  <div className="traces-detail-empty">
                    <p>该会话尚未产生事件。</p>
                  </div>
                ) : (
                  detail.events.map((evt, idx) => (
                    <EventCard
                      key={`${evt.ts}-${idx}`}
                      event={evt}
                      index={idx}
                    />
                  ))
                )}
              </div>
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}

export default TracesCenterPanel;
