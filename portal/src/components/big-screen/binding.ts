export function bindingField(
  row: Record<string, unknown>,
  bindings: Record<string, string> | undefined,
  ...fallbackKeys: string[]
): unknown {
  const logical = fallbackKeys[0];
  const mapped = logical && bindings?.[logical];
  if (mapped && row[mapped] !== undefined) return row[mapped];
  for (const k of fallbackKeys) if (row[k] !== undefined) return row[k];
  return undefined;
}

export function coerceNumber(v: unknown): number {
  if (typeof v === "number") return v;
  const n = Number(String(v ?? "").replace(/[,%\s]/g, ""));
  return Number.isNaN(n) ? 0 : n;
}
