import assert from "node:assert/strict";
import test from "node:test";
import {
  adaptLegacyScreen,
  mapComponentType,
  mapSourceStatus,
  normalizeBindings,
} from "./adaptLegacyScreen.ts";

test("maps legacy types to D-max component types", () => {
  assert.equal(mapComponentType("metric-card"), "metric-kpi");
  assert.equal(mapComponentType("table"), "table"); // first-class table widget
  assert.equal(mapComponentType("list"), "alarm-stream"); // stream-shaped
  assert.equal(mapComponentType("topology"), "graph");
  assert.equal(mapComponentType("line-chart"), "line-chart"); // already known
  assert.equal(mapComponentType("risk-pulse"), "risk-pulse"); // already known
  assert.equal(mapComponentType("riskPulse"), "risk-pulse"); // legacy alias
  assert.equal(mapComponentType("totally-unknown"), "text"); // fallback
});

test("maps source status, falling back to row presence", () => {
  assert.equal(mapSourceStatus("ok", true), "live");
  assert.equal(mapSourceStatus("unavailable", false), "failed");
  assert.equal(mapSourceStatus("empty", false), "empty");
  assert.equal(mapSourceStatus(undefined, true), "live");
  assert.equal(mapSourceStatus(undefined, false), "empty");
});

test("drops legacy grid coordinates so auto-layout positions components", () => {
  const spec = adaptLegacyScreen({
    id: "s1",
    name: "Ops",
    status: "published",
    components: [
      {
        id: "a",
        type: "metric-card",
        title: "Alarms",
        layoutPosition: { x: 0, y: 0, w: 4, h: 2 },
        data: { sourceStatus: "ok", value: 1284 },
      },
    ],
  });
  assert.equal(spec.components.length, 1);
  assert.equal(spec.components[0].layoutPosition, undefined, "coords dropped");
  assert.equal(spec.components[0].type, "metric-kpi");
  assert.equal(spec.status, "published");
});

test("carries a pinned move but still drops generated coords; style flows", () => {
  const spec = adaptLegacyScreen({
    id: "s",
    name: "n",
    components: [
      {
        id: "pinned",
        type: "graph",
        title: "拓扑",
        layoutPosition: { x: 0, y: 0, w: 6, h: 5, pinned: true },
        visualSpec: { style: { sizeScale: 1.5, palette: "warm" } },
        data: { sourceStatus: "ok", nodes: [{ name: "a" }] },
      },
      {
        id: "generated",
        type: "graph",
        title: "拓扑2",
        layoutPosition: { x: 6, y: 0, w: 6, h: 5 },
        data: { sourceStatus: "ok", nodes: [{ name: "b" }] },
      },
    ],
  });
  const byId = Object.fromEntries(spec.components.map((c) => [c.id, c]));
  assert.deepEqual(byId["pinned"].layoutPosition, {
    x: 0,
    y: 0,
    w: 6,
    h: 5,
    pinned: true,
  });
  assert.equal(byId["generated"].layoutPosition, undefined, "generated dropped");
  assert.equal(byId["pinned"].visualSpec.style?.sizeScale, 1.5);
  assert.equal(byId["pinned"].visualSpec.style?.palette, "warm");
});

test("adapts data payload into CapabilityResult (rows + scalar metrics)", () => {
  const spec = adaptLegacyScreen({
    id: "s",
    name: "n",
    components: [
      {
        id: "k",
        type: "metric-card",
        title: "Online",
        capabilityId: "cmdb-resources",
        data: { sourceStatus: "ok", total: 8642, rows: [{ host: "a" }] },
      },
    ],
  });
  const d = spec.components[0].data!;
  assert.equal(d.capabilityId, "cmdb-resources");
  assert.equal(d.sourceStatus, "live");
  assert.deepEqual(d.rows, [{ host: "a" }]);
  assert.equal(d.metrics?.total, 8642, "scalar field promoted to metrics");
});

test("failed/empty status surfaces honestly with message", () => {
  const spec = adaptLegacyScreen({
    id: "s",
    name: "n",
    components: [
      {
        id: "h",
        type: "table",
        title: "Heat",
        data: { sourceStatus: "unavailable", message: "timeout", rows: [] },
      },
    ],
  });
  assert.equal(spec.components[0].data?.sourceStatus, "failed");
  assert.equal(spec.components[0].data?.message, "timeout");
});

test("filters components without id; defaults layout to 1920x1080", () => {
  const spec = adaptLegacyScreen({
    components: [
      { id: "", type: "text", title: "x" },
      { id: "ok", type: "text", title: "y" },
    ],
  });
  assert.equal(spec.components.length, 1);
  assert.equal(spec.components[0].id, "ok");
  assert.deepEqual(spec.layout, { designWidth: 1920, designHeight: 1080 });
});

test("normalizeBindings aliases legacy roles to widget vocabulary", () => {
  const b = normalizeBindings({
    title: "title",
    severity: "level",
    time: "eventTime",
    status: "alarmStatus",
  });
  assert.equal(b?.message, "title", "message <- title");
  assert.equal(b?.tone, "level", "tone <- severity field");
  assert.equal(b?.time, "eventTime", "time preserved");
});

test("workorder table stays a table and carries its columns as fields", () => {
  // 工单: table type + backend columns; must render as a real grid, not a
  // single-line alarm-stream (regression for blank work-order rows).
  const spec = adaptLegacyScreen({
    id: "s",
    name: "n",
    components: [
      {
        id: "wo",
        type: "table",
        title: "待办工单",
        capabilityId: "workorders",
        data: {
          sourceStatus: "live",
          columns: [
            { key: "workorderNo", label: "工单号" },
            { key: "title", label: "标题" },
            { key: "status", label: "状态" },
          ],
          rows: [{ workorderNo: "WO-1", title: "工单A", status: "处理中" }],
        },
      },
    ],
  });
  const c = spec.components[0];
  assert.equal(c.type, "table", "table stays first-class");
  // columns → fields so the TableWidget can render every column
  assert.deepEqual(
    c.data?.fields,
    [
      { key: "workorderNo", label: "工单号" },
      { key: "title", label: "标题" },
      { key: "status", label: "状态" },
    ],
    "columns surfaced as fields",
  );
  const row0 = c.data?.rows?.[0] as Record<string, unknown>;
  assert.equal(row0["status"], "处理中", "row cells preserved");
});

test("prefers the asset title over the legacy name for the screen heading", () => {
  const withTitle = adaptLegacyScreen({
    id: "s-title",
    title: "智观大屏",
    name: "internal-name",
    components: [],
  });
  assert.equal(withTitle.name, "智观大屏");

  const withoutTitle = adaptLegacyScreen({
    id: "s-name",
    name: "internal-name",
    components: [],
  });
  assert.equal(withoutTitle.name, "internal-name");

  const withNeither = adaptLegacyScreen({ id: "s-none", components: [] });
  assert.equal(withNeither.name, "");
});
