import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  AgentScopeRuntimeWebUI,
  type IAgentScopeRuntimeWebUIOptions,
} from "@agentscope-ai/chat";
import { App as AntdApp } from "antd";
import { ConfigProvider, bailianTheme } from "@agentscope-ai/design";
import { theme as antdTheme } from "antd";
import { createPortalRuntimeSessionApi } from "../lib/portalRuntimeSessionApi";
import { stopChat } from "../api/copawChat";
import PortalStreamingResponseCard from "./PortalStreamingResponseCard";

const DEFAULT_API_BASE_URL = "/copaw-api/api";
const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);
const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const RUNTIME_DESC_SCROLL_SELECTOR =
  ".qwenpaw-bubble-list-scroll.qwenpaw-bubble-list-order-desc";

const CONNECTION_NOTICE_STYLE: CSSProperties = {
  position: "absolute",
  top: 12,
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 20,
  maxWidth: "min(720px, calc(100% - 32px))",
  padding: "8px 12px",
  borderRadius: 8,
  color: "#92400e",
  background: "rgba(251, 191, 36, 0.95)",
  border: "1px solid rgba(245, 158, 11, 0.35)",
  boxShadow: "0 10px 30px rgba(15, 23, 42, 0.16)",
  fontSize: 13,
  lineHeight: 1.6,
};

function extractUserMessageText(message: any): string {
  const content = Array.isArray(message?.content) ? message.content : [];
  return content
    .filter((item: any) => item?.type === "text")
    .map((item: any) => String(item?.text || ""))
    .join("\n")
    .trim();
}

function parseRuntimeResponse(chunk: string) {
  const payload = JSON.parse(chunk) as Record<string, any>;
  if (payload.type === "turn_usage" || payload.type === "replay_end") {
    return null;
  }
  if (
    payload.object === "response"
    && payload.status === "completed"
    && (!payload.output || (Array.isArray(payload.output) && !payload.output.length))
  ) {
    payload.output = [
      {
        type: "message",
        role: "assistant",
        content: [
          {
            type: "text",
            text: payload.error?.message || "本次回复未返回可展示内容。",
          },
        ],
      },
    ];
  }
  return payload;
}

function canScrollVertically(element: Element, deltaY: number) {
  if (!(element instanceof HTMLElement)) {
    return false;
  }
  const style = window.getComputedStyle(element);
  if (!/(auto|scroll)/.test(style.overflowY)) {
    return false;
  }
  const maxScrollTop = element.scrollHeight - element.clientHeight;
  if (maxScrollTop <= 1) {
    return false;
  }
  return deltaY > 0 ? element.scrollTop < maxScrollTop - 1 : element.scrollTop > 1;
}

function findNestedVerticalScroller(
  target: Element | null,
  boundary: HTMLElement,
  deltaY: number,
) {
  let current: Element | null = target;
  while (current && current !== boundary) {
    if (canScrollVertically(current, deltaY)) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

export function PortalRemoteRuntimeChat({
  agentId,
  agentName,
  isDark = false,
}: {
  agentId?: string | null;
  agentName: string;
  isDark?: boolean;
}) {
  const sessionApi = useMemo(() => createPortalRuntimeSessionApi(agentId || undefined), [agentId]);
  const [connectionNotice, setConnectionNotice] = useState("");
  const connectionNoticeTimersRef = useRef<number[]>([]);
  const mountedRef = useRef(true);
  const shellRef = useRef<HTMLDivElement | null>(null);

  const clearConnectionNoticeTimers = useCallback(() => {
    connectionNoticeTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    connectionNoticeTimersRef.current = [];
  }, []);

  useEffect(
    () => () => {
      mountedRef.current = false;
      clearConnectionNoticeTimers();
    },
    [clearConnectionNoticeTimers],
  );

  useEffect(() => {
    const root = shellRef.current;
    if (!root) {
      return undefined;
    }

    const cleanupHandlers: Array<() => void> = [];
    const attachWheelNormalizer = () => {
      root.querySelectorAll<HTMLElement>(RUNTIME_DESC_SCROLL_SELECTOR).forEach((scrollElement) => {
        if (scrollElement.dataset.portalWheelNormalized === "true") {
          return;
        }
        scrollElement.dataset.portalWheelNormalized = "true";
        const handleWheel = (event: WheelEvent) => {
          if (event.defaultPrevented || !event.deltaY || event.shiftKey) {
            return;
          }
          const target = event.target instanceof Element ? event.target : null;
          if (
            target?.closest("textarea,input,select,[contenteditable='true']")
            || findNestedVerticalScroller(target, scrollElement, event.deltaY)
          ) {
            return;
          }

          const minScrollTop = Math.min(0, scrollElement.clientHeight - scrollElement.scrollHeight);
          const nextScrollTop = Math.max(
            minScrollTop,
            Math.min(0, scrollElement.scrollTop - event.deltaY),
          );
          if (Math.abs(nextScrollTop - scrollElement.scrollTop) < 0.5) {
            return;
          }

          event.preventDefault();
          scrollElement.scrollTop = nextScrollTop;
        };
        scrollElement.addEventListener("wheel", handleWheel, { passive: false });
        cleanupHandlers.push(() => {
          scrollElement.removeEventListener("wheel", handleWheel);
          delete scrollElement.dataset.portalWheelNormalized;
        });
      });
    };

    attachWheelNormalizer();
    const observer = new MutationObserver(attachWheelNormalizer);
    observer.observe(root, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      cleanupHandlers.forEach((cleanup) => cleanup());
    };
  }, []);

  const setConnectionNoticeIfMounted = useCallback((notice: string) => {
    if (mountedRef.current) {
      setConnectionNotice(notice);
    }
  }, []);

  const scheduleConnectionNotices = useCallback(() => {
    clearConnectionNoticeTimers();
    setConnectionNoticeIfMounted("");
    connectionNoticeTimersRef.current = [
      window.setTimeout(() => {
        setConnectionNoticeIfMounted("正在等待后端建立模型流式连接，请稍候。");
      }, 12000),
      window.setTimeout(() => {
        setConnectionNoticeIfMounted(
          "LLM 响应时间较长，可能正在等待上游模型、DNS 解析或自动重试。",
        );
      }, 45000),
      window.setTimeout(() => {
        setConnectionNoticeIfMounted(
          "仍未建立可读的模型流，请检查 LLM 服务、DNS 或网络状态；后端可能还在重试。",
        );
      }, 90000),
    ];
  }, [clearConnectionNoticeTimers, setConnectionNoticeIfMounted]);

  const customFetch = useCallback(
    async (data: {
      input?: Array<Record<string, unknown>>;
      biz_params?: Record<string, unknown>;
      signal?: AbortSignal;
    }): Promise<Response> => {
      const { input = [], biz_params } = data;
      const lastMessage = input[input.length - 1] as Record<string, any> | undefined;
      const session: Record<string, any> = (lastMessage?.session || {}) as Record<string, any>;
      const lastInput = input.slice(-1);
      const sessionContext = sessionApi.getSessionContext(String(session?.session_id || ""));
      const requestSessionId = sessionContext.sessionId || String(session?.session_id || "");
      const requestBody = {
        input: lastInput,
        session_id: requestSessionId,
        user_id: sessionContext.userId || session?.user_id || DEFAULT_USER_ID,
        channel: sessionContext.channel || session?.channel || DEFAULT_CHANNEL,
        stream: true,
        ...biz_params,
      };

      const backendChatId =
        sessionContext.realId ||
        requestBody.session_id;

      if (backendChatId) {
        const userText = lastInput
          .filter((message: any) => message.role === "user")
          .map(extractUserMessageText)
          .join("\n")
          .trim();
        if (userText) {
          sessionApi.setLastUserMessage(backendChatId, userText);
        }
      }

      scheduleConnectionNotices();
      try {
        return await fetch(`${API_BASE_URL}/console/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(agentId ? { "X-Agent-Id": agentId } : {}),
          },
          body: JSON.stringify(requestBody),
          signal: data.signal,
        });
      } finally {
        clearConnectionNoticeTimers();
        setConnectionNoticeIfMounted("");
      }
    },
    [
      agentId,
      clearConnectionNoticeTimers,
      scheduleConnectionNotices,
      sessionApi,
      setConnectionNoticeIfMounted,
    ],
  );

  const options = useMemo(
    () =>
      ({
        theme: {
          colorPrimary: "#FF7F16",
          darkMode: isDark,
          prefix: "qwenpaw",
          leftHeader: {
            logo: "",
            title: `${agentName}`,
          },
        },
        sender: {
          maxLength: 10000,
          placeholder: `向 ${agentName} 描述您的需求...`,
        },
        welcome: {
          greeting: `你好，我是 ${agentName}`,
          description: "智观 Paw 流式聊天服务。",
          prompts: [],
        },
        session: {
          multiple: true,
          hideBuiltInSessionList: false,
          api: sessionApi,
        },
        cards: {
          AgentScopeRuntimeResponseCard: PortalStreamingResponseCard,
        },
        api: {
          fetch: customFetch,
          responseParser: parseRuntimeResponse,
          cancel(data: { session_id: string }) {
            const chatId =
              sessionApi.getRealIdForSession(data.session_id) ?? data.session_id;
            if (chatId) {
              stopChat(agentId || undefined, chatId).catch(() => {});
            }
          },
          async reconnect(data: { session_id: string; signal?: AbortSignal }) {
            const sessionContext = sessionApi.getSessionContext(data.session_id);
            return fetch(`${API_BASE_URL}/console/chat`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...(agentId ? { "X-Agent-Id": agentId } : {}),
              },
              body: JSON.stringify({
                reconnect: true,
                session_id: sessionContext.sessionId || data.session_id,
                user_id: sessionContext.userId || DEFAULT_USER_ID,
                channel: sessionContext.channel || DEFAULT_CHANNEL,
              }),
              signal: data.signal,
            });
          },
        },
      }) as unknown as IAgentScopeRuntimeWebUIOptions,
    [agentId, agentName, customFetch, isDark, sessionApi],
  );

  return (
    <div ref={shellRef} className="portal-runtime-chat-shell" style={{ position: "relative" }}>
      {connectionNotice ? (
        <div style={CONNECTION_NOTICE_STYLE} role="status" aria-live="polite">
          {connectionNotice}
        </div>
      ) : null}
      <ConfigProvider
        {...bailianTheme}
        prefix="qwenpaw"
        prefixCls="qwenpaw"
        theme={{
          ...(bailianTheme as any)?.theme,
          algorithm: isDark
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: "#FF7F16",
          },
        }}
      >
        <AntdApp>
          <AgentScopeRuntimeWebUI options={options} />
        </AntdApp>
      </ConfigProvider>
    </div>
  );
}
