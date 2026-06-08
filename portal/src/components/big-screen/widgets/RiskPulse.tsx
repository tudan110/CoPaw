import { evaluateRules, toneRank } from "../rules.ts";
import { visualSpecClassTokens } from "../visualSpec.ts";
import type { WidgetProps } from "../registry.ts";

const LEVEL_LABELS: Record<string, string> = {
  critical: "高危",
  high: "高危",
  medium: "中危",
  normal: "正常",
  cool: "低危",
  warm: "中危",
};

/** Risk pulse widget — overall risk level + keyword chips. */
export function RiskPulse({ component }: WidgetProps) {
  const rows = (component.data?.rows ?? []) as Array<
    Record<string, unknown>
  >;
  const rules = component.visualSpec?.highlightRules ?? [];
  const vsClasses = visualSpecClassTokens(component.visualSpec);
  const tones = evaluateRules(rows, rules);

  // Determine overall risk: highest tone across all rows
  let overallTone = "normal";
  for (const t of tones) {
    if (t && toneRank(t) > toneRank(overallTone)) overallTone = t;
  }

  // Collect keyword chips from metrics
  const metrics = (component.data?.metrics ?? {}) as Record<string, unknown>;
  const chips = Object.entries(metrics).map(([k, v]) => ({
    key: k,
    count: String(v),
  }));

  const bindings = component.visualSpec?.bindings;
  const descKey = bindings?.["description"] ?? "description";
  const desc = String(
    (component.data?.metrics as Record<string, unknown> | undefined)?.[
      descKey
    ] ?? rows[0]?.[descKey] ?? "",
  );

  return (
    <div className={`bs-risk-pulse ${vsClasses.join(" ")}`}>
      <div className={`bs-risk-level bs-risk-level--${overallTone}`}>
        {LEVEL_LABELS[overallTone] ?? overallTone}
      </div>
      {desc && (
        <div
          style={{
            fontSize: 9,
            color: "#9fb2cc",
            lineHeight: 1.4,
          }}
        >
          {desc}
        </div>
      )}
      {chips.length > 0 && (
        <div className="bs-risk-tags">
          {chips.map((chip) => (
            <span
              key={chip.key}
              className={`bs-risk-tag bs-risk-tag--${overallTone}`}
            >
              {chip.key} {chip.count ? `×${chip.count}` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
