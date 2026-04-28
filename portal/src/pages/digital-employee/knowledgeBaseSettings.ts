export const DEFAULT_KNOWLEDGE_AI_THRESHOLD_PERCENT = 75;
export const KNOWLEDGE_AI_THRESHOLD_CHANGED_EVENT = "portal-knowledge-ai-threshold-changed";

const KNOWLEDGE_AI_THRESHOLD_STORAGE_KEY = "portal.knowledgeBase.aiThresholdPercent";

export function normalizeKnowledgeAiThreshold(value: unknown) {
  if (value === null || value === undefined || String(value).trim() === "") {
    return DEFAULT_KNOWLEDGE_AI_THRESHOLD_PERCENT;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_KNOWLEDGE_AI_THRESHOLD_PERCENT;
  }
  return Math.min(100, Math.max(0, Math.round(parsed)));
}

export function readKnowledgeAiThresholdPercent() {
  if (typeof window === "undefined") {
    return DEFAULT_KNOWLEDGE_AI_THRESHOLD_PERCENT;
  }
  return normalizeKnowledgeAiThreshold(
    window.localStorage.getItem(KNOWLEDGE_AI_THRESHOLD_STORAGE_KEY),
  );
}

export function writeKnowledgeAiThresholdPercent(value: unknown) {
  const normalized = normalizeKnowledgeAiThreshold(value);
  if (typeof window !== "undefined") {
    window.localStorage.setItem(KNOWLEDGE_AI_THRESHOLD_STORAGE_KEY, String(normalized));
    window.dispatchEvent(
      new CustomEvent(KNOWLEDGE_AI_THRESHOLD_CHANGED_EVENT, {
        detail: { thresholdPercent: normalized },
      }),
    );
  }
  return normalized;
}

export function readKnowledgeAiThresholdRatio() {
  return readKnowledgeAiThresholdPercent() / 100;
}
