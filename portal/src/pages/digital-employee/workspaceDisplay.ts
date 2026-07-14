/** User-facing names for the built-in digital-employee workspaces.
 *
 * Self-monitoring receives stable workspace IDs from the runtime. Keep those
 * IDs out of the primary UI while preserving unknown/custom IDs for operators.
 */
const WORKSPACE_DISPLAY_NAMES: Record<string, string> = {
  gateway: "智观 AI",
  query: "数据分析专家",
  fault: "故障分析专家",
  resource: "资产管理专员",
  inspection: "运维巡检专员",
  order: "工单处置专员",
  knowledge: "知识库助手",
  operator: "操作助手",
  fde: "技能构建助手",
  default: "默认助手",
};

export function workspaceDisplayName(workspace: string): string {
  const id = String(workspace || "").trim();
  return WORKSPACE_DISPLAY_NAMES[id] || id || "未标注工作空间";
}
