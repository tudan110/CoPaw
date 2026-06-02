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
  const categories = stringArray(data.categories);
  const series = numberArray(data.series);
  const isBar = component.type === "bar-chart";
  const palette = String(component.visualConfig?.palette || "professional");
  const color = palette === "warm" ? "#f97316" : palette === "cool" ? "#38bdf8" : "#60a5fa";

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

function renderMetric(component: AiBigScreenComponent) {
  const data = component.data || {};
  return (
    <div className="ai-big-screen-metric">
      <div className="ai-big-screen-metric-value">
        {String(data.value ?? "--")}
        <span>{String(data.unit || "")}</span>
      </div>
      <div className="ai-big-screen-metric-trend">{String(data.trend || "暂无趋势")}</div>
    </div>
  );
}

function renderTable(component: AiBigScreenComponent) {
  const rows = Array.isArray(component.data?.rows) ? component.data?.rows as Array<Record<string, unknown>> : [];
  return (
    <table className="ai-big-screen-table">
      <thead>
        <tr>
          <th>事项</th>
          <th>数量</th>
          <th>风险</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${String(row.name || "row")}-${index}`}>
            <td>{String(row.name || "--")}</td>
            <td>{String(row.count ?? "--")}</td>
            <td>{String(row.risk || "--")}</td>
          </tr>
        ))}
      </tbody>
    </table>
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

export function AiBigScreenRenderer({
  screen,
  selectedComponentId = "",
  interactive = false,
  onSelectComponent,
}: AiBigScreenRendererProps) {
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
    <section className="ai-big-screen-shell">
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
          return (
            <article
              key={component.id}
              className={[
                "ai-big-screen-card",
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
                <span>{component.pluginId || "custom"}</span>
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
