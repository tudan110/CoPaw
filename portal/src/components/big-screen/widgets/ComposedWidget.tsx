import { coerceNumber } from "../binding.ts";
import {
  normalizeBlueprint,
  type Blueprint,
  type BlueprintCell,
  type BlueprintElement,
  type BadgeElement,
  type ChartElement,
  type ListElement,
  type ProgressElement,
  type SparklineElement,
  type ValueElement,
} from "../blueprint.ts";
import {
  buildAreaOption,
  buildBarOption,
  buildDonutOption,
  buildGaugeOption,
  buildHeatmapOption,
  buildLineOption,
  buildRadarOption,
} from "../charts/options.ts";
import { EChart } from "../charts/EChart.tsx";
import type { WidgetProps } from "../registry.ts";
import type { CapabilityResult } from "../types.ts";

/**
 * ComposedWidget — interprets a `visualSpec.blueprint` declaration.
 *
 * The generative half of the big-screen: the LLM composes a panel from
 * controlled atoms (value/chart/list/badge/label/progress/sparkline,
 * nested via group) instead of picking a prefab. The blueprint is plain
 * data — it is normalized again here and rendered; nothing is executed.
 */

const TONE_DOT: Record<string, string> = {
  critical: "bs-dot--critical",
  high: "bs-dot--high",
  medium: "bs-dot--medium",
  normal: "bs-dot--normal",
  cool: "bs-dot--cool",
  warm: "bs-dot--warm",
};

function resolveScalar(data: CapabilityResult, key: string): unknown {
  const metrics = (data.metrics ?? {}) as Record<string, unknown>;
  if (metrics[key] !== undefined) return metrics[key];
  const extra = data as unknown as Record<string, unknown>;
  if (extra[key] !== undefined) return extra[key];
  const firstRow = (data.rows?.[0] ?? {}) as Record<string, unknown>;
  return firstRow[key];
}

function ValueAtom({
  element,
  data,
}: {
  element: ValueElement;
  data: CapabilityResult;
}) {
  // unresolved bind (LLM-invented field name) falls back to the
  // capability's primary scalar — real data beats an empty "--"
  const bound = resolveScalar(data, element.bind["value"]);
  const raw = bound ?? (data as unknown as Record<string, unknown>)["value"];
  const display =
    raw === undefined || raw === null ? "--" : String(raw).slice(0, 16);
  const unit = element.bind["unit"] ?? "";
  const prefix = element.bind["prefix"] ?? "";
  const label =
    element.bind["label"] !== undefined
      ? String(
          resolveScalar(data, element.bind["label"]) ?? element.bind["label"],
        )
      : "";
  const sizeCls = element.size ? ` bs-bp-value--${element.size}` : "";
  const styleCls = element.style ? ` bs-bp-value--${element.style}` : "";

  if (element.style === "flip") {
    const digits = String(display).split("");
    return (
      <div className={`bs-bp-value${sizeCls}`}>
        {label && <div className="bs-kpi-label">{label}</div>}
        <div className="bs-flip">
          {prefix && (
            <span className="bs-flip-digit bs-flip-unit">{prefix}</span>
          )}
          {digits.map((d, i) => (
            <span key={i} className="bs-flip-digit">
              {d}
            </span>
          ))}
          {unit && <span className="bs-flip-digit bs-flip-unit">{unit}</span>}
        </div>
      </div>
    );
  }
  return (
    <div className={`bs-bp-value${sizeCls}${styleCls}`}>
      {label && <div className="bs-kpi-label">{label}</div>}
      <div className="bs-bp-value-num">
        {prefix && <span className="bs-bp-value-unit">{prefix}</span>}
        <span>{display}</span>
        {unit && <span className="bs-bp-value-unit">{unit}</span>}
      </div>
    </div>
  );
}

function ChartAtom({
  element,
  data,
}: {
  element: ChartElement;
  data: CapabilityResult;
}) {
  const bind = element.bind ?? {};
  let option: Record<string, unknown> | null = null;
  switch (element.chart) {
    case "line":
      option = buildLineOption(data, { x: bind["x"], y: bind["y"] });
      break;
    case "area":
      option = buildAreaOption(data, { x: bind["x"], y: bind["y"] });
      break;
    case "bar":
      option = buildBarOption(data, { x: bind["x"], y: bind["y"] });
      break;
    case "donut":
      option = buildDonutOption(data, {
        name: bind["name"],
        value: bind["value"],
      });
      break;
    case "gauge":
      option = buildGaugeOption(data, bind["value"]);
      break;
    case "radar":
      option = buildRadarOption(data);
      break;
    case "heatmap":
      option = buildHeatmapOption(data, {
        x: bind["x"],
        y: bind["y"],
        value: bind["value"],
      });
      break;
  }
  if (!option) return null;
  return (
    <div className="bs-bp-chart">
      <EChart option={option} />
    </div>
  );
}

function ListAtom({
  element,
  data,
}: {
  element: ListElement;
  data: CapabilityResult;
}) {
  const bind = element.bind ?? {};
  const rows = ((data.rows ?? []) as Array<Record<string, unknown>>).slice(
    0,
    element.limit,
  );
  if (rows.length === 0) return <div className="bs-bp-empty">暂无条目</div>;
  const titleKey = bind["title"] ?? bind["name"] ?? "title";
  const timeKey = bind["time"] ?? "time";
  const toneKey = bind["tone"] ?? "level";
  const valueKey = bind["value"] ?? "value";

  if (element.style === "rank") {
    const maxVal = Math.max(...rows.map((r) => coerceNumber(r[valueKey])), 1);
    return (
      <div className="bs-bp-list">
        {rows.map((row, i) => {
          const pct = (coerceNumber(row[valueKey]) / maxVal) * 100;
          return (
            <div key={i} className="bs-topn-row">
              <span className="bs-topn-label">
                {String(row[titleKey] ?? `#${i + 1}`)}
              </span>
              <div className="bs-topn-bar-track">
                <div
                  className="bs-topn-bar-fill"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="bs-topn-value">
                {coerceNumber(row[valueKey])}
              </span>
            </div>
          );
        })}
      </div>
    );
  }

  const items = element.style === "stream" ? [...rows, ...rows] : rows;
  return (
    <div className={element.style === "stream" ? "bs-stream" : "bs-bp-list"}>
      <ul className="bs-stream-list">
        {items.map((row, i) => {
          const tone = String(row[toneKey] ?? "");
          const dotCls = TONE_DOT[tone] ?? "bs-dot--normal";
          return (
            <li key={i} className="bs-stream-item">
              <span className={`bs-dot ${dotCls}`} />
              {row[timeKey] !== undefined && (
                <span className="bs-timeline-time">{String(row[timeKey])}</span>
              )}
              <span className="bs-stream-msg">
                {String(row[titleKey] ?? row["message"] ?? "")}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function BadgeAtom({
  element,
  data,
}: {
  element: BadgeElement;
  data: CapabilityResult;
}) {
  const bound = element.bind?.["text"]
    ? resolveScalar(data, element.bind["text"])
    : undefined;
  const text = String(bound ?? element.text ?? "");
  if (!text) return null;
  if (element.kind === "label") {
    return <div className="bs-bp-label">{text}</div>;
  }
  const toneCls = element.tone ? ` bs-bp-badge--${element.tone}` : "";
  return <span className={`bs-bp-badge${toneCls}`}>{text}</span>;
}

function ProgressAtom({
  element,
  data,
}: {
  element: ProgressElement;
  data: CapabilityResult;
}) {
  const value = coerceNumber(resolveScalar(data, element.bind["value"]));
  const max =
    element.max ??
    (element.bind["max"]
      ? coerceNumber(resolveScalar(data, element.bind["max"]))
      : 100);
  const pct = Math.max(0, Math.min(100, (value / (max || 100)) * 100));

  if (element.style === "ring" || element.style === "liquid") {
    return (
      <div className="bs-bp-ring-wrap">
        <div
          className="bs-bp-ring"
          style={{
            background: `conic-gradient(#22d3ee ${pct}%, rgba(255,255,255,.08) ${pct}% 100%)`,
          }}
        >
          <div className="bs-bp-ring-inner">{Math.round(pct)}%</div>
        </div>
      </div>
    );
  }
  return (
    <div className="bs-bp-progress">
      <div className="bs-topn-bar-track">
        <div className="bs-topn-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="bs-bp-progress-num">{Math.round(pct)}%</span>
    </div>
  );
}

function SparklineAtom({
  element,
  data,
}: {
  element: SparklineElement;
  data: CapabilityResult;
}) {
  const yKey = element.bind["y"];
  const source = (
    Array.isArray(data.series) && data.series.length > 0
      ? data.series
      : data.rows ?? []
  ) as Array<Record<string, unknown>>;
  const values = source
    .map((row) =>
      typeof row === "object" && row !== null
        ? coerceNumber((row as Record<string, unknown>)[yKey])
        : coerceNumber(row),
    )
    .slice(0, 48);
  if (values.length < 2) return <div className="bs-bp-empty">--</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * 100;
      const y = 30 - ((v - min) / range) * 26 - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className="bs-bp-sparkline"
      viewBox="0 0 100 32"
      preserveAspectRatio="none"
    >
      <polyline
        points={points}
        fill="none"
        stroke="#22d3ee"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function ElementView({
  element,
  data,
}: {
  element: BlueprintElement;
  data: CapabilityResult;
}) {
  switch (element.kind) {
    case "value":
      return <ValueAtom element={element} data={data} />;
    case "chart":
      return <ChartAtom element={element} data={data} />;
    case "list":
      return <ListAtom element={element} data={data} />;
    case "badge":
    case "label":
      return <BadgeAtom element={element} data={data} />;
    case "progress":
      return <ProgressAtom element={element} data={data} />;
    case "sparkline":
      return <SparklineAtom element={element} data={data} />;
    case "group":
      return (
        <BlueprintView
          blueprint={{
            layout: element.layout,
            gap: element.gap,
            cells: element.cells,
          }}
          data={data}
        />
      );
    default:
      return null;
  }
}

function CellView({
  cell,
  data,
}: {
  cell: BlueprintCell;
  data: CapabilityResult;
}) {
  return (
    <div className="bs-bp-cell" style={{ flexGrow: cell.span, flexBasis: 0 }}>
      <ElementView element={cell.element} data={data} />
    </div>
  );
}

function BlueprintView({
  blueprint,
  data,
}: {
  blueprint: Blueprint;
  data: CapabilityResult;
}) {
  const gapCls = blueprint.gap ? ` bs-bp--gap-${blueprint.gap}` : "";
  return (
    <div className={`bs-bp bs-bp--${blueprint.layout}${gapCls}`}>
      {blueprint.cells.map((cell, i) => (
        <CellView key={i} cell={cell} data={data} />
      ))}
    </div>
  );
}

export function ComposedWidget({ component }: WidgetProps) {
  const data: CapabilityResult = component.data ?? {
    capabilityId: "",
    sourceStatus: "empty",
  };
  const blueprint = normalizeBlueprint(
    (component.visualSpec as Record<string, unknown> | undefined)?.[
      "blueprint"
    ],
  );
  if (!blueprint) {
    return <div className="bs-bp-empty">创作版式无效，已忽略</div>;
  }
  return <BlueprintView blueprint={blueprint} data={data} />;
}
