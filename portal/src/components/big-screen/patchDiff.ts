/**
 * patchDiff — render the backend's structured patch diff as readable lines.
 *
 * The backend `POST /{id}/patch` with `preview: true` returns a `diff`
 * array of `{ componentId, field, before, after }` entries (plus
 * `preview: true`) without persisting. This turns those machine entries
 * into human-facing Chinese summary lines for a "preview before apply"
 * step. Pure + dependency-free so it is unit-testable with node --test.
 */

export interface PatchDiffEntry {
  componentId: string;
  field: string;
  before: unknown;
  after: unknown;
}

/** Field key → human label for the per-component config fields. */
const FIELD_LABELS: Record<string, string> = {
  title: "标题",
  type: "组件类型",
  layoutPosition: "布局位置",
  visualConfig: "配色/样式",
  queryParams: "查询参数",
  "theme.palette": "主题配色",
};

function briefValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value.slice(0, 40);
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (typeof value === "object") {
    // a brief component descriptor {type,title,capabilityId} or a config
    const obj = value as Record<string, unknown>;
    const label = obj.title ?? obj.type ?? obj.capabilityId;
    return label ? `「${String(label)}」` : "(已调整)";
  }
  return String(value);
}

function componentLabel(componentId: string): string {
  return componentId ? `组件 ${componentId}` : "大屏";
}

/** One readable line per diff entry. */
export function summarizePatchDiff(
  diff: PatchDiffEntry[] | undefined,
): string[] {
  if (!Array.isArray(diff) || diff.length === 0) return [];
  const lines: string[] = [];
  for (const entry of diff) {
    if (!entry || typeof entry !== "object") continue;
    const { componentId, field, before, after } = entry;

    if (field === "component") {
      if (before === null || before === undefined) {
        lines.push(`＋ 新增组件 ${briefValue(after)}`);
      } else if (after === null || after === undefined) {
        lines.push(`－ 移除组件 ${briefValue(before)}`);
      } else {
        lines.push(`组件 ${componentId} 已更新`);
      }
      continue;
    }

    const label = FIELD_LABELS[field] ?? field;
    if (field === "theme.palette") {
      lines.push(`${label}：${briefValue(before)} → ${briefValue(after)}`);
      continue;
    }
    // structured fields (layout/config/queryParams) read better as
    // "adjusted" than dumping the whole object
    if (
      field === "layoutPosition" ||
      field === "visualConfig" ||
      field === "queryParams"
    ) {
      lines.push(`${componentLabel(componentId)} 的${label}已调整`);
      continue;
    }
    lines.push(
      `${componentLabel(componentId)} 的${label}：` +
        `${briefValue(before)} → ${briefValue(after)}`,
    );
  }
  return lines;
}

/** True when there is at least one renderable change. */
export function hasPatchChanges(diff: PatchDiffEntry[] | undefined): boolean {
  return Array.isArray(diff) && diff.length > 0;
}
