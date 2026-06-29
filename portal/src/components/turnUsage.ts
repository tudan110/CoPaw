/**
 * Per-turn token + context usage shapes for the portal chat.
 *
 * The backend (console channel, shared by the portal /console/chat stream)
 * emits a trailing ``{type: "turn_usage", usage, context_usage}`` SSE event
 * after the response — ``useRemoteChatSession`` captures it live and attaches
 * it to the closing assistant message as ``turnUsage``. The same payload is
 * also persisted onto that message's ``metadata.qwenpaw_turn_usage`` so it
 * survives a reload; :func:`extractTurnUsageFromMetadata` reads it back when
 * normalizing history. ``TurnUsageRing`` renders either source.
 */

export interface TurnUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  estimated?: boolean;
}

export interface ContextUsage {
  estimated_tokens: number;
  max_input_length: number;
  context_usage_ratio: number;
}

export interface TurnUsageSnapshot {
  usage: TurnUsage | null;
  context_usage: ContextUsage | null;
}

const TURN_USAGE_META_KEY = "qwenpaw_turn_usage";

function readNumber(obj: unknown, key: string): number {
  if (!obj || typeof obj !== "object") return 0;
  const v = (obj as Record<string, unknown>)[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function parseTurnUsagePayload(raw: unknown): TurnUsageSnapshot | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  const usage =
    obj.usage && typeof obj.usage === "object"
      ? (obj.usage as TurnUsage)
      : null;
  const context =
    obj.context_usage && typeof obj.context_usage === "object"
      ? (obj.context_usage as ContextUsage)
      : null;
  const usageTotal =
    readNumber(usage, "total_tokens") ||
    readNumber(usage, "prompt_tokens") + readNumber(usage, "completion_tokens");
  const hasUsage = !!usage && usageTotal > 0;
  const hasCtx = !!context && readNumber(context, "estimated_tokens") > 0;
  if (!hasUsage && !hasCtx) return null;
  return {
    usage: hasUsage ? usage : null,
    context_usage: hasCtx ? context : null,
  };
}

/**
 * Read the persisted ``qwenpaw_turn_usage`` from a backend message's
 * ``metadata`` (handles both the direct key and a nested ``metadata``
 * wrapper). Returns null when absent — used when normalizing history so the
 * usage ring shows on reloaded conversations too.
 */
export function extractTurnUsageFromMetadata(
  meta: unknown,
): TurnUsageSnapshot | null {
  if (!meta || typeof meta !== "object") return null;
  const wrapper = meta as Record<string, unknown>;
  const direct = parseTurnUsagePayload(wrapper[TURN_USAGE_META_KEY]);
  if (direct) return direct;
  const inner = wrapper.metadata;
  if (inner && typeof inner === "object") {
    return parseTurnUsagePayload(
      (inner as Record<string, unknown>)[TURN_USAGE_META_KEY],
    );
  }
  return null;
}
