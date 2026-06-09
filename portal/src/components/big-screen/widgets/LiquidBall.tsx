import { coerceNumber } from "../binding.ts";
import type { WidgetProps } from "../registry.ts";

/** Water-ball (liquid gauge) widget — CSS wave animation. */
export function LiquidBall({ component }: WidgetProps) {
  const metrics = (component.data?.metrics ?? {}) as Record<string, unknown>;
  const bindings = component.visualSpec?.bindings;
  const valueKey = bindings?.["value"] ?? Object.keys(metrics)[0] ?? "value";
  const raw = metrics[valueKey] ?? 0;
  const pct = Math.max(0, Math.min(100, coerceNumber(raw)));
  // Wave top offset: 100% means full (wave at top), 0% means empty (wave off bottom)
  // At pct=92: top ~= 34%; at pct=0: top ~= 110%
  const waveTop = `${100 - pct + 8}%`;
  const wave2Top = `${100 - pct + 14}%`;

  const label =
    component.title || String(bindings?.["label"] ?? "");

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
      }}
    >
      {label && <div className="bs-kpi-label">{label}</div>}
      <div className="bs-ball">
        <div className="bs-ball-wave" style={{ top: waveTop }} />
        <div
          className="bs-ball-wave bs-ball-wave--2"
          style={{ top: wave2Top }}
        />
        <div className="bs-ball-value">{pct}%</div>
      </div>
    </div>
  );
}
