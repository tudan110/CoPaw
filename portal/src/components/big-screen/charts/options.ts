/**
 * Pure chart option builders — no echarts import, no function literals.
 * These return plain serializable objects safe to JSON.stringify.
 */

const BS_PALETTE = ["#22d3ee", "#34d399", "#a78bfa", "#fb923c", "#f87171"];

const DARK_BG = "transparent";
const AXIS_LABEL_COLOR = "#9fb2cc";
const SPLIT_LINE_COLOR = "rgba(255,255,255,.08)";

function darkGrid() {
  return { containLabel: true, left: 16, right: 16, top: 16, bottom: 16 };
}

function darkXAxis(data: unknown[]) {
  return {
    type: "category",
    data,
    axisLine: { lineStyle: { color: "rgba(255,255,255,.18)" } },
    axisLabel: { color: AXIS_LABEL_COLOR },
    splitLine: { show: false },
  };
}

function darkYAxis() {
  return {
    type: "value",
    axisLabel: { color: AXIS_LABEL_COLOR },
    splitLine: { lineStyle: { color: SPLIT_LINE_COLOR } },
  };
}

// ---------- buildLineOption ----------

export function buildLineOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { x?: string; y?: string },
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const xKey = bindings?.x ?? "x";
  const yKey = bindings?.y ?? "y";
  const xData = rows.map((r) => r[xKey]);
  const yData = rows.map((r) => r[yKey]);
  return {
    backgroundColor: DARK_BG,
    color: BS_PALETTE,
    grid: darkGrid(),
    xAxis: darkXAxis(xData),
    yAxis: darkYAxis(),
    series: [
      {
        type: "line",
        data: yData,
        smooth: true,
        lineStyle: { color: BS_PALETTE[0], width: 2 },
        itemStyle: { color: BS_PALETTE[0] },
        areaStyle: { color: "rgba(34,211,238,.12)" },
      },
    ],
  };
}

// ---------- buildBarOption ----------

export function buildBarOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { x?: string; y?: string },
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const xKey = bindings?.x ?? "x";
  const yKey = bindings?.y ?? "y";
  const xData = rows.map((r) => r[xKey]);
  const yData = rows.map((r) => r[yKey]);
  return {
    backgroundColor: DARK_BG,
    color: BS_PALETTE,
    grid: darkGrid(),
    xAxis: darkXAxis(xData),
    yAxis: darkYAxis(),
    series: [
      {
        type: "bar",
        data: yData,
        itemStyle: { color: BS_PALETTE[0], borderRadius: [3, 3, 0, 0] },
      },
    ],
  };
}

// ---------- buildAreaOption ----------

export function buildAreaOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { x?: string; y?: string },
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const xKey = bindings?.x ?? "x";
  const yKey = bindings?.y ?? "y";
  const xData = rows.map((r) => r[xKey]);
  const yData = rows.map((r) => r[yKey]);
  return {
    backgroundColor: DARK_BG,
    color: BS_PALETTE,
    grid: darkGrid(),
    xAxis: darkXAxis(xData),
    yAxis: darkYAxis(),
    series: [
      {
        type: "line",
        data: yData,
        smooth: true,
        areaStyle: { color: "rgba(34,211,238,.18)" },
        lineStyle: { color: BS_PALETTE[0], width: 2 },
        itemStyle: { color: BS_PALETTE[0] },
      },
    ],
  };
}

// ---------- buildDonutOption ----------

export function buildDonutOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { name?: string; value?: string },
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const nameKey = bindings?.name ?? "name";
  const valueKey = bindings?.value ?? "value";
  const seriesData = rows.map((r) => ({ name: r[nameKey], value: r[valueKey] }));
  return {
    backgroundColor: DARK_BG,
    color: BS_PALETTE,
    legend: { orient: "vertical", right: 10, textStyle: { color: AXIS_LABEL_COLOR } },
    series: [
      {
        type: "pie",
        radius: ["55%", "75%"],
        center: ["45%", "50%"],
        data: seriesData,
        label: { color: AXIS_LABEL_COLOR },
        emphasis: { label: { show: true } },
      },
    ],
  };
}

// ---------- buildGaugeOption ----------

export function buildGaugeOption(
  data: { metrics?: Record<string, unknown> },
  key?: string,
): Record<string, unknown> {
  const metrics = data.metrics ?? {};
  const k = key ?? Object.keys(metrics)[0] ?? "value";
  const val = Number(metrics[k] ?? 0);
  return {
    backgroundColor: DARK_BG,
    series: [
      {
        type: "gauge",
        startAngle: 220,
        endAngle: -40,
        min: 0,
        max: 100,
        data: [{ value: val, name: k }],
        axisLine: { lineStyle: { width: 12, color: [[val / 100, BS_PALETTE[0]], [1, "rgba(255,255,255,.1)"]] } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: AXIS_LABEL_COLOR },
        pointer: { itemStyle: { color: BS_PALETTE[0] } },
        detail: { color: "#e2eaf4", fontSize: 28 },
        title: { color: AXIS_LABEL_COLOR },
      },
    ],
  };
}

// ---------- buildRadarOption ----------

export function buildRadarOption(
  data: { metrics?: Record<string, unknown> },
): Record<string, unknown> {
  const metrics = data.metrics ?? {};
  const keys = Object.keys(metrics);
  const values = keys.map((k) => Number(metrics[k] ?? 0));
  const maxVal = Math.max(...values, 100);
  const indicators = keys.map((k) => ({ name: k, max: maxVal }));
  return {
    backgroundColor: DARK_BG,
    color: BS_PALETTE,
    radar: {
      indicator: indicators,
      shape: "polygon",
      axisName: { color: AXIS_LABEL_COLOR },
      splitLine: { lineStyle: { color: SPLIT_LINE_COLOR } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: "rgba(255,255,255,.15)" } },
    },
    series: [
      {
        type: "radar",
        data: [
          {
            value: values,
            areaStyle: { color: "rgba(34,211,238,.15)" },
            lineStyle: { color: BS_PALETTE[0] },
            itemStyle: { color: BS_PALETTE[0] },
          },
        ],
      },
    ],
  };
}

// ---------- buildHeatmapOption ----------

export function buildHeatmapOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { x?: string; y?: string; value?: string },
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const xKey = bindings?.x ?? "x";
  const yKey = bindings?.y ?? "y";
  const vKey = bindings?.value ?? "value";
  const xVals = Array.from(new Set(rows.map((r) => String(r[xKey] ?? ""))));
  const yVals = Array.from(new Set(rows.map((r) => String(r[yKey] ?? ""))));
  const seriesData = rows.map((r) => [
    xVals.indexOf(String(r[xKey] ?? "")),
    yVals.indexOf(String(r[yKey] ?? "")),
    r[vKey],
  ]);
  return {
    backgroundColor: DARK_BG,
    grid: darkGrid(),
    xAxis: { type: "category", data: xVals, axisLabel: { color: AXIS_LABEL_COLOR } },
    yAxis: { type: "category", data: yVals, axisLabel: { color: AXIS_LABEL_COLOR } },
    visualMap: { min: 0, max: 100, inRange: { color: ["rgba(34,211,238,.1)", "#22d3ee"] }, textStyle: { color: AXIS_LABEL_COLOR } },
    series: [{ type: "heatmap", data: seriesData, emphasis: { itemStyle: { shadowBlur: 10 } } }],
  };
}

// ---------- buildGraphOption ----------

export function buildGraphOption(
  data: {
    nodes?: Array<Record<string, unknown>>;
    rows?: Array<Record<string, unknown>>;
    links?: Array<{ source: string; target: string }>;
  },
): Record<string, unknown> {
  const nodes = (data.nodes ?? data.rows ?? []).map((n, i) => ({
    id: String(n["id"] ?? i),
    name: String(n["name"] ?? n["id"] ?? i),
    symbolSize: Number(n["size"] ?? 20),
    itemStyle: { color: BS_PALETTE[i % BS_PALETTE.length] },
  }));
  // Prefer explicit links; fall back to rows with source/target fields (backward-compatible)
  const edges =
    data.links ??
    (data.rows ?? [])
      .filter((r) => r["source"] !== undefined && r["target"] !== undefined)
      .map((r) => ({
        source: String(r["source"]),
        target: String(r["target"]),
      }));
  return {
    backgroundColor: DARK_BG,
    color: BS_PALETTE,
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        nodes,
        links: edges,
        lineStyle: { color: "rgba(255,255,255,.2)", width: 1 },
        label: { show: true, color: AXIS_LABEL_COLOR },
        force: { repulsion: 120 },
      },
    ],
  };
}

// ---------- buildMapFlyOption ----------

export function buildMapFlyOption(
  data: { nodes?: Array<Record<string, unknown>> },
  edges?: Array<{ from: string; to: string }>,
): Record<string, unknown> {
  const nodes = data.nodes ?? [];

  // Build a name->coord lookup
  const coordMap: Record<string, unknown[]> = {};
  for (const n of nodes) {
    const name = String(n["name"] ?? "");
    const coord = n["coord"];
    if (name && Array.isArray(coord)) coordMap[name] = coord as unknown[];
  }

  const effectScatterData = nodes.map((n) => ({
    name: String(n["name"] ?? ""),
    value: n["coord"],
  }));

  const linesData = (edges ?? [])
    .filter((e) => coordMap[e.from] && coordMap[e.to])
    .map((e) => ({
      coords: [coordMap[e.from], coordMap[e.to]],
    }));

  return {
    backgroundColor: "transparent",
    geo: {
      map: "china",
      roam: false,
      itemStyle: {
        areaColor: "rgba(56,189,248,.06)",
        borderColor: "rgba(56,189,248,.25)",
        borderWidth: 1,
      },
      emphasis: {
        itemStyle: { areaColor: "rgba(56,189,248,.18)" },
      },
    },
    series: [
      {
        type: "effectScatter",
        coordinateSystem: "geo",
        data: effectScatterData,
        symbolSize: 8,
        itemStyle: { color: BS_PALETTE[0] },
        rippleEffect: { brushType: "stroke", period: 3 },
        label: { show: true, color: "#e2eaf4", fontSize: 11, position: "right" },
      },
      {
        type: "lines",
        coordinateSystem: "geo",
        data: linesData,
        lineStyle: { color: BS_PALETTE[0], width: 1, opacity: 0.6, curveness: 0.2 },
        effect: {
          show: true,
          period: 4,
          trailLength: 0.1,
          symbol: "arrow",
          symbolSize: 6,
          color: BS_PALETTE[1],
        },
      },
    ],
  };
}
