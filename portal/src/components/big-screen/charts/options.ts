/**
 * Pure chart option builders — no echarts import, no function literals.
 * These return plain serializable objects safe to JSON.stringify.
 *
 * Every builder takes an optional resolved `style` (see chartStyle.ts) so a
 * component's controlled visualSpec.style (palette / accent / brightness /
 * line-opacity / node-size) actually reaches echarts. When omitted, builders
 * fall back to DEFAULT_CHART_STYLE — identical to the previous hardcoded look.
 */
import {
  DEFAULT_CHART_STYLE,
  withAlpha,
  type ResolvedChartStyle,
} from "./chartStyle.ts";

const DARK_BG = "transparent";
const SPLIT_LINE_COLOR = "rgba(255,255,255,.08)";

function darkGrid() {
  return { containLabel: true, left: 16, right: 16, top: 16, bottom: 16 };
}

function darkXAxis(data: unknown[], labelColor: string) {
  return {
    type: "category",
    data,
    axisLine: { lineStyle: { color: "rgba(255,255,255,.18)" } },
    axisLabel: { color: labelColor },
    splitLine: { show: false },
  };
}

function darkYAxis(labelColor: string) {
  return {
    type: "value",
    axisLabel: { color: labelColor },
    splitLine: { lineStyle: { color: SPLIT_LINE_COLOR } },
  };
}

// ---------- buildLineOption ----------

export function buildLineOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { x?: string; y?: string },
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const xKey = bindings?.x ?? "x";
  const yKey = bindings?.y ?? "y";
  const xData = rows.map((r) => r[xKey]);
  const yData = rows.map((r) => r[yKey]);
  return {
    backgroundColor: DARK_BG,
    color: style.palette,
    grid: darkGrid(),
    xAxis: darkXAxis(xData, style.labelColor),
    yAxis: darkYAxis(style.labelColor),
    series: [
      {
        type: "line",
        data: yData,
        smooth: true,
        lineStyle: { color: style.primary, width: 2 },
        itemStyle: { color: style.primary },
        areaStyle: { color: withAlpha(style.primary, style.lineOpacity ?? 0.12) },
      },
    ],
  };
}

// ---------- buildBarOption ----------

export function buildBarOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { x?: string; y?: string },
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const xKey = bindings?.x ?? "x";
  const yKey = bindings?.y ?? "y";
  const xData = rows.map((r) => r[xKey]);
  const yData = rows.map((r) => r[yKey]);
  return {
    backgroundColor: DARK_BG,
    color: style.palette,
    grid: darkGrid(),
    xAxis: darkXAxis(xData, style.labelColor),
    yAxis: darkYAxis(style.labelColor),
    series: [
      {
        type: "bar",
        data: yData,
        itemStyle: { color: style.primary, borderRadius: [3, 3, 0, 0] },
      },
    ],
  };
}

// ---------- buildAreaOption ----------

export function buildAreaOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { x?: string; y?: string },
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const xKey = bindings?.x ?? "x";
  const yKey = bindings?.y ?? "y";
  const xData = rows.map((r) => r[xKey]);
  const yData = rows.map((r) => r[yKey]);
  return {
    backgroundColor: DARK_BG,
    color: style.palette,
    grid: darkGrid(),
    xAxis: darkXAxis(xData, style.labelColor),
    yAxis: darkYAxis(style.labelColor),
    series: [
      {
        type: "line",
        data: yData,
        smooth: true,
        areaStyle: { color: withAlpha(style.primary, style.lineOpacity ?? 0.18) },
        lineStyle: { color: style.primary, width: 2 },
        itemStyle: { color: style.primary },
      },
    ],
  };
}

// ---------- buildDonutOption ----------

export function buildDonutOption(
  data: { rows?: Array<Record<string, unknown>> },
  bindings?: { name?: string; value?: string },
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
): Record<string, unknown> {
  const rows = data.rows ?? [];
  const nameKey = bindings?.name ?? "name";
  const valueKey = bindings?.value ?? "value";
  const seriesData = rows.map((r) => ({ name: r[nameKey], value: r[valueKey] }));
  return {
    backgroundColor: DARK_BG,
    color: style.palette,
    legend: {
      orient: "vertical",
      right: 10,
      textStyle: { color: style.labelColor },
    },
    series: [
      {
        type: "pie",
        radius: ["55%", "75%"],
        center: ["45%", "50%"],
        data: seriesData,
        label: { color: style.labelColor },
        emphasis: { label: { show: true } },
      },
    ],
  };
}

// ---------- buildGaugeOption ----------

export function buildGaugeOption(
  data: { metrics?: Record<string, unknown> },
  key?: string,
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
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
        axisLine: {
          lineStyle: {
            width: 12,
            color: [
              [val / 100, style.primary],
              [1, "rgba(255,255,255,.1)"],
            ],
          },
        },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: style.labelColor },
        pointer: { itemStyle: { color: style.primary } },
        detail: { color: "#e2eaf4", fontSize: 28 },
        title: { color: style.labelColor },
      },
    ],
  };
}

// ---------- buildRadarOption ----------

export function buildRadarOption(
  data: { metrics?: Record<string, unknown> },
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
): Record<string, unknown> {
  const metrics = data.metrics ?? {};
  const keys = Object.keys(metrics);
  const values = keys.map((k) => Number(metrics[k] ?? 0));
  const maxVal = Math.max(...values, 100);
  const indicators = keys.map((k) => ({ name: k, max: maxVal }));
  return {
    backgroundColor: DARK_BG,
    color: style.palette,
    radar: {
      indicator: indicators,
      shape: "polygon",
      axisName: { color: style.labelColor },
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
            areaStyle: {
              color: withAlpha(style.primary, style.lineOpacity ?? 0.15),
            },
            lineStyle: { color: style.primary },
            itemStyle: { color: style.primary },
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
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
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
    xAxis: { type: "category", data: xVals, axisLabel: { color: style.labelColor } },
    yAxis: { type: "category", data: yVals, axisLabel: { color: style.labelColor } },
    visualMap: {
      min: 0,
      max: 100,
      inRange: { color: [withAlpha(style.primary, 0.1), style.primary] },
      textStyle: { color: style.labelColor },
    },
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
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
): Record<string, unknown> {
  const palette = style.palette;
  const nodes = (data.nodes ?? data.rows ?? []).map((n, i) => ({
    id: String(n["id"] ?? i),
    name: String(n["name"] ?? n["id"] ?? i),
    symbolSize: Number(n["size"] ?? 20) * style.nodeSizeScale,
    itemStyle: { color: palette[i % palette.length] },
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
  // Raise the link-opacity floor from .2 → .35 so topologies are legible by
  // default; an explicit lineOpacity (e.g. from "变亮一点") overrides it.
  const linkAlpha = style.lineOpacity ?? 0.35;
  return {
    backgroundColor: DARK_BG,
    color: palette,
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        nodes,
        links: edges,
        lineStyle: { color: `rgba(255,255,255,${linkAlpha})`, width: 1 },
        label: { show: true, color: style.labelColor },
        force: { repulsion: 120 },
      },
    ],
  };
}

// ---------- buildMapFlyOption ----------

export function buildMapFlyOption(
  data: { nodes?: Array<Record<string, unknown>> },
  edges?: Array<{ from: string; to: string }>,
  style: ResolvedChartStyle = DEFAULT_CHART_STYLE,
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
        itemStyle: { color: style.primary },
        rippleEffect: { brushType: "stroke", period: 3 },
        label: { show: true, color: "#e2eaf4", fontSize: 11, position: "right" },
      },
      {
        type: "lines",
        coordinateSystem: "geo",
        data: linesData,
        lineStyle: {
          color: style.primary,
          width: 1,
          opacity: style.lineOpacity ?? 0.6,
          curveness: 0.2,
        },
        effect: {
          show: true,
          period: 4,
          trailLength: 0.1,
          symbol: "arrow",
          symbolSize: 6,
          color: style.secondary,
        },
      },
    ],
  };
}
