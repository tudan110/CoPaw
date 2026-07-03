export type SourceStatus = "live" | "empty" | "failed" | "gap";

export interface CapabilityResult {
  capabilityId: string;
  sourceStatus: SourceStatus;
  rows?: Array<Record<string, unknown>>;
  series?: Array<Record<string, unknown>>;
  nodes?: Array<Record<string, unknown>>;
  metrics?: Record<string, unknown>;
  fields?: Array<{ key: string; label: string }>;
  message?: string;
}

export interface VisualRule {
  field: string;
  operator: ">" | ">=" | "<" | "<=" | "=" | "contains";
  value: string | number;
  tone: "critical" | "high" | "medium" | "normal" | "cool" | "warm";
}

/**
 * Controlled presentation style — the single declarative vocabulary the
 * LLM generator and the natural-language edit loop both write, and the
 * renderer reads. Mirrors the backend sanitizer (visualSpec.style):
 * enums + clamped numbers only, never raw CSS/code.
 */
export interface VisualStyle {
  sizeScale?: number;        // 0.5–2.0  component zoom (bigger/smaller)
  palette?: string;          // palette name (see charts/darkTheme PALETTES)
  accentColor?: string;      // primary accent (#hex or colour name)
  lineOpacity?: number;      // 0–100    chart line / area / link brightness
  labelBrightness?: number;  // -100..100 lighten/darken labels
  emphasis?: "standard" | "strong";
}

export interface VisualSpec {
  kind?: string;
  motion?: "none" | "pulse" | "scan" | "flow" | "stagger";
  density?: "compact" | "balanced" | "showcase";
  layoutPattern?: "grid" | "focus" | "split" | "timeline" | "matrix" | "flow";
  composition?: "primary" | "secondary" | "supporting";
  bindings?: Record<string, string>;
  highlightRules?: VisualRule[];
  emphasisRules?: VisualRule[];
  /** Generative composition (composed type) — validated by blueprint.ts. */
  blueprint?: unknown;
  /** Controlled presentation style (size / colour / brightness / emphasis). */
  style?: VisualStyle;
}

export interface LayoutPosition {
  x: number;
  y: number;
  w: number;
  h: number;
  /** True only when the user explicitly moved/positioned the component.
   * Generated (un-pinned) positions are dropped in favour of auto-layout. */
  pinned?: boolean;
}

export interface ScreenComponent {
  id: string;
  type: string;            // validated against COMPONENT_REGISTRY at render
  title: string;
  layoutPosition?: LayoutPosition;
  /** Composition role from the screen-level layout plan:
   *  "hero" | "support" | "context" | "" (unassigned). */
  compositionRole?: string;
  capabilityId?: string;
  dataRef?: string;        // id of a CapabilityResult in spec.data
  data?: CapabilityResult; // P1 fixtures inline data here
  visualSpec: VisualSpec;
}

export interface DashboardSpec {
  schemaVersion: number;
  id: string;
  name: string;
  status: "draft" | "published" | "archived";
  layout: { designWidth: number; designHeight: number };
  /** Screen-level composition decision from the planner (T-018). */
  layoutPlan?: { pattern?: string };
  theme: Record<string, unknown>;
  components: ScreenComponent[];
}

export function normalizeSpec(input: Partial<DashboardSpec> & { components?: any[] }): DashboardSpec {
  const components = (input.components ?? [])
    .filter((c) => c && typeof c.id === "string" && c.id.length > 0)
    .map((c) => ({
      id: c.id,
      type: String(c.type ?? "text"),
      title: String(c.title ?? ""),
      layoutPosition: c.layoutPosition,
      compositionRole: c.compositionRole,
      capabilityId: c.capabilityId,
      dataRef: c.dataRef,
      data: c.data,
      visualSpec: (c.visualSpec ?? {}) as VisualSpec,
    }));
  return {
    schemaVersion: input.schemaVersion ?? 1,
    id: String(input.id ?? ""),
    name: String(input.name ?? ""),
    status: input.status ?? "draft",
    layout: { designWidth: input.layout?.designWidth ?? 1920, designHeight: input.layout?.designHeight ?? 1080 },
    layoutPlan: input.layoutPlan,
    theme: input.theme ?? {},
    components,
  };
}
