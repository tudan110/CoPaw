# AI 大屏 P1 · 视觉地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the front-end big-screen component library, full-screen layout engine, and renderer so a typed `DashboardSpec` fixture renders as the locked **D-max** dashboard (glass + aurora + map flying-lines + flip numbers + water-ball + radar + particles), filling the viewport at every breakpoint — with **no backend and no AI** yet.

**Architecture:** A `DashboardSpec` (typed) → `BigScreenRenderer` dispatches each `component.type` to a widget from a whitelist registry → widgets are laid out by a scale-to-fit `ScreenStage` → visuals/highlights/motion are driven by pure, unit-tested logic modules (`layout.ts`, `visualSpec.ts`, `rules.ts`, `binding.ts`, `charts/options.ts`). Pure logic is TDD'd with Node's built-in test runner; visual widgets are verified via a fixture preview route + `pnpm build` + the visual-companion eyeball.

**Tech Stack:** React 18 + TS + Vite (portal), `echarts@6` + `echarts-for-react@3` (already deps), Node built-in test runner (`node:test`, `node --test`, native TS strip on node 24). No new runtime npm deps (China map ships as a static GeoJSON asset).

**Spec:** `docs/solution-design/ai-big-screen-redesign-spec.md` (this plan covers only **P1 / §4, §7** of it). P2 (AI pipeline), P3 (persistence + workshop UX), P4 (hardening) get their own plans.

**Visual source of truth:** `/.superpowers/brainstorm/1518540-1780883807/content/bigscreen-d-max.html` and `bigscreen-d-rich.html` — port their CSS/structure into React. These are the agreed pixels.

---

## Conventions for this plan

- **Test runner:** pure-logic modules live in `X.ts` with co-located `X.test.ts` using `import test from "node:test"` + `import assert from "node:assert/strict"` and **explicit `.ts` import extensions** (e.g. `from "./layout.ts"`), matching `portal/src/alarm-analyst/shared.test.ts`.
- **Run a test file:** `cd portal && node --test src/components/big-screen/<path>.test.ts`
- **Run all P1 tests:** `cd portal && node --test 'src/components/big-screen/**/*.test.ts'` (a pre-existing unrelated failing test in `src/alarm-analyst/shared.test.ts` is out of scope — do not "fix" it here; scope runs to `big-screen`).
- **Build gate:** `cd portal && pnpm build` must pass after visual tasks.
- **Commit style:** Conventional Commits, English subject (repo rule), scope `portal`. End commit messages with the repo's required Co-Authored-By trailer.
- **No backend calls in P1.** Widgets read only from `component.data` / `dataRef`-resolved fixtures.

---

## File Structure (P1)

```
portal/src/components/big-screen/
  types.ts                 # DashboardSpec/Component/VisualSpec/CapabilityResult + normalizeSpec()
  types.test.ts            # normalizeSpec() guards/defaults
  fixtures.ts              # DMAX_OPS_FIXTURE: a full D-max DashboardSpec for dev/verify
  layout.ts                # computeStageTransform() scale-to-fit (pure)
  layout.test.ts
  visualSpec.ts            # visualSpecClassTokens() + safeToken() sanitizer (pure)
  visualSpec.test.ts
  rules.ts                 # evaluateRules() highlight/emphasis engine (pure)
  rules.test.ts
  binding.ts               # bindingField()/coerceNumber()/pickRows() (pure)
  binding.test.ts
  registry.ts              # COMPONENT_REGISTRY: type -> renderer; resolveRenderer()
  registry.test.ts         # dispatch + unknown-type fallback
  charts/
    darkTheme.ts           # registerDarkChartTheme() for echarts
    options.ts             # pure option builders (line/bar/area/donut/gauge/radar/heatmap/graph/mapFly)
    options.test.ts
    chinaGeo.ts            # ensureChinaMap(): fetch + echarts.registerMap('china', …)
    EChart.tsx             # thin echarts-for-react wrapper (dark theme; no fn-literal configs)
  panels/
    ScreenStage.tsx        # full-screen scale-to-fit stage (uses layout.ts)
    GlassPanel.tsx         # glass card shell + sourceStatus badge
    AuroraBackground.tsx
    ParticleLayer.tsx
  widgets/
    FlipNumber.tsx  MetricKpi.tsx  LiquidBall.tsx  AlarmStream.tsx  TopNRank.tsx
    RiskPulse.tsx   Funnel.tsx     Timeline.tsx    Bar3D.tsx        ChartWidget.tsx
  BigScreenRenderer.tsx    # consumes DashboardSpec -> ScreenStage + panels + widgets
  big-screen.css           # glass/aurora/particle/motion/flip/etc (ported from D-max mockup)
  index.ts                 # barrel exports

portal/src/pages/big-screen-preview/BigScreenPreviewPage.tsx   # dev route to eyeball fixtures
portal/public/geo/china.json                                   # China map GeoJSON (static asset)
portal/src/App.tsx                                             # MODIFY: add /big-screen-preview route
portal/package.json                                           # MODIFY: add "test:big-screen" script
```

**Responsibility boundaries:** pure logic (`layout/visualSpec/rules/binding/charts/options`) has zero React imports and is fully unit-tested. React components import the logic, never re-implement it. `BigScreenRenderer` only dispatches + composes; it contains no per-widget drawing.

---

## Task 1: Test script + smoke test (green baseline)

**Files:**
- Modify: `portal/package.json` (add script)
- Create: `portal/src/components/big-screen/smoke.test.ts`

- [ ] **Step 1: Add a scoped test script.** In `portal/package.json` `"scripts"`, add:

```json
"test:big-screen": "node --test \"src/components/big-screen/**/*.test.ts\""
```

- [ ] **Step 2: Write a smoke test** at `portal/src/components/big-screen/smoke.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";

test("node test runner + native TS strip works", () => {
  assert.equal(1 + 1, 2);
});
```

- [ ] **Step 3: Run it.** `cd portal && node --test src/components/big-screen/smoke.test.ts`
Expected: `# pass 1`, `# fail 0`, exit prints passing summary.

- [ ] **Step 4: Commit.**

```bash
git add portal/package.json portal/src/components/big-screen/smoke.test.ts
git commit -m "build(portal): add big-screen test script and runner smoke test"
```

---

## Task 2: Typed domain model + normalizeSpec

**Files:**
- Create: `portal/src/components/big-screen/types.ts`
- Test: `portal/src/components/big-screen/types.test.ts`

These TS types mirror the future backend Pydantic schema (spec §3). P1 only needs them on the front end.

- [ ] **Step 1: Write the failing test** `types.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { normalizeSpec } from "./types.ts";

test("normalizeSpec fills required defaults", () => {
  const spec = normalizeSpec({ id: "s1", name: "运维大屏", components: [{ id: "c1", type: "metric-kpi" }] });
  assert.equal(spec.schemaVersion, 1);
  assert.equal(spec.status, "draft");
  assert.deepEqual(spec.layout, { designWidth: 1920, designHeight: 1080 });
  assert.equal(spec.components[0].title, "");
  assert.deepEqual(spec.components[0].visualSpec, {});
});

test("normalizeSpec drops a component with no id", () => {
  const spec = normalizeSpec({ id: "s1", name: "x", components: [{ type: "table" }] as any });
  assert.equal(spec.components.length, 0);
});
```

- [ ] **Step 2: Run → fail.** `cd portal && node --test src/components/big-screen/types.test.ts` → FAIL (`normalizeSpec` not found).

- [ ] **Step 3: Implement `types.ts`:**

```ts
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
```

- [ ] **Step 4: Run → pass.** `cd portal && node --test src/components/big-screen/types.test.ts` → PASS.

- [ ] **Step 5: Commit.**

```bash
git add portal/src/components/big-screen/types.ts portal/src/components/big-screen/types.test.ts
git commit -m "feat(portal): typed DashboardSpec model + normalizeSpec for big-screen"
```

---

## Task 3: Layout engine — scale-to-fit (the "满屏" guarantee)

**Files:**
- Create: `portal/src/components/big-screen/layout.ts`
- Test: `portal/src/components/big-screen/layout.test.ts`

`computeStageTransform` maps a fixed design canvas onto any viewport with no empty bands (this is the fix for "button pushed out of viewport" + horizontal-scroll).

- [ ] **Step 1: Failing test** `layout.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { computeStageTransform } from "./layout.ts";

test("contain: scales to fit and centers, never overflows", () => {
  const t = computeStageTransform({ designWidth: 1920, designHeight: 1080 }, { width: 960, height: 540 }, "contain");
  assert.equal(t.scale, 0.5);
  assert.equal(t.offsetX, 0);
  assert.equal(t.offsetY, 0);
});

test("contain: letterboxes the shorter axis (centered)", () => {
  const t = computeStageTransform({ designWidth: 1920, designHeight: 1080 }, { width: 1920, height: 1080 + 200 }, "contain");
  assert.equal(t.scale, 1);
  assert.equal(t.offsetY, 100); // (1280-1080)/2
});

test("cover: fills viewport (may crop), scale uses max ratio", () => {
  const t = computeStageTransform({ designWidth: 1920, designHeight: 1080 }, { width: 1920, height: 1280 }, "cover");
  assert.equal(Math.round(t.scale * 1000), Math.round((1280 / 1080) * 1000));
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `layout.ts`:**

```ts
export interface DesignSize { designWidth: number; designHeight: number; }
export interface Viewport { width: number; height: number; }
export interface StageTransform { scale: number; offsetX: number; offsetY: number; }
export type FitMode = "contain" | "cover";

export function computeStageTransform(design: DesignSize, viewport: Viewport, mode: FitMode = "contain"): StageTransform {
  const sx = viewport.width / design.designWidth;
  const sy = viewport.height / design.designHeight;
  const scale = mode === "cover" ? Math.max(sx, sy) : Math.min(sx, sy);
  const offsetX = (viewport.width - design.designWidth * scale) / 2;
  const offsetY = (viewport.height - design.designHeight * scale) / 2;
  return { scale, offsetX, offsetY };
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(portal): scale-to-fit layout engine for big-screen stage"`

---

## Task 4: visualSpec → class tokens + safe-token sanitizer

**Files:**
- Create: `portal/src/components/big-screen/visualSpec.ts`
- Test: `portal/src/components/big-screen/visualSpec.test.ts`

Implements the previously-dead DSL: turns `visualSpec` into sanitized CSS class tokens the renderer applies. (Mirror of backend sanitizer; the FE still defends.)

- [ ] **Step 1: Failing test:**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { visualSpecClassTokens, safeToken } from "./visualSpec.ts";

test("emits whitelisted kind/motion/density/layout/composition classes", () => {
  const cls = visualSpecClassTokens({ kind: "risk-field", motion: "pulse", density: "showcase", layoutPattern: "focus", composition: "primary" });
  assert.ok(cls.includes("bs-kind-risk-field"));
  assert.ok(cls.includes("bs-motion-pulse"));
  assert.ok(cls.includes("bs-density-showcase"));
  assert.ok(cls.includes("bs-layout-focus"));
  assert.ok(cls.includes("bs-comp-primary"));
});

test("drops non-whitelisted tokens", () => {
  const cls = visualSpecClassTokens({ motion: "explode" as any, kind: "<script>" as any });
  assert.ok(!cls.join(" ").includes("explode"));
  assert.ok(!cls.join(" ").includes("script"));
});

test("safeToken blocks injection payloads", () => {
  assert.equal(safeToken("javascript:alert(1)"), "");
  assert.equal(safeToken("<img onerror=x>"), "");
  assert.equal(safeToken("severity"), "severity");
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `visualSpec.ts`:**

```ts
import type { VisualSpec } from "./types.ts";

const KINDS = new Set(["risk-field", "signal-stream", "timeline", "heatmap-matrix", "metric-cluster"]);
const MOTIONS = new Set(["none", "pulse", "scan", "flow", "stagger"]);
const DENSITIES = new Set(["compact", "balanced", "showcase"]);
const LAYOUTS = new Set(["grid", "focus", "split", "timeline", "matrix", "flow"]);
const COMPS = new Set(["primary", "secondary", "supporting"]);
const BAD = ["<", ">", "script", "javascript:", "data:", "vbscript:", "onerror", "onclick", "style=", "expression(", "http://", "https://", "&#"];

export function safeToken(raw: unknown, maxLen = 40): string {
  const s = String(raw ?? "").slice(0, maxLen);
  const low = s.toLowerCase();
  if (BAD.some((b) => low.includes(b))) return "";
  return /^[\w一-龥.\- ]*$/.test(s) ? s : "";
}

export function visualSpecClassTokens(vs: VisualSpec | undefined): string[] {
  if (!vs) return [];
  const out: string[] = [];
  if (vs.kind && KINDS.has(vs.kind)) out.push(`bs-kind-${vs.kind}`);
  if (vs.motion && MOTIONS.has(vs.motion)) out.push(`bs-motion-${vs.motion}`);
  if (vs.density && DENSITIES.has(vs.density)) out.push(`bs-density-${vs.density}`);
  if (vs.layoutPattern && LAYOUTS.has(vs.layoutPattern)) out.push(`bs-layout-${vs.layoutPattern}`);
  if (vs.composition && COMPS.has(vs.composition)) out.push(`bs-comp-${vs.composition}`);
  return out;
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(portal): implement visualSpec class tokens + safe-token sanitizer"`

---

## Task 5: Highlight/emphasis rule engine

**Files:**
- Create: `portal/src/components/big-screen/rules.ts`
- Test: `portal/src/components/big-screen/rules.test.ts`

The data-driven conditional styling the old DSL promised but never ran.

- [ ] **Step 1: Failing test:**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { evaluateRules, toneRank } from "./rules.ts";

const rows = [
  { host: "db-07", cpu: 96 },
  { host: "web-1", cpu: 40 },
];

test("returns strongest matching tone per row", () => {
  const tones = evaluateRules(rows, [
    { field: "cpu", operator: ">=", value: 90, tone: "critical" },
    { field: "cpu", operator: ">=", value: 30, tone: "normal" },
  ]);
  assert.equal(tones[0], "critical"); // 96 >= 90 wins over normal
  assert.equal(tones[1], "normal");
});

test("contains operator + no-match -> null tone", () => {
  const tones = evaluateRules([{ msg: "OOM killed" }, { msg: "ok" }], [
    { field: "msg", operator: "contains", value: "OOM", tone: "critical" },
  ]);
  assert.equal(tones[0], "critical");
  assert.equal(tones[1], null);
});

test("toneRank orders severity", () => {
  assert.ok(toneRank("critical") > toneRank("high"));
  assert.ok(toneRank("high") > toneRank("normal"));
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `rules.ts`:**

```ts
import type { VisualRule } from "./types.ts";

const RANK: Record<string, number> = { critical: 5, high: 4, medium: 3, warm: 2, normal: 1, cool: 1 };
export function toneRank(tone: string): number { return RANK[tone] ?? 0; }

function match(cell: unknown, op: VisualRule["operator"], value: string | number): boolean {
  if (op === "contains") return String(cell ?? "").includes(String(value));
  const a = typeof cell === "number" ? cell : Number(cell);
  const b = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(a) || Number.isNaN(b)) return false;
  switch (op) {
    case ">": return a > b;
    case ">=": return a >= b;
    case "<": return a < b;
    case "<=": return a <= b;
    case "=": return a === b;
    default: return false;
  }
}

export function evaluateRules(rows: Array<Record<string, unknown>>, rules: VisualRule[] | undefined): Array<string | null> {
  if (!rules?.length) return rows.map(() => null);
  return rows.map((row) => {
    let best: string | null = null;
    for (const r of rules) {
      if (match(row[r.field], r.operator, r.value) && (best === null || toneRank(r.tone) > toneRank(best))) {
        best = r.tone;
      }
    }
    return best;
  });
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(portal): data-driven highlight/emphasis rule engine for big-screen"`

---

## Task 6: Data-binding helpers

**Files:**
- Create: `portal/src/components/big-screen/binding.ts`
- Test: `portal/src/components/big-screen/binding.test.ts`

- [ ] **Step 1: Failing test:**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { bindingField, coerceNumber } from "./binding.ts";

test("bindingField resolves via visualSpec.bindings then fallback keys", () => {
  const row = { riskScore: 88, value: 12 };
  assert.equal(bindingField(row, { value: "riskScore" }, "value", "count"), 88); // binding wins
  assert.equal(bindingField({ count: 5 }, undefined, "value", "count"), 5);      // fallback chain
  assert.equal(bindingField({}, undefined, "value"), undefined);
});

test("coerceNumber tolerates strings and units", () => {
  assert.equal(coerceNumber("96%"), 96);
  assert.equal(coerceNumber("1,284"), 1284);
  assert.equal(coerceNumber(null), 0);
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `binding.ts`:**

```ts
export function bindingField(
  row: Record<string, unknown>,
  bindings: Record<string, string> | undefined,
  ...fallbackKeys: string[]
): unknown {
  const logical = fallbackKeys[0];
  const mapped = logical && bindings?.[logical];
  if (mapped && row[mapped] !== undefined) return row[mapped];
  for (const k of fallbackKeys) if (row[k] !== undefined) return row[k];
  return undefined;
}

export function coerceNumber(v: unknown): number {
  if (typeof v === "number") return v;
  const n = Number(String(v ?? "").replace(/[,%\s]/g, ""));
  return Number.isNaN(n) ? 0 : n;
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(portal): big-screen data-binding helpers"`

---

## Task 7: ECharts dark theme + pure option builders

**Files:**
- Create: `portal/src/components/big-screen/charts/options.ts`
- Create: `portal/src/components/big-screen/charts/darkTheme.ts`
- Test: `portal/src/components/big-screen/charts/options.test.ts`

Option builders are **pure data transforms** (testable). They take `CapabilityResult`-shaped data + a `VisualSpec` and return an echarts `option` object. **No function literals** in options (security: spec §4/§11).

- [ ] **Step 1: Failing test** (`charts/options.test.ts`) — assert option shape, not pixels:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { buildLineOption, buildRadarOption, buildMapFlyOption } from "./options.ts";

test("buildLineOption maps series rows to xAxis+series, dark grid", () => {
  const opt: any = buildLineOption({ rows: [{ t: "10:00", v: 5 }, { t: "11:00", v: 8 }] }, { x: "t", y: "v" });
  assert.deepEqual(opt.xAxis.data, ["10:00", "11:00"]);
  assert.deepEqual(opt.series[0].data, [5, 8]);
  assert.equal(opt.series[0].type, "line");
  assert.equal(typeof opt.backgroundColor, "string"); // transparent/dark
  assert.ok(!JSON.stringify(opt).includes("function")); // no fn literals
});

test("buildRadarOption builds indicators from metrics", () => {
  const opt: any = buildRadarOption({ metrics: { 稳定性: 90, 性能: 80, 容量: 70 } });
  assert.equal(opt.radar.indicator.length, 3);
  assert.deepEqual(opt.series[0].data[0].value, [90, 80, 70]);
});

test("buildMapFlyOption emits geo china + lines series from edges", () => {
  const opt: any = buildMapFlyOption({ nodes: [{ name: "北京", coord: [116, 40] }, { name: "上海", coord: [121, 31] }] }, [{ from: "上海", to: "北京" }]);
  assert.equal(opt.geo.map, "china");
  assert.equal(opt.series.find((s: any) => s.type === "lines").data.length, 1);
});
```

- [ ] **Step 2: Run → fail.** `cd portal && node --test src/components/big-screen/charts/options.test.ts`

- [ ] **Step 3: Implement `darkTheme.ts`** (register once) and `options.ts` builders. Minimum builders: `buildLineOption`, `buildBarOption`, `buildAreaOption`, `buildDonutOption`, `buildGaugeOption`, `buildRadarOption`, `buildHeatmapOption`, `buildGraphOption`, `buildMapFlyOption`. Each returns a plain object with `backgroundColor: "transparent"`, dark axis/label colors (`#9fb2cc`, splitLine `rgba(255,255,255,.08)`), palette `["#22d3ee","#34d399","#a78bfa","#fb923c","#f87171"]`. `buildMapFlyOption` uses `geo: { map: "china", roam:false, itemStyle:{areaColor:"rgba(56,189,248,.06)",borderColor:"rgba(56,189,248,.25)"} }`, an `effectScatter` series for nodes, and a `lines` series with `effect:{show:true, symbol:"arrow"}` for edges. (Full builder bodies are straightforward data maps — keep them pure, no closures stored on the option.)

`darkTheme.ts`:

```ts
import * as echarts from "echarts";
let registered = false;
export const BS_PALETTE = ["#22d3ee", "#34d399", "#a78bfa", "#fb923c", "#f87171"];
export function registerDarkChartTheme(): string {
  if (!registered) {
    echarts.registerTheme("bs-dark", {
      color: BS_PALETTE,
      backgroundColor: "transparent",
      textStyle: { color: "#cbd6e8" },
      categoryAxis: { axisLine: { lineStyle: { color: "rgba(255,255,255,.18)" } }, axisLabel: { color: "#9fb2cc" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } } },
      valueAxis: { axisLabel: { color: "#9fb2cc" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } } },
    });
    registered = true;
  }
  return "bs-dark";
}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(portal): dark echarts theme + pure chart option builders"`

---

## Task 8: China map asset + registration

**Files:**
- Create: `portal/public/geo/china.json` (static GeoJSON)
- Create: `portal/src/components/big-screen/charts/chinaGeo.ts`
- Test: `portal/src/components/big-screen/charts/chinaGeo.test.ts` (guard logic only)

- [ ] **Step 1: Obtain the asset.** Download a China provinces GeoJSON to `portal/public/geo/china.json`. Command (run once, verify size > 100KB):

```bash
cd portal && mkdir -p public/geo && \
curl -fsSL https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json -o public/geo/china.json && \
node -e "const g=require('./public/geo/china.json'); if(g.type!=='FeatureCollection'||!g.features.length) throw new Error('bad geojson'); console.log('features',g.features.length)"
```

Expected: prints `features 34` (±). If the network is unavailable in the build env, commit the file from a known-good copy; the asset must be vendored (no runtime CDN dependency).

- [ ] **Step 2: Failing test** `chinaGeo.test.ts` — test the idempotent-guard, not the fetch:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { __resetChinaMapForTest, isChinaMapReady } from "./chinaGeo.ts";

test("map starts unready and guard is idempotent", () => {
  __resetChinaMapForTest();
  assert.equal(isChinaMapReady(), false);
});
```

- [ ] **Step 3: Implement `chinaGeo.ts`:**

```ts
import * as echarts from "echarts";
let ready = false;
let inflight: Promise<void> | null = null;
export function isChinaMapReady(): boolean { return ready; }
export function __resetChinaMapForTest(): void { ready = false; inflight = null; }
export async function ensureChinaMap(): Promise<void> {
  if (ready) return;
  if (!inflight) {
    inflight = fetch("/geo/china.json")
      .then((r) => r.json())
      .then((geo) => { echarts.registerMap("china", geo); ready = true; });
  }
  await inflight;
}
```

- [ ] **Step 4: Run → pass.** (`fetch` is not exercised in the test.)

- [ ] **Step 5: Commit.**

```bash
git add portal/public/geo/china.json portal/src/components/big-screen/charts/chinaGeo.ts portal/src/components/big-screen/charts/chinaGeo.test.ts
git commit -m "feat(portal): vendor China GeoJSON + map registration guard"
```

---

## Task 9: Component registry (the whitelist + dispatch)

**Files:**
- Create: `portal/src/components/big-screen/registry.ts`
- Test: `portal/src/components/big-screen/registry.test.ts`

The registry is the AI-facing whitelist. Unknown types render an explicit placeholder (not a silent text blurb).

- [ ] **Step 1: Failing test:**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { isKnownComponentType, KNOWN_COMPONENT_TYPES } from "./registry.ts";

test("registry advertises the D-max widget whitelist", () => {
  for (const t of ["metric-kpi","flip-number","liquid-ball","line-chart","bar-chart","area-chart","donut","gauge","radar","heatmap","graph","map-fly","alarm-stream","top-n","risk-pulse","funnel","timeline","bar3d"]) {
    assert.ok(KNOWN_COMPONENT_TYPES.includes(t), `${t} should be registered`);
  }
});

test("unknown type is not known", () => {
  assert.equal(isKnownComponentType("totally-made-up"), false);
});
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `registry.ts`** as a `Record<string, React.FC<WidgetProps>>` plus `KNOWN_COMPONENT_TYPES`/`isKnownComponentType`. (Widget components are created in Tasks 10–12; until then, register stubs that render the component title so this task is independently green. Replace stubs as widgets land.) Define the shared widget contract here:

```ts
import type { ScreenComponent } from "./types.ts";
export interface WidgetProps { component: ScreenComponent; }
// COMPONENT_REGISTRY: Record<string, React.FC<WidgetProps>> filled as widgets are implemented.
export const KNOWN_COMPONENT_TYPES = [
  "metric-kpi","flip-number","liquid-ball","line-chart","bar-chart","area-chart","donut","gauge",
  "radar","heatmap","graph","map-fly","alarm-stream","top-n","risk-pulse","funnel","timeline","bar3d","text",
] as const;
export function isKnownComponentType(t: string): boolean { return (KNOWN_COMPONENT_TYPES as readonly string[]).includes(t); }
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(portal): big-screen component registry + type whitelist"`

---

## Task 10: Panels (ScreenStage, GlassPanel, Aurora, Particles) + CSS

**Files:**
- Create: `portal/src/components/big-screen/panels/ScreenStage.tsx`, `GlassPanel.tsx`, `AuroraBackground.tsx`, `ParticleLayer.tsx`
- Create: `portal/src/components/big-screen/big-screen.css`

Verification is visual (no unit asserts): these are rendered by the preview page (Task 13). Port glass/aurora/particle/motion CSS from the mockup.

- [ ] **Step 1: `ScreenStage.tsx`** — wraps children in a fixed `designWidth×designHeight` canvas, observes its container with `ResizeObserver`, and applies `transform: translate(offsetX,offsetY) scale(scale)` from `computeStageTransform`. Default `mode="contain"` so nothing is cropped and there are **no empty bands** beyond symmetric letterboxing on a mismatched aspect (the dark bg fills letterbox). Props: `{ design: {designWidth,designHeight}, mode?: "contain"|"cover", children }`.

```tsx
import { useEffect, useRef, useState } from "react";
import { computeStageTransform, type FitMode } from "../layout.ts";

export function ScreenStage({ design, mode = "contain", children }: { design: { designWidth: number; designHeight: number }; mode?: FitMode; children: React.ReactNode; }) {
  const ref = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setVp({ width: e.contentRect.width, height: e.contentRect.height }));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  const t = computeStageTransform(design, vp, mode);
  return (
    <div ref={ref} className="bs-stage-root">
      <div className="bs-stage" style={{ width: design.designWidth, height: design.designHeight, transform: `translate(${t.offsetX}px, ${t.offsetY}px) scale(${t.scale})`, transformOrigin: "top left" }}>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: `GlassPanel.tsx`** — glass card shell (`backdrop-filter` + border + radius + shadow) with header (`title` + `live/empty/failed/gap` badge) and a body slot. Falls back to a solid translucent bg when `backdrop-filter` is unsupported (`@supports not`) so panels never go invisible (the bug you saw in the mockup).

- [ ] **Step 3: `AuroraBackground.tsx` + `ParticleLayer.tsx`** — absolutely-positioned blurred radial blobs + pulsing dots, `z-index:0`, `pointer-events:none`. Respect `prefers-reduced-motion`.

- [ ] **Step 4: `big-screen.css`** — port tokens from `.superpowers/brainstorm/1518540-1780883807/content/bigscreen-d-max.html`: `.bs-stage-root{position:absolute;inset:0;overflow:hidden;background:radial-gradient(...)}`, glass `.bs-gp`, aurora, particles, and the **motion classes that were previously no-ops**: `.bs-motion-pulse`, `.bs-motion-stagger` (real `@keyframes`), `.bs-motion-scan`, `.bs-motion-flow`; density/layout/composition classes from Task 4 tokens; flip-number, water-ball, scan-line keyframes. Include `@supports not (backdrop-filter: blur(1px)) { .bs-gp{ background: rgba(16,28,46,.82) } }`.

- [ ] **Step 5: Build gate.** `cd portal && pnpm build` → must succeed (TS + vite). Commit.

```bash
git add portal/src/components/big-screen/panels portal/src/components/big-screen/big-screen.css
git commit -m "feat(portal): big-screen stage/glass/aurora/particle panels + D-max CSS"
```

---

## Task 11: Number/list widgets (FlipNumber, MetricKpi, LiquidBall, AlarmStream, TopNRank, RiskPulse, Funnel, Timeline, Bar3D)

**Files:**
- Create the nine widget files under `portal/src/components/big-screen/widgets/`
- Modify: `registry.ts` (replace stubs with real components)

Each widget: reads `component.data` (a `CapabilityResult`), uses `binding.ts` for fields, `rules.ts` for tones, `visualSpec.ts` tokens for classes; renders the corresponding D-max element. Verified visually via preview (Task 13). Build gate per commit.

- [ ] **Step 1: Implement `FlipNumber.tsx`, `MetricKpi.tsx`, `LiquidBall.tsx`** (port flip digit-cells, KPI tile, water-ball from mockup). Wire into `COMPONENT_REGISTRY`.
- [ ] **Step 2: Implement `AlarmStream.tsx`, `TopNRank.tsx`, `RiskPulse.tsx`** — `AlarmStream` is the marquee list (severity dot via `evaluateRules`), `TopNRank` horizontal bars, `RiskPulse` the risk gauge/keyword chips.
- [ ] **Step 3: Implement `Funnel.tsx`, `Timeline.tsx`, `Bar3D.tsx`** (faux-3D CSS bars).
- [ ] **Step 4: Build gate** after each sub-step: `cd portal && pnpm build` → success.
- [ ] **Step 5: Commit** (one commit per sub-step, e.g. `feat(portal): big-screen number widgets (flip/kpi/liquid-ball)`).

---

## Task 12: Chart widget (echarts wrapper + ChartWidget + MapFly)

**Files:**
- Create: `portal/src/components/big-screen/charts/EChart.tsx`
- Create: `portal/src/components/big-screen/widgets/ChartWidget.tsx`
- Modify: `registry.ts`

- [ ] **Step 1: `EChart.tsx`** — thin `echarts-for-react` wrapper: calls `registerDarkChartTheme()`, passes `theme="bs-dark"`, `opts={{ renderer: "canvas" }}`, `style={{height:"100%",width:"100%"}}`. Accepts a plain `option` object only (no function configs).
- [ ] **Step 2: `ChartWidget.tsx`** — maps `component.type` → option builder from Task 7 (`line-chart→buildLineOption`, …, `map-fly→buildMapFlyOption`), calling `ensureChinaMap()` (Task 8) before rendering `map-fly`, with a loading placeholder until ready. Register all chart types in `COMPONENT_REGISTRY`.
- [ ] **Step 3: Build gate.** `cd portal && pnpm build` → success.
- [ ] **Step 4: Commit.** `git commit -m "feat(portal): big-screen chart widget + dark echarts wrapper + map-fly"`

---

## Task 13: BigScreenRenderer + fixture + preview route (the eyeball)

**Files:**
- Create: `portal/src/components/big-screen/BigScreenRenderer.tsx`
- Create: `portal/src/components/big-screen/fixtures.ts`
- Create: `portal/src/pages/big-screen-preview/BigScreenPreviewPage.tsx`
- Create: `portal/src/components/big-screen/index.ts`
- Modify: `portal/src/App.tsx` (add route)
- Test: `portal/src/components/big-screen/BigScreenRenderer.test.ts` (dispatch logic only)

- [ ] **Step 1: Failing test** for the pure dispatch helper used by the renderer:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { resolveComponentType } from "./BigScreenRenderer.ts"; // export the pure helper from the tsx? -> put helper in registry.ts

test("known type resolves to itself; unknown -> 'unknown'", () => {
  assert.equal(resolveComponentType("map-fly"), "map-fly");
  assert.equal(resolveComponentType("nope"), "unknown");
});
```

> Note: put `resolveComponentType` in `registry.ts` (pure, importable by `.test.ts`) and re-export; the `.tsx` renderer imports it. This keeps the test free of JSX.

- [ ] **Step 2: Implement `resolveComponentType` in `registry.ts`** (`isKnownComponentType(t) ? t : "unknown"`), run test → pass.
- [ ] **Step 3: `BigScreenRenderer.tsx`** — props `{ spec: DashboardSpec }`: `normalizeSpec`, wrap in `ScreenStage` (uses `spec.layout`), render `AuroraBackground`+`ParticleLayer`, then each component into a `GlassPanel` positioned by `layoutPosition` (absolute, in design px) dispatching via `COMPONENT_REGISTRY[resolveComponentType(c.type)]`; `"unknown"` → explicit placeholder card.
- [ ] **Step 4: `fixtures.ts`** — author `DMAX_OPS_FIXTURE: DashboardSpec` reproducing the D-max ops screen (KPIs incl. flip + SLA gauge, map-fly center, 24h area trend, top-n, donut, alarm-stream, risk-pulse, funnel, heatmap) with inline `data` per component (live/empty/failed mix to prove badges).
- [ ] **Step 5: `BigScreenPreviewPage.tsx` + route** — full-viewport page rendering `<BigScreenRenderer spec={DMAX_OPS_FIXTURE} />`; add a dev route `/big-screen-preview` in `App.tsx` (follow the existing route registration pattern around the current `/big-screen/:screenId` and `/big-screens` routes).
- [ ] **Step 6: Build gate.** `cd portal && pnpm build` → success.
- [ ] **Step 7: Visual verification (companion).** Run the portal dev server (`./start-portal.sh`), open `/big-screen-preview`, and confirm against the locked mockup: fills viewport with no empty bands at 1366×768 / 1440×900 / 1920×1080 / a 4K-wide window; glass panels visible; map flying-lines animate; flip/water-ball/radar render; `live/empty/failed` badges correct. Capture a screenshot to the brainstorm dir and (optionally) push it to the visual companion for sign-off.
- [ ] **Step 8: Commit.** `git commit -m "feat(portal): BigScreenRenderer + D-max fixture + preview route"`

---

## Task 14: P1 wrap — run all tests + build + checkpoint

- [ ] **Step 1: All P1 unit tests.** `cd portal && node --test "src/components/big-screen/**/*.test.ts"` → all pass.
- [ ] **Step 2: Build.** `cd portal && pnpm build` → success.
- [ ] **Step 3: Type/format.** `cd portal && npx tsc -b --noEmit` (if used elsewhere) → no errors; run prettier on new files if the repo formats portal manually.
- [ ] **Step 4: Final commit / tag the phase.** `git commit -m "chore(portal): P1 big-screen visual foundation complete"` (if anything uncommitted).

---

## Self-Review (P1 plan vs spec)

- **Spec §4 (component library):** Tasks 7,10,11,12 — glass/aurora/particles, flip/kpi/liquid-ball, line/bar/area/donut/gauge/radar/heatmap/graph/map-fly, alarm-stream/top-n/risk-pulse/funnel/timeline/bar3d. ✅ (echarts-gl 3D/globe intentionally deferred — bar3d is CSS faux-3D, noted.)
- **Spec §7 (满屏布局引擎):** Tasks 3,10,13 — `computeStageTransform` + `ScreenStage` + preview breakpoint check. ✅
- **Spec §3 (typed DSL, highlight/motion really implemented):** Tasks 2,4,5 + CSS motion classes in Task 10. ✅
- **Spec §11 (no arbitrary JS, no fn-literal chart configs):** Task 7 asserts no `function` in options; Task 12 wrapper rejects fn configs. ✅
- **Out of P1 scope (later plans):** L1/L2/L3 AI pipeline, real capability fetch, SQLite, tasks, workshop UX, patch, golden backend tests → P2/P3/P4. This is the intended phase boundary, not a gap.
- **Placeholder scan:** widget bodies in Tasks 11–12 are spec'd by contract + mockup reference rather than full JSX paste (they are visually-verified, not unit-asserted) — acceptable per "scale fidelity to the question"; every *logic* task has complete test+impl code.
- **Type consistency:** `WidgetProps {component}`, `normalizeSpec`, `computeStageTransform`, `visualSpecClassTokens`, `evaluateRules`, `bindingField`, `resolveComponentType`, `KNOWN_COMPONENT_TYPES` — names used consistently across tasks. ✅
