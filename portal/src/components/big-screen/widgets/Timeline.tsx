import { evaluateRules } from "../rules.ts";
import type { WidgetProps } from "../registry.ts";

const TONE_DOT_COLOR: Record<string, string> = {
  critical: "#f87171",
  high: "#fb923c",
  medium: "#fbbf24",
  normal: "#34d399",
  cool: "#22d3ee",
  warm: "#fb923c",
};

/** Timeline widget — vertical event list with time + message. */
export function Timeline({ component }: WidgetProps) {
  const rows = (component.data?.rows ?? []) as Array<
    Record<string, unknown>
  >;
  const rules = component.visualSpec?.highlightRules;
  const tones = evaluateRules(rows, rules);
  const bindings = component.visualSpec?.bindings;
  const msgKey = bindings?.["message"] ?? "msg";
  const timeKey = bindings?.["time"] ?? "time";

  return (
    <div className="bs-timeline">
      {rows.map((row, i) => {
        const tone = tones[i] ?? "normal";
        const dotColor = TONE_DOT_COLOR[tone] ?? "#22d3ee";
        const msg = String(row[msgKey] ?? row["message"] ?? "");
        const time = String(row[timeKey] ?? row["ts"] ?? "");
        return (
          <div key={i} className="bs-timeline-item">
            <div
              className="bs-timeline-dot"
              style={{ background: dotColor, boxShadow: `0 0 6px ${dotColor}` }}
            />
            {time && <span className="bs-timeline-time">{time}</span>}
            <span className="bs-timeline-msg">{msg}</span>
          </div>
        );
      })}
    </div>
  );
}
