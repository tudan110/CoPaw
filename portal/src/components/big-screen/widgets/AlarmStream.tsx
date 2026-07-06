import { evaluateRules } from "../rules.ts";
import type { WidgetProps } from "../registry.ts";
import { resolveScrollMode } from "../visualSpec.ts";

const TONE_DOT: Record<string, string> = {
  critical: "bs-dot--critical",
  high: "bs-dot--high",
  medium: "bs-dot--medium",
  normal: "bs-dot--normal",
  cool: "bs-dot--cool",
  warm: "bs-dot--warm",
};

/** Scrolling alarm stream — marquee list with severity dots. */
export function AlarmStream({ component }: WidgetProps) {
  const rows = (component.data?.rows ?? []) as Array<
    Record<string, unknown>
  >;
  const rules = component.visualSpec?.highlightRules;
  const tones = evaluateRules(rows, rules);
  const bindings = component.visualSpec?.bindings;
  const msgKey = bindings?.["message"] ?? "msg";
  const timeKey = bindings?.["time"] ?? "time";
  const toneKey = bindings?.["tone"] ?? "severity";

  // A stream marquees by default; scroll:"off" pins it static with a
  // manual scrollbar (same control vocabulary as tables).
  const mode = resolveScrollMode(component.visualSpec?.style, rows.length, 0);
  const marquee = mode === "marquee";
  const items = marquee && rows.length > 0 ? [...rows, ...rows] : rows;

  return (
    <div className={`bs-stream${marquee ? "" : " bs-stream--static"}`}>
      <ul className="bs-stream-list">
        {items.map((row, i) => {
          const tone =
            tones[i % rows.length] ??
            String((row as Record<string, unknown>)[toneKey] ?? "");
          const dotCls = TONE_DOT[tone] ?? "bs-dot--normal";
          // Fall back through common label-ish keys so tabular rows (工单/资源)
          // never render a fully blank line if bindings are missing.
          const msg = String(
            row[msgKey] ??
              row["message"] ??
              row["msg"] ??
              row["title"] ??
              row["name"] ??
              row["workorderNo"] ??
              "",
          );
          const time = String(
            row[timeKey] ?? row["time"] ?? row["ts"] ?? row["eventTime"] ?? "",
          );
          return (
            <li key={i} className="bs-stream-item">
              <span className={`bs-dot ${dotCls}`} />
              {time && <span className="bs-timeline-time">{time}</span>}
              <span className="bs-stream-msg">{msg}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
