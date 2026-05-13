import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import {
  createChat,
  getChatHistory,
  listChats,
  stopChat,
  streamChat,
} from "../api/copawChat";
import {
  extractCopawMessageText,
  mergeStreamingText,
} from "../pages/digital-employee/helpers";
import { PortalQwenPawMarkdown } from "./PortalQwenPawMarkdown";

const USER_ID = "default";
const CHANNEL = "console";
const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "error",
  "cancelled",
  "canceled",
  "stopped",
]);

let segSeq = 0;
function nextId(prefix: string): string {
  segSeq += 1;
  return `${prefix}-${Date.now().toString(36)}-${segSeq}`;
}

type AssistantSegment = { msgId: string; text: string };

type Turn =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      segments: AssistantSegment[];
      trace: string[];
      status: "running" | "done" | "error";
      error?: string;
    };

function isAssistant(
  turn: Turn,
): turn is Extract<Turn, { role: "assistant" }> {
  return turn.role === "assistant";
}

function renderAnswer(turn: Extract<Turn, { role: "assistant" }>): string {
  return turn.segments
    .map((s) => s.text.trim())
    .filter(Boolean)
    .join("\n\n");
}

type HistoryChat = {
  id: string;
  name?: string;
  session_id?: string;
  created_at?: string;
  updated_at?: string;
};

function formatChatTime(value?: string): string {
  if (!value) {
    return "";
  }
  const t = new Date(value).getTime();
  if (!Number.isFinite(t)) {
    return "";
  }
  const diff = Date.now() - t;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return new Date(t).toLocaleDateString();
}

function normalizeFdeHistory(messages: unknown): Turn[] {
  const list = Array.isArray(messages) ? messages : [];
  const out: Turn[] = [];
  let active: Extract<Turn, { role: "assistant" }> | null = null;
  for (const raw of list) {
    const m = (raw || {}) as Record<string, unknown>;
    const role = String(m.role || "");
    const type = String(m.type || "");
    if (role === "user" && (!type || type === "message")) {
      const text = extractCopawMessageText(m).trim();
      if (!text) {
        continue;
      }
      active = null;
      out.push({ id: String(m.id || nextId("u")), role: "user", text });
      continue;
    }
    if (!active) {
      active = {
        id: String(m.id || nextId("a")),
        role: "assistant",
        segments: [],
        trace: [],
        status: "done",
      };
      out.push(active);
    }
    if (type === "reasoning") {
      continue;
    }
    if (type === "plugin_call" || type === "plugin_call_output") {
      const name = toolNameFromEvent(m);
      if (!active.trace.includes(name)) {
        active.trace.push(name);
      }
      continue;
    }
    if (role === "assistant" && (!type || type === "message")) {
      const text = extractCopawMessageText(m).trim();
      if (text) {
        active.segments.push({ msgId: String(m.id || nextId("s")), text });
      }
    }
  }
  return out;
}

function toolNameFromEvent(event: Record<string, unknown>): string {
  const direct = String((event as { name?: unknown }).name || "").trim();
  if (direct) {
    return direct;
  }
  const content = (event as { content?: unknown }).content;
  if (Array.isArray(content)) {
    for (const item of content) {
      if (item && typeof item === "object") {
        const n = String(
          (item as { name?: unknown }).name ||
            (item as { tool_name?: unknown }).tool_name ||
            "",
        ).trim();
        if (n) {
          return n;
        }
      }
    }
  }
  return "工具";
}

export function FdeConsoleChat({
  agentId,
  agentName,
  onTurnComplete,
}: {
  agentId: string;
  agentName: string;
  onTurnComplete?: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statusLabel, setStatusLabel] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyChats, setHistoryChats] = useState<HistoryChat[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [currentChatName, setCurrentChatName] = useState<string>("");

  const chatIdRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const metaRef = useRef<Map<string, string>>(new Map());
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const statusTimerRef = useRef<number | null>(null);
  const onTurnCompleteRef = useRef(onTurnComplete);
  onTurnCompleteRef.current = onTurnComplete;

  const flashStatus = useCallback((label: string) => {
    if (statusTimerRef.current) {
      window.clearTimeout(statusTimerRef.current);
    }
    setStatusLabel(label);
    statusTimerRef.current = window.setTimeout(() => {
      setStatusLabel("");
      statusTimerRef.current = null;
    }, 2600);
  }, []);

  const adoptChat = useCallback(
    (id: string | null, name?: string, sessionId?: string | null) => {
      chatIdRef.current = id;
      if (sessionId !== undefined) {
        sessionIdRef.current = sessionId;
      } else if (!id) {
        sessionIdRef.current = null;
      }
      setCurrentChatId(id);
      setCurrentChatName(name || "");
    },
    [],
  );

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [turns, statusLabel]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (statusTimerRef.current) {
        window.clearTimeout(statusTimerRef.current);
      }
    },
    [],
  );

  const patchLastAssistant = useCallback(
    (fn: (t: Extract<Turn, { role: "assistant" }>) => Turn) => {
      setTurns((prev) => {
        for (let i = prev.length - 1; i >= 0; i -= 1) {
          const t = prev[i];
          if (isAssistant(t)) {
            const next = prev.slice();
            next[i] = fn(t);
            return next;
          }
        }
        return prev;
      });
    },
    [],
  );

  const upsertSegment = useCallback(
    (msgId: string, apply: (current: string) => string) => {
      patchLastAssistant((t) => {
        const idx = t.segments.findIndex((s) => s.msgId === msgId);
        const segments =
          idx >= 0
            ? t.segments.map((s, i) =>
                i === idx ? { ...s, text: apply(s.text) } : s,
              )
            : [...t.segments, { msgId, text: apply("") }];
        return { ...t, segments };
      });
    },
    [patchLastAssistant],
  );

  const send = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || streaming) {
      return;
    }
    if (overrideText === undefined) {
      setInput("");
    }
    if (statusTimerRef.current) {
      window.clearTimeout(statusTimerRef.current);
      statusTimerRef.current = null;
    }
    metaRef.current = new Map();
    const assistantId = nextId("a");
    setTurns((prev) => [
      ...prev,
      { id: nextId("u"), role: "user", text },
      {
        id: assistantId,
        role: "assistant",
        segments: [],
        trace: [],
        status: "running",
      },
    ]);
    setStreaming(true);
    setStatusLabel("连接中…");
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      let chat = {
        id: chatIdRef.current || "",
        session_id: sessionIdRef.current || "",
      };
      if (!chat.id || !chat.session_id) {
        const name = text.slice(0, 40) || "FDE 交付会话";
        const created = (await createChat(agentId, {
          name,
          session_id: nextId("portal-fde"),
          user_id: USER_ID,
          channel: CHANNEL,
        })) as { id: string; session_id: string; name?: string };
        chat = { id: created.id, session_id: created.session_id };
        adoptChat(chat.id, created.name || name, chat.session_id);
      }

      await streamChat(
        agentId,
        {
          input: [
            {
              role: "user",
              type: "message",
              content: [{ type: "text", text, status: "created" }],
            },
          ],
          session_id: chat.session_id,
          user_id: USER_ID,
          channel: CHANNEL,
          stream: true,
        },
        {
          signal: controller.signal,
          onEvent: (event) => {
            const obj = String(event.object || "");
            if (obj === "message" && event.id && event.role) {
              metaRef.current.set(String(event.id), String(event.type || ""));
              if (event.role === "assistant") {
                if (event.type === "message") {
                  setStatusLabel("");
                } else if (event.type === "reasoning") {
                  setStatusLabel("思考中…");
                } else if (event.type === "plugin_call") {
                  setStatusLabel("调用工具…");
                }
              }
            }
            if (obj === "response" && event.status) {
              setStatusLabel(
                TERMINAL_STATUSES.has(String(event.status)) ? "" : "运行中…",
              );
            }
            if (
              obj === "message" &&
              event.role === "assistant" &&
              (event.type === "plugin_call" ||
                event.type === "plugin_call_output") &&
              event.status === "completed"
            ) {
              const name = toolNameFromEvent(event);
              patchLastAssistant((t) =>
                t.trace.includes(name)
                  ? t
                  : { ...t, trace: [...t.trace, name] },
              );
              return;
            }
            if (
              obj === "message" &&
              event.role === "assistant" &&
              event.type === "message" &&
              event.status === "completed" &&
              event.id
            ) {
              const finalText = extractCopawMessageText(event);
              if (finalText) {
                upsertSegment(String(event.id), () => finalText);
              }
              return;
            }
            if (obj === "content" && event.type === "text" && event.msg_id) {
              const kind = metaRef.current.get(String(event.msg_id));
              if (kind === "reasoning") {
                return;
              }
              const delta = String(event.text || "");
              if (!delta) {
                return;
              }
              upsertSegment(String(event.msg_id), (cur) =>
                mergeStreamingText(cur, delta),
              );
            }
          },
        },
      );
    } catch (error) {
      const msg =
        error instanceof Error ? error.message : "请求失败，请稍后重试";
      patchLastAssistant((t) => ({ ...t, status: "error", error: msg }));
    } finally {
      setStreaming(false);
      setStatusLabel("");
      abortRef.current = null;
      patchLastAssistant((t) =>
        t.status === "running" ? { ...t, status: "done" } : t,
      );
      onTurnCompleteRef.current?.();
    }
  }, [input, streaming, agentId, patchLastAssistant, upsertSegment, adoptChat]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    const id = chatIdRef.current;
    if (id) {
      void stopChat(agentId, id).catch(() => {});
    }
  }, [agentId]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    adoptChat(null);
    metaRef.current = new Map();
    setTurns([]);
    setHistoryOpen(false);
    flashStatus("已开始新会话");
  }, [adoptChat, flashStatus]);

  const openHistory = useCallback(async () => {
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = (await listChats(agentId, {
        user_id: USER_ID,
        channel: CHANNEL,
      })) as unknown;
      const chats: HistoryChat[] = Array.isArray(res)
        ? (res as HistoryChat[])
        : [];
      chats.sort(
        (a, b) =>
          new Date(b.updated_at || b.created_at || 0).getTime() -
          new Date(a.updated_at || a.created_at || 0).getTime(),
      );
      setHistoryChats(chats);
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "加载历史会话失败",
      );
    } finally {
      setHistoryLoading(false);
    }
  }, [agentId]);

  const loadHistoryChat = useCallback(
    async (chat: HistoryChat) => {
      // Allow switching even mid-stream: drop the running stream first.
      abortRef.current?.abort();
      abortRef.current = null;
      setStreaming(false);
      setHistoryOpen(false);
      if (statusTimerRef.current) {
        window.clearTimeout(statusTimerRef.current);
        statusTimerRef.current = null;
      }
      setStatusLabel("载入历史会话…");
      // Adopt eagerly from the list entry so a follow-up message reuses this
      // chat even if the history fetch is slow / fails.
      adoptChat(chat.id, chat.name, chat.session_id || null);
      metaRef.current = new Map();
      try {
        const history = (await getChatHistory(agentId, chat.id)) as {
          messages?: unknown;
          session_id?: string;
          sessionId?: string;
        };
        const sid = String(
          chat.session_id || history.session_id || history.sessionId || "",
        );
        if (sid) {
          sessionIdRef.current = sid;
        }
        const loaded = normalizeFdeHistory(history.messages);
        if (loaded.length) {
          setTurns(loaded);
          flashStatus(`已载入「${chat.name || "历史会话"}」`);
        } else {
          setTurns([
            {
              id: nextId("a"),
              role: "assistant",
              segments: [
                {
                  msgId: nextId("s"),
                  text: "这个会话还没有留下消息记录，直接在下面继续发消息即可。",
                },
              ],
              trace: [],
              status: "done",
            },
          ]);
          flashStatus(`已载入「${chat.name || "历史会话"}」（空会话）`);
        }
      } catch (error) {
        const msg =
          error instanceof Error ? error.message : "载入历史会话失败";
        setTurns([
          {
            id: nextId("a"),
            role: "assistant",
            segments: [{ msgId: nextId("s"), text: `载入历史会话失败：${msg}` }],
            trace: [],
            status: "error",
            error: msg,
          },
        ]);
        setStatusLabel("");
      }
    },
    [agentId, adoptChat, flashStatus],
  );

  const retryLast = useCallback(() => {
    if (streaming) {
      return;
    }
    let lastUserIdx = -1;
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      if (turns[i].role === "user") {
        lastUserIdx = i;
        break;
      }
    }
    if (lastUserIdx < 0) {
      return;
    }
    const t = turns[lastUserIdx];
    const text = t.role === "user" ? t.text : "";
    if (!text) {
      return;
    }
    setTurns((prev) => prev.slice(0, lastUserIdx));
    void send(text);
  }, [streaming, turns, send]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        void send();
      }
    },
    [send],
  );

  return (
    <div className="fde-cc">
      <div className="fde-cc-toolbar">
        <span className="fde-cc-channel">
          <span className="fde-live-dot" aria-hidden />
          {agentName}
        </span>
        {currentChatName ? (
          <span className="fde-cc-session" title="当前会话">
            {currentChatName}
          </span>
        ) : null}
        {statusLabel ? (
          <span className="fde-cc-status">{statusLabel}</span>
        ) : null}
        <div className="fde-cc-toolbar-spacer" />
        <div className="fde-cc-history-wrap">
          <button
            type="button"
            className="fde-link-btn"
            onClick={() =>
              historyOpen ? setHistoryOpen(false) : void openHistory()
            }
          >
            历史
          </button>
          {historyOpen ? (
            <>
              <div
                className="fde-cc-popover-backdrop"
                onClick={() => setHistoryOpen(false)}
              />
              <div className="fde-cc-history" role="menu">
                <div className="fde-cc-history-head">历史交付会话</div>
                {historyLoading ? (
                  <div className="fde-cc-history-empty">加载中…</div>
                ) : historyError ? (
                  <div className="fde-cc-history-empty fde-cc-history-err">
                    {historyError}
                  </div>
                ) : historyChats.length === 0 ? (
                  <div className="fde-cc-history-empty">还没有历史会话</div>
                ) : (
                  <div className="fde-cc-history-list">
                    {historyChats.map((c) => (
                      <button
                        type="button"
                        key={c.id}
                        className={`fde-cc-history-item${
                          currentChatId === c.id ? " is-current" : ""
                        }`}
                        onClick={() => void loadHistoryChat(c)}
                      >
                        <span className="fde-cc-history-name">
                          {c.name || "未命名会话"}
                        </span>
                        <span className="fde-cc-history-time">
                          {currentChatId === c.id
                            ? "当前会话"
                            : formatChatTime(c.updated_at || c.created_at)}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>
        <button
          type="button"
          className="fde-link-btn"
          onClick={reset}
          disabled={!streaming && turns.length === 0 && !currentChatId}
        >
          新会话
        </button>
      </div>

      <div className="fde-cc-stream" ref={scrollRef}>
        {turns.length === 0 ? (
          <div className="fde-cc-intro">
            <div className="fde-cc-intro-glyph">⌁</div>
            <p>
              把客户需求和系统现状告诉 {agentName}：要做什么数字员工、对接哪些系统、
              鉴权方式、接口文档或返回报文样例（直接贴上来都行）、最终装到哪个业务智能体。
              它会走完<strong>访谈 → 方案 → 生成</strong>，把可上线的技能暂存到右侧。
            </p>
            <div className="fde-cc-chips">
              {[
                "我想要个能查 XX 系统某接口、按设备分组统计、出柱状图的数字员工",
                "帮我交付一个对接工单系统的数字员工，下面是它的 API 文档…",
                "二开一个查 CMDB 应用拓扑的技能，装到 resource",
              ].map((q) => (
                <button
                  type="button"
                  key={q}
                  className="fde-cc-chip"
                  onClick={() => setInput(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn) =>
            turn.role === "user" ? (
              <div className="fde-cc-turn fde-cc-turn--you" key={turn.id}>
                <span className="fde-cc-who">你</span>
                <div className="fde-cc-bubble">{turn.text}</div>
              </div>
            ) : (
              <div className="fde-cc-turn fde-cc-turn--fde" key={turn.id}>
                <span className="fde-cc-who fde-cc-who--fde">FDE</span>
                <div className="fde-cc-bubble fde-cc-bubble--fde">
                  {turn.trace.length > 0 ? (
                    <div className="fde-cc-trace">
                      {turn.trace.map((name, i) => (
                        <span className="fde-cc-trace-item" key={`${name}-${i}`}>
                          ▸ {name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {(() => {
                    const answer = renderAnswer(turn);
                    if (answer) {
                      return (
                        <PortalQwenPawMarkdown
                          content={answer}
                          isStreaming={turn.status === "running"}
                          className="fde-cc-md"
                        />
                      );
                    }
                    if (turn.status === "running") {
                      return (
                        <span className="fde-cc-typing">
                          <i />
                          <i />
                          <i />
                        </span>
                      );
                    }
                    if (turn.status === "error") {
                      return null;
                    }
                    return (
                      <span className="fde-cc-empty">
                        这一轮没有文字回复
                        {turn.trace.length
                          ? "（FDE 在执行工具，可以再说一句让它继续）"
                          : "，可以再说一句让它继续"}
                      </span>
                    );
                  })()}
                  {turn.status === "error" ? (
                    <div className="fde-cc-error">
                      ⚠ {turn.error}
                      <button
                        type="button"
                        className="fde-cc-retry"
                        onClick={() => void retryLast()}
                        disabled={streaming}
                      >
                        重试这一轮
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
            ),
          )
        )}
      </div>

      <div className="fde-cc-composer">
        <textarea
          className="fde-cc-input"
          rows={2}
          placeholder={`和 ${agentName}说点什么…（Enter 发送，Shift+Enter 换行）`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {streaming ? (
          <button
            type="button"
            className="fde-btn fde-btn--danger fde-cc-send"
            onClick={stop}
          >
            停止
          </button>
        ) : (
          <button
            type="button"
            className="fde-btn fde-btn--primary fde-cc-send"
            onClick={() => void send()}
            disabled={!input.trim()}
          >
            发送
          </button>
        )}
      </div>
    </div>
  );
}

export default FdeConsoleChat;
