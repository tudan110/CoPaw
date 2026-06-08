import { coerceNumber } from "../binding.ts";
import { evaluateRules } from "../rules.ts";
import type { WidgetProps } from "../registry.ts";

/** Faux-3D CSS bar chart (no echarts). */
export function Bar3D({ component }: WidgetProps) {
  const rows = (component.data?.rows ?? []) as Array<
    Record<string, unknown>
  >;
  const bindings = component.visualSpec?.bindings;
  const valueKey = bindings?.["value"] ?? "value";
  const rules = component.visualSpec?.highlightRules;
  const tones = evaluateRules(rows, rules);

  const maxVal = Math.max(
    ...rows.map((r) => coerceNumber(r[valueKey])),
    1,
  );

  return (
    <div className="bs-bar3d">
      {rows.map((row, i) => {
        const val = coerceNumber(row[valueKey]);
        const heightPct = `${Math.max(4, (val / maxVal) * 94)}%`;
        const tone = tones[i];
        let barClass = "bs-bar3d-bar";
        if (tone === "critical") barClass += " bs-bar3d-bar--warn";
        else if (tone === "medium" || tone === "warm")
          barClass += " bs-bar3d-bar--violet";
        return (
          <div
            key={i}
            className={barClass}
            style={{ height: heightPct }}
            title={String(row[bindings?.["name"] ?? "name"] ?? val)}
          />
        );
      })}
    </div>
  );
}
