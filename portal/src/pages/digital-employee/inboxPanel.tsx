import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { inboxApi, type InboxEvent, type InboxTrace } from "../../api/inbox";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import "../inbox-panel.css";

type InboxTab = "messages" | "approvals";
type SourceFilter = "all" | "cron" | "heartbeat";
type NoticeTone = "success" | "error";

const POLL_INTERVAL_MS = 6000;
const PAGE_SIZE = 5;

const SOURCE_FILTERS: Array<{ value: SourceFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "cron", label: "定时" },
  { value: "heartbeat", label: "心跳" },
];

function normalizeTimestamp(value: string | number | null | undefined) {
  if (typeof value === "number") {
    return value > 1e12 ? value : value * 1000;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return Date.now();
    }
    if (/^\d+(\.\d+)?$/.test(trimmed)) {
      const numeric = Number(trimmed);
      return numeric > 1e12 ? numeric : numeric * 1000;
    }
    const parsed = Date.parse(trimmed);
    return Number.isNaN(parsed) ? Date.now() : parsed;
  }
  return Date.now();
}

function formatTimestamp(value: string | number) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(normalizeTimestamp(value)));
}

function formatDateTime(value: string | number) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(normalizeTimestamp(value)));
}

function getSeverityLabel(severity: string) {
  const normalized = severity.toLowerCase();
  if (normalized === "critical") return "紧急";
  if (normalized === "error") return "错误";
  if (normalized === "warning") return "提醒";
  return "信息";
}

function getSourceLabel(sourceType: string) {
  if (sourceType === "cron") return "Cron";
  if (sourceType === "heartbeat") return "Heartbeat";
  return sourceType || "System";
}

function getSourceIcon(sourceType: string) {
  if (sourceType === "cron") return "fas fa-clock";
  if (sourceType === "heartbeat") return "fas fa-heartbeat";
  if (sourceType === "approval") return "fas fa-check-circle";
  return "fas fa-envelope";
}

function getStatusLabel(status: string) {
  const normalized = (status || "").toLowerCase();
  if (normalized === "success") return "成功";
  if (normalized === "error") return "失败";
  if (normalized === "timeout") return "超时";
  if (normalized === "cancelled") return "已取消";
  if (normalized === "running") return "进行中";
  return status || "未知";
}

function summarizeBody(text: string, maxLength = 132) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "暂无详细内容";
  }
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}…` : normalized;
}

function stringifyJson(value: unknown) {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function resolveTraceRunId(event: InboxEvent | null) {
  if (!event) {
    return "";
  }
  const payload = event.payload && typeof event.payload === "object"
    ? (event.payload as Record<string, unknown>)
    : {};
  const candidates = [
    payload.run_id,
    payload.runId,
    payload.trace_run_id,
    payload.traceRunId,
    payload.task_run_id,
    payload.taskRunId,
    event.source_id,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "";
}

// ── Trace timeline rendering helpers ──────────────────────────────────────────

interface TraceEventRaw {
  at: number;
  event: Record<string, unknown>;
}

function getTraceBlock(evt: Record<string, unknown>) {
  const content = evt.content;
  if (!Array.isArray(content) || !content.length) return null;
  return content[0] as Record<string, unknown>;
}

function classifyTraceEvent(evt: Record<string, unknown>): string {
  if (evt.role === "user") return "user";
  const block = getTraceBlock(evt);
  const bt = String(block?.type || "").toLowerCase();
  if (bt === "thinking") return "thinking";
  if (bt === "tool_use") return "tool_call";
  if (bt === "tool_result") return "tool_output";
  if (bt === "text") return "assistant";
  if (evt.type === "response_completed") return "skip";
  return "other";
}

function extractText(evt: Record<string, unknown>): string {
  const block = getTraceBlock(evt);
  if (!block) return "";
  const bt = String(block.type || "").toLowerCase();
  if (bt === "thinking") return String(block.thinking || "");
  if (bt === "text") return String(block.text || "");
  if (bt === "tool_use") {
    if (typeof block.raw_input === "string") return block.raw_input;
    if (block.input !== undefined) {
      try { return JSON.stringify(block.input, null, 2); } catch { return String(block.input); }
    }
    return "";
  }
  if (bt === "tool_result") {
    const output = block.output;
    if (Array.isArray(output)) {
      return output
        .map((o: Record<string, unknown>) => (typeof o?.text === "string" ? o.text : ""))
        .filter(Boolean)
        .join("\n");
    }
    if (output !== undefined) {
      try { return JSON.stringify(output, null, 2); } catch { return String(output); }
    }
    return "";
  }
  return "";
}

function getToolName(evt: Record<string, unknown>): string {
  const block = getTraceBlock(evt);
  return String(block?.name || evt.tool_name || "tool");
}

function renderTraceTimeline(rawEvents: TraceEventRaw[]) {
  if (!rawEvents.length) return <div className="inbox-trace-state empty">暂无执行追踪</div>;

  // Flatten multi-content events
  const flat: Array<{ at: number; evt: Record<string, unknown>; kind: string }> = [];
  for (const raw of rawEvents) {
    const evt = (raw.event || {}) as Record<string, unknown>;
    const content = evt.content;
    if (Array.isArray(content) && content.length > 1) {
      for (const block of content) {
        const sub = { ...evt, content: [block] } as Record<string, unknown>;
        const kind = classifyTraceEvent(sub);
        if (kind !== "skip") flat.push({ at: raw.at, evt: sub, kind });
      }
    } else {
      const kind = classifyTraceEvent(evt);
      if (kind !== "skip") flat.push({ at: raw.at, evt, kind });
    }
  }

  const elements: JSX.Element[] = [];
  for (let i = 0; i < flat.length; i++) {
    const { evt, kind } = flat[i];
    const text = extractText(evt);
    if (!text && kind !== "tool_call" && kind !== "tool_output") continue;

    if (kind === "user") {
      elements.push(
        <div key={i} className="inbox-trace-user-row">
          <div className="inbox-trace-user-bubble">{text}</div>
        </div>
      );
    } else if (kind === "tool_call") {
      const toolName = getToolName(evt);
      // Try to pair with next tool_output
      let toolOutput = "";
      if (i + 1 < flat.length && flat[i + 1].kind === "tool_output") {
        toolOutput = extractText(flat[i + 1].evt);
        i++; // skip paired output
      }
      elements.push(
        <TraceToolBlock key={i} name={toolName} input={text} output={toolOutput} />
      );
    } else if (kind === "tool_output") {
      // Unpaired output
      elements.push(
        <TraceToolBlock key={i} name="tool" input="" output={text} />
      );
    } else if (kind === "thinking") {
      elements.push(
        <TraceCollapsible key={i} title="💡 Thinking" content={text} />
      );
    } else {
      // assistant / other
      elements.push(
        <div key={i} className="inbox-trace-assistant">
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>{text}</ReactMarkdown>
        </div>
      );
    }
  }
  return elements.length ? <>{elements}</> : <div className="inbox-trace-state empty">暂无可展示的追踪内容</div>;
}

function TraceToolBlock({ name, input, output }: { name: string; input: string; output: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`inbox-trace-tool${open ? " open" : ""}`}>
      <button type="button" className="inbox-trace-tool-header" onClick={() => setOpen((p) => !p)}>
        <span className="inbox-trace-tool-icon">🔗</span>
        <span className="inbox-trace-tool-name">{name}</span>
        <span className={`inbox-trace-chevron${open ? " rotated" : ""}`}>▸</span>
      </button>
      {open && (
        <div className="inbox-trace-tool-body">
          {input && (
            <>
              <div className="inbox-trace-tool-label">Input</div>
              <pre className="inbox-trace-tool-code">{input}</pre>
            </>
          )}
          {output && (
            <>
              <div className="inbox-trace-tool-label">Output</div>
              <pre className="inbox-trace-tool-code">{output}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function TraceCollapsible({ title, content }: { title: string; content: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`inbox-trace-tool${open ? " open" : ""}`}>
      <button type="button" className="inbox-trace-tool-header" onClick={() => setOpen((p) => !p)}>
        <span className="inbox-trace-tool-name">{title}</span>
        <span className={`inbox-trace-chevron${open ? " rotated" : ""}`}>▸</span>
      </button>
      {open && (
        <div className="inbox-trace-tool-body">
          <pre className="inbox-trace-tool-code">{content}</pre>
        </div>
      )}
    </div>
  );
}

export function InboxPanel() {
  const [activeTab, setActiveTab] = useState<InboxTab>("messages");
  const [events, setEvents] = useState<InboxEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ tone: NoticeTone; text: string } | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [detailEventId, setDetailEventId] = useState<string | null>(null);
  const [drawerClosing, setDrawerClosing] = useState(false);
  const [detailTrace, setDetailTrace] = useState<InboxTrace | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState("");
  const [markingAllRead, setMarkingAllRead] = useState(false);
  const [deletingIds, setDeletingIds] = useState<string[]>([]);
  const drawerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const closeDetail = useCallback(() => {
    setDrawerClosing(true);
    drawerTimerRef.current = setTimeout(() => {
      setDetailEventId(null);
      setDrawerClosing(false);
    }, 250);
  }, []);

  useEffect(() => () => {
    if (drawerTimerRef.current) clearTimeout(drawerTimerRef.current);
  }, []);

  const fetchEvents = useCallback(async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
    if (!options.silent) {
      setLoading(true);
    }
    if (!options.silent) {
      setError("");
    }
    try {
      const response = await inboxApi.listInboxEvents({ limit: 200 }, options.signal);
      const nextEvents = [...(response.events || [])].sort(
        (a, b) => normalizeTimestamp(b.created_at) - normalizeTimestamp(a.created_at),
      );
      setEvents(nextEvents);
      setSelectedIds((prev) => prev.filter((id) => nextEvents.some((event) => event.id === id)));
      setNotice(null);
    } catch (err) {
      if (options.signal?.aborted) {
        return;
      }
      setError(err instanceof Error ? err.message : "收件箱加载失败");
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchEvents({ signal: controller.signal });

    const timer = window.setInterval(() => {
      void fetchEvents({ silent: true });
    }, POLL_INTERVAL_MS);

    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [fetchEvents]);

  const unreadCount = useMemo(
    () => events.filter((event) => !event.read).length,
    [events],
  );

  const filteredEvents = useMemo(
    () => events.filter((event) => sourceFilter === "all" || event.source_type === sourceFilter),
    [events, sourceFilter],
  );

  const totalPages = Math.max(1, Math.ceil(filteredEvents.length / PAGE_SIZE));

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages));
  }, [totalPages]);

  const pagedEvents = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredEvents.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredEvents]);

  const detailEvent = useMemo(
    () => events.find((event) => event.id === detailEventId) || null,
    [detailEventId, events],
  );

  useEffect(() => {
    if (detailEventId && !detailEvent) {
      setDetailEventId(null);
    }
  }, [detailEvent, detailEventId]);

  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const currentPageIds = useMemo(() => pagedEvents.map((event) => event.id), [pagedEvents]);
  const allPageSelected = currentPageIds.length > 0 && currentPageIds.every((id) => selectedIdSet.has(id));

  const setEventsReadState = useCallback((eventIds: string[], read: boolean) => {
    const idSet = new Set(eventIds);
    setEvents((prev) => prev.map((event) => (idSet.has(event.id) ? { ...event, read } : event)));
  }, []);

  const markEventsRead = useCallback(async (eventIds: string[]) => {
    const ids = Array.from(new Set(eventIds.filter(Boolean))).filter((id) => {
      const target = events.find((event) => event.id === id);
      return Boolean(target && !target.read);
    });
    if (!ids.length) {
      return;
    }
    setEventsReadState(ids, true);
    try {
      await inboxApi.markRead(ids);
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "标记已读失败" });
      void fetchEvents({ silent: true });
    }
  }, [events, fetchEvents, setEventsReadState]);

  useEffect(() => {
    if (!detailEventId) {
      setDetailTrace(null);
      setTraceError("");
      setTraceLoading(false);
      return;
    }

    const event = events.find((e) => e.id === detailEventId) || null;
    if (!event) {
      setDetailTrace(null);
      setTraceError("");
      setTraceLoading(false);
      return;
    }

    const runId = resolveTraceRunId(event);
    if (!runId) {
      setDetailTrace(null);
      setTraceError("该消息暂无可展示的执行追踪");
      setTraceLoading(false);
      return;
    }

    const controller = new AbortController();
    setTraceLoading(true);
    setTraceError("");
    setDetailTrace(null);

    void inboxApi
      .getTrace(runId, controller.signal)
      .then((trace) => {
        setDetailTrace(trace);
      })
      .catch((err) => {
        if (controller.signal.aborted) {
          return;
        }
        setTraceError(err instanceof Error ? err.message : "加载追踪失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setTraceLoading(false);
        }
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailEventId]);

  const openDetail = useCallback((event: InboxEvent) => {
    setDetailEventId(event.id);
    if (!event.read) {
      void markEventsRead([event.id]);
    }
  }, [markEventsRead]);

  const toggleSelection = useCallback((eventId: string) => {
    setSelectedIds((prev) => (
      prev.includes(eventId) ? prev.filter((id) => id !== eventId) : [...prev, eventId]
    ));
  }, []);

  const toggleSelectCurrentPage = useCallback(() => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allPageSelected) {
        currentPageIds.forEach((id) => next.delete(id));
      } else {
        currentPageIds.forEach((id) => next.add(id));
      }
      return Array.from(next);
    });
  }, [allPageSelected, currentPageIds]);

  const removeEventsLocally = useCallback((eventIds: string[]) => {
    const idSet = new Set(eventIds);
    setEvents((prev) => prev.filter((event) => !idSet.has(event.id)));
    setSelectedIds((prev) => prev.filter((id) => !idSet.has(id)));
    if (detailEventId && idSet.has(detailEventId)) {
      closeDetail();
    }
  }, [detailEventId]);

  const deleteEvents = useCallback(async (eventIds: string[]) => {
    const ids = Array.from(new Set(eventIds.filter(Boolean)));
    if (!ids.length) {
      return;
    }
    setDeletingIds(ids);
    const results = await Promise.allSettled(ids.map((id) => inboxApi.deleteEvent(id)));
    const deletedIds = ids.filter((_, index) => results[index]?.status === "fulfilled");
    const failedCount = ids.length - deletedIds.length;
    if (deletedIds.length) {
      removeEventsLocally(deletedIds);
      setNotice({
        tone: failedCount ? "error" : "success",
        text: failedCount
          ? `已删除 ${deletedIds.length} 条消息，${failedCount} 条删除失败`
          : `已删除 ${deletedIds.length} 条消息`,
      });
    } else if (failedCount) {
      setNotice({ tone: "error", text: "删除失败，请稍后重试" });
    }
    setDeletingIds([]);
  }, [removeEventsLocally]);

  const handleMarkAllRead = useCallback(async () => {
    if (!unreadCount) {
      setNotice({ tone: "success", text: "当前没有未读消息" });
      return;
    }
    setMarkingAllRead(true);
    setEvents((prev) => prev.map((event) => (event.read ? event : { ...event, read: true })));
    try {
      await inboxApi.markAllRead();
      setNotice({ tone: "success", text: `已全部标记为已读（${unreadCount} 条）` });
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "全部已读操作失败" });
      void fetchEvents({ silent: true });
    } finally {
      setMarkingAllRead(false);
    }
  }, [fetchEvents, unreadCount]);

  return (
    <>
      <div className="inbox-panel">
        <div className="inbox-panel-static">
          <div className="inbox-panel-header">
            <div className="inbox-panel-title-wrap">
              <div className="inbox-panel-title">收件箱</div>
              <div className="inbox-panel-subtitle">任务通知、心跳消息与审批入口汇总</div>
            </div>
            <div className="inbox-panel-summary">
              <span className="inbox-summary-pill">
                <i className="fas fa-envelope" /> {events.length} 条消息
              </span>
              <span className="inbox-summary-pill unread">
                <i className="fas fa-circle" /> {unreadCount} 未读
              </span>
            </div>
          </div>

          <div className="inbox-tabs" role="tablist" aria-label="收件箱标签页">
            <button
              type="button"
              className={activeTab === "messages" ? "inbox-tab active" : "inbox-tab"}
              onClick={() => setActiveTab("messages")}
            >
              消息
              <span>{events.length}</span>
            </button>
            <button
              type="button"
              className={activeTab === "approvals" ? "inbox-tab active" : "inbox-tab"}
              onClick={() => setActiveTab("approvals")}
            >
              审批
              <span>0</span>
            </button>
          </div>

          {notice ? (
            <div className={`inbox-notice ${notice.tone}`}>
              <span>{notice.text}</span>
              <button type="button" onClick={() => setNotice(null)} aria-label="关闭提示">
                <i className="fas fa-times" />
              </button>
            </div>
          ) : null}

          {activeTab === "messages" ? (
            <div className="inbox-toolbar">
              <div className="inbox-filter-group">
                {SOURCE_FILTERS.map((item) => {
                  const count = item.value === "all"
                    ? events.length
                    : events.filter((event) => event.source_type === item.value).length;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      className={sourceFilter === item.value ? "inbox-filter-chip active" : "inbox-filter-chip"}
                      onClick={() => {
                        setSourceFilter(item.value);
                        setCurrentPage(1);
                      }}
                    >
                      {item.label}
                      <span>{count}</span>
                    </button>
                  );
                })}
              </div>

              <div className="inbox-actions-bar">
                <button
                  type="button"
                  className="inbox-ghost-btn"
                  onClick={toggleSelectCurrentPage}
                  disabled={!pagedEvents.length}
                >
                  {allPageSelected ? "取消本页" : "本页全选"}
                </button>
                <button
                  type="button"
                  className="inbox-ghost-btn"
                  onClick={handleMarkAllRead}
                  disabled={markingAllRead || !unreadCount}
                >
                  <i className="fas fa-check-circle" /> 全部已读
                </button>
                <button
                  type="button"
                  className="inbox-danger-btn"
                  onClick={() => void deleteEvents(selectedIds)}
                  disabled={!selectedIds.length || deletingIds.length > 0}
                >
                  <i className="fas fa-trash-alt" /> 删除已选{selectedIds.length ? `（${selectedIds.length}）` : ""}
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <div className="inbox-panel-scroll">
          {activeTab === "messages" ? (
            loading ? (
              <div className="inbox-panel-loading">正在同步消息...</div>
            ) : error ? (
              <div className="inbox-panel-error">
                <i className="fas fa-triangle-exclamation" />
                <span>{error}</span>
                <button type="button" className="inbox-ghost-btn" onClick={() => void fetchEvents()}>
                  重试
                </button>
              </div>
            ) : filteredEvents.length ? (
              <div className="inbox-card-list">
                {pagedEvents.map((event) => {
                  const deleting = deletingIds.includes(event.id);
                  const selected = selectedIdSet.has(event.id);
                  return (
                    <article
                      key={event.id}
                      className={event.read ? "inbox-card" : "inbox-card unread"}
                      onClick={() => openDetail(event)}
                    >
                      <label
                        className="inbox-card-check"
                        onClick={(currentEvent) => currentEvent.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleSelection(event.id)}
                        />
                      </label>

                      <div className={`inbox-card-icon tone-${event.severity || "info"}`}>
                        <i className={getSourceIcon(event.source_type)} />
                      </div>

                      <div className="inbox-card-main">
                        <div className="inbox-card-topline">
                          <div className="inbox-card-heading">
                            {!event.read ? <span className="inbox-card-dot" /> : null}
                            <h3>{event.title || "未命名消息"}</h3>
                          </div>
                          <div className="inbox-card-meta">
                            <span className={`inbox-severity-badge tone-${event.severity || "info"}`}>
                              {getSeverityLabel(event.severity || "info")}
                            </span>
                            <time>{formatTimestamp(event.created_at)}</time>
                          </div>
                        </div>

                        <p className="inbox-card-preview">{summarizeBody(event.body)}</p>

                        <div className="inbox-card-footer">
                          <span>
                            <i className={getSourceIcon(event.source_type)} /> {getSourceLabel(event.source_type)}
                          </span>
                          <span>状态：{getStatusLabel(event.status)}</span>
                          <span>Agent：{event.agent_id || "default"}</span>
                        </div>
                      </div>

                      <button
                        type="button"
                        className="inbox-card-delete"
                        disabled={deleting}
                        onClick={(currentEvent) => {
                          currentEvent.stopPropagation();
                          void deleteEvents([event.id]);
                        }}
                        aria-label="删除消息"
                      >
                        <i className="fas fa-trash-alt" />
                      </button>
                    </article>
                  );
                })}

                <div className="inbox-pagination">
                  <span className="inbox-pagination-total">
                    第 {currentPage} / {totalPages} 页 · 共 {filteredEvents.length} 条
                  </span>
                  <button
                    type="button"
                    onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                    disabled={currentPage <= 1}
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    onClick={() => setCurrentPage((page) => Math.min(page + 1, totalPages))}
                    disabled={currentPage >= totalPages}
                  >
                    下一页
                  </button>
                </div>
              </div>
            ) : (
              <div className="inbox-empty-state">
                <i className="fas fa-inbox" />
                <strong>暂无消息</strong>
                <span>当前筛选条件下没有可展示的收件箱内容。</span>
              </div>
            )
          ) : (
            <div className="inbox-empty-state approvals">
              <i className="fas fa-check-circle" />
              <strong>暂无审批请求</strong>
              <span>后续审批类消息会在这里集中展示。</span>
            </div>
          )}
        </div>
      </div>

      {detailEvent ? (
        <div className={`inbox-drawer-overlay${drawerClosing ? " closing" : ""}`} onClick={closeDetail}>
          <aside className={`inbox-drawer${drawerClosing ? " closing" : ""}`} onClick={(event) => event.stopPropagation()}>
            <div className="inbox-drawer-header">
              <h3>{detailEvent.source_type === "cron"
                ? `定时任务：${(detailEvent.title || "").replace(/^(cron result|定时任务结果)\s*[:：]\s*/i, "").trim() || "未命名"}`
                : detailEvent.source_type === "heartbeat"
                ? "心跳检测结果"
                : detailEvent.title || "消息详情"
              }</h3>
              <button type="button" className="inbox-drawer-close" onClick={closeDetail}>
                ✕
              </button>
            </div>

            <div className="inbox-drawer-scroll">
              {/* ── Metadata table (2x2) ────────────────────────── */}
              <table className="inbox-meta-table">
                <tbody>
                  <tr>
                    <td className="inbox-meta-label">执行状态</td>
                    <td>
                      <span className={`inbox-status-tag ${detailEvent.status === "error" ? "error" : "success"}`}>
                        {detailEvent.status || "success"}
                      </span>
                    </td>
                    <td className="inbox-meta-label">所属 Agent</td>
                    <td>{detailEvent.agent_id || "default"}</td>
                  </tr>
                  <tr>
                    <td className="inbox-meta-label">收件时间</td>
                    <td>{formatDateTime(detailEvent.created_at)}</td>
                    <td className="inbox-meta-label">任务 ID</td>
                    <td className="inbox-meta-id">{detailEvent.id || "-"}</td>
                  </tr>
                </tbody>
              </table>

              {/* ── 执行轨迹 ────────────────────────────────────── */}
              <section className="inbox-detail-section">
                <div className="inbox-detail-section-title">执行轨迹</div>
                {traceLoading ? (
                  <div className="inbox-trace-state">正在加载追踪...</div>
                ) : detailTrace && detailTrace.events?.length ? (
                  <div className="inbox-trace-timeline">
                    {renderTraceTimeline(detailTrace.events)}
                  </div>
                ) : detailEvent.body ? (
                  <div className="inbox-trace-body-fallback">
                    <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>{detailEvent.body}</ReactMarkdown>
                  </div>
                ) : (
                  <div className="inbox-trace-state empty">{traceError || "暂无执行追踪"}</div>
                )}
              </section>
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
