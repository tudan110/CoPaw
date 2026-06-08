import type { VisualRule } from "./types.ts";

const RANK: Record<string, number> = { critical: 5, high: 4, medium: 3, warm: 2, normal: 1, cool: 1 };
export function toneRank(tone: string): number { return RANK[tone] ?? 0; }

function match(cell: unknown, op: VisualRule["operator"], value: string | number): boolean {
  if (op === "contains") return String(cell ?? "").includes(String(value));
  const a = typeof cell === "number" ? cell : Number(cell);
  const b = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(a) || Number.isNaN(b)) return false;
  switch (op) {
    case ">": return a > b;
    case ">=": return a >= b;
    case "<": return a < b;
    case "<=": return a <= b;
    case "=": return a === b;
    default: return false;
  }
}

export function evaluateRules(rows: Array<Record<string, unknown>>, rules: VisualRule[] | undefined): Array<string | null> {
  if (!rules?.length) return rows.map(() => null);
  return rows.map((row) => {
    let best: string | null = null;
    for (const r of rules) {
      if (match(row[r.field], r.operator, r.value) && (best === null || toneRank(r.tone) > toneRank(best))) {
        best = r.tone;
      }
    }
    return best;
  });
}
