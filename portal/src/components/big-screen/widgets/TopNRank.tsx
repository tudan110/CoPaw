import { coerceNumber } from "../binding.ts";
import type { WidgetProps } from "../registry.ts";

/** Horizontal bar ranking (Top-N) widget. */
export function TopNRank({ component }: WidgetProps) {
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
    <div style={{ display: "flex", flexDirection: "column" }}>
      {rows.map((row, i) => {
        const label = String(row[nameKey] ?? `#${i + 1}`);
        const val = coerceNumber(row[valueKey]);
        const pct = (val / maxVal) * 100;
        return (
          <div key={i} className="bs-topn-row">
            <span className="bs-topn-label">{label}</span>
            <div className="bs-topn-bar-track">
              <div
                className="bs-topn-bar-fill"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="bs-topn-value">{val}</span>
          </div>
        );
      })}
    </div>
  );
}
