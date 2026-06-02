import { useMemo } from "react";
import type {
  AiBigScreenApp,
  AiBigScreenComponent,
  AiBigScreenLayoutPosition,
} from "../../types/aiBigScreen";
import { DeferredEChartsBlock } from "../DeferredVisualizationBlocks";
import "./ai-big-screen-renderer.css";

interface AiBigScreenRendererProps {
  screen: AiBigScreenApp;
  selectedComponentId?: string;
  interactive?: boolean;
  onSelectComponent?: (componentId: string) => void;
}

function getGridStyle(position?: AiBigScreenLayoutPosition) {
  const x = Number(position?.x ?? 0);
  const y = Number(position?.y ?? 0);
  const w = Math.max(1, Math.min(12, Number(position?.w ?? 3)));
  const h = Math.max(1, Number(position?.h ?? 2));
  return {
    gridColumn: `${x + 1} / span ${w}`,
    gridRow: `${y + 1} / span ${h}`,
  };
}

function numberValue(value: unknown, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function numberArray(value: unknown): number[] {
  return Array.isArray(value)
    ? value.map((item) => numberValue(item)).filter((item) => Number.isFinite(item))
    : [];
}

function buildChartOption(component: AiBigScreenComponent) {
  const data = component.data || {};
  const rows = Array.isArray(data.rows) ? data.rows as Array<Record<string, unknown>> : [];
  const categories = stringArray(data.categories).length
    ? stringArray(data.categories)
    : rows.map((row) => String(row.name || row.title || row.eventTime || "--")).slice(0, 12);
  const series = numberArray(data.series).length
    ? numberArray(data.series)
    : rows.map((row) => numberValue(row.value ?? row.count ?? row.total)).slice(0, 12);
  const isBar = component.type === "bar-chart";
  const palette = String(component.visualConfig?.palette || "professional");
  const colorByPalette: Record<string, string> = {
    warm: "#f97316",
    cool: "#38bdf8",
    executive: "#f59e0b",
    industrial: "#22c55e",
    aurora: "#2dd4bf",
    mono: "#cbd5e1",
    professional: "#60a5fa",
  };
  const color = colorByPalette[palette] || colorByPalette.professional;

  return {
    backgroundColor: "transparent",
    color: [color],
    tooltip: { trigger: "axis" },
    grid: { top: 28, right: 18, bottom: 28, left: 42 },
    xAxis: {
      type: "category",
      data: categories,
      axisLine: { lineStyle: { color: "rgba(226, 232, 240, 0.36)" } },
      axisLabel: { color: "rgba(226, 232, 240, 0.72)" },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "rgba(226, 232, 240, 0.22)" } },
      splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.15)" } },
      axisLabel: { color: "rgba(226, 232, 240, 0.68)" },
    },
    series: [
      {
        type: isBar ? "bar" : "line",
        data: series,
        smooth: !isBar,
        barMaxWidth: 30,
        areaStyle: isBar ? undefined : { opacity: 0.18 },
      },
    ],
  };
}

function safeClassToken(value: unknown, fallback: string) {
  const token = String(value || fallback).toLowerCase().replace(/[^a-z0-9_-]/g, "");
  return token || fallback;
}

function renderMetric(component: AiBigScreenComponent) {
  const data = component.data || {};
  return (
    <div className="ai-big-screen-metric">
      <div className="ai-big-screen-metric-value">
        {String(data.value ?? "--")}
        <span>{String(data.unit || "")}</span>
      </div>
      <div className="ai-big-screen-metric-trend">
        {String(data.trend || data.message || "暂无趋势")}
      </div>
    </div>
  );
}

function getTableColumns(component: AiBigScreenComponent) {
  const columns = Array.isArray(component.data?.columns)
    ? component.data?.columns as Array<Record<string, unknown>>
    : [];
  if (columns.length) {
    return columns
      .map((column) => ({
        key: String(column.key || ""),
        label: String(column.label || column.key || ""),
      }))
      .filter((column) => column.key);
  }
  return [
    { key: "name", label: "事项" },
    { key: "count", label: "数量" },
    { key: "risk", label: "风险" },
  ];
}

function renderTable(component: AiBigScreenComponent) {
  const rows = Array.isArray(component.data?.rows) ? component.data?.rows as Array<Record<string, unknown>> : [];
  const columns = getTableColumns(component);
  return (
    <div className="ai-big-screen-table-wrap">
      <table className="ai-big-screen-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column.key}>{column.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${String(row.id || row.name || row.title || "row")}-${index}`}>
              {columns.map((column) => (
                <td key={column.key}>{String(row[column.key] ?? "--")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length ? (
        <div className="ai-big-screen-empty-data">
          {String(component.data?.message || "当前窗口暂无数据")}
        </div>
      ) : null}
    </div>
  );
}

function renderTopology(component: AiBigScreenComponent) {
  const nodes = Array.isArray(component.data?.nodes) ? component.data?.nodes as Array<Record<string, unknown>> : [];
  return (
    <div className="ai-big-screen-topology">
      {nodes.map((node, index) => (
        <div key={`${String(node.name || "node")}-${index}`} className="ai-big-screen-topology-node">
          <span className={`ai-big-screen-node-dot status-${String(node.status || "normal")}`} />
          <span>{String(node.name || "--")}</span>
        </div>
      ))}
    </div>
  );
}

function renderComponentBody(component: AiBigScreenComponent) {
  if (component.type === "metric-card") {
    return renderMetric(component);
  }
  if (component.type === "line-chart" || component.type === "bar-chart") {
    return (
      <DeferredEChartsBlock
        chart={JSON.stringify(buildChartOption(component))}
        style={{ height: "100%", minHeight: 180 }}
        fallbackMinHeight={180}
      />
    );
  }
  if (component.type === "table") {
    return renderTable(component);
  }
  if (component.type === "topology") {
    return renderTopology(component);
  }
  return <div className="ai-big-screen-text">{String(component.description || "")}</div>;
}

function getSourceStatusLabel(component: AiBigScreenComponent) {
  const status = String(component.data?.sourceStatus || "");
  if (status === "live") {
    return "实时";
  }
  if (status === "empty") {
    return "暂无";
  }
  if (status === "unavailable") {
    return "未接入";
  }
  return "数据";
}

export function AiBigScreenRenderer({
  screen,
  selectedComponentId = "",
  interactive = false,
  onSelectComponent,
}: AiBigScreenRendererProps) {
  const themePalette = safeClassToken(screen.theme?.palette, "professional");
  const sortedComponents = useMemo(
    () => [...(screen.components || [])].sort((left, right) => {
      const leftPosition = left.layoutPosition || {};
      const rightPosition = right.layoutPosition || {};
      return Number(leftPosition.y || 0) - Number(rightPosition.y || 0)
        || Number(leftPosition.x || 0) - Number(rightPosition.x || 0);
    }),
    [screen.components],
  );

  return (
    <section className={`ai-big-screen-shell theme-${themePalette}`}>
      <header className="ai-big-screen-header">
        <div>
          <p>AI Big Screen</p>
          <h1>{screen.name}</h1>
        </div>
        <div className="ai-big-screen-status">
          <span>{screen.status === "published" ? "已发布" : "草稿"}</span>
          <small>{screen.updatedAt ? new Date(screen.updatedAt).toLocaleString() : "未保存"}</small>
        </div>
      </header>

      <div className="ai-big-screen-canvas">
        {sortedComponents.map((component) => {
          const selected = component.id === selectedComponentId;
          const componentPalette = safeClassToken(component.visualConfig?.palette, "professional");
          const componentEmphasis = safeClassToken(component.visualConfig?.emphasis, "standard");
          const sourceStatus = safeClassToken(component.data?.sourceStatus, "unknown");
          return (
            <article
              key={component.id}
              className={[
                "ai-big-screen-card",
                `palette-${componentPalette}`,
                `emphasis-${componentEmphasis}`,
                selected ? "selected" : "",
                interactive ? "interactive" : "",
              ].filter(Boolean).join(" ")}
              style={getGridStyle(component.layoutPosition)}
              role={interactive ? "button" : undefined}
              tabIndex={interactive ? 0 : undefined}
              onClick={() => interactive && onSelectComponent?.(component.id)}
              onKeyDown={(event) => {
                if (!interactive) {
                  return;
                }
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectComponent?.(component.id);
                }
              }}
            >
              <div className="ai-big-screen-card-head">
                <div>
                  <h2>{component.title}</h2>
                  <p>{component.description}</p>
                </div>
                <span className={`ai-big-screen-source-badge status-${sourceStatus}`}>
                  {getSourceStatusLabel(component)}
                </span>
              </div>
              <div className="ai-big-screen-card-body">
                {renderComponentBody(component)}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default AiBigScreenRenderer;
