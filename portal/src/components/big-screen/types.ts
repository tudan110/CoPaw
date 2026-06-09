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

export interface VisualSpec {
  kind?: string;
  motion?: "none" | "pulse" | "scan" | "flow" | "stagger";
  density?: "compact" | "balanced" | "showcase";
  layoutPattern?: "grid" | "focus" | "split" | "timeline" | "matrix" | "flow";
  composition?: "primary" | "secondary" | "supporting";
  bindings?: Record<string, string>;
  highlightRules?: VisualRule[];
  emphasisRules?: VisualRule[];
}

export interface LayoutPosition { x: number; y: number; w: number; h: number; }

export interface ScreenComponent {
  id: string;
  type: string;            // validated against COMPONENT_REGISTRY at render
  title: string;
  layoutPosition?: LayoutPosition;
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
    theme: input.theme ?? {},
    components,
  };
}
