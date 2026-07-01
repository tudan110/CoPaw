/**
 * registerWidgets — import this file for its side effect only.
 *
 * Populates COMPONENT_REGISTRY by mutating the exported object from
 * registry.ts. This module is JSX-aware (can import .tsx widget files)
 * while registry.ts stays JSX-free and node:test-friendly.
 *
 * Usage: import "../widgets/registerWidgets.tsx" (or just .js at runtime)
 * in BigScreenRenderer.tsx before any registry lookup.
 *
 * Chart types (line-chart, bar-chart, area-chart, donut, gauge, radar,
 * heatmap, graph, map-fly) all map to ChartWidget.
 * text → TextWidget (simple fallback).
 * Non-chart widgets map to their dedicated components.
 */

import { COMPONENT_REGISTRY } from "../registry.ts";

// Non-chart widgets
import { FlipNumber } from "./FlipNumber.tsx";
import { MetricKpi } from "./MetricKpi.tsx";
import { LiquidBall } from "./LiquidBall.tsx";
import { AlarmStream } from "./AlarmStream.tsx";
import { TableWidget } from "./TableWidget.tsx";
import { TopNRank } from "./TopNRank.tsx";
import { RiskPulse } from "./RiskPulse.tsx";
import { Funnel } from "./Funnel.tsx";
import { Timeline } from "./Timeline.tsx";
import { Bar3D } from "./Bar3D.tsx";

// Chart widget (handles all echarts-based types)
import { ChartWidget } from "./ChartWidget.tsx";

// Simple text widget
import { TextWidget } from "./TextWidget.tsx";

// Generative blueprint interpreter
import { ComposedWidget } from "./ComposedWidget.tsx";

// ── Register non-chart widgets ─────────────────────────────────
COMPONENT_REGISTRY["flip-number"] = FlipNumber;
COMPONENT_REGISTRY["metric-kpi"] = MetricKpi;
COMPONENT_REGISTRY["liquid-ball"] = LiquidBall;
COMPONENT_REGISTRY["alarm-stream"] = AlarmStream;
COMPONENT_REGISTRY["table"] = TableWidget;
COMPONENT_REGISTRY["top-n"] = TopNRank;
COMPONENT_REGISTRY["risk-pulse"] = RiskPulse;
COMPONENT_REGISTRY["funnel"] = Funnel;
COMPONENT_REGISTRY["timeline"] = Timeline;
COMPONENT_REGISTRY["bar3d"] = Bar3D;

// ── Register chart types → ChartWidget ────────────────────────
const CHART_TYPES = [
  "line-chart",
  "bar-chart",
  "area-chart",
  "donut",
  "gauge",
  "radar",
  "heatmap",
  "graph",
  "map-fly",
] as const;

for (const t of CHART_TYPES) {
  COMPONENT_REGISTRY[t] = ChartWidget;
}

// ── Text / fallback ────────────────────────────────────────────
COMPONENT_REGISTRY["text"] = TextWidget;

// ── Generative composed widget (visualSpec.blueprint) ─────────
COMPONENT_REGISTRY["composed"] = ComposedWidget;
