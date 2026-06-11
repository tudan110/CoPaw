import {
  digitalEmployees,
  employeeResults,
  employeeWorkflows,
  executionHistory,
  getEmployeeById,
} from "../../data/portalData";
import type { DigitalEmployee } from "../../types/portal";
import {
  type PortalEmployeeRuntimeStatus,
} from "../../api/portalEmployeeStatus";
import { portalAppTitle, portalGatewayAgentId } from "../../config/portalBranding";
export const sidebarEmployeePriority = [
  "query",
  "fault",
  "resource",
  "inspection",
  "order",
  "knowledge",
] as const;

export const REMOTE_AGENT_IDS: Record<string, string> = {
  fault: "fault",
  resource: "resource",
  inspection: "inspection",
  query: "query",
  order: "order",
  knowledge: "knowledge",
};
export const DASHBOARD_CHAT_CHANNEL = "console";

export const PORTAL_HOME_AGENT_ID = portalGatewayAgentId;
export const EMPLOYEE_MENTION_ALIASES: Record<string, string[]> = {
  resource: ["资产", "资源", "纳管"],
  fault: ["故障", "处置", "修复", "根因"],
  inspection: ["巡检", "巡查", "检查"],
  order: ["工单", "待办", "已办", "流程", "审批", "派单", "转派"],
  query: ["数据", "数字", "洞察", "报表", "查询", "告警"],
  knowledge: ["知识", "知库", "文档"],
};

export const PAGE_THEME_STORAGE_KEY = "portal-digital-employee-theme";
export const SIDEBAR_COLLAPSED_STORAGE_KEY = "portal-sidebar-collapsed";
export const CHAT_SIDEBAR_COLLAPSED_STORAGE_KEY = "portal-chat-sidebar-collapsed";
export const PORTAL_HOME_ID = "portal-home";
export const PORTAL_CLOSE_DRAWER_MESSAGE = {
  source: "qwenpaw-portal",
  type: "portal:close-drawer",
  reason: "switch-traditional-view",
} as const;

export function postPortalCloseDrawerMessage() {
  if (window.parent !== window) {
    window.parent.postMessage(PORTAL_CLOSE_DRAWER_MESSAGE, "*");
  }
}

export const TRADITIONAL_VIEW_PORT = "30081";

export function navigateToTraditionalView() {
  const { protocol, hostname } = window.location;
  const url = `${protocol}//${hostname}:${TRADITIONAL_VIEW_PORT}/`;
  const target = window.top ?? window;
  target.location.href = url;
}
export const RESOURCE_IMPORT_OWNER_ID = "resource";
export const KNOWLEDGE_BASE_OWNER_ID = "knowledge";
export const ORDER_OWNER_ID = "order";
export const RESOURCE_IMPORT_COMMAND = "导入资源清单";
export const KNOWLEDGE_BASE_SEARCH_COMMAND = "知识库检索";
export const PORTAL_RESOURCE_IMPORT_SOURCE = "portal-resource-import";
export const PORTAL_KNOWLEDGE_BASE_SOURCE = "portal-knowledge-base";
export const RESOURCE_IMPORT_DIRECT_INTENT_PATTERN =
  /(导入资源清单|资源清单导入|批量导入|资源纳管|智能导入|上传台账导入)/;
export const RESOURCE_IMPORT_INTENT_PATTERN =
  /(导入资源清单|资源清单导入|批量导入|资源纳管|导入资源|智能导入|上传台账导入|导入.{0,12}(资源|资产|设备|主机|服务器|虚拟机|应用|产品|网络设备|数据库|IP|子网|机柜|清单|台账)|上传.{0,12}(资源|资产|设备|清单|台账)|资源.{0,12}(导入|纳管|录入|入库)|资产.{0,12}(导入|纳管|录入|入库)|设备.{0,12}(导入|纳管|录入|入库)|清单.{0,12}(导入|纳管|录入|入库)|台账.{0,12}(导入|纳管|录入|入库)|(CMDB|cmdb).{0,12}(导入|纳管|录入|入库|上传|解析|报错|失败|异常)|(导入|纳管|录入|入库|上传|解析).{0,12}(CMDB|cmdb)|文件.{0,12}(导入|纳管|录入|入库|上传|解析).{0,8}(报错|失败|异常|问题)?|导入.{0,8}(报错|失败|异常|问题|不成功))/i;
export const KNOWLEDGE_BASE_INTENT_PATTERN =
  /(知识库检索|检索知识库|上传知识文档|导入知识文档|文档入库|资料入库|知识沉淀|手动沉淀知识|查看知识资料)/;
export const KNOWLEDGE_BASE_CARD_INTENT_PATTERN =
  /(上传知识|上传文档|上传资料|上传文件|上传附件|导入知识|导入文档|导入资料|导入文件|文档入库|资料入库|知识入库|知识沉淀|手动沉淀|手动录入|新增知识|保存经验|录入知识)/;
export const CHAT_SCROLL_BOTTOM_THRESHOLD_PX = 48;

export function createResourceImportFlowId() {
  return `resource-import-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createKnowledgeBaseFlowId() {
  return `knowledge-base-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function isResourceImportIntent(value: string) {
  const normalized = String(value || "").replace(/\s+/g, "");
  return RESOURCE_IMPORT_INTENT_PATTERN.test(normalized);
}

export function isResourceImportDirectIntent(value: string) {
  const normalized = String(value || "").replace(/\s+/g, "");
  return RESOURCE_IMPORT_DIRECT_INTENT_PATTERN.test(normalized);
}

export function isKnowledgeBaseIntent(value: string) {
  const normalized = String(value || "").replace(/\s+/g, "");
  return KNOWLEDGE_BASE_INTENT_PATTERN.test(normalized);
}

export function isKnowledgeBaseCardIntent(value: string) {
  const normalized = String(value || "").replace(/\s+/g, "");
  return KNOWLEDGE_BASE_CARD_INTENT_PATTERN.test(normalized);
}

export function isPortalResourceImportSession(session: SessionRecord | null | undefined) {
  return String(session?.meta?.source || "") === PORTAL_RESOURCE_IMPORT_SOURCE;
}

export function isPortalKnowledgeBaseSession(session: SessionRecord | null | undefined) {
  return String(session?.meta?.source || "") === PORTAL_KNOWLEDGE_BASE_SOURCE;
}

export function resolveResourceImportApplicationName(flow: any): string {
  const resourceGroups = Array.isArray(flow?.resourceGroups)
    ? flow.resourceGroups
    : Array.isArray(flow?.preview?.resourceGroups)
      ? flow.preview.resourceGroups
      : [];
  const resourceResults = Array.isArray(flow?.result?.resourceResults) ? flow.result.resourceResults : [];
  const successfulPreviewKeys = new Set(
    resourceResults
      .filter((item: any) => ["success", "skipped"].includes(String(item?.status || "")))
      .map((item: any) => String(item?.previewKey || ""))
      .filter(Boolean),
  );
  const projectGroup = resourceGroups.find((group: any) => group?.ciType === "project");
  const projectRecords = Array.isArray(projectGroup?.records) ? projectGroup.records : [];
  const firstProjectRecord = projectRecords.find((record: any) => (
    !successfulPreviewKeys.size || successfulPreviewKeys.has(String(record?.previewKey || ""))
  )) || projectRecords[0] || null;
  return String(
    firstProjectRecord?.attributes?.project_name
      || firstProjectRecord?.name
      || "",
  ).trim();
}

export function resolveResourceImportTopologyScope(flow: any) {
  type ImportedResourceScopeItem = {
    previewKey: string;
    ciId: string | number;
    name: string;
    ciType: string;
  };
  const resourceGroups = Array.isArray(flow?.resourceGroups)
    ? flow.resourceGroups
    : Array.isArray(flow?.preview?.resourceGroups)
      ? flow.preview.resourceGroups
      : [];
  const resourceResults = Array.isArray(flow?.result?.resourceResults) ? flow.result.resourceResults : [];
  const recordMap = new Map<string, any>(
    resourceGroups
      .flatMap((group: any) => (Array.isArray(group?.records) ? group.records : []))
      .map((record: any) => [String(record?.previewKey || ""), record]),
  );
  const resources: ImportedResourceScopeItem[] = resourceResults
    .filter((item: any) => ["success", "skipped"].includes(String(item?.status || "")) && item?.ciId !== undefined)
    .map((item: any) => {
      const previewKey = String(item?.previewKey || "");
      const record = recordMap.get(previewKey) || {};
      return {
        previewKey,
        ciId: item.ciId,
        name: String(record?.name || previewKey || "").trim(),
        ciType: String(record?.ciType || "").trim(),
      };
    });
  const uniqueResources: ImportedResourceScopeItem[] = Array.from(
    new Map(resources.map((item) => [String(item.ciId), item])).values(),
  );
  return {
    applicationName: resolveResourceImportApplicationName(flow),
    includesProject: uniqueResources.some((item) => item.ciType === "project"),
    resources: uniqueResources,
    ciIds: uniqueResources.map((item) => item.ciId),
  };
}

export function buildResourceImportSessionRecord(
  employee: { id: string; name: string },
  messages: any[],
  {
    sessionId,
    visibleContent,
    previous,
  }: {
    sessionId?: string;
    visibleContent?: string;
    previous?: SessionRecord | null;
  } = {},
): SessionRecord {
  const now = new Date().toISOString();
  const latestFlow = [...messages]
    .reverse()
    .map((message) => message?.resourceImportFlow)
    .find(Boolean) as Record<string, any> | undefined;

  const stageLabelMap: Record<string, string> = {
    intro: "等待上传文件",
    parsing: "文件解析中",
    structure: "分组与模型预检查",
    confirm: "确认导入内容",
    topology: "拓扑关系预览",
    importing: "写入 CMDB 中",
    result: "导入结果",
  };
  const detail = latestFlow
    ? stageLabelMap[String(latestFlow.stage || "")] || "资源导入处理中"
    : "资源导入处理中";
  const status =
    latestFlow?.status === "error"
      ? "error"
      : latestFlow?.stage === "result"
        ? "completed"
        : latestFlow?.status === "running"
          ? "running"
          : "idle";

  return {
    id: sessionId || previous?.id || `portal-resource-import-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    employeeId: employee.id,
    title: previous?.title || `资源导入 · ${new Date().toLocaleString("zh-CN")}`,
    createdAt: previous?.createdAt || now,
    updatedAt: now,
    messages,
    status,
    detail,
    tag: "资源导入",
    meta: {
      ...(previous?.meta || {}),
      source: PORTAL_RESOURCE_IMPORT_SOURCE,
      visibleContent: visibleContent || previous?.meta?.visibleContent || RESOURCE_IMPORT_COMMAND,
    },
  };
}

export function buildKnowledgeBaseSessionRecord(
  employee: { id: string; name: string },
  messages: any[],
  {
    sessionId,
    visibleContent,
    previous,
  }: {
    sessionId?: string;
    visibleContent?: string;
    previous?: SessionRecord | null;
  } = {},
): SessionRecord {
  const now = new Date().toISOString();
  const latestFlow = [...messages]
    .reverse()
    .map((message) => message?.knowledgeBaseFlow)
    .find(Boolean) as Record<string, any> | undefined;
  const mode = String(latestFlow?.mode || latestFlow?.stage || "");
  const status = latestFlow?.status === "error"
    ? "error"
    : latestFlow?.status === "completed"
      ? "completed"
      : latestFlow?.status === "running"
        ? "running"
        : "idle";
  const detailMap: Record<string, string> = {
    intro: "等待选择知识库操作",
    search: "知识库检索",
    upload: "文档导入",
    manual: "手动沉淀知识",
  };

  return {
    id: sessionId || previous?.id || `portal-knowledge-base-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    employeeId: employee.id,
    title: previous?.title || `知识库 · ${new Date().toLocaleString("zh-CN")}`,
    createdAt: previous?.createdAt || now,
    updatedAt: now,
    messages,
    status,
    detail: detailMap[mode] || "知识库处理中",
    tag: "知识库",
    meta: {
      ...(previous?.meta || {}),
      source: PORTAL_KNOWLEDGE_BASE_SOURCE,
      visibleContent: visibleContent || previous?.meta?.visibleContent || KNOWLEDGE_BASE_SEARCH_COMMAND,
    },
  };
}

export function mergeSessionRecords(primary: SessionRecord[], secondary: SessionRecord[]) {
  const seen = new Set<string>();
  return [...primary, ...secondary]
    .filter((session) => {
      if (!session?.id || seen.has(session.id)) {
        return false;
      }
      seen.add(session.id);
      return true;
    })
    .sort((left, right) => {
      const leftTime = new Date(left.updatedAt || left.createdAt || 0).getTime();
      const rightTime = new Date(right.updatedAt || right.createdAt || 0).getTime();
      return rightTime - leftTime;
    });
}
export type DashboardKanbanMode = "work" | "employee";
export type DashboardKanbanFilter = "all" | "urgent" | "running" | "idle";
export type DashboardWorkColumnId = "pending" | "running" | "completed" | "closed";

export type DashboardWorkCard = {
  id: string;
  ownerEmployeeIds: string[];
  ownerLabel: string;
  ownerColor: string;
  title: string;
  description: string;
  label: string;
  tagBg: string;
  tagColor: string;
  timeText: string;
  progress?: number;
  score?: number;
  isUrgent: boolean;
  isRunning: boolean;
};

export type DashboardWorkColumn = {
  id: DashboardWorkColumnId;
  title: string;
  dot: string;
  cards: DashboardWorkCard[];
};

export type DashboardEmployeeSnapshot = {
  id: string;
  name: string;
  desc: string;
  color: string;
  runtimeState: "running" | "idle";
  statusLabel: string;
  currentJob: string;
  historyCount: number;
  progress: number;
  workStatus: string;
  updatedAt: string;
  urgent: boolean;
};

export const DASHBOARD_EMPLOYEE_COLORS: Record<string, string> = {
  resource: "#3b82f6",
  fault: "#ef4444",
  inspection: "#22c55e",
  order: "#f59e0b",
  query: "#8b5cf6",
  knowledge: "#06b6d4",
};

export const DASHBOARD_TAG_STYLES = {
  resource: { bg: "rgba(59, 130, 246, 0.15)", color: "#60a5fa" },
  fault: { bg: "rgba(239, 68, 68, 0.15)", color: "#f87171" },
  inspection: { bg: "rgba(34, 197, 94, 0.15)", color: "#4ade80" },
  order: { bg: "rgba(245, 158, 11, 0.15)", color: "#fbbf24" },
  query: { bg: "rgba(139, 92, 246, 0.15)", color: "#a78bfa" },
  knowledge: { bg: "rgba(6, 182, 212, 0.15)", color: "#22d3ee" },
  collaboration: { bg: "rgba(168, 85, 247, 0.14)", color: "#c084fc" },
} as const;

export function getDashboardEmployeeColor(employeeId: string) {
  return DASHBOARD_EMPLOYEE_COLORS[employeeId] || "#6366f1";
}

export function formatRuntimeUpdatedAt(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value || "";
  }

  const diffMs = Math.max(0, Date.now() - timestamp);
  const diffMinutes = Math.floor(diffMs / 60000);
  if (diffMinutes < 1) {
    return "刚刚";
  }
  if (diffMinutes < 60) {
    return `${diffMinutes}分钟前`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}小时前`;
  }

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) {
    return `${diffDays}天前`;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function parseRuntimeProgress(value: PortalEmployeeRuntimeStatus["progress"] | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(0, Math.min(100, value));
  }

  const text = String(value || "").trim();
  if (!text || text === "--") {
    return 0;
  }

  const match = text.match(/^(\d{1,3})%$/);
  if (!match) {
    return null;
  }

  return Math.max(0, Math.min(100, Number(match[1])));
}

export function areEmployeeRuntimeStatusMapsEqual(
  left: Record<string, PortalEmployeeRuntimeStatus>,
  right: Record<string, PortalEmployeeRuntimeStatus>,
) {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) {
    return false;
  }

  return leftKeys.every((key) => JSON.stringify(left[key]) === JSON.stringify(right[key]));
}

export function getDashboardFilterLabels(
  mode: DashboardKanbanMode,
): Partial<Record<DashboardKanbanFilter, string>> {
  return mode === "employee"
    ? {
        all: "全部",
        running: "运行中",
        idle: "待机",
        urgent: "紧急任务",
      }
    : {
        all: "全部",
        urgent: "紧急",
        running: "进行中",
      };
}

export function formatDashboardClock(value: Date) {
  return value.toLocaleTimeString("zh-CN", {
    hour12: false,
  });
}

export function buildDashboardWorkColumns(): DashboardWorkColumn[] {
  const employee = (employeeId: string) => getEmployeeById(employeeId);
  const employeeName = (employeeId: string) => employee(employeeId)?.name || employeeId;
  const employeeColor = (employeeId: string) => getDashboardEmployeeColor(employeeId);
  const employeeTag = (employeeId: keyof typeof DASHBOARD_TAG_STYLES) =>
    DASHBOARD_TAG_STYLES[employeeId];
  const collaborationTag = DASHBOARD_TAG_STYLES.collaboration;

  return [
    {
      id: "pending",
      title: "待处理",
      dot: "#f59e0b",
      cards: [
        {
          id: "pending-fault-port-down",
          ownerEmployeeIds: ["fault"],
          ownerLabel: employeeName("fault"),
          ownerColor: employeeColor("fault"),
          title: `${employeeName("fault")}核心交换端口 down 待接续`,
          description: "南北向链路告警已聚合，等待继续执行根因定位与恢复策略。",
          label: "故障",
          tagBg: employeeTag("fault").bg,
          tagColor: employeeTag("fault").color,
          timeText: "6分钟前",
          isUrgent: true,
          isRunning: false,
        },
        {
          id: "pending-inspection-baseline",
          ownerEmployeeIds: ["inspection"],
          ownerLabel: employeeName("inspection"),
          ownerColor: employeeColor("inspection"),
          title: `${employeeName("inspection")}夜间基线巡检待执行`,
          description: "核心主机、数据库与中间件的例行健康检查窗口已排入待办。",
          label: "巡检",
          tagBg: employeeTag("inspection").bg,
          tagColor: employeeTag("inspection").color,
          timeText: "20分钟前",
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "pending-knowledge-archive",
          ownerEmployeeIds: ["knowledge"],
          ownerLabel: employeeName("knowledge"),
          ownerColor: employeeColor("knowledge"),
          title: `${employeeName("knowledge")}故障案例归档待同步`,
          description: "上一轮数据库慢查询处置案例待结构化归档并写回知识库。",
          label: "知识",
          tagBg: employeeTag("knowledge").bg,
          tagColor: employeeTag("knowledge").color,
          timeText: "42分钟前",
          isUrgent: false,
          isRunning: false,
        },
      ],
    },
    {
      id: "running",
      title: "进行中",
      dot: "#3b82f6",
      cards: [
        {
          id: "running-resource-discovery",
          ownerEmployeeIds: ["resource"],
          ownerLabel: employeeName("resource"),
          ownerColor: employeeColor("resource"),
          title: `${employeeName("resource")}核心网段纳管扫描中`,
          description: "正在发现新入网设备与服务端口，补全资源模型与纳管标签。",
          label: "纳管",
          tagBg: employeeTag("resource").bg,
          tagColor: employeeTag("resource").color,
          timeText: "进行中",
          progress: 68,
          isUrgent: false,
          isRunning: true,
        },
        {
          id: "running-fault-diagnosis",
          ownerEmployeeIds: ["fault"],
          ownerLabel: employeeName("fault"),
          ownerColor: employeeColor("fault"),
          title: `${employeeName("fault")}端口 down 根因定位中`,
          description: "正在关联接口流量、邻接状态与拓扑路径，输出根因与处置建议。",
          label: "故障",
          tagBg: employeeTag("fault").bg,
          tagColor: employeeTag("fault").color,
          timeText: "紧急",
          progress: 84,
          isUrgent: true,
          isRunning: true,
        },
        {
          id: "running-query-report",
          ownerEmployeeIds: ["query"],
          ownerLabel: employeeName("query"),
          ownerColor: employeeColor("query"),
          title: `${employeeName("query")}设备分布报表生成中`,
          description: "设备类型、区域分布和容量画像已进入聚合与图表输出阶段。",
          label: "报表",
          tagBg: employeeTag("query").bg,
          tagColor: employeeTag("query").color,
          timeText: "进行中",
          progress: 57,
          isUrgent: false,
          isRunning: true,
        },
        {
          id: "running-order-routing",
          ownerEmployeeIds: ["order"],
          ownerLabel: employeeName("order"),
          ownerColor: employeeColor("order"),
          title: `${employeeName("order")}告警派单流转中`,
          description: "正在对接告警入口，将高优先级事件分派到对应数字员工流程。",
          label: "工单",
          tagBg: employeeTag("order").bg,
          tagColor: employeeTag("order").color,
          timeText: "进行中",
          progress: 63,
          isUrgent: false,
          isRunning: true,
        },
        {
          id: "running-collaboration-fault-query",
          ownerEmployeeIds: ["fault", "query"],
          ownerLabel: `${employeeName("fault")} + ${employeeName("query")}`,
          ownerColor: "#8b5cf6",
          title: "故障与数据协同复盘中",
          description: "围绕链路抖动、响应时间与异常分布进行联合分析，输出复盘结论。",
          label: "协同",
          tagBg: collaborationTag.bg,
          tagColor: collaborationTag.color,
          timeText: "进行中",
          progress: 49,
          isUrgent: false,
          isRunning: true,
        },
      ],
    },
    {
      id: "completed",
      title: "已完成",
      dot: "#22c55e",
      cards: [
        {
          id: "completed-query-summary",
          ownerEmployeeIds: ["query"],
          ownerLabel: employeeName("query"),
          ownerColor: employeeColor("query"),
          title: `${employeeName("query")}容量趋势分析已完成`,
          description: "核心业务链路的容量曲线、峰值时段与增长趋势已归档。",
          label: "分析",
          tagBg: employeeTag("query").bg,
          tagColor: employeeTag("query").color,
          timeText: "1小时前",
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "completed-resource-onboard",
          ownerEmployeeIds: ["resource"],
          ownerLabel: employeeName("resource"),
          ownerColor: employeeColor("resource"),
          title: `${employeeName("resource")}新增设备纳管已完成`,
          description: "新接入交换机与服务器已完成识别、分类与资源建模。",
          label: "纳管",
          tagBg: employeeTag("resource").bg,
          tagColor: employeeTag("resource").color,
          timeText: "2小时前",
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "completed-order-closure",
          ownerEmployeeIds: ["order"],
          ownerLabel: employeeName("order"),
          ownerColor: employeeColor("order"),
          title: `${employeeName("order")}告警闭环记录已输出`,
          description: "上一轮自动派单、确认和关闭流程已生成处理摘要。",
          label: "流程",
          tagBg: employeeTag("order").bg,
          tagColor: employeeTag("order").color,
          timeText: "今天",
          isUrgent: false,
          isRunning: false,
        },
      ],
    },
    {
      id: "closed",
      title: "已关闭",
      dot: "#64748b",
      cards: [
        {
          id: "closed-knowledge-retro",
          ownerEmployeeIds: ["knowledge"],
          ownerLabel: employeeName("knowledge"),
          ownerColor: employeeColor("knowledge"),
          title: `${employeeName("knowledge")}历史方案归档已关闭`,
          description: "重复知识条目合并完成，旧版本方案已下线归档。",
          label: "知识",
          tagBg: employeeTag("knowledge").bg,
          tagColor: employeeTag("knowledge").color,
          timeText: "昨天",
          score: 4.8,
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "closed-fault-false-positive",
          ownerEmployeeIds: ["fault"],
          ownerLabel: employeeName("fault"),
          ownerColor: employeeColor("fault"),
          title: `${employeeName("fault")}误报告警复盘已关闭`,
          description: "阈值误触发问题已定位，处置记录已完成回收与复盘闭环。",
          label: "复盘",
          tagBg: "rgba(100, 116, 139, 0.15)",
          tagColor: "#94a3b8",
          timeText: "2天前",
          score: 4.6,
          isUrgent: false,
          isRunning: false,
        },
      ],
    },
  ];
}

export function buildDashboardEmployeeSnapshots(
  historyCounts: Record<string, number>,
  employees: typeof digitalEmployees,
  runtimeStatuses: Record<string, PortalEmployeeRuntimeStatus>,
): DashboardEmployeeSnapshot[] {
  const templates: Record<
    string,
    Omit<
      DashboardEmployeeSnapshot,
      | "id"
      | "name"
      | "desc"
      | "color"
      | "runtimeState"
      | "statusLabel"
      | "historyCount"
      | "urgent"
    >
  > = {
    resource: {
      currentJob: `${getEmployeeById("resource")?.name || "资产管理员"}核心网段纳管扫描中`,
      progress: 68,
      workStatus: "纳管扫描中",
      updatedAt: "2分钟前",
    },
    fault: {
      currentJob: `${getEmployeeById("fault")?.name || "故障分析专家"}端口 down 根因定位中`,
      progress: 84,
      workStatus: "根因定位中",
      updatedAt: "刚刚",
    },
    inspection: {
      currentJob: `${getEmployeeById("inspection")?.name || "巡检专家"}夜间健康巡检待执行`,
      progress: 12,
      workStatus: "待执行",
      updatedAt: "15分钟前",
    },
    order: {
      currentJob: `${getEmployeeById("order")?.name || "工单处置员"}告警派单流转中`,
      progress: 63,
      workStatus: "流转处理中",
      updatedAt: "4分钟前",
    },
    query: {
      currentJob: `${getEmployeeById("query")?.name || "数据分析专家"}设备分布报表生成中`,
      progress: 57,
      workStatus: "报表生成中",
      updatedAt: "7分钟前",
    },
    knowledge: {
      currentJob: `${getEmployeeById("knowledge")?.name || "知识库助手"}故障案例归档中`,
      progress: 46,
      workStatus: "知识整理中",
      updatedAt: "9分钟前",
    },
  };

  return employees.map((employee) => {
    const template = templates[employee.id];
    const runtime = runtimeStatuses[employee.id];
    const runtimeState = employee.status === "running" ? "running" : "idle";
    const statusLabel =
      runtime?.stateLabel ||
      (employee.urgent ? "紧急任务" : runtimeState === "running" ? "运行中" : "待机");
    return {
      id: employee.id,
      name: employee.name,
      desc: employee.desc,
      color: getDashboardEmployeeColor(employee.id),
      runtimeState,
      statusLabel,
      currentJob:
        runtime?.currentJob ||
        template?.currentJob ||
        (runtimeState === "running" ? `${employee.name}任务处理中` : "暂无对话"),
      historyCount: historyCounts[employee.id] || 0,
      progress: parseRuntimeProgress(runtime?.progress) ?? template?.progress ?? 0,
      workStatus:
        runtime?.workStatus ||
        template?.workStatus ||
        statusLabel,
      updatedAt: formatRuntimeUpdatedAt(runtime?.updatedAt || "") || template?.updatedAt || "刚刚",
      urgent: employee.urgent,
    };
  });
}

export function formatEmployeeStatsLabel(employee: (typeof digitalEmployees)[number]) {
  const total = employee.tasks.toLocaleString("zh-CN");
  switch (employee.id) {
    case PORTAL_HOME_ID:
      return "统一受理并协调后台能力";
    case "query":
      return `已分析 ${total} 份报表`;
    case "fault":
      return `已处置 ${total} 条事件`;
    case "resource":
      return `已管理 ${total} 台主机`;
    case "inspection":
      return `已巡检 ${total} 次`;
    case "order":
      return `已流转 ${total} 张工单`;
    case "knowledge":
      return `已命中 ${total} 条知识`;
    default:
      return `累计处理 ${total} 次`;
  }
}

export function getEmployeeProfileMotto(employeeId: string, fallback: string) {
  const mottos: Record<string, string> = {
    [PORTAL_HOME_ID]: "统一接入，按需协同",
    query: "精准洞察，数据即答案",
    fault: "秒级响应，闭环处置",
    resource: "精准纳管，一网打尽",
    inspection: "主动巡检，防患未然",
    order: "流转有序，协同闭环",
    knowledge: "知识即战力，随问随答",
  };

  return mottos[employeeId] || fallback;
}

export function getChatSidebarActivities(employeeId: string): ChatSidebarActivityItem[] {
  const activities: Record<string, ChatSidebarActivityItem[]> = {
    [PORTAL_HOME_ID]: [
      { id: "portal-home-activity-1", time: "10:32", text: "接收新的自然语言请求", tone: "green" },
      { id: "portal-home-activity-2", time: "10:08", text: "协调后台能力处理任务", tone: "blue" },
      { id: "portal-home-activity-3", time: "09:40", text: "汇总结果并回传会话", tone: "purple" },
      { id: "portal-home-activity-4", time: "09:18", text: "维护统一入口会话上下文", tone: "slate" },
    ],
    query: [
      { id: "query-activity-1", time: "10:23", text: "执行趋势分析任务", tone: "green" },
      { id: "query-activity-2", time: "09:45", text: "生成设备分布报表", tone: "blue" },
      { id: "query-activity-3", time: "09:12", text: "完成容量复盘摘要", tone: "purple" },
      { id: "query-activity-4", time: "08:30", text: "同步今日分析看板", tone: "slate" },
    ],
    fault: [
      { id: "fault-activity-1", time: "10:28", text: "接管 P1 告警工单", tone: "green" },
      { id: "fault-activity-2", time: "09:56", text: "完成根因定位分析", tone: "blue" },
      { id: "fault-activity-3", time: "09:20", text: "执行自动修复脚本", tone: "purple" },
      { id: "fault-activity-4", time: "08:48", text: "同步恢复验证结果", tone: "slate" },
    ],
    resource: [
      { id: "resource-activity-1", time: "10:15", text: "新增主机纳管入库", tone: "green" },
      { id: "resource-activity-2", time: "09:41", text: "同步云账号资产", tone: "blue" },
      { id: "resource-activity-3", time: "09:08", text: "生成资源拓扑关系", tone: "purple" },
      { id: "resource-activity-4", time: "08:20", text: "启动网段扫描任务", tone: "slate" },
    ],
    inspection: [
      { id: "inspection-activity-1", time: "10:02", text: "输出巡检日报", tone: "green" },
      { id: "inspection-activity-2", time: "09:36", text: "执行健康基线检查", tone: "blue" },
      { id: "inspection-activity-3", time: "08:58", text: "归档异常巡检项", tone: "purple" },
      { id: "inspection-activity-4", time: "08:12", text: "加载今日巡检计划", tone: "slate" },
    ],
    order: [
      { id: "order-activity-1", time: "10:18", text: "派发紧急变更工单", tone: "green" },
      { id: "order-activity-2", time: "09:44", text: "流转待审批任务", tone: "blue" },
      { id: "order-activity-3", time: "09:05", text: "关闭已完成工单", tone: "purple" },
      { id: "order-activity-4", time: "08:22", text: "同步 SLA 统计报表", tone: "slate" },
    ],
    knowledge: [
      { id: "knowledge-activity-1", time: "10:11", text: "更新知识条目摘要", tone: "green" },
      { id: "knowledge-activity-2", time: "09:39", text: "检索相似故障案例", tone: "blue" },
      { id: "knowledge-activity-3", time: "09:10", text: "生成处置建议草稿", tone: "purple" },
      { id: "knowledge-activity-4", time: "08:26", text: "同步知识库快照", tone: "slate" },
    ],
  };

  return activities[employeeId] || activities.query;
}

export const PORTAL_HOME_EMPLOYEE: DigitalEmployee = {
  id: PORTAL_HOME_ID,
  name: portalAppTitle,
  desc: "统一入口",
  icon: "fa-comments",
  tasks: 0,
  success: "100%",
  status: "running",
  urgent: false,
  gradient: "linear-gradient(135deg, #1d4ed8, #0f172a)",
  capabilities: [
    "自然语言对话",
    "统一入口接入",
    "后台能力协同",
    "运维问题受理",
  ],
  quickCommands: [
      RESOURCE_IMPORT_COMMAND,
    "知识库检索",
    "数据库响应很慢，请帮我定位",
    "查看待办工单",
  ],
  welcome:
    `您好！我是 ${portalAppTitle}，是当前 portal 对外的统一入口。<br><br>您可以直接和我对话，先从普通问题开始即可。`,
};

export type PendingPortalDispatch = {
  token: string;
  targetEmployeeId: string;
  content: string;
  visibleContent: string;
  forceNewChat?: boolean;
  alarmId?: string;
};

export type PortalLocationState = {
  gatewayPresentationEmployeeId?: string;
  pendingPortalDispatch?: PendingPortalDispatch;
  pendingResourceImport?: {
    token: string;
    targetEmployeeId: string;
    visibleContent: string;
  };
  pendingKnowledgeBase?: {
    token: string;
    targetEmployeeId: string;
    visibleContent: string;
  };
  pendingKnowledgeSearch?: {
    token: string;
    targetEmployeeId: string;
    visibleContent: string;
  };
  openHistoryForEmployeeId?: string;
  openSession?: {
    employeeId: string;
    sessionId: string;
  };
  workbenchInitialPrompt?: {
    token: string;
    prompt: string;
    source?: "nl-customization";
  };
};

export type PortalOpsAlertLevel = "critical" | "urgent" | "warning" | "info";

export type PortalOpsAlert = {
  id: string;
  resId: string;
  employeeId: string;
  level: PortalOpsAlertLevel;
  message: string;
  timeLabel: string;
  routeEntry?: string | null;
  dispatchContent?: string;
  visibleContent?: string;
};

export type PortalAlertToastState = {
  alert: PortalOpsAlert;
  visible: boolean;
};

export type ChatSidebarSectionKey = "profile" | "activity" | "efficiency" | "collaboration";

export type ChatSidebarActivityItem = {
  id: string;
  text: string;
  time: string;
  tone: "green" | "blue" | "purple" | "slate";
};

export const PORTAL_ALERT_LEVEL_LABELS: Record<PortalOpsAlertLevel, string> = {
  critical: "紧急",
  urgent: "严重",
  warning: "警告",
  info: "通知",
};

export const PORTAL_ALERT_LEVEL_COLORS: Record<PortalOpsAlertLevel, string> = {
  critical: "#ef4444",
  urgent: "#f97316",
  warning: "#f59e0b",
  info: "#22d3ee",
};

export type SessionRecord = {
  id: string;
  employeeId?: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  messages?: any[];
  sessionId?: string;
  status?: string;
  meta?: Record<string, unknown>;
  detail?: string;
  tag?: string;
};

export type ConversationStoreState = Record<string, SessionRecord[]>;
export type ExecutionRecord = {
  id: string | number;
  time?: string;
  title?: string;
  detail?: string;
  agent?: string;
  agentIcon?: string;
  status?: string;
};

export function loadPageTheme(): "light" | "dark" {
  if (typeof window === "undefined") {
    return "light";
  }

  try {
    return window.localStorage.getItem(PAGE_THEME_STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch (error) {
    console.error("Failed to load persisted page theme:", error);
    return "light";
  }
}

export function persistPageTheme(theme: "light" | "dark"): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(PAGE_THEME_STORAGE_KEY, theme);
  } catch (error) {
    console.error("Failed to persist page theme:", error);
  }
}

export function loadSidebarCollapsed(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function persistSidebarCollapsed(collapsed: boolean): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(collapsed));
  } catch {
    // ignore
  }
}

export function loadChatSidebarCollapsed(): boolean {
  if (typeof window === "undefined") {
    return true;
  }
  try {
    const storedValue = window.localStorage.getItem(CHAT_SIDEBAR_COLLAPSED_STORAGE_KEY);
    if (storedValue === null) {
      return true;
    }
    return storedValue === "true";
  } catch {
    return true;
  }
}

export function persistChatSidebarCollapsed(collapsed: boolean): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(CHAT_SIDEBAR_COLLAPSED_STORAGE_KEY, String(collapsed));
  } catch {
    // ignore
  }
}

export function ensureSessionRecords(value: unknown): SessionRecord[] {
  return Array.isArray(value) ? (value as SessionRecord[]) : [];
}

export function ensureObjectArray<T = Record<string, unknown>>(value: unknown): T[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is T => typeof item === "object" && item !== null,
  );
}

export function ensureStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

export function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function extractMentionTarget(rawContent: string) {
  const normalizedContent = String(rawContent || "").trim();
  if (!normalizedContent.includes("@")) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const employeeNames = [...digitalEmployees]
    .sort((left, right) => right.name.length - left.name.length)
    .map((employee) => escapeRegExp(employee.name))
    .join("|");

  if (!employeeNames) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const mentionPattern = new RegExp(`@\\s*(${employeeNames})`);
  const matched = normalizedContent.match(mentionPattern);
  if (!matched?.[1]) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const employee = digitalEmployees.find((item) => item.name === matched[1]) || null;
  if (!employee) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const cleanContent = normalizedContent
    .replace(mentionPattern, "")
    .replace(/^[\s,，:：;；-]+/, "")
    .trim();

  return {
    employee,
    cleanContent,
    visibleContent: normalizedContent,
  };
}

export function resolveEmployeeAgentId(employeeId: string) {
  return REMOTE_AGENT_IDS[employeeId] || employeeId;
}

export function buildMentionCollaborationPrompt({
  currentEmployee,
  currentAgentId,
  targetEmployee,
  userRequest,
  preferBackground = false,
}: {
  currentEmployee: any;
  currentAgentId: string;
  targetEmployee: any;
  userRequest: string;
  preferBackground?: boolean;
}) {
  const targetAgentId = resolveEmployeeAgentId(String(targetEmployee?.id || ""));
  const normalizedRequest = String(userRequest || "").trim();
  const isQueryAgent = targetAgentId === "query";
  const requestLooksLikeTopology = /拓扑|topology|关系图|树状图|echarts/i.test(normalizedRequest);
  const extraCollaborationHints =
    isQueryAgent && requestLooksLikeTopology
      ? [
          "本次协作涉及 CMDB 资源关系拓扑时，请优先使用 query 数字员工已启用的 zgops-cmdb skill。",
          "如果拿到了应用或资源拓扑，请直接返回可渲染的 ```echarts 代码块，优先使用 tree 树状图并设置从左到右展开，不要只返回文字摘要。",
        ]
      : [];
  const executionHints = preferBackground
    ? [
        "这次协同可能耗时较长，但如果改用 chat_with_agent 协同，仍应先做一次前台调用，timeout 建议 60 秒。",
        "只有 chat_with_agent 明确超时、用户要求后台执行，或任务确实需要长时间批处理时，才改用 submit_to_agent / check_agent_task 后台路径。",
        "不要为了普通查询、告警查询、CMDB 查询或拓扑查询默认使用 qwenpaw agents chat --background 轮询。",
      ]
    : [];

  return [
    `你当前是数字员工「${currentEmployee?.name || currentAgentId}」。`,
    `用户在当前会话中 @ 了另一位数字员工「${targetEmployee?.name || targetAgentId}」。`,
    "请不要要求用户切换页面，也不要把本次请求交回前端路由处理。",
    "处理顺序：① 先看你当前工作区已启用的本地 skill / 工具能否直接完成本次请求，可以就直接执行并回复；② 本地能力缺失、配置不全或执行失败时，使用内置工具 chat_with_agent 发起前台智能体协同并整合结果；③ chat_with_agent 不可用时，再退回 Multi-Agent Collaboration（multi_agent_collaboration）技能。",
    "需要协同时使用 chat_with_agent，参数示例：to_agent 为目标智能体 ID，text 为任务正文，timeout 建议 60。",
    "给目标智能体的协同请求正文请直接概括任务本身，不要重复写 [Agent ... requesting]，也不要以 User explicitly asked... 这类泛化说明开头。",
    ...executionHints,
    ...extraCollaborationHints,
    `当前智能体（from-agent）：${currentAgentId}`,
    `目标智能体（to-agent）：${targetAgentId}`,
    normalizedRequest
      ? `用户希望协同处理的内容：${normalizedRequest}`
      : `用户目前只 @ 了「${targetEmployee?.name || targetAgentId}」，请先确认需要对方协助的具体问题，再决定如何发起协同。`,
  ].join("\n");
}

export function buildResourceImportTopologyCollaborationRequest(scope: {
  includesProject: boolean;
  applicationName: string;
  ciIds: Array<string | number>;
  resources: Array<{
    ciId?: string | number;
    ciType?: string;
    name?: string;
    previewKey?: string;
  }>;
}) {
  const ciIdText = scope.ciIds.join(", ");
  const resourceSummary = scope.resources
    .slice(0, 12)
    .map((item) => `${item.name || item.previewKey || "未命名资源"}(${item.ciType || "未分类"}${item.ciId ? `, CI ID: ${item.ciId}` : ""})`)
    .join("；");
  const ciCountText = scope.ciIds.length ? `${scope.ciIds.length} 个` : "0 个";

  if (scope.includesProject && scope.applicationName) {
    return [
      `请基于本次导入结果，查询应用 ${scope.applicationName} 的 CMDB 关系拓扑。`,
      `这次导入/保留的资源范围共 ${ciCountText} CI，CI ID：${ciIdText || "无"}。`,
      resourceSummary ? `本次导入资源摘要：${resourceSummary}。` : "",
      "请优先围绕这次导入涉及的资源构建结果，不要扩展到无关应用或全系统。",
      "如支持按 CI ID 或应用过滤，请先过滤再查询。",
      "请优先使用已启用的 zgops-cmdb skill，并返回可直接渲染的 ```echarts 代码块，优先 tree 树状图，从左到右展开。",
    ].filter(Boolean).join("\n");
  }

  if (scope.ciIds.length) {
    return [
      "请基于本次导入结果，查询这批资源之间的局部 CMDB 拓扑。",
      `本次导入/保留的资源共 ${ciCountText} CI，CI ID：${ciIdText}。`,
      resourceSummary ? `本次导入资源摘要：${resourceSummary}。` : "",
      "不要查询全系统，也不要自动扩展到无关应用。",
      "只返回这些资源之间的节点和关系；没有关系的资源也要作为独立节点展示。",
      "请优先使用已启用的 zgops-cmdb skill，并返回可直接渲染的 ```echarts 代码块，优先 tree 树状图，从左到右展开。",
    ].filter(Boolean).join("\n");
  }

  return [
    "用户希望查看本次导入拓扑，但当前上下文没有可靠的导入范围。",
    "请先提示用户重新选择导入结果，或明确本次导入的应用/资源范围后再查询。",
  ].join("\n");
}

export function extractMentionQuery(value: string, cursorPosition: number | null) {
  const safeCursor = cursorPosition ?? value.length;
  const beforeCursor = String(value || "").slice(0, safeCursor);
  const matched = beforeCursor.match(/(^|\s)@([^\s@]*)$/);
  if (!matched) {
    return null;
  }

  const query = matched[2] || "";
  return {
    query,
    start: safeCursor - query.length - 1,
    end: safeCursor,
  };
}

export function scoreMentionCandidate(employee: (typeof digitalEmployees)[number], query: string) {
  const normalizedQuery = query.trim();
  if (!normalizedQuery) {
    return 1;
  }

  const sources = [
    employee.name,
    employee.desc,
    ...(EMPLOYEE_MENTION_ALIASES[employee.id] || []),
  ].filter(Boolean);

  let bestScore = 0;
  for (const source of sources) {
    if (source === normalizedQuery) {
      bestScore = Math.max(bestScore, 100);
      continue;
    }
    if (source.startsWith(normalizedQuery)) {
      bestScore = Math.max(bestScore, 80);
      continue;
    }
    if (source.includes(normalizedQuery)) {
      bestScore = Math.max(bestScore, 60);
      continue;
    }

    const overlap = [...normalizedQuery].filter((char) => source.includes(char)).length;
    if (overlap > 0) {
      bestScore = Math.max(bestScore, overlap * 10);
    }
  }

  return bestScore;
}

export function buildPortalAssistantReply(content: string) {
  const normalized = String(content || "").trim();
  const isOrderIntent = /工单|待办|已办|审批|流程|派单|转派/.test(normalized);
  const suggestions = [
    { employee: "工单处置员", keywords: ["工单", "待办", "已办", "审批", "流程", "派单", "转派"] },
    { employee: "数据分析专家", keywords: ["设备", "指标", "报表", "趋势", "性能", "查询", "可用性", "告警", "报警"] },
    { employee: "故障分析专家", keywords: ["故障", "异常", "超时", "中断", "恢复", "慢", "处置", "根因"] },
    { employee: "资产管理员", keywords: ["资产", "纳管", "扫描", "发现", "拓扑", "资源"] },
    { employee: "巡检专家", keywords: ["巡检", "健康", "检查", "日报", "周报"] },
    { employee: "知识库助手", keywords: ["怎么", "最佳实践", "方案", "知识", "原理"] },
  ];
  const rankedSuggestions = isOrderIntent
    ? suggestions
    : [...suggestions.slice(1), suggestions[0]];

  const recommended = rankedSuggestions
    .filter((item) => item.keywords.some((keyword) => normalized.includes(keyword)))
    .map((item) => item.employee)
    .slice(0, 2);

  const recommendationLine = recommended.length
    ? `更适合接手的数字员工：${recommended.map((name) => `\`@${name}\``).join("、")}。`
    : "如果您已经知道处理角色，可以直接在问题前加上 `@数字员工名`。";

  return [
    "我已经收到您的问题。",
    "",
    recommendationLine,
    "",
    "当前支持的常用协同方式：",
    "- 直接点击上方数字员工标签，进入该员工专属对话",
    "- 输入 `@数字员工名 + 需求`，我会自动切换并执行对应员工逻辑",
    "",
    "可直接复制这些示例继续：",
    "- `当前有哪些设备？`",
    "- `数据库响应很慢，请帮我定位`",
    `- \`${RESOURCE_IMPORT_COMMAND}\``,
  ].join("\n");
}

export function buildPortalAlertDispatchText(content: string, resId?: string, eventTime?: string) {
  const normalizedContent = String(content || "").trim();
  const normalizedResId = String(resId || "").trim();
  const normalizedEventTime = String(eventTime || "").trim();
  const appendedLines: string[] = [];

  if (normalizedResId) {
    const resIdLine = `资源 ID（CI ID）：${normalizedResId}`;
    if (!normalizedContent.includes(resIdLine)) {
      appendedLines.push(resIdLine);
    }
  }

  if (normalizedEventTime) {
    const eventTimeLine = `告警时间：${normalizedEventTime}`;
    if (!normalizedContent.includes(eventTimeLine)) {
      appendedLines.push(eventTimeLine);
    }
  }

  if (!normalizedContent) {
    return appendedLines.join("\n");
  }
  if (!appendedLines.length) {
    return normalizedContent;
  }
  return `${normalizedContent}\n${appendedLines.join("\n")}`;
}
