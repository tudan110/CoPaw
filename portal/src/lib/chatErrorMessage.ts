// Turn backend chat/stream errors into safe, user-friendly text.
//
// End users must never see raw tracebacks, internal temp-dump paths
// (e.g. "(Details: /tmp/qwenpaw_query_error_xxx.json)"), internal
// product/package names, or raw provider error codes. We map known error
// categories to friendly Chinese messages and, for everything else, fall back
// to a single generic friendly line rather than echoing the raw error.

// Generic, always-safe fallback shown when we can't (or shouldn't) say more.
const GENERIC_FRIENDLY = "服务暂时遇到点问题，请稍后重试。";

// Stack-trace signatures (Python / JS) that must never reach end users.
const TRACEBACK_PATTERN =
  /Traceback \(most recent call last\)|File "[^"]+", line \d+|\n\s*at [\w.$<>]+ \(/i;

/**
 * Normalize whatever the runtime hands us — a plain string, an
 * `IAgentScopeRuntimeError` (`{ code, message }`), or an ERROR message item
 * (`{ code, message, content: [...] }`) — into a single raw string that
 * {@link toFriendlyChatError} can categorize. The non-sensitive `code` token is
 * appended so category mapping can still key on it.
 */
export function extractRuntimeErrorText(errorLike: unknown): string {
  if (errorLike == null) return "";
  if (typeof errorLike === "string") return errorLike;
  if (typeof errorLike !== "object") return String(errorLike);

  const obj = errorLike as Record<string, unknown>;
  const parts: string[] = [];

  if (typeof obj.message === "string" && obj.message.trim()) {
    parts.push(obj.message.trim());
  }
  if (Array.isArray(obj.content)) {
    for (const item of obj.content) {
      const text = (item as { text?: unknown } | null)?.text;
      if (typeof text === "string" && text.trim()) {
        parts.push(text.trim());
      }
    }
  }

  let text = parts.join(" ").trim();
  const code = typeof obj.code === "string" ? obj.code.trim() : "";
  if (code && !text.includes(code)) {
    text = text ? `${text} (${code})` : code;
  }
  return text;
}

export function toFriendlyChatError(error: unknown): string {
  const raw = String(
    (error as { message?: unknown } | null)?.message ??
      (typeof error === "string" ? error : ""),
  ).trim();

  if (!raw) {
    return GENERIC_FRIENDLY;
  }

  // 明确的堆栈/崩溃特征：直接给通用友好提示，绝不外泄原始内容。
  if (TRACEBACK_PATTERN.test(raw)) {
    return GENERIC_FRIENDLY;
  }

  // 网络 / 流式连接中断
  if (
    /RemoteProtocolError|incomplete chunked read|peer closed connection|流式连接超时|未返回可读取的流式数据/i.test(
      raw,
    )
  ) {
    return "模型流式连接中断，请重试当前步骤。";
  }

  // 模型执行类错误：按类别给出友好提示，隐藏内部实现细节
  // （临时文件路径、错误码、内部名称）。
  const looksLikeModelError =
    /execution of model|MODEL_EXECUTION|MODEL_TIMEOUT|MODEL_QUOTA|UNAUTHORIZED_MODEL|CONTEXT_LENGTH|qwenpaw_query_error|[（(]\s*Details:/i.test(
      raw,
    );

  if (looksLikeModelError) {
    if (/timeout|timed out|MODEL_TIMEOUT|超时/i.test(raw)) {
      return "模型响应超时，请稍后重试。";
    }
    if (/quota|rate limit|too many requests|MODEL_QUOTA/i.test(raw)) {
      return "当前访问量较大，请稍后重试。";
    }
    if (/context|too many tokens|CONTEXT_LENGTH/i.test(raw)) {
      return "本轮对话内容过长，请精简后重试。";
    }
    if (/unauthorized|authentication|api key|UNAUTHORIZED/i.test(raw)) {
      return "模型服务暂不可用，请联系管理员。";
    }
    return "模型服务暂时不可用，请稍后重试。";
  }

  // 兜底：绝不回显原始错误（可能含堆栈/内部路径），统一给友好提示。
  return GENERIC_FRIENDLY;
}

/** Convenience: normalize a runtime error object/string, then friendly-map it. */
export function runtimeErrorToFriendly(errorLike: unknown): string {
  return toFriendlyChatError(extractRuntimeErrorText(errorLike));
}
