import { useEffect, useState } from "react";
import {
  buildLineOption,
  buildBarOption,
  buildAreaOption,
  buildDonutOption,
  buildGaugeOption,
  buildRadarOption,
  buildHeatmapOption,
  buildGraphOption,
  buildMapFlyOption,
} from "../charts/options.ts";
import { ensureChinaMap, isChinaMapReady } from "../charts/chinaGeo.ts";
import { EChart } from "../charts/EChart.tsx";
import type { WidgetProps } from "../registry.ts";
import type { CapabilityResult } from "../types.ts";

function buildOption(
  type: string,
  data: CapabilityResult,
  bindings?: Record<string, string>,
): Record<string, unknown> | null {
  switch (type) {
    case "line-chart":
      return buildLineOption(data, {
        x: bindings?.["x"],
        y: bindings?.["y"],
      });
    case "bar-chart":
      return buildBarOption(data, {
        x: bindings?.["x"],
        y: bindings?.["y"],
      });
    case "area-chart":
      return buildAreaOption(data, {
        x: bindings?.["x"],
        y: bindings?.["y"],
      });
    case "donut":
      return buildDonutOption(data, {
        name: bindings?.["name"],
        value: bindings?.["value"],
      });
    case "gauge":
      return buildGaugeOption(data, bindings?.["value"]);
    case "radar":
      return buildRadarOption(data);
    case "heatmap":
      return buildHeatmapOption(data, {
        x: bindings?.["x"],
        y: bindings?.["y"],
        value: bindings?.["value"],
      });
    case "graph": {
      // Support explicit links via bindings metadata stored in metrics
      const links = (data as Record<string, unknown>)["links"] as
        | Array<{ source: string; target: string }>
        | undefined;
      return buildGraphOption({ ...data, links });
    }
    default:
      return null;
  }
}

/**
 * ChartWidget — dispatches to the correct option builder and renders via EChart.
 * For "map-fly" it awaits ensureChinaMap() before rendering.
 */
export function ChartWidget({ component }: WidgetProps) {
  const { type } = component;
  const data: CapabilityResult = component.data ?? {
    capabilityId: "",
    sourceStatus: "empty",
  };
  const bindings = component.visualSpec?.bindings;

  const isMapFly = type === "map-fly";
  const [mapReady, setMapReady] = useState(isChinaMapReady);

  useEffect(() => {
    if (!isMapFly || mapReady) return;
    let cancelled = false;
    ensureChinaMap()
      .then(() => {
        if (!cancelled) setMapReady(true);
      })
      .catch(() => {
        // Map load failed — keep mapReady false; will show placeholder
      });
    return () => {
      cancelled = true;
    };
  }, [isMapFly, mapReady]);

  if (isMapFly) {
    if (!mapReady) {
      return (
        <div
          style={{
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#9fb2cc",
            fontSize: 12,
          }}
        >
          加载地图…
        </div>
      );
    }
    // Build map-fly option
    const nodes = data.nodes ?? [];
    // Edges: rows with {from,to} or explicit links in data
    const edges = (
      (data as Record<string, unknown>)["edges"] as
        | Array<{ from: string; to: string }>
        | undefined
    ) ??
      (data.rows as Array<{ from: string; to: string }> | undefined) ??
      [];
    const option = buildMapFlyOption(
      { nodes: nodes as Array<Record<string, unknown>> },
      edges,
    );
    return <EChart option={option} />;
  }

  const option = buildOption(type, data, bindings);

  if (!option) {
    return (
      <div
        style={{
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#9fb2cc",
          fontSize: 11,
          border: "1px dashed rgba(255,255,255,.2)",
          borderRadius: 8,
        }}
      >
        未知图表类型: {type}
      </div>
    );
  }

  return <EChart option={option} />;
}
