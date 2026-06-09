// Turn backend chat/stream errors into safe, user-friendly text.
//
// The backend may surface raw model-execution errors such as
//   "Error occurred during execution of model: GLM-5.1
//    (Details: /tmp/qwenpaw_query_error_xxx.json) (MODEL_EXECUTION_FAILED)"
// which leak internal implementation details (temp dump paths, internal
// product/package names, raw error codes). We must never show those to end
// users, so we map known error categories to friendly Chinese messages and,
// as a last resort, strip any remaining internal markers before display.

// "(Details: /tmp/...json)" hints appended by the backend error dumper.
const DETAILS_HINT_PATTERN = /\s*[（(]\s*Details:\s*[^)）]*[)）]/gi;
// Internal product / package identifiers that must never reach users.
const INTERNAL_MARKER_PATTERN = /qwenpaw|copaw/gi;

function stripInternalMarkers(text: string): string {
  return text
    .replace(DETAILS_HINT_PATTERN, "")
    .replace(INTERNAL_MARKER_PATTERN, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function toFriendlyChatError(error: unknown): string {
  const raw = String(
    (error as { message?: unknown } | null)?.message ??
      (typeof error === "string" ? error : ""),
  ).trim();

  if (!raw) {
    return "请稍后重试";
  }

  // 网络 / 流式连接中断
  if (
    /RemoteProtocolError|incomplete chunked read|peer closed connection|流式连接超时|未返回可读取的流式数据/i.test(
      raw,
    )
  ) {
    return "模型流式连接中断，请重试当前步骤。";
  }

  // 模型执行类错误：隐藏内部实现细节（临时文件路径、错误码、内部名称）
  const looksLikeModelError =
    /execution of model|MODEL_EXECUTION_FAILED|MODEL_TIMEOUT|MODEL_QUOTA|UNAUTHORIZED_MODEL|CONTEXT_LENGTH|qwenpaw_query_error|[（(]\s*Details:/i.test(
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

  // 兜底：清理可能泄露的内部标记后展示
  return stripInternalMarkers(raw) || "请稍后重试";
}
