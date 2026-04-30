export const DEFAULT_CONVERSATION_PROCESS_RECORD_DISPLAY_MODE = "collapsed";
export const CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_CHANGED_EVENT =
  "portal-conversation-process-record-display-mode-changed";

const CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_STORAGE_KEY =
  "portal.conversation.processRecordDisplayMode";
const CONVERSATION_PROCESS_RECORD_DISPLAY_MODES = ["expanded", "collapsed"] as const;

export type ConversationProcessRecordDisplayMode =
  (typeof CONVERSATION_PROCESS_RECORD_DISPLAY_MODES)[number];

export function normalizeConversationProcessRecordDisplayMode(
  value: unknown,
): ConversationProcessRecordDisplayMode {
  return CONVERSATION_PROCESS_RECORD_DISPLAY_MODES.includes(
    value as ConversationProcessRecordDisplayMode,
  )
    ? (value as ConversationProcessRecordDisplayMode)
    : DEFAULT_CONVERSATION_PROCESS_RECORD_DISPLAY_MODE;
}

export function readConversationProcessRecordDisplayMode(): ConversationProcessRecordDisplayMode {
  if (typeof window === "undefined") {
    return DEFAULT_CONVERSATION_PROCESS_RECORD_DISPLAY_MODE;
  }

  try {
    return normalizeConversationProcessRecordDisplayMode(
      window.localStorage.getItem(CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_STORAGE_KEY),
    );
  } catch (error) {
    console.error("Failed to load conversation process record display mode:", error);
    return DEFAULT_CONVERSATION_PROCESS_RECORD_DISPLAY_MODE;
  }
}

export function writeConversationProcessRecordDisplayMode(
  value: unknown,
): ConversationProcessRecordDisplayMode {
  const normalized = normalizeConversationProcessRecordDisplayMode(value);
  if (typeof window === "undefined") {
    return normalized;
  }

  try {
    window.localStorage.setItem(
      CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_STORAGE_KEY,
      normalized,
    );
    window.dispatchEvent(
      new CustomEvent(CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_CHANGED_EVENT, {
        detail: { mode: normalized },
      }),
    );
  } catch (error) {
    console.error("Failed to persist conversation process record display mode:", error);
  }

  return normalized;
}
