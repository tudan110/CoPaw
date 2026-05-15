const DEFAULT_API_BASE_URL = "/copaw-api/api";
const DEFAULT_FALLBACK_AGENT_ID = "default";
// Plain JSON calls (create chat, list chats, history, stop). These also cover
// the case where the backend is lazily loading an agent on first use, so give
// them headroom rather than the previous tight 30s.
const DEFAULT_REQUEST_TIMEOUT_MS = 45000;
// Time the streaming endpoint has to send its *headers* (the SSE stream then
// runs untimed). A busy model / first-token latency under load can take a
// while, so 90s instead of 30s.
const DEFAULT_STREAM_CONNECT_TIMEOUT_MS = 90000;

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

interface CopawRequestOptions {
  agentId?: string;
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

interface ChatListParams {
  user_id?: string;
  channel?: string;
}

interface StreamChatOptions {
  signal?: AbortSignal;
  onEvent?: (event: Record<string, any>) => void;
}

function safeJsonParse(value: string) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function extractErrorMessage(error: unknown): string {
  if (!error) {
    return "";
  }

  if (typeof error === "string") {
    const trimmed = error.trim();
    if (!trimmed) {
      return "";
    }

    const parsed = safeJsonParse(trimmed);
    if (parsed && parsed !== error) {
      const nestedMessage = extractErrorMessage(parsed);
      if (nestedMessage) {
        return nestedMessage;
      }
    }

    return trimmed;
  }

  if (error instanceof Error) {
    return extractErrorMessage(error.message) || "请求失败";
  }

  if (Array.isArray(error)) {
    return error
      .map((item) => extractErrorMessage(item))
      .filter(Boolean)
      .join("; ");
  }

  if (typeof error === "object") {
    const record = error as Record<string, unknown>;
    return (
      extractErrorMessage(record.message) ||
      extractErrorMessage(record.detail) ||
      extractErrorMessage(record.error) ||
      extractErrorMessage(record.reason) ||
      ""
    );
  }

  return String(error);
}

function getAgentCandidates(agentId?: string) {
  const fallbackAgentId =
    import.meta.env.VITE_COPAW_FALLBACK_AGENT_ID || DEFAULT_FALLBACK_AGENT_ID;
  const trimmedAgentId = agentId?.trim();
  if (trimmedAgentId) {
    return [trimmedAgentId];
  }
  return fallbackAgentId ? [fallbackAgentId] : [];
}

function isMissingAgentResponse(status: number, errorText?: string) {
  return status === 404 && /Agent\s+['"].+['"]\s+not\s+found/i.test(errorText || "");
}

function bindAbortSignal(
  controller: AbortController,
  signal?: AbortSignal,
): () => void {
  if (!signal) {
    return () => {};
  }

  const abort = () => controller.abort(signal.reason);
  if (signal.aborted) {
    abort();
    return () => {};
  }

  signal.addEventListener("abort", abort, { once: true });
  return () => signal.removeEventListener("abort", abort);
}

async function requestCopaw<T = any>(
  path: string,
  { agentId, method = "GET", body, signal }: CopawRequestOptions = {},
): Promise<T> {
  const agentCandidates = getAgentCandidates(agentId);
  let lastErrorText = "";
  let lastStatus = 0;

  for (const candidateAgentId of agentCandidates) {
    const controller = new AbortController();
    const unbindAbort = bindAbortSignal(controller, signal);
    let timedOut = false;
    const timerId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, DEFAULT_REQUEST_TIMEOUT_MS);

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method,
        signal: controller.signal,
        headers: {
          ...(body ? { "Content-Type": "application/json" } : {}),
          ...(candidateAgentId ? { "X-Agent-Id": candidateAgentId } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (error: any) {
      if (error?.name === "AbortError" && timedOut) {
        throw new Error("请求超时，请稍后重试");
      }
      throw error;
    } finally {
      window.clearTimeout(timerId);
      unbindAbort();
    }

    if (response.ok) {
      if (response.status === 204) {
        return null;
      }
      return response.json();
    }

    lastStatus = response.status;
    lastErrorText = await response.text().catch(() => "");
    if (!isMissingAgentResponse(response.status, lastErrorText)) {
      throw new Error(
        extractErrorMessage(lastErrorText) || `请求失败：${response.status}`,
      );
    }
  }

  throw new Error(
    extractErrorMessage(lastErrorText) || `请求失败：${lastStatus}`,
  );
}

export function listChats(agentId?: string, params: ChatListParams = {}) {
  const searchParams = new URLSearchParams();
  if (params.user_id) {
    searchParams.set("user_id", params.user_id);
  }
  if (params.channel) {
    searchParams.set("channel", params.channel);
  }
  const query = searchParams.toString();
  return requestCopaw(`/chats${query ? `?${query}` : ""}`, { agentId });
}

export function createChat(agentId: string | undefined, chat: Record<string, unknown>) {
  return requestCopaw("/chats", {
    agentId,
    method: "POST",
    body: chat,
  });
}

export function getChatHistory(agentId: string | undefined, chatId: string) {
  return requestCopaw(`/chats/${encodeURIComponent(chatId)}`, {
    agentId,
  });
}

export function updateChat(
  agentId: string | undefined,
  chatId: string,
  payload: Record<string, unknown>,
) {
  return requestCopaw(`/chats/${encodeURIComponent(chatId)}`, {
    agentId,
    method: "PUT",
    body: payload,
  });
}

export function deleteChat(agentId: string | undefined, chatId: string) {
  return requestCopaw(`/chats/${encodeURIComponent(chatId)}`, {
    agentId,
    method: "DELETE",
  });
}

export function stopChat(agentId: string | undefined, chatId: string) {
  return requestCopaw(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, {
    agentId,
    method: "POST",
  });
}

export async function streamChat(
  agentId: string | undefined,
  payload: Record<string, unknown>,
  { signal, onEvent }: StreamChatOptions = {},
) {
  const agentCandidates = getAgentCandidates(agentId);
  let response: Response | null = null;
  let releaseStreamAbort: (() => void) | null = null;
  let lastErrorText = "";
  let lastStatus = 0;

  for (const candidateAgentId of agentCandidates) {
    const controller = new AbortController();
    const unbindAbort = bindAbortSignal(controller, signal);
    let connectTimedOut = false;
    const timerId = window.setTimeout(() => {
      connectTimedOut = true;
      controller.abort();
    }, DEFAULT_STREAM_CONNECT_TIMEOUT_MS);

    let candidateResponse: Response;
    let keepAbortBound = false;
    try {
      candidateResponse = await fetch(`${API_BASE_URL}/console/chat`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...(candidateAgentId ? { "X-Agent-Id": candidateAgentId } : {}),
        },
        body: JSON.stringify(payload),
      });
      keepAbortBound = candidateResponse.ok;
    } catch (error: any) {
      if (error?.name === "AbortError" && connectTimedOut) {
        throw new Error("流式连接超时，请稍后重试");
      }
      throw error;
    } finally {
      window.clearTimeout(timerId);
      if (!keepAbortBound) {
        unbindAbort();
      }
    }

    if (candidateResponse.ok) {
      response = candidateResponse;
      releaseStreamAbort = unbindAbort;
      break;
    }

    lastStatus = candidateResponse.status;
    lastErrorText = await candidateResponse.text().catch(() => "");
    if (!isMissingAgentResponse(candidateResponse.status, lastErrorText)) {
      throw new Error(
        extractErrorMessage(lastErrorText) ||
          `流式请求失败：${candidateResponse.status}`,
      );
    }
  }

  if (!response) {
    throw new Error(
      extractErrorMessage(lastErrorText) || `流式请求失败：${lastStatus}`,
    );
  }

  if (!response.body) {
    throw new Error("未返回可读取的流式数据");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawNonResponseEvent = false;

  const dispatchEvent = (event: Record<string, any> | null) => {
    if (!event) {
      return;
    }
    if (String(event.object || "") !== "response") {
      sawNonResponseEvent = true;
    }
    onEvent?.(event);
  };

  const dispatchResponseOutputFallback = (event: Record<string, any>) => {
    if (
      String(event?.object || "") !== "response"
      || String(event?.status || "") !== "completed"
      || sawNonResponseEvent
      || !Array.isArray(event?.output)
    ) {
      return;
    }
    for (const item of event.output) {
      dispatchEvent(item);
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";

      for (const chunk of chunks) {
        const event = parseSseChunk(chunk);
        if (!event) {
          continue;
        }
        if (event.error) {
          throw new Error(
            extractErrorMessage(event.error) || "流式请求失败",
          );
        }
        dispatchEvent(event);
        dispatchResponseOutputFallback(event);
      }
    }

    const finalEvent = parseSseChunk(buffer);
    if (finalEvent) {
      if (finalEvent.error) {
        throw new Error(
          extractErrorMessage(finalEvent.error) || "流式请求失败",
        );
      }
      dispatchEvent(finalEvent);
      dispatchResponseOutputFallback(finalEvent);
    }
  } finally {
    releaseStreamAbort?.();
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }
}

function parseSseChunk(chunk: string): Record<string, any> | null {
  const lines = chunk
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.startsWith("data:"));

  if (!lines.length) {
    return null;
  }

  const data = lines.map((line) => line.slice(5).trimStart()).join("\n").trim();
  if (!data) {
    return null;
  }

  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}
