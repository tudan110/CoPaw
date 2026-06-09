import { coerceNumber } from "../binding.ts";
import type { WidgetProps } from "../registry.ts";

/** Simple KPI tile with numeric value + optional sparkline shape. */
export function MetricKpi({ component }: WidgetProps) {
  const metrics = (component.data?.metrics ?? {}) as Record<string, unknown>;
  const bindings = component.visualSpec?.bindings;
  const valueKey = bindings?.["value"] ?? Object.keys(metrics)[0] ?? "value";
  const raw =
    metrics[valueKey] ??
    (component.data?.rows?.[0] as Record<string, unknown> | undefined)?.[
      valueKey
    ] ??
    0;
  const display = String(
    typeof raw === "string" ? raw : coerceNumber(raw),
  );
  const color = bindings?.["color"] ?? "";
  const rows = component.data?.rows ?? [];

  // Build mini sparkline from rows if available
  const sparkKey = bindings?.["y"] ?? "value";
  const sparkValues = rows.map((r) =>
    coerceNumber((r as Record<string, unknown>)[sparkKey]),
  );
  const hasSpark = sparkValues.length > 1;
  const maxV = Math.max(...sparkValues, 1);
  const W = 100;
  const H = 16;
  const sparkPoints = sparkValues
    .map((v, i) => {
      const x = (i / (sparkValues.length - 1)) * W;
      const y = H - (v / maxV) * H;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="bs-kpi">
      {component.title && (
        <div className="bs-kpi-label">{component.title}</div>
      )}
      <div
        className="bs-kpi-value"
        style={color ? { color: String(color) } : undefined}
      >
        {display}
      </div>
      {hasSpark && (
        <svg
          className="bs-kpi-sparkline"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
        >
          <polyline
            points={sparkPoints}
            fill="none"
            stroke={color ? String(color) : "#67e8f9"}
            strokeWidth="2"
          />
        </svg>
      )}
    </div>
  );
}
