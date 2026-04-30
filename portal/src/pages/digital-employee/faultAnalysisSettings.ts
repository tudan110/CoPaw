export const DEFAULT_FAULT_ANALYSIS_CONFIDENCE_VISIBLE = true;
export const FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_CHANGED_EVENT =
  "portal-fault-analysis-confidence-visibility-changed";

const FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_STORAGE_KEY =
  "portal.faultAnalysis.showConfidence";

export function normalizeFaultAnalysisConfidenceVisible(value: unknown) {
  if (typeof value === "boolean") {
    return value;
  }

  if (value === null || value === undefined || String(value).trim() === "") {
    return DEFAULT_FAULT_ANALYSIS_CONFIDENCE_VISIBLE;
  }

  const normalized = String(value).trim().toLowerCase();
  if (normalized === "true") {
    return true;
  }
  if (normalized === "false") {
    return false;
  }

  return DEFAULT_FAULT_ANALYSIS_CONFIDENCE_VISIBLE;
}

export function readFaultAnalysisConfidenceVisible() {
  if (typeof window === "undefined") {
    return DEFAULT_FAULT_ANALYSIS_CONFIDENCE_VISIBLE;
  }

  try {
    return normalizeFaultAnalysisConfidenceVisible(
      window.localStorage.getItem(FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_STORAGE_KEY),
    );
  } catch (error) {
    console.error("Failed to load fault analysis confidence visibility:", error);
    return DEFAULT_FAULT_ANALYSIS_CONFIDENCE_VISIBLE;
  }
}

export function writeFaultAnalysisConfidenceVisible(value: unknown) {
  const normalized = normalizeFaultAnalysisConfidenceVisible(value);
  if (typeof window === "undefined") {
    return normalized;
  }

  try {
    window.localStorage.setItem(
      FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_STORAGE_KEY,
      String(normalized),
    );
    window.dispatchEvent(
      new CustomEvent(FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_CHANGED_EVENT, {
        detail: { visible: normalized },
      }),
    );
  } catch (error) {
    console.error("Failed to persist fault analysis confidence visibility:", error);
  }

  return normalized;
}
