import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createChat, stopChat, streamChat } from "../../api/copawChat";
import {
  buildThinkingBlock,
  buildToolBlock,
  createRemoteSessionId,
  extractCopawMessageText,
  isCopawReasoningMessage,
  mergeStreamingText,
} from "./helpers";
import { MessageMarkdown } from "./components";
import "../app-workbench.css";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "thinking" | "tool";
  content: string;
  streaming?: boolean;
};

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const AGENT_ID = "gateway";
const COPAW_USER_ID = "default";
const COPAW_CHANNEL = "console";

const WORKBENCH_SYSTEM_PREFIX = `你现在处于「AI 应用开发工作台」模式。用户会描述想要的应用、图表或页面，你需要生成**完整的、可独立运行的 HTML 文件**。

要求：
1. 始终返回一个 \`\`\`html 代码块，包含完整的 <!DOCTYPE html> 页面
2. 所有依赖（CSS/JS库）通过 CDN 引入（ECharts、Chart.js、Tailwind CSS 等）
3. 页面应当美观、响应式、包含示例数据
4. 如果用户要求修改，在之前的基础上修改并返回完整的新版 HTML
5. 用中文回复说明，但代码注释可以用中英文

可用的 CDN 库参考：
- ECharts: https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js
- Tailwind CSS: https://cdn.tailwindcss.com
- Chart.js: https://cdn.jsdelivr.net/npm/chart.js
- D3.js: https://cdn.jsdelivr.net/npm/d3@7
- Animate.css: https://cdn.jsdelivr.net/npm/animate.css

用户需求：`;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function uid() {
  return `wb-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Extract the last ```html ... ``` code block from markdown content. */
function extractHtmlBlock(text: string): string | null {
  // Try ```html blocks first
  const htmlRe = /```html\s*\n([\s\S]*?)```/g;
  let lastHtml: string | null = null;
  let m: RegExpExecArray | null;
  while ((m = htmlRe.exec(text)) !== null) {
    lastHtml = m[1].trim();
  }
  if (lastHtml) return lastHtml;

  // Try ```echarts blocks — wrap in a full HTML page
  const echartsRe = /```echarts\s*\n([\s\S]*?)```/g;
  let lastEcharts: string | null = null;
  while ((m = echartsRe.exec(text)) !== null) {
    lastEcharts = m[1].trim();
  }
  if (lastEcharts) {
    return wrapEchartsHtml(lastEcharts);
  }

  return null;
}

/** Wrap an ECharts option JSON into a standalone HTML page. */
function wrapEchartsHtml(optionJson: string): string {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>ECharts Preview</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"><\/script>
<style>
html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #fff; }
#chart { width: 100%; height: 100%; }
</style>
</head>
<body>
<div id="chart"></div>
<script>
(function(){
  var chart = echarts.init(document.getElementById('chart'));
  var option = ${optionJson};
  chart.setOption(option);
  window.addEventListener('resize', function(){ chart.resize(); });
})();
<\/script>
</body>
</html>`;
}

/** Build a sandboxed data-URI or blob URL for the HTML to render in iframe. */
function buildPreviewUrl(html: string): string {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  return URL.createObjectURL(blob);
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function AppWorkbenchPanel({
  onBack,
  editAppId,
}: {
  onBack?: () => void;
  editAppId?: string;
}) {
  /* ---- chat state ---- */
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  /* ---- editing state ---- */
  const [editingApp, setEditingApp] = useState<{
    id: string;
    title: string;
    description: string;
    type: "app" | "widget" | "dashboard";
    tags: string[];
  } | null>(null);

  /* ---- session ---- */
  const chatIdRef = useRef("");
  const sessionIdRef = useRef("");
  const streamAbortRef = useRef<AbortController | null>(null);

  /* ---- streaming bookkeeping ---- */
  const assistantMapRef = useRef(new Map<string, string>());
  const contentMapRef = useRef(new Map<string, string>());
  const streamMetaRef = useRef(new Map<string, { role: string; type: string }>());
  const pendingTextRef = useRef(new Map<string, string>());

  /* ---- preview state ---- */
  const [previewHtml, setPreviewHtml] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [viewSource, setViewSource] = useState(false);
  const [previewDevice, setPreviewDevice] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const [fullscreen, setFullscreen] = useState(false);
  const previousBlobRef = useRef("");

  /* ---- publish state ---- */
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishTitle, setPublishTitle] = useState("");
  const [publishDesc, setPublishDesc] = useState("");
  const [publishType, setPublishType] = useState<"app" | "widget" | "dashboard">("app");
  const [publishTags, setPublishTags] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<{ url: string; title: string } | null>(null);

  /* ---- auto-scroll chat ---- */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* ---- load existing app for editing ---- */
  useEffect(() => {
    if (!editAppId) return;
    (async () => {
      try {
        // Fetch app metadata
        const metaRes = await fetch(`/portal-api/app-artifacts/${editAppId}`);
        if (!metaRes.ok) return;
        const meta = await metaRes.json();
        setEditingApp({
          id: meta.id,
          title: meta.title,
          description: meta.description || "",
          type: meta.type || "app",
          tags: meta.tags || [],
        });
        setPublishTitle(meta.title || "");
        setPublishDesc(meta.description || "");
        setPublishType(meta.type || "app");
        setPublishTags((meta.tags || []).join(", "));

        // Fetch HTML content for preview
        const htmlRes = await fetch(`/portal-api/app-artifacts/${editAppId}/preview`);
        if (!htmlRes.ok) return;
        const html = await htmlRes.text();
        if (html) {
          setPreviewHtml(html);
          setPreviewUrl(buildPreviewUrl(html));
        }
      } catch {}
    })();
  }, [editAppId]);

  /* ---- revoke blob on change ---- */
  useEffect(() => {
    if (previousBlobRef.current && previousBlobRef.current !== previewUrl) {
      URL.revokeObjectURL(previousBlobRef.current);
    }
    previousBlobRef.current = previewUrl;
  }, [previewUrl]);

  /* ---- cleanup ---- */
  useEffect(() => {
    return () => {
      if (previousBlobRef.current) {
        URL.revokeObjectURL(previousBlobRef.current);
      }
    };
  }, []);

  /* ================================================================ */
  /*  Message helpers                                                  */
  /* ================================================================ */

  const appendMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg]);
    return msg.id;
  }, []);

  const updateMessageContent = useCallback((id: string, content: string, extras?: Partial<ChatMessage>) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, content, ...extras } : m)),
    );
  }, []);

  /* ================================================================ */
  /*  Streaming event handler                                          */
  /* ================================================================ */

  const appendAssistantText = useCallback((msgId: string, text: string) => {
    let lineId = assistantMapRef.current.get(msgId);
    const old = contentMapRef.current.get(lineId || "") || "";
    const next = mergeStreamingText(old, text);
    if (!lineId) {
      const id = uid();
      lineId = id;
      assistantMapRef.current.set(msgId, id);
      setMessages((prev) => [...prev, { id, role: "assistant", content: next, streaming: true }]);
    } else {
      setMessages((prev) =>
        prev.map((m) => (m.id === lineId ? { ...m, content: next } : m)),
      );
    }
    contentMapRef.current.set(lineId, next);

    // Extract HTML for preview
    const html = extractHtmlBlock(next);
    if (html) {
      setPreviewHtml(html);
      setPreviewUrl(buildPreviewUrl(html));
    }
  }, []);

  const flushPending = useCallback((msgId: string) => {
    const pending = pendingTextRef.current.get(msgId);
    if (!pending) return;
    const meta = streamMetaRef.current.get(msgId);
    if (meta?.role === "assistant" && meta?.type === "message") {
      appendAssistantText(msgId, pending);
      pendingTextRef.current.delete(msgId);
    }
  }, [appendAssistantText]);

  const handleStreamEvent = useCallback((event: any) => {
    if (event.object === "message" && event.id) {
      streamMetaRef.current.set(event.id, { role: event.role, type: event.type });
      flushPending(event.id);
    }

    // Completed reasoning (thinking)
    if (event.object === "message" && event.status === "completed") {
      if (isCopawReasoningMessage(event)) {
        pendingTextRef.current.delete(event.id);
        const block = buildThinkingBlock(event);
        if (block.content) {
          appendMessage({ id: uid(), role: "thinking", content: block.content });
        }
        return;
      }
      if (event.type === "plugin_call" || event.type === "plugin_call_output") {
        const block = buildToolBlock(event);
        if (block.content) {
          appendMessage({ id: uid(), role: "tool", content: block.content });
        }
        return;
      }
    }

    // Final completed assistant message
    if (
      event.object === "message" &&
      event.role === "assistant" &&
      event.type === "message"
    ) {
      const finalText = extractCopawMessageText(event);
      if (event.status === "completed" && finalText) {
        pendingTextRef.current.delete(event.id);
        appendAssistantText(event.id, finalText);
        const lineId = assistantMapRef.current.get(event.id);
        if (lineId) {
          updateMessageContent(lineId, contentMapRef.current.get(lineId) || finalText, { streaming: false });
        }
      }
      return;
    }

    // Streaming content chunk
    if (event.object === "content" && event.type === "text" && event.msg_id && event.text) {
      const meta = streamMetaRef.current.get(event.msg_id);
      if (meta?.role === "assistant" && meta?.type === "message") {
        appendAssistantText(event.msg_id, event.text);
        return;
      }
      // Buffer until we know the role
      const cur = pendingTextRef.current.get(event.msg_id) || "";
      pendingTextRef.current.set(event.msg_id, mergeStreamingText(cur, event.text));
    }
  }, [appendAssistantText, appendMessage, flushPending, updateMessageContent]);

  /* ================================================================ */
  /*  Send message                                                     */
  /* ================================================================ */

  const isFirstMessageRef = useRef(true);

  const sendMessage = useCallback(async () => {
    const content = inputValue.trim();
    if (!content || isStreaming) return;

    setInputValue("");
    appendMessage({ id: uid(), role: "user", content });

    // Prepend system instructions on first message of a session
    const effectiveContent = isFirstMessageRef.current
      ? `${WORKBENCH_SYSTEM_PREFIX}${content}`
      : content;

    // Reset streaming state
    assistantMapRef.current = new Map();
    contentMapRef.current = new Map();
    streamMetaRef.current = new Map();
    pendingTextRef.current = new Map();
    setIsStreaming(true);

    const controller = new AbortController();
    streamAbortRef.current = controller;

    try {
      // Ensure chat session
      if (!chatIdRef.current) {
        const chat = await createChat(AGENT_ID, {
          name: content.slice(0, 60),
          session_id: createRemoteSessionId("app-workbench"),
          user_id: COPAW_USER_ID,
          channel: COPAW_CHANNEL,
        });
        chatIdRef.current = chat.id;
        sessionIdRef.current = chat.session_id;
      }

      isFirstMessageRef.current = false;

      await streamChat(
        AGENT_ID,
        {
          input: [
            {
              role: "user",
              type: "message",
              content: [{ type: "text", text: effectiveContent, status: "created" }],
            },
          ],
          session_id: sessionIdRef.current,
          user_id: COPAW_USER_ID,
          channel: COPAW_CHANNEL,
          stream: true,
        },
        {
          signal: controller.signal,
          onEvent: handleStreamEvent,
        },
      );

      if (!assistantMapRef.current.size) {
        appendMessage({ id: uid(), role: "assistant", content: "本轮对话未返回可展示内容。" });
      }
    } catch (error: any) {
      if (!controller.signal.aborted) {
        appendMessage({
          id: uid(),
          role: "assistant",
          content: `对话失败：${String(error?.message || "请稍后重试")}`,
        });
      }
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      streamMetaRef.current = new Map();
      pendingTextRef.current = new Map();
      setIsStreaming(false);
      // Mark all assistant messages as not streaming
      setMessages((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)));
    }
  }, [inputValue, isStreaming, appendMessage, handleStreamEvent]);

  const handleStop = useCallback(async () => {
    const controller = streamAbortRef.current;
    if (!controller) return;
    controller.abort();
    streamAbortRef.current = null;
    setIsStreaming(false);
    if (chatIdRef.current) {
      try { await stopChat(AGENT_ID, chatIdRef.current); } catch {}
    }
    appendMessage({ id: uid(), role: "assistant", content: "对话已停止。" });
  }, [appendMessage]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }, [sendMessage]);

  /* ================================================================ */
  /*  Publish                                                          */
  /* ================================================================ */

  const handlePublish = useCallback(async () => {
    if (!previewHtml || !publishTitle.trim()) return;
    setPublishing(true);
    try {
      const tags = publishTags
        .split(/[,，\s]+/)
        .map((t) => t.trim())
        .filter(Boolean);

      let response: Response;
      if (editingApp) {
        // Update existing app
        response = await fetch(`/portal-api/app-artifacts/${editingApp.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: publishTitle.trim(),
            description: publishDesc.trim(),
            html_content: previewHtml,
            tags,
          }),
        });
      } else {
        // Create new app
        response = await fetch("/portal-api/app-artifacts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: publishTitle.trim(),
            description: publishDesc.trim(),
            html_content: previewHtml,
            type: publishType,
            tags,
          }),
        });
      }
      if (!response.ok) throw new Error(`发布失败: ${response.status}`);
      const data = await response.json();
      setPublishResult({ url: data.url || `/portal-api/app-artifacts/${data.id}/preview`, title: data.title });
      if (!editingApp) {
        setEditingApp({ id: data.id, title: data.title, description: data.description || "", type: data.type, tags: data.tags || [] });
      }
    } catch (error: any) {
      alert(`发布失败：${error.message}`);
    } finally {
      setPublishing(false);
    }
  }, [previewHtml, publishTitle, publishDesc, publishType, publishTags, editingApp]);

  /* ================================================================ */
  /*  New session                                                      */
  /* ================================================================ */

  const handleNewSession = useCallback(() => {
    chatIdRef.current = "";
    sessionIdRef.current = "";
    isFirstMessageRef.current = true;
    setMessages([]);
    setPreviewHtml("");
    setPreviewUrl("");
    setInputValue("");
    setViewSource(false);
    setPublishOpen(false);
    setPublishResult(null);
  }, []);

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */

  const deviceWidths: Record<string, string> = {
    desktop: "100%",
    tablet: "768px",
    mobile: "375px",
  };

  return (
    <div className={`app-workbench ${fullscreen ? "app-workbench--fullscreen" : ""}`}>
      {/* ---- Header ---- */}
      <header className="app-workbench__header">
        <div className="app-workbench__header-left">
          {onBack && (
            <button className="app-workbench__back-btn" onClick={onBack} title="返回">
              <i className="fas fa-arrow-left" />
            </button>
          )}
          <h2 className="app-workbench__title">
            <i className="fas fa-wand-magic-sparkles" />
            {editingApp ? `编辑 · ${editingApp.title}` : "AI 应用开发工作台"}
          </h2>
        </div>
        <div className="app-workbench__header-right">
          <button className="app-workbench__action-btn" onClick={handleNewSession} title="新建会话">
            <i className="fas fa-plus" /> 新建
          </button>
        </div>
      </header>

      {/* ---- Main area ---- */}
      <div className="app-workbench__body">
        {/* ---- Left: Chat ---- */}
        <section className="app-workbench__chat">
          <div className="app-workbench__messages">
            {messages.length === 0 && (
              <div className="app-workbench__empty">
                <div className="app-workbench__empty-icon">🚀</div>
                <h3>描述你想要的应用</h3>
                <p>告诉 AI 你需要什么，它会为你生成可运行的 HTML 应用</p>
                <div className="app-workbench__suggestions">
                  {[
                    "帮我做一个告警 TOP10 柱状图",
                    "制作一个系统健康度仪表盘",
                    "生成一个服务器资源监控大屏",
                  ].map((s) => (
                    <button
                      key={s}
                      className="app-workbench__suggestion"
                      onClick={() => {
                        setInputValue(s);
                      }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <div key={msg.id} className={`app-workbench__msg app-workbench__msg--${msg.role}`}>
                {msg.role === "user" ? (
                  <div className="app-workbench__msg-bubble app-workbench__msg-bubble--user">
                    {msg.content}
                  </div>
                ) : msg.role === "thinking" ? (
                  <details className="app-workbench__thinking">
                    <summary>💭 思考过程</summary>
                    <div className="app-workbench__thinking-content">
                      <MessageMarkdown content={msg.content} />
                    </div>
                  </details>
                ) : msg.role === "tool" ? (
                  <details className="app-workbench__tool-call">
                    <summary>🔧 工具调用</summary>
                    <div className="app-workbench__tool-content">
                      <MessageMarkdown content={msg.content} />
                    </div>
                  </details>
                ) : (
                  <div className="app-workbench__msg-bubble app-workbench__msg-bubble--assistant">
                    <MessageMarkdown content={msg.content} isStreaming={msg.streaming} />
                  </div>
                )}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* ---- Input ---- */}
          <div className="app-workbench__input-area">
            <textarea
              className="app-workbench__textarea"
              rows={2}
              placeholder="描述你想要的应用，或提出修改意见..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
            />
            <div className="app-workbench__input-actions">
              {isStreaming ? (
                <button className="app-workbench__stop-btn" onClick={() => void handleStop()}>
                  <i className="fas fa-stop" /> 停止
                </button>
              ) : (
                <button
                  className="app-workbench__send-btn"
                  onClick={() => void sendMessage()}
                  disabled={!inputValue.trim()}
                >
                  <i className="fas fa-paper-plane" /> 发送
                </button>
              )}
            </div>
          </div>
        </section>

        {/* ---- Right: Preview ---- */}
        <section className="app-workbench__preview">
          <div className="app-workbench__preview-toolbar">
            <div className="app-workbench__device-switcher">
              {(["desktop", "tablet", "mobile"] as const).map((d) => (
                <button
                  key={d}
                  className={`app-workbench__device-btn ${previewDevice === d ? "active" : ""}`}
                  onClick={() => setPreviewDevice(d)}
                  title={d === "desktop" ? "桌面" : d === "tablet" ? "平板" : "手机"}
                >
                  <i className={`fas ${d === "desktop" ? "fa-desktop" : d === "tablet" ? "fa-tablet-alt" : "fa-mobile-alt"}`} />
                </button>
              ))}
            </div>
            <div className="app-workbench__preview-actions">
              <button
                className={`app-workbench__toggle-btn ${viewSource ? "active" : ""}`}
                onClick={() => setViewSource(!viewSource)}
                title="查看源码"
                disabled={!previewHtml}
              >
                <i className="fas fa-code" />
              </button>
              <button
                className="app-workbench__toggle-btn"
                onClick={() => setFullscreen(!fullscreen)}
                title={fullscreen ? "退出全屏" : "全屏预览"}
              >
                <i className={`fas ${fullscreen ? "fa-compress" : "fa-expand"}`} />
              </button>
              <button
                className="app-workbench__publish-btn"
                onClick={() => setPublishOpen(true)}
                disabled={!previewHtml}
                title="发布应用"
              >
                <i className="fas fa-cloud-upload-alt" /> 发布
              </button>
            </div>
          </div>

          <div className="app-workbench__preview-frame" style={{ maxWidth: deviceWidths[previewDevice] }}>
            {viewSource ? (
              <pre className="app-workbench__source-code"><code>{previewHtml}</code></pre>
            ) : previewUrl ? (
              <iframe
                key={previewUrl}
                src={previewUrl}
                className="app-workbench__iframe"
                sandbox="allow-scripts allow-same-origin"
                title="应用预览"
              />
            ) : (
              <div className="app-workbench__preview-empty">
                <div className="app-workbench__preview-empty-icon">
                  <i className="fas fa-eye" />
                </div>
                <p>预览区域</p>
                <p className="app-workbench__preview-empty-hint">
                  AI 生成 HTML 后将自动在此处渲染预览
                </p>
              </div>
            )}
          </div>
        </section>
      </div>

      {/* ---- Publish Modal ---- */}
      {publishOpen && (
        <div className="app-workbench__modal-overlay" onClick={() => !publishing && setPublishOpen(false)}>
          <div className="app-workbench__modal" onClick={(e) => e.stopPropagation()}>
            {publishResult ? (
              <>
                <div className="app-workbench__modal-header">
                  <h3>🎉 {editingApp ? "更新成功" : "发布成功"}</h3>
                </div>
                <div className="app-workbench__modal-body">
                  <p>应用「{publishResult.title}」已成功发布！</p>
                  <p className="app-workbench__publish-url">
                    <a href={publishResult.url} target="_blank" rel="noopener noreferrer">
                      {publishResult.url}
                    </a>
                  </p>
                </div>
                <div className="app-workbench__modal-footer">
                  <button
                    className="app-workbench__btn-primary"
                    onClick={() => {
                      setPublishOpen(false);
                      setPublishResult(null);
                    }}
                  >
                    完成
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="app-workbench__modal-header">
                  <h3>{editingApp ? "更新应用" : "发布应用"}</h3>
                  <button
                    className="app-workbench__modal-close"
                    onClick={() => setPublishOpen(false)}
                    disabled={publishing}
                  >
                    ✕
                  </button>
                </div>
                <div className="app-workbench__modal-body">
                  <label className="app-workbench__field">
                    <span>应用名称 *</span>
                    <input
                      type="text"
                      value={publishTitle}
                      onChange={(e) => setPublishTitle(e.target.value)}
                      placeholder="给你的应用取个名字"
                      disabled={publishing}
                    />
                  </label>
                  <label className="app-workbench__field">
                    <span>描述</span>
                    <textarea
                      value={publishDesc}
                      onChange={(e) => setPublishDesc(e.target.value)}
                      placeholder="简要描述应用功能"
                      rows={2}
                      disabled={publishing}
                    />
                  </label>
                  <label className="app-workbench__field">
                    <span>类型</span>
                    <select
                      value={publishType}
                      onChange={(e) => setPublishType(e.target.value as any)}
                      disabled={publishing}
                    >
                      <option value="app">🌐 应用</option>
                      <option value="widget">🧩 卡片</option>
                      <option value="dashboard">📊 仪表盘</option>
                    </select>
                  </label>
                  <label className="app-workbench__field">
                    <span>标签</span>
                    <input
                      type="text"
                      value={publishTags}
                      onChange={(e) => setPublishTags(e.target.value)}
                      placeholder="用逗号分隔，如：监控, 告警, 大屏"
                      disabled={publishing}
                    />
                  </label>
                </div>
                <div className="app-workbench__modal-footer">
                  <button
                    className="app-workbench__btn-cancel"
                    onClick={() => setPublishOpen(false)}
                    disabled={publishing}
                  >
                    取消
                  </button>
                  <button
                    className="app-workbench__btn-primary"
                    onClick={() => void handlePublish()}
                    disabled={publishing || !publishTitle.trim()}
                  >
                    {publishing ? (editingApp ? "更新中..." : "发布中...") : (editingApp ? "确认更新" : "确认发布")}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default AppWorkbenchPanel;
