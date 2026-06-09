import { coerceNumber } from "../binding.ts";
import type { WidgetProps } from "../registry.ts";

const STEP_GRADIENTS = [
  "linear-gradient(90deg,#22d3ee,#0e7490)",
  "linear-gradient(90deg,#34d399,#047857)",
  "linear-gradient(90deg,#a78bfa,#6d28d9)",
  "linear-gradient(90deg,#fb923c,#b45309)",
  "linear-gradient(90deg,#f87171,#b91c1c)",
];

/** Funnel widget — converging horizontal bars. */
export function Funnel({ component }: WidgetProps) {
  const rows = (component.data?.rows ?? []) as Array<
    Record<string, unknown>
  >;
  const bindings = component.visualSpec?.bindings;
  const nameKey = bindings?.["name"] ?? "name";
  const valueKey = bindings?.["value"] ?? "value";

  const maxVal = Math.max(
    ...rows.map((r) => coerceNumber(r[valueKey])),
    1,
  );

  return (
    <div className="bs-funnel">
      {rows.map((row, i) => {
        const label = String(row[nameKey] ?? `Step ${i + 1}`);
        const val = coerceNumber(row[valueKey]);
        const widthPct = `${Math.max(20, (val / maxVal) * 92)}%`;
        return (
          <div
            key={i}
            className="bs-funnel-step"
            style={{
              width: widthPct,
              background: STEP_GRADIENTS[i % STEP_GRADIENTS.length],
            }}
          >
            {label} {val}
          </div>
        );
      })}
    </div>
  );
}
