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

type PackedComponent = {
  component: AiBigScreenComponent;
  layoutPosition: Required<AiBigScreenLayoutPosition>;
};

type DisplayColumn = {
  key: string;
  label: string;
};

function getGridStyle(position: Required<AiBigScreenLayoutPosition>) {
  return {
    gridColumn: `${position.x + 1} / span ${position.w}`,
    gridRow: `${position.y + 1} / span ${position.h}`,
  };
}

function numberValue(value: unknown, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function gridNumber(value: unknown, fallback: number) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.floor(number) : fallback;
}

function getMinimumGridHeight(component: AiBigScreenComponent) {
  if (component.type === "metric-card") {
    return 3;
  }
  if (
    component.type === "line-chart"
    || component.type === "bar-chart"
    || component.type === "table"
    || component.type === "topology"
    || component.type === "risk-pulse"
    || component.type === "status-stream"
  ) {
    return 4;
  }
  return 2;
}

function normalizeLayoutPosition(
  component: AiBigScreenComponent,
  index: number,
): Required<AiBigScreenLayoutPosition> {
  const raw = component.layoutPosition || {};
  const fallbackW = component.type === "metric-card" ? 4 : 6;
  const fallbackX = index % 2 ? 6 : 0;
  const fallbackY = Math.floor(index / 2) * 4;
  const x = Math.max(0, Math.min(11, gridNumber(raw.x, fallbackX)));
  const w = Math.max(1, Math.min(12 - x, gridNumber(raw.w, fallbackW)));
  const minH = getMinimumGridHeight(component);
  const h = Math.max(minH, Math.min(8, gridNumber(raw.h, minH)));
  const y = Math.max(0, gridNumber(raw.y, fallbackY));
  return { x, y, w, h };
}

function canPlace(occupied: Set<string>, position: Required<AiBigScreenLayoutPosition>) {
  for (let row = position.y; row < position.y + position.h; row += 1) {
    for (let column = position.x; column < position.x + position.w; column += 1) {
      if (occupied.has(`${column}:${row}`)) {
        return false;
      }
    }
  }
  return true;
}

function markPosition(occupied: Set<string>, position: Required<AiBigScreenLayoutPosition>) {
  for (let row = position.y; row < position.y + position.h; row += 1) {
    for (let column = position.x; column < position.x + position.w; column += 1) {
      occupied.add(`${column}:${row}`);
    }
  }
}

function findOpenPosition(
  occupied: Set<string>,
  desired: Required<AiBigScreenLayoutPosition>,
): Required<AiBigScreenLayoutPosition> {
  const maxX = 12 - desired.w;
  const preferredColumns = [
    desired.x,
    ...Array.from({ length: maxX + 1 }, (_, index) => index).filter((x) => x !== desired.x),
  ];
  let y = desired.y;
  while (true) {
    for (const x of preferredColumns) {
      const candidate = { ...desired, x, y };
      if (canPlace(occupied, candidate)) {
        return candidate;
      }
    }
    y += 1;
  }
}

function packComponents(components: AiBigScreenComponent[]): PackedComponent[] {
  const occupied = new Set<string>();
  return [...components]
    .sort((left, right) => {
      const leftPosition = left.layoutPosition || {};
      const rightPosition = right.layoutPosition || {};
      return Number(leftPosition.y || 0) - Number(rightPosition.y || 0)
        || Number(leftPosition.x || 0) - Number(rightPosition.x || 0);
    })
    .map((component, index) => {
      const desiredPosition = normalizeLayoutPosition(component, index);
      const layoutPosition = findOpenPosition(occupied, desiredPosition);
      markPosition(occupied, layoutPosition);
      return { component, layoutPosition };
    });
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
  const columns = getExplicitDataColumns(component);
  if (columns.length) {
    return columns;
  }
  return [
    { key: "name", label: "事项" },
    { key: "count", label: "数量" },
    { key: "risk", label: "风险" },
  ];
}

function getExplicitDataColumns(component: AiBigScreenComponent): DisplayColumn[] {
  const columns = Array.isArray(component.data?.columns)
    ? component.data?.columns as Array<Record<string, unknown>>
    : [];
  return columns
    .map((column) => ({
      key: String(column.key || ""),
      label: String(column.label || column.key || ""),
    }))
    .filter((column) => column.key);
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

function riskRows(component: AiBigScreenComponent) {
  const riskItems = Array.isArray(component.data?.riskItems)
    ? component.data?.riskItems as Array<Record<string, unknown>>
    : [];
  if (riskItems.length) {
    return riskItems;
  }
  return Array.isArray(component.data?.rows) ? component.data?.rows as Array<Record<string, unknown>> : [];
}

function getVisualSpec(component: AiBigScreenComponent) {
  return component.visualSpec && typeof component.visualSpec === "object"
    ? component.visualSpec as Record<string, unknown>
    : {};
}

function getVisualBindings(component: AiBigScreenComponent) {
  const bindings = getVisualSpec(component).bindings;
  return bindings && typeof bindings === "object" ? bindings as Record<string, unknown> : {};
}

function bindingField(component: AiBigScreenComponent, key: string, fallback: string) {
  const value = getVisualBindings(component)[key];
  return String(value || fallback);
}

function rowText(row: Record<string, unknown>, field: string, fallback = "--") {
  return String(row[field] ?? fallback);
}

function rowNumber(row: Record<string, unknown>, field: string, fallback = 0) {
  return numberValue(row[field], fallback);
}

function riskLevelClass(row: Record<string, unknown>) {
  const explicit = String(row.riskLevel || "").toLowerCase();
  if (explicit) {
    return safeClassToken(explicit, "medium");
  }
  const score = numberValue(row.riskScore, 0);
  if (score >= 88) {
    return "critical";
  }
  if (score >= 72) {
    return "high";
  }
  return "medium";
}

function renderRiskPulse(component: AiBigScreenComponent) {
  const rows = riskRows(component).slice(0, 5);
  const valueField = bindingField(component, "value", "riskScore");
  const messageField = bindingField(component, "message", "message");
  const titleField = bindingField(component, "title", "riskReason");
  const score = numberValue(component.data?.riskScore ?? component.data?.value, 0);
  const scoreLabel = score > 0 ? String(Math.round(score)) : "--";
  return (
    <div className="ai-big-screen-risk-pulse">
      <div className="ai-big-screen-risk-score">
        <div className="ai-big-screen-risk-rings" aria-hidden="true">
          <span />
          <span />
          <strong>{scoreLabel}</strong>
        </div>
        <div>
          <span>Risk Pulse</span>
          <p>{String(component.data?.summary || component.data?.trend || "等待风险信号")}</p>
        </div>
      </div>
      <div className="ai-big-screen-risk-list">
        {rows.map((row, index) => (
          <div
            key={`${String(row.time || row.message || "risk")}-${index}`}
            className={`ai-big-screen-risk-item level-${riskLevelClass(row)}`}
            style={{ animationDelay: `${index * 0.12}s` }}
          >
              <i aria-hidden="true" />
              <div>
              <strong>{rowText(row, titleField, String(row.level || "风险日志"))}</strong>
              <span>{rowText(row, messageField, String(row.content || row.title || "--"))}</span>
            </div>
            <em>{String(row[valueField] ?? row.riskScore ?? "")}</em>
          </div>
        ))}
        {!rows.length ? (
          <div className="ai-big-screen-empty-data">
            {String(component.data?.message || "未识别到高危日志")}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function renderStatusStream(component: AiBigScreenComponent) {
  const rows = Array.isArray(component.data?.rows) ? component.data?.rows as Array<Record<string, unknown>> : [];
  const titleField = bindingField(component, "title", "title");
  const timeField = bindingField(component, "time", "eventTime");
  const severityField = bindingField(component, "severity", "level");
  const messageField = bindingField(component, "message", "visibleContent");
  const primaryFields = new Set([titleField, timeField, severityField, messageField, "visibleContent"]);
  const detailColumns = getExplicitDataColumns(component)
    .filter((column) => !primaryFields.has(column.key))
    .slice(0, 6);
  return (
    <div className="ai-big-screen-status-stream">
      {rows.slice(0, 8).map((row, index) => {
        const details = detailColumns
          .map((column) => ({
            ...column,
            value: rowText(row, column.key, ""),
          }))
          .filter((item) => item.value);
        return (
          <div
            key={`${String(row.id || row.title || row.name || "stream")}-${index}`}
            className={`ai-big-screen-stream-row level-${safeClassToken(row[severityField] || row.status, "normal")}`}
            style={{ animationDelay: `${index * 0.1}s` }}
          >
            <span aria-hidden="true" />
            <div>
              <strong>{rowText(row, titleField, String(row.name || row.message || "--"))}</strong>
              <small>{rowText(row, timeField, String(row[messageField] || row.deviceName || row.status || ""))}</small>
              {details.length ? (
                <dl className="ai-big-screen-stream-fields">
                  {details.map((detail) => (
                    <div key={detail.key}>
                      <dt>{detail.label}</dt>
                      <dd>{detail.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </div>
          </div>
        );
      })}
      {!rows.length ? (
        <div className="ai-big-screen-empty-data">
          {String(component.data?.message || "当前暂无流式数据")}
        </div>
      ) : null}
    </div>
  );
}

function renderSpecTimeline(component: AiBigScreenComponent) {
  const rows = riskRows(component).slice(0, 7);
  const timeField = bindingField(component, "time", "time");
  const titleField = bindingField(component, "title", "title");
  const messageField = bindingField(component, "message", "message");
  const severityField = bindingField(component, "severity", "riskLevel");
  return (
    <div className="ai-big-screen-spec-timeline">
      {rows.map((row, index) => (
        <div
          key={`${rowText(row, timeField, "time")}-${index}`}
          className={`ai-big-screen-timeline-row level-${safeClassToken(row[severityField], "normal")}`}
        >
          <span>{rowText(row, timeField, "--")}</span>
          <i aria-hidden="true" />
          <div>
            <strong>{rowText(row, titleField, String(row.riskReason || row.level || "事件"))}</strong>
            <small>{rowText(row, messageField, "--")}</small>
          </div>
        </div>
      ))}
      {!rows.length ? <div className="ai-big-screen-empty-data">暂无时间线数据</div> : null}
    </div>
  );
}

function renderSpecMatrix(component: AiBigScreenComponent) {
  const rows = riskRows(component).slice(0, 18);
  const titleField = bindingField(component, "title", "title");
  const valueField = bindingField(component, "value", "value");
  const severityField = bindingField(component, "severity", "riskLevel");
  return (
    <div className="ai-big-screen-spec-matrix">
      {rows.map((row, index) => (
        <div
          key={`${rowText(row, titleField, "cell")}-${index}`}
          className={`ai-big-screen-matrix-cell level-${safeClassToken(row[severityField], "normal")}`}
          style={{ animationDelay: `${index * 0.045}s` }}
        >
          <strong>{String(Math.round(rowNumber(row, valueField, numberValue(row.riskScore))))}</strong>
          <span>{rowText(row, titleField, String(row.message || row.name || "--"))}</span>
        </div>
      ))}
      {!rows.length ? <div className="ai-big-screen-empty-data">暂无矩阵数据</div> : null}
    </div>
  );
}

function renderSpecMetricCluster(component: AiBigScreenComponent) {
  const rows = riskRows(component).slice(0, 6);
  const titleField = bindingField(component, "title", "name");
  const valueField = bindingField(component, "value", "value");
  return (
    <div className="ai-big-screen-spec-metrics">
      {rows.map((row, index) => (
        <div key={`${rowText(row, titleField, "metric")}-${index}`} className="ai-big-screen-spec-metric">
          <strong>{String(row[valueField] ?? row.count ?? row.total ?? "--")}</strong>
          <span>{rowText(row, titleField, String(row.title || row.message || "--"))}</span>
        </div>
      ))}
      {!rows.length ? (
        <>
          <div className="ai-big-screen-spec-metric">
            <strong>{String(component.data?.value ?? component.data?.riskScore ?? "--")}</strong>
            <span>{String(component.data?.trend || component.data?.summary || "核心指标")}</span>
          </div>
        </>
      ) : null}
    </div>
  );
}

function renderVisualSpec(component: AiBigScreenComponent) {
  const kind = String(getVisualSpec(component).kind || "");
  if (kind === "risk-field") {
    return renderRiskPulse(component);
  }
  if (kind === "signal-stream") {
    return renderStatusStream(component);
  }
  if (kind === "timeline") {
    return renderSpecTimeline(component);
  }
  if (kind === "heatmap-matrix") {
    return renderSpecMatrix(component);
  }
  if (kind === "metric-cluster") {
    return renderSpecMetricCluster(component);
  }
  return null;
}

function renderComponentBody(component: AiBigScreenComponent) {
  const visualSpecBody = renderVisualSpec(component);
  if (visualSpecBody) {
    return visualSpecBody;
  }
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
  if (component.type === "risk-pulse") {
    return renderRiskPulse(component);
  }
  if (component.type === "status-stream") {
    return renderStatusStream(component);
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
  const packedComponents = useMemo(
    () => packComponents(screen.components || []),
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
        {packedComponents.map(({ component, layoutPosition }) => {
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
              style={getGridStyle(layoutPosition)}
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
