/**
 * Pure column-derivation for TableWidget (JSX-free so node:test can import
 * it). Prefer the backend-declared fields/columns; fall back to the union of
 * row keys so any tabular payload renders instead of going blank.
 */
import type { ScreenComponent } from "../types.ts";

export interface Column {
  key: string;
  label: string;
}

export function cell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function deriveColumns(
  component: Pick<ScreenComponent, "data">,
): Column[] {
  const declared = component.data?.fields;
  if (Array.isArray(declared) && declared.length > 0) {
    return declared.map((f) => ({
      key: String(f.key),
      label: String(f.label ?? f.key),
    }));
  }
  const rows = (component.data?.rows ?? []) as Array<Record<string, unknown>>;
  const seen = new Set<string>();
  const cols: Column[] = [];
  for (const row of rows.slice(0, 20)) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k);
        cols.push({ key: k, label: k });
      }
    }
  }
  return cols.slice(0, 8); // keep it readable on a dashboard panel
}
