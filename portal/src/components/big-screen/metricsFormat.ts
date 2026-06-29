/**
 * metricsFormat — present the big-screen generation metrics summary.
 *
 * Backend `GET /ai-big-screens/metrics` returns aggregate quality
 * signals over the recent window: total, successRate, degradedRate,
 * avgDurationMs, capabilityFailureRates, kinds. These pure helpers turn
 * those raw numbers into display strings + a ranked failing-capability
 * list. Pure + dependency-free so it is unit-testable with node --test.
 */

export interface BigScreenMetrics {
  total: number;
  successRate: number;
  degradedRate: number;
  avgDurationMs: number;
  capabilityFailureRates: Record<string, number>;
  kinds: Record<string, number>;
}

/** 0.5 → "50%"; clamps to [0,100], rounds to whole percent. */
export function formatPercent(rate: number): string {
  if (!Number.isFinite(rate)) return "—";
  const pct = Math.min(100, Math.max(0, rate * 100));
  return `${Math.round(pct)}%`;
}

/** Milliseconds → compact human string: "820ms" / "1.5s" / "2m03s". */
export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return `${minutes}m${String(seconds).padStart(2, "0")}s`;
}

/** Capabilities with a non-zero failure rate, worst first. */
export function topFailingCapabilities(
  rates: Record<string, number> | undefined,
  limit = 5,
): Array<{ capabilityId: string; rate: number }> {
  if (!rates || typeof rates !== "object") return [];
  return Object.entries(rates)
    .filter(([, rate]) => Number.isFinite(rate) && rate > 0)
    .map(([capabilityId, rate]) => ({ capabilityId, rate }))
    .sort((a, b) => b.rate - a.rate)
    .slice(0, Math.max(0, limit));
}

/** True when there is at least one recorded generation event. */
export function hasMetrics(metrics: BigScreenMetrics | undefined): boolean {
  return !!metrics && Number(metrics.total) > 0;
}
