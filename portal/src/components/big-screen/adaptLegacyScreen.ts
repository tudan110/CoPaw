import { isKnownComponentType } from "./registry.ts";
import type {
  CapabilityResult,
  DashboardSpec,
  LayoutPosition,
  ScreenComponent,
  SourceStatus,
  VisualSpec,
} from "./types.ts";

/**
 * Adapts the legacy AiBigScreenApp spec (produced by the existing real-data
 * backend pipeline) into the typed DashboardSpec the D-max renderer consumes.
 * The backend already does prompt → LLM plan → real data; this lets that
 * pipeline drive the new visual stack without a backend rewrite.
 *
 * Legacy 12-col grid coordinates are intentionally DROPPED so the auto-layout
 * engine positions components from their visual weight (the locked design:
 * LLM decides semantics, engine decides geometry).
 */

/** Loose shape of the legacy spec — only the fields we read. */
export interface LegacyComponent {
  id: string;
  type?: string;
  title?: string;
  capabilityId?: string;
  visualSpec?: Record<string, unknown>;
  data?: Record<string, unknown>;
  layoutPosition?: unknown;
}
export interface LegacyScreen {
  id?: string;
  name?: string;
  status?: string;
  theme?: Record<string, unknown>;
  components?: LegacyComponent[];
}

/** Legacy visualType / type → D-max component type. */
const TYPE_MAP: Record<string, string> = {
  "metric-card": "metric-kpi",
  metric: "metric-kpi",
  kpi: "metric-kpi",
  number: "flip-number",
  line: "line-chart",
  bar: "bar-chart",
  area: "area-chart",
  pie: "donut",
  // `table` is now a first-class type (TableWidget renders its columns);
  // only genuinely stream-shaped legacy types fall back to alarm-stream.
  list: "alarm-stream",
  stream: "alarm-stream",
  "status-stream": "alarm-stream",
  statusStream: "alarm-stream",
  riskPulse: "risk-pulse",
  topology: "graph",
  group: "text",
};

/** Meta keys on a legacy data payload that must not be promoted into metrics. */
const META_KEYS = new Set([
  "source",
  "sourceStatus",
  "status",
  "message",
  "capabilityId",
  "rows",
  "series",
  "nodes",
  "metrics",
  "fields",
  "columns",
]);

export function mapComponentType(raw: string): string {
  const t = (raw ?? "").trim();
  if (isKnownComponentType(t)) return t; // already a D-max type
  if (TYPE_MAP[t]) return TYPE_MAP[t];
  return "text"; // safe fallback — renderer always has a text widget
}

/**
 * Translate legacy binding roles into the vocabulary the D-max widgets read.
 * Legacy specs bind {title, severity, status, time, value, group}; the new
 * widgets read {message, tone, name, value, time, x, y, ...}. Without this,
 * e.g. AlarmStream looks for `message` while the data only has `title`, so
 * rows render blank. Keeps the original keys and adds derived ones.
 */
export function normalizeBindings(
  b?: Record<string, string>,
): Record<string, string> | undefined {
  if (!b || typeof b !== "object") return b;
  const out: Record<string, string> = { ...b };
  const alias = (target: string, ...sources: string[]) => {
    if (out[target]) return;
    for (const s of sources) {
      if (b[s]) {
        out[target] = b[s];
        return;
      }
    }
  };
  alias("message", "message", "title", "content");
  alias("tone", "tone", "severity", "riskLevel", "level");
  alias("name", "name", "title", "group");
  // value / time / x / y / unit / prefix / color pass through unchanged
  return out;
}

export function mapSourceStatus(raw: unknown, hasRows: boolean): SourceStatus {
  const s = String(raw ?? "").toLowerCase();
  if (["live", "ok", "success", "ready", "online"].includes(s)) return "live";
  if (["empty", "no-data", "nodata", "none"].includes(s)) return "empty";
  if (["failed", "error", "unavailable", "timeout"].includes(s)) return "failed";
  if (["gap", "partial", "stale"].includes(s)) return "gap";
  return hasRows ? "live" : "empty";
}

function adaptData(c: LegacyComponent): CapabilityResult | undefined {
  const d = c.data;
  if (!d || typeof d !== "object") return undefined;

  const rows = Array.isArray(d.rows)
    ? (d.rows as Array<Record<string, unknown>>)
    : undefined;
  const series = Array.isArray(d.series)
    ? (d.series as Array<Record<string, unknown>>)
    : undefined;
  const nodes = Array.isArray(d.nodes)
    ? (d.nodes as Array<Record<string, unknown>>)
    : undefined;

  // metrics = explicit metrics + any top-level scalar fields, so KPI / gauge /
  // flip widgets can find a value wherever the legacy payload placed it.
  const metrics: Record<string, unknown> = {
    ...((d.metrics && typeof d.metrics === "object"
      ? d.metrics
      : {}) as Record<string, unknown>),
  };
  for (const [k, v] of Object.entries(d)) {
    if (!META_KEYS.has(k) && (typeof v === "number" || typeof v === "string")) {
      metrics[k] = v;
    }
  }

  const columns = Array.isArray(d.columns) ? d.columns : undefined;
  const fields = columns
    ?.map((col) => {
      const o = (col ?? {}) as Record<string, unknown>;
      const key = String(o.key ?? o.field ?? o.dataIndex ?? "");
      return key ? { key, label: String(o.label ?? o.title ?? key) } : null;
    })
    .filter((x): x is { key: string; label: string } => x !== null);

  return {
    capabilityId: c.capabilityId ?? String((d.source as string) ?? ""),
    sourceStatus: mapSourceStatus(d.sourceStatus ?? d.status, !!rows?.length),
    rows,
    series,
    nodes,
    metrics: Object.keys(metrics).length ? metrics : undefined,
    fields: fields?.length ? fields : undefined,
    message: typeof d.message === "string" ? d.message : undefined,
  };
}

export function adaptLegacyScreen(screen: LegacyScreen): DashboardSpec {
  const components: ScreenComponent[] = (screen.components ?? [])
    .filter((c) => c && typeof c.id === "string" && c.id.length > 0)
    .map((c) => {
      const vs = (c.visualSpec ?? {}) as VisualSpec;
      const lp = c.layoutPosition as LayoutPosition | undefined;
      return {
        id: c.id,
        type: mapComponentType(String(c.type ?? "text")),
        title: String(c.title ?? ""),
        // Generated coordinates are still dropped so auto-layout owns
        // geometry; only an explicit user "move" (pinned) is honoured —
        // it carries 12-col grid units the renderer converts to pixels.
        layoutPosition: lp && lp.pinned ? lp : undefined,
        visualSpec: { ...vs, bindings: normalizeBindings(vs.bindings) },
        data: adaptData(c),
      };
    });
  return {
    schemaVersion: 1,
    id: String(screen.id ?? ""),
    name: String(screen.name ?? ""),
    status: (screen.status as DashboardSpec["status"]) ?? "draft",
    layout: { designWidth: 1920, designHeight: 1080 },
    theme: (screen.theme as Record<string, unknown>) ?? {},
    components,
  };
}
