import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import * as XLSX from "xlsx";
import {
  getResourceImportMetadata,
  getResourceImportStart,
  previewResourceImport,
} from "../../api/resourceImport";
import type {
  ResourceImportCiTypeAttributeDefinition,
  ResourceImportCiTypeMetadata,
  ResourceImportGroup,
  ResourceImportMetadata,
  ResourceImportPreviewJob,
  ResourceImportPreview,
  ResourceImportRecord,
  ResourceImportRelation,
  ResourceImportResult,
  ResourceImportStartPayload,
} from "../../types/resourceImport";
import "./resource-import-conversation.css";

export type ResourceImportFlowStage =
  | "intro"
  | "parsing"
  | "structure"
  | "confirm"
  | "topology"
  | "importing"
  | "result";

type ResourceImportFileSummary = {
  name: string;
  size: number;
};

type ResourceImportRecordIssue = NonNullable<ResourceImportRecord["issues"]>[number];
type ResourceImportRequiredIssue = ResourceImportRecordIssue & {
  previewKey: string;
  ciType: string;
  recordName: string;
  sourceLabel: string;
};
type ResourceImportDefaultedRequiredIssue = ResourceImportRequiredIssue & {
  defaultValue: string;
};

export type ResourceImportFlowPayload = {
  flowId: string;
  stage: ResourceImportFlowStage;
  files?: ResourceImportFileSummary[];
  status?: "idle" | "running" | "completed" | "error";
  preview?: ResourceImportPreview | null;
  resourceGroups?: ResourceImportGroup[];
  relations?: ResourceImportRelation[];
  result?: ResourceImportResult | null;
  error?: string;
  locked?: boolean;
  readonly?: boolean;
};

type ResourceImportConversationCardProps = {
  agentId?: string | null;
  message: {
    id: string;
    resourceImportFlow?: ResourceImportFlowPayload;
  };
  onUploadFiles: (payload: {
    sourceMessageId: string;
    flowId: string;
    files: File[];
  }) => void;
  onStartParse: (payload: {
    messageId: string;
    flowId: string;
  }) => void;
  onParseResolved: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview;
  }) => void;
  onParseFailed: (payload: {
    messageId: string;
    flowId: string;
    error: string;
  }) => void;
  onReturnToUpload: (payload: {
    flowId: string;
    sourceMessageId?: string;
  }) => void;
  onBuildTopology: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview | null;
    resourceGroups: ResourceImportGroup[];
    relations: ResourceImportRelation[];
  }) => void;
  onConfirmStructure: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview | null;
    resourceGroups: ResourceImportGroup[];
    relations: ResourceImportRelation[];
  }) => void;
  onBackToConfirm: (payload: {
    messageId: string;
    flowId: string;
  }) => void;
  onSubmitImport: (payload: {
    messageId: string;
    flowId: string;
    preview: ResourceImportPreview | null;
    resourceGroups: ResourceImportGroup[];
    relations: ResourceImportRelation[];
  }) => void;
  onContinueImport: (payload: {
    flowId: string;
  }) => void;
  onOpenSystemTopology: (payload: {
    flowId: string;
  }) => void;
  onScrollToStage: (payload: {
    flowId: string;
    stage: ResourceImportFlowStage;
  }) => void;
  resolveFiles: (flowId: string) => File[];
  releaseFiles: (flowId: string) => void;
};

const FLOW_STEPS = [
  { index: 1, icon: "📂", label: "上传文件" },
  { index: 2, icon: "🔍", label: "AI解析" },
  { index: 3, icon: "✅", label: "确认数据" },
  { index: 4, icon: "🔗", label: "建立关系" },
  { index: 5, icon: "🚀", label: "导入CMDB" },
] as const;

const CUSTOM_STRUCTURE_OPTION_VALUE = "__custom__";

const STATUS_OPTIONS = ["待确认", "未监控", "已纳管", "在线", "离线", "告警"] as const;
const ATTRIBUTE_FIELD_LABELS: Record<string, string> = {
  asset_code: "资产编号",
  name: "名称",
  private_ip: "内网IP",
  public_ip: "公网IP",
  status: "状态",
  vendor: "厂商",
  model: "型号",
  version: "版本",
  service_port: "服务端口",
  monitor_status: "监控接入",
  host_name: "宿主机/部署主机",
  deploy_target: "部署目标",
  upstream_resource: "上联/依赖资源",
  os_version: "操作系统版本",
  owner: "维护团队",
  environment: "运行环境",
  description: "说明",
  dev_no: "设备编码",
  dev_name: "设备名称",
  manage_ip: "管理IP",
  dev_model: "设备型号",
  dev_class: "设备类型",
  alarm_status: "告警状态",
  dev_software_version: "设备软件版本",
  dev_sn: "设备序列号",
  property_no: "资产编号",
  city: "地市",
  county: "区县",
  data_center: "所属数据中心",
  server_room: "所属机房",
  platform: "平台",
  op_duty: "运维负责人",
  u_count: "U数",
  u_start: "起始U位",
  cabinet: "所属机柜",
  buy_date: "采购日期",
  maintain_enddate: "过保日期",
  proto_snmp: "SNMP版本",
  snmp_port: "SNMP端口",
  snmp_read: "读口令",
  snmp_write: "写口令",
};
const ATTRIBUTE_FIELD_ORDER = [
  "asset_code",
  "name",
  "private_ip",
  "public_ip",
  "status",
  "vendor",
  "model",
  "version",
  "service_port",
  "monitor_status",
  "host_name",
  "deploy_target",
  "upstream_resource",
  "os_version",
  "owner",
  "environment",
  "description",
] as const;
const DEFAULT_PARSE_LOGS = [
  "→ 文件已上传，等待后台开始解析...",
  "→ 正在读取文件内容与 sheet 结构...",
  "→ 正在并行执行字段语义映射...",
  "→ 正在执行数据清洗与标准化...",
  "→ 正在推断资源关系与拓扑...",
  "→ 正在生成待确认预览结果...",
] as const;
const ROOT_RELATION_TYPES = new Set(["project", "product", "Department"]);
const RESOURCE_DEPLOY_TYPES = new Set(["PhysicalMachine", "vserver", "docker", "kubernetes"]);
const SOFTWARE_RESOURCE_TYPES = new Set([
  "database",
  "mysql",
  "PostgreSQL",
  "redis",
  "Kafka",
  "elasticsearch",
  "nginx",
  "apache",
  "docker",
  "kubernetes",
]);

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

function formatFileSize(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileEmoji(name: string) {
  const extension = name.split(".").pop()?.toLowerCase() || "";
  if (["xlsx", "xls", "csv"].includes(extension)) {
    return "📊";
  }
  if (["doc", "docx", "txt", "md"].includes(extension)) {
    return "📝";
  }
  if (["png", "jpg", "jpeg"].includes(extension)) {
    return "🖼️";
  }
  return "📄";
}

function countSelectedRecords(groups: ResourceImportGroup[]) {
  return groups.reduce(
    (total, group) => total + group.records.filter((record) => record.selected).length,
    0,
  );
}

function getRecordAddress(record: ResourceImportRecord) {
  return (
    record.attributes.manage_ip
    || record.attributes.private_ip
    || record.attributes.host
    || record.attributes.host_name
    || record.attributes.public_ip
    || "-"
  );
}

function getDisplayName(record: ResourceImportRecord) {
  return record.name || "待确认";
}

function getDisplayStatus(record: ResourceImportRecord) {
  return record.attributes.status || record.attributes.alarm_status || "待确认";
}

function getAttributeLabel(key: string) {
  return ATTRIBUTE_FIELD_LABELS[key] || key;
}

function parseRowPreviewKey(previewKey: string) {
  const raw = String(previewKey || "").trim();
  const match = raw.match(/^row::(.+?)::(.+?)::(\d+)$/);
  if (!match) {
    return null;
  }
  return {
    fileName: match[1],
    sheetName: match[2],
    rowIndex: match[3],
  };
}

function getResultItemTitle(
  item: { previewKey?: string },
  recordMap: Map<string, ResourceImportRecord>,
) {
  const previewKey = String(item.previewKey || "").trim();
  const record = recordMap.get(previewKey);
  const source = record?.sourceRows?.[0];
  if (source?.filename && source?.sheet && source?.rowIndex !== undefined) {
    const name = String(record?.name || "").trim();
    return name
      ? `${source.filename} / ${source.sheet} / 第 ${source.rowIndex} 行 · ${name}`
      : `${source.filename} / ${source.sheet} / 第 ${source.rowIndex} 行`;
  }
  const parsed = parseRowPreviewKey(previewKey);
  if (parsed) {
    return `${parsed.fileName} / ${parsed.sheetName} / 第 ${parsed.rowIndex} 行`;
  }
  return String(record?.name || previewKey || "未命名记录").trim();
}

function getCiTypeMeta(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
) {
  return preview?.ciTypeMetadata?.[ciType] || null;
}

function getMetadataCiTypeMeta(
  metadata: ResourceImportMetadata | null | undefined,
  ciType: string,
) {
  return (metadata?.ciTypes || []).find((item) => item.name === ciType) || null;
}

function getVisibleAttributeDefinitions(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
  record: ResourceImportRecord,
) {
  const typeMeta = getCiTypeMeta(preview, ciType);
  const definitions = typeMeta?.attributeDefinitions || [];
  const visibleDefinitions = definitions.filter((item) => item.default_show || item.required);
  const definitionMap = new Map(definitions.map((item) => [item.name, item]));

  Object.keys(record.attributes || {}).forEach((key) => {
    if (!definitionMap.has(key)) {
      visibleDefinitions.push({
        name: key,
        alias: getAttributeLabel(key),
      });
      definitionMap.set(key, visibleDefinitions[visibleDefinitions.length - 1]);
    }
  });

  return visibleDefinitions.sort((left, right) => {
    const leftRequired = left.required ? 0 : 1;
    const rightRequired = right.required ? 0 : 1;
    return leftRequired - rightRequired || (left.alias || left.name).localeCompare(right.alias || right.name, "zh-CN");
  });
}

function getRequiredAttributeDefinitions(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
) {
  const typeMeta = getCiTypeMeta(preview, ciType);
  if (!typeMeta) {
    return [];
  }
  const systemGeneratedUniqueKey = typeMeta?.system_generated_unique_key
    ? String(typeMeta.unique_key || "").trim()
    : "";
  const requiredDefinitions = (typeMeta.attributeDefinitions || []).filter((definition) => {
    const fieldName = String(definition.name || "").trim();
    if (!fieldName || !definition.required) {
      return false;
    }
    return !(systemGeneratedUniqueKey && fieldName === systemGeneratedUniqueKey);
  });
  if (requiredDefinitions.length) {
    return requiredDefinitions;
  }
  const uniqueKey = String(typeMeta.unique_key || "").trim();
  if (!uniqueKey || systemGeneratedUniqueKey) {
    return [];
  }
  return [{
    name: uniqueKey,
    alias: getAttributeLabel(uniqueKey),
    required: true,
  }];
}

function getChoiceOptions(definition?: ResourceImportCiTypeAttributeDefinition | null) {
  return definition?.choices || [];
}

function isServerDefaultMacro(value: unknown) {
  return String(value ?? "").trim().startsWith("$");
}

function cleanDefaultValue(value: unknown) {
  const cleaned = String(value ?? "").trim();
  return cleaned && !isServerDefaultMacro(cleaned) ? cleaned : "";
}

function getAttributeDefaultValue(definition?: ResourceImportCiTypeAttributeDefinition | null) {
  if (!definition) {
    return "";
  }
  const rawDefault = definition.default;
  if (rawDefault && typeof rawDefault === "object" && !Array.isArray(rawDefault)) {
    const defaultObject = rawDefault as Record<string, unknown>;
    for (const key of ["default", "value", "label"]) {
      const value = cleanDefaultValue(defaultObject[key]);
      if (value) {
        return value;
      }
    }
  } else if (Array.isArray(rawDefault)) {
    for (const item of rawDefault) {
      const value = cleanDefaultValue(item);
      if (value) {
        return value;
      }
    }
  } else {
    const value = cleanDefaultValue(rawDefault);
    if (value) {
      return value;
    }
  }

  const fieldName = String(definition.name || "").trim().toLowerCase();
  const fieldAlias = String(definition.alias || "").trim();
  if (fieldName === "status" || fieldAlias === "资产状态") {
    const onlineOption = (definition.choices || []).find(
      (option) => option.value === "在线" || option.label === "在线",
    );
    if (onlineOption) {
      return onlineOption.value || onlineOption.label || "";
    }
    const firstOption = (definition.choices || []).find((option) => option.value || option.label);
    return firstOption?.value || firstOption?.label || "";
  }
  return "";
}

function hasEffectiveAttributeDefault(definition?: ResourceImportCiTypeAttributeDefinition | null) {
  const defaultValue = getAttributeDefaultValue(definition);
  if (!defaultValue) {
    return false;
  }
  if (!definition?.is_choice) {
    return true;
  }
  const options = definition.choices || [];
  return !options.length || options.some((option) => option.value === defaultValue || option.label === defaultValue);
}

function requiredFieldNeedsManualValue(
  record: ResourceImportRecord,
  field: string,
  definition?: ResourceImportCiTypeAttributeDefinition | null,
) {
  if (!definition?.required) {
    return false;
  }
  return isEmptyValue(getRecordFieldValue(record, field)) && !hasEffectiveAttributeDefault(definition);
}

function getRequiredDefaultMessage(
  record: ResourceImportRecord,
  field: string,
  definition?: ResourceImportCiTypeAttributeDefinition | null,
) {
  if (!definition?.required || !isEmptyValue(getRecordFieldValue(record, field))) {
    return "";
  }
  const defaultValue = getAttributeDefaultValue(definition);
  if (!defaultValue || !hasEffectiveAttributeDefault(definition)) {
    return "";
  }
  return `未填写将使用模型默认值：${defaultValue}`;
}

type ResourceImportStructureItem = NonNullable<
  ResourceImportPreview["structureAnalysis"]
>["items"][number];

function getStructureStatusLabel(status: ResourceImportStructureItem["status"]) {
  switch (status) {
    case "matched":
      return "已匹配";
    case "ambiguous_model":
      return "待确认模型";
    case "missing_group":
      return "待创建分组";
    case "missing_model":
      return "待创建模型";
    default:
      return "待确认";
  }
}

function getStructureConfidenceLabel(confidence?: ResourceImportStructureItem["semanticConfidence"]) {
  switch (confidence) {
    case "high":
      return "高";
    case "medium":
      return "中";
    default:
      return "低";
  }
}

function getBlockingAnalysisIssues(preview: ResourceImportPreview | null | undefined) {
  return (preview?.analysisIssues || []).filter((item) => item.severity === "blocking");
}

function getBlockingAnalysisMessage(preview: ResourceImportPreview | null | undefined) {
  const blockingIssues = getBlockingAnalysisIssues(preview);
  if (!blockingIssues.length) {
    return "";
  }
  return "本次解析存在关键失败，当前结果可能不完整，已禁止继续导入。请重新解析后再试。";
}

function getTopologyPalette(ciType: string, generated: boolean) {
  if (generated) {
    return {
      fill: "#fff7ed",
      border: "#fb923c",
      shadow: "rgba(249, 115, 22, 0.18)",
      badge: "#ffedd5",
      text: "#9a3412",
      line: "#fdba74",
    };
  }
  const normalized = String(ciType || "").toLowerCase();
  if (["project", "product", "department"].includes(normalized)) {
    return {
      fill: "#ecfeff",
      border: "#14b8a6",
      shadow: "rgba(20, 184, 166, 0.18)",
      badge: "#ccfbf1",
      text: "#0f766e",
      line: "#5eead4",
    };
  }
  if (["physicalmachine", "vserver"].includes(normalized)) {
    return {
      fill: "#eff6ff",
      border: "#3b82f6",
      shadow: "rgba(59, 130, 246, 0.18)",
      badge: "#dbeafe",
      text: "#1d4ed8",
      line: "#93c5fd",
    };
  }
  if (["database", "mysql", "postgresql"].includes(normalized)) {
    return {
      fill: "#fff7ed",
      border: "#f97316",
      shadow: "rgba(249, 115, 22, 0.16)",
      badge: "#fed7aa",
      text: "#c2410c",
      line: "#fdba74",
    };
  }
  if (["redis", "kafka", "elasticsearch", "nginx", "apache", "docker", "kubernetes"].includes(normalized)) {
    return {
      fill: "#faf5ff",
      border: "#8b5cf6",
      shadow: "rgba(139, 92, 246, 0.16)",
      badge: "#ede9fe",
      text: "#6d28d9",
      line: "#c4b5fd",
    };
  }
  if (normalized === "networkdevice") {
    return {
      fill: "#ecfdf5",
      border: "#22c55e",
      shadow: "rgba(34, 197, 94, 0.16)",
      badge: "#dcfce7",
      text: "#15803d",
      line: "#86efac",
    };
  }
  return {
    fill: "#f8fafc",
    border: "#94a3b8",
    shadow: "rgba(148, 163, 184, 0.16)",
    badge: "#e2e8f0",
    text: "#475569",
    line: "#cbd5e1",
  };
}

function truncateTopologyText(value: string, maxLength = 22) {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function getMappingStatusLabel(status?: string) {
  switch (status) {
    case "needs_confirmation":
      return "待确认";
    case "mapped":
      return "已应用";
    default:
      return "未应用";
  }
}

function formatAutoFilledHint(hints?: string[]) {
  if (!hints?.length) {
    return "";
  }
  return `已自动补全：${hints.join("、")}`;
}

function buildAggregatedAmbiguousMappings(
  items: NonNullable<ResourceImportPreview["mappingSummary"]>,
) {
  const grouped = new Map<string, {
    sourceField: string;
    message: string;
    candidates: Array<{ targetField: string; confidence: string; source?: string }>;
    scopes: Array<{ fileName: string; sheetName: string }>;
  }>();

  items.forEach((item) => {
    if (!(item.status === "needs_confirmation" || item.needsConfirmation)) {
      return;
    }
    const candidates = (item.candidates || [])
      .filter((candidate) => candidate?.targetField)
      .map((candidate) => ({
        targetField: String(candidate.targetField || ""),
        confidence: String(candidate.confidence || ""),
        source: candidate.source,
      }))
      .sort((left, right) =>
        left.targetField.localeCompare(right.targetField, "zh-CN")
        || left.confidence.localeCompare(right.confidence, "zh-CN"),
      );
    const candidateKey = candidates.map((candidate) => `${candidate.targetField}:${candidate.confidence}`).join("|");
    const key = `${item.sourceField}::${candidateKey}`;
    const scope = {
      fileName: String(item.fileName || ""),
      sheetName: String(item.sheetName || "当前文件"),
    };
    const current = grouped.get(key);
    if (current) {
      if (!current.scopes.some((entry) => entry.fileName === scope.fileName && entry.sheetName === scope.sheetName)) {
        current.scopes.push(scope);
      }
      return;
    }
    grouped.set(key, {
      sourceField: String(item.sourceField || ""),
      message: String(item.message || ""),
      candidates,
      scopes: [scope],
    });
  });

  return Array.from(grouped.values())
    .map((item) => ({
      ...item,
      scopes: item.scopes.sort((left, right) =>
        left.fileName.localeCompare(right.fileName, "zh-CN")
        || left.sheetName.localeCompare(right.sheetName, "zh-CN"),
      ),
    }))
    .sort((left, right) =>
      left.sourceField.localeCompare(right.sourceField, "zh-CN")
      || right.scopes.length - left.scopes.length,
    );
}

function buildTopologyTreeData(
  resourceGroups: ResourceImportGroup[],
  relations: ResourceImportRelation[],
  options?: {
    collapsedDepth?: number;
  },
) {
  const selectedRecords = resourceGroups
    .flatMap((group) => group.records)
    .filter((record) => record.selected);
  const selectedRelations = relations.filter((relation) => relation.selected);
  const recordMap = new Map(selectedRecords.map((record) => [record.previewKey, record]));
  const collapsedDepth = options?.collapsedDepth ?? Number.POSITIVE_INFINITY;
  const relationPriority: Record<string, number> = {
    contain: 0,
    deploy: 1,
    install: 2,
    connect: 3,
  };

  const parentChoiceMap = new Map<string, ResourceImportRelation>();
  selectedRelations.forEach((relation) => {
    if (!recordMap.has(relation.sourceKey) || !recordMap.has(relation.targetKey)) {
      return;
    }
    const current = parentChoiceMap.get(relation.targetKey);
    const nextPriority = relationPriority[relation.relationType] ?? 99;
    const currentPriority = current ? (relationPriority[current.relationType] ?? 99) : Number.POSITIVE_INFINITY;
    if (!current || nextPriority < currentPriority) {
      parentChoiceMap.set(relation.targetKey, relation);
    }
  });

  const childMap = new Map<string, string[]>();
  parentChoiceMap.forEach((relation, targetKey) => {
    const sourceKey = relation.sourceKey;
    const current = childMap.get(sourceKey) || [];
    current.push(targetKey);
    childMap.set(sourceKey, current);
  });

  const buildNode = (previewKey: string, relationTypeFromParent = "", depth = 0): any => {
    const record = recordMap.get(previewKey);
    if (!record) {
      return null;
    }
    const palette = getTopologyPalette(record.ciType, Boolean(record.generated));
    const children = (childMap.get(previewKey) || [])
      .map((childKey) => buildNode(childKey, parentChoiceMap.get(childKey)?.relationType || "", depth + 1))
      .filter(Boolean);
    children.sort((left, right) => {
      const leftBranch = left.children?.length ? 1 : 0;
      const rightBranch = right.children?.length ? 1 : 0;
      if (leftBranch !== rightBranch) {
        return rightBranch - leftBranch;
      }
      const leftDescendants = Number(left.descendantCount || 0);
      const rightDescendants = Number(right.descendantCount || 0);
      if (leftDescendants !== rightDescendants) {
        return rightDescendants - leftDescendants;
      }
      return String(left.name || "").localeCompare(String(right.name || ""), "zh-CN");
    });
    const descendantCount = children.reduce(
      (total, child) => total + 1 + Number(child.descendantCount || 0),
      0,
    );
    const shouldCollapse = children.length > 0 && depth >= collapsedDepth;
    return {
      id: previewKey,
      name: record.name || previewKey,
      value: record.ciType,
      typeLabel: record.ciType || "未分类",
      relationTypeFromParent,
      descendantCount,
      collapsed: shouldCollapse,
      symbolSize: children.length ? 10 : 7,
      itemStyle: {
        color: palette.border,
        borderColor: palette.border,
        borderWidth: 1,
        shadowBlur: 0,
        shadowOffsetY: 0,
        shadowColor: "transparent",
        opacity: 0.96,
      },
      label: {
        position: "right",
        distance: 10,
        formatter: () => (
          `{name|${truncateTopologyText(record.name || previewKey)}}`
          + ` {meta|${truncateTopologyText(record.ciType || "未分类", 14)}}`
          + (descendantCount ? ` {count|+${descendantCount}}` : "")
        ),
        rich: {
          name: {
            color: "#0f172a",
            fontSize: 12,
            fontWeight: 600,
            lineHeight: 16,
          },
          meta: {
            color: palette.text,
            fontSize: 11,
            lineHeight: 16,
          },
          count: {
            color: "#64748b",
            fontSize: 11,
            fontWeight: 600,
            lineHeight: 16,
          },
        },
      },
      lineStyle: {
        color: palette.line,
        width: 1.2,
      },
      children,
    };
  };

  const rootKeys = selectedRecords
    .map((record) => record.previewKey)
    .filter((previewKey) => !parentChoiceMap.has(previewKey));
  const rootChildren = rootKeys
    .map((previewKey) => buildNode(previewKey))
    .filter(Boolean);

  return {
    rootChildren,
    chartData: {
      name: "本次导入拓扑",
      value: `${selectedRecords.length} 个资源`,
      descendantCount: selectedRecords.length,
      symbolSize: 6,
      itemStyle: {
        color: "#38bdf8",
        borderColor: "#38bdf8",
        borderWidth: 0,
      },
      label: {
        position: "right",
        distance: 12,
        formatter: () => `{name|本次导入拓扑} {meta|${selectedRecords.length}个资源}`,
        rich: {
          name: {
            color: "#0f172a",
            fontSize: 13,
            fontWeight: 700,
            lineHeight: 18,
          },
          meta: {
            color: "#0369a1",
            fontSize: 11,
            lineHeight: 18,
          },
        },
      },
      children: rootChildren,
    },
  };
}

function getStructureSelectValue(
  currentValue: string,
  options: Array<{ name: string; existing: boolean }>,
) {
  const targetValue = String(currentValue || "").trim();
  if (targetValue && options.some((option) => option.existing && option.name === targetValue)) {
    return targetValue;
  }
  return CUSTOM_STRUCTURE_OPTION_VALUE;
}

function getStructureModelOptions(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
  selectedGroupName: string,
) {
  const optionMap = new Map<string, {
    id?: number | string;
    name: string;
    alias?: string;
    groupName?: string;
    existing: boolean;
  }>();

  (item.modelOptions || [])
    .filter((option) => !selectedGroupName || !option.groupName || option.groupName === selectedGroupName)
    .forEach((option) => {
      if (!option?.name) {
        return;
      }
      optionMap.set(option.name, {
        id: option.id,
        name: option.name,
        alias: option.alias,
        groupName: option.groupName,
        existing: option.existing !== false,
      });
    });

  const selectedGroup = (metadata?.ciTypeGroups || []).find((group) => group.name === selectedGroupName);
  if (selectedGroup) {
    selectedGroup.ciTypes.forEach((ciType) => {
      if (!ciType?.name) {
        return;
      }
      optionMap.set(ciType.name, {
        id: ciType.id,
        name: ciType.name,
        alias: ciType.alias,
        groupName: selectedGroup.name,
        existing: true,
      });
    });
  }

  const preferredNames = [
    String(item.suggestedModelName || "").trim(),
    String(item.selectedModelName || "").trim(),
    String(item.resourceCiType || "").trim(),
  ].filter(Boolean);

  return Array.from(optionMap.values()).sort((left, right) => {
    const leftIndex = preferredNames.findIndex((name) => name === left.name);
    const rightIndex = preferredNames.findIndex((name) => name === right.name);
    if (leftIndex !== rightIndex) {
      return (leftIndex === -1 ? 99 : leftIndex) - (rightIndex === -1 ? 99 : rightIndex);
    }
    return left.name.localeCompare(right.name, "zh-CN");
  });
}

function getStructureGroupOptions(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
) {
  const optionMap = new Map<string, {
    id?: number | string;
    name: string;
    existing: boolean;
  }>();

  (item.groupOptions || []).forEach((option) => {
    if (!option?.name) {
      return;
    }
    optionMap.set(option.name, {
      id: option.id,
      name: option.name,
      existing: option.existing !== false,
    });
  });

  (metadata?.ciTypeGroups || []).forEach((group) => {
    if (!group?.name) {
      return;
    }
    optionMap.set(group.name, {
      id: group.id,
      name: group.name,
      existing: true,
    });
  });

  return Array.from(optionMap.values()).sort((left, right) =>
    left.name.localeCompare(right.name, "zh-CN"),
  );
}

function isExistingStructureGroup(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
  groupName: string,
) {
  const targetName = String(groupName || "").trim();
  if (!targetName) {
    return false;
  }
  return getStructureGroupOptions(item, metadata).some(
    (option) => option.existing && option.name === targetName,
  );
}

function isExistingStructureModel(
  item: ResourceImportStructureItem,
  metadata: ResourceImportMetadata | null,
) {
  const selectedGroupName = String(item.selectedGroupName || "").trim();
  const selectedModelName = String(item.selectedModelName || "").trim();
  if (!selectedModelName) {
    return false;
  }
  return getStructureModelOptions(item, metadata, selectedGroupName).some(
    (option) => option.existing && option.name === selectedModelName,
  );
}

function getStructureTargetGroup(
  preview: ResourceImportPreview | null | undefined,
  item: ResourceImportStructureItem,
) {
  return (preview?.resourceGroups || []).find((group) => group.ciType === item.resourceCiType || group.label === item.resourceLabel) || null;
}

function getStructureUniqueKeyOptions(
  preview: ResourceImportPreview | null | undefined,
  item: ResourceImportStructureItem,
  metadata?: ResourceImportMetadata | null,
  draft?: {
    inheritFrom?: string;
    uniqueKey?: string;
  },
) {
  const targetGroup = getStructureTargetGroup(preview, item);
  const counts = new Map<string, number>();
  const labels = new Map<string, string>();
  const total = targetGroup?.records.length || 0;

  for (const record of targetGroup?.records || []) {
    const keys = new Set<string>([
      ...Object.keys(record.attributes || {}),
      ...Object.keys(record.analysisAttributes || {}),
    ]);
    keys.forEach((key) => {
      counts.set(key, (counts.get(key) || 0) + 1);
      labels.set(key, getAttributeLabel(key));
    });
  }

  const optionMap = new Map<string, {
    name: string;
    label: string;
    coverage: number;
    priority: number;
  }>();
  const preferredTypeName =
    draft?.inheritFrom
    || item.modelDraft?.inheritFrom
    || item.selectedModelName
    || item.suggestedModelName
    || item.resourceCiType;
  const preferredTypeMeta = getMetadataCiTypeMeta(metadata, preferredTypeName || "");
  const preferredUniqueKey = preferredTypeMeta?.unique_key || "";

  (preferredTypeMeta?.attributeDefinitions || []).forEach((definition) => {
    const name = definition.name;
    if (!name) {
      return;
    }
    const coverage = total ? Math.round(((counts.get(name) || 0) / total) * 100) : 0;
    const priority = name === preferredUniqueKey
      ? 0
      : counts.has(name)
        ? 1
        : ["dev_no", "property_no", "manage_ip", "private_ip", "name", "dev_name"].includes(name)
          ? 2
          : 5;
    optionMap.set(name, {
      name,
      label: definition.alias || getAttributeLabel(name),
      coverage,
      priority,
    });
  });

  Array.from(counts.entries()).forEach(([name, count]) => {
    if (count <= 0) {
      return;
    }
    const existing = optionMap.get(name);
    const priority = ["dev_no", "property_no", "asset_code", "private_ip", "manage_ip", "serverName", "name", "dev_name"].indexOf(name);
    optionMap.set(name, {
      name,
      label: labels.get(name) || existing?.label || name,
      coverage: total ? Math.round((count / total) * 100) : 0,
      priority: existing?.priority ?? (priority === -1 ? 9 : 3 + priority),
    });
  });

  return Array.from(optionMap.values())
    .sort((left, right) =>
      left.priority - right.priority
      || right.coverage - left.coverage
      || left.label.localeCompare(right.label, "zh-CN"),
    )
    .map(({ priority, ...option }) => option);
}

function getStructureInheritanceOptions(
  metadata: ResourceImportMetadata | null,
  item: ResourceImportStructureItem,
) {
  const options = getStructureModelOptions(item, metadata, item.selectedGroupName || "");
  if (options.length) {
    return options;
  }
  return (metadata?.ciTypes || []).map((ciType) => ({
    id: ciType.id,
    name: ciType.name,
    alias: ciType.alias,
    existing: true,
  }));
}

function getSuggestedUniqueKey(
  preview: ResourceImportPreview | null | undefined,
  item: ResourceImportStructureItem,
  metadata?: ResourceImportMetadata | null,
  draft?: {
    inheritFrom?: string;
    uniqueKey?: string;
  },
) {
  return getStructureUniqueKeyOptions(preview, item, metadata, draft)[0]?.name || "";
}

function normalizeFieldToken(value: string) {
  return String(value || "").trim().toLowerCase().replace(/[\s_\-/:]+/g, "");
}

function splitSemanticTokens(value: string) {
  return String(value || "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9\u4e00-\u9fff]+/)
    .filter(Boolean);
}

function isNameLikeUniqueKey(uniqueKey: string) {
  const normalized = normalizeFieldToken(uniqueKey);
  const raw = String(uniqueKey || "").trim().toLowerCase();
  const tokens = new Set(splitSemanticTokens(uniqueKey));
  return (
    normalized.endsWith("name")
    || tokens.has("name")
    || tokens.has("instance")
    || tokens.has("hostname")
    || tokens.has("servername")
    || tokens.has("devname")
    || tokens.has("vservername")
    || ["名称", "名字", "主机名", "设备名", "实例名", "实例名称", "组件实例名", "数据库实例名"].some((token) => raw.includes(token))
  );
}

function isIpLikeUniqueKey(uniqueKey: string) {
  const normalized = normalizeFieldToken(uniqueKey);
  const raw = String(uniqueKey || "").trim().toLowerCase();
  return (
    normalized.includes("ip")
    || ["管理地址", "管理ip", "内网地址", "内网ip", "ip地址", "主机地址", "数据库地址", "组件地址"].some((token) => raw.includes(token))
  );
}

function isCodeLikeUniqueKey(uniqueKey: string) {
  const normalized = normalizeFieldToken(uniqueKey);
  const raw = String(uniqueKey || "").trim().toLowerCase();
  const tokens = new Set(splitSemanticTokens(uniqueKey));
  if (["主键", "唯一", "唯一标识", "资源主键", "资产标识", "编号", "编码", "标识"].some((token) => raw.includes(token))) {
    return true;
  }
  if (["rowid", "ciid", "pid"].includes(normalized)) {
    return true;
  }
  return ["code", "no", "id", "key", "pk", "unique", "identifier"].some((token) => tokens.has(token));
}

function getUniqueKeySemanticKind(uniqueKey: string, uniqueKeyLabel?: string) {
  const merged = `${uniqueKey} ${uniqueKeyLabel || ""}`.trim();
  if (isCodeLikeUniqueKey(merged)) {
    return "code";
  }
  if (isIpLikeUniqueKey(merged)) {
    return "ip";
  }
  if (isNameLikeUniqueKey(merged)) {
    return "name";
  }
  return "unknown";
}

function getUniqueKeyLabel(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
) {
  const typeMeta = getCiTypeMeta(preview, ciType);
  const uniqueKey = String(typeMeta?.unique_key || "").trim();
  if (!uniqueKey) {
    return "";
  }
  const definition = (typeMeta?.attributeDefinitions || []).find((item) => item.name === uniqueKey);
  return definition?.alias || getAttributeLabel(uniqueKey);
}

function getUniqueKeyDisplay(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
) {
  const typeMeta = getCiTypeMeta(preview, ciType);
  const uniqueKey = String(typeMeta?.unique_key || "").trim();
  if (!uniqueKey) {
    return "";
  }
  const label = getUniqueKeyLabel(preview, ciType);
  return label && label !== uniqueKey ? `${label} (${uniqueKey})` : uniqueKey;
}

function isSystemGeneratedUniqueKey(
  preview: ResourceImportPreview | null | undefined,
  ciType: string,
) {
  const typeMeta = getCiTypeMeta(preview, ciType);
  if (!typeMeta) {
    return false;
  }
  if (typeMeta.system_generated_unique_key) {
    return true;
  }

  const uniqueKey = String(typeMeta.unique_key || "").trim();
  const normalized = normalizeFieldToken(uniqueKey);
  if (!normalized) {
    return false;
  }
  if (["pid", "rowid", "ciid"].includes(normalized)) {
    return true;
  }

  const definition = (typeMeta.attributeDefinitions || []).find((item) => item.name === uniqueKey);
  const alias = String(definition?.alias || "").trim();
  const valueType = String(definition?.value_type || "").trim().toLowerCase();
  return normalized === "id" && ["主键", "系统主键"].includes(alias) && ["int", "integer", "bigint", "smallint", "long", "number"].includes(valueType);
}

function getRecordFieldValue(record: ResourceImportRecord, field: string) {
  if (field === "name") {
    return getRecordDisplayNameValue(record);
  }
  return String(
    record.attributes?.[field]
    || record.analysisAttributes?.[field]
    || record.sourceAttributes?.[field]
    || "",
  ).trim();
}

function getSemanticSourceAttributeValue(
  record: ResourceImportRecord,
  semanticKind: "name" | "ip" | "code",
  uniqueKey = "",
  uniqueKeyLabel = "",
) {
  const sourceEntries = Object.entries(record.sourceAttributes || {})
    .map(([field, value]) => ({
      field,
      value: String(value || "").trim(),
      label: getAttributeLabel(field),
      semanticKind: getFieldSemanticKind(field, getAttributeLabel(field)),
      similarity: getUniqueKeySemanticSimilarity(uniqueKey || semanticKind, uniqueKeyLabel, field, getAttributeLabel(field)),
    }))
    .filter((item) => item.value);
  const candidates = sourceEntries
    .filter((item) => item.semanticKind === semanticKind)
    .sort((left, right) =>
      right.similarity - left.similarity
      || left.field.localeCompare(right.field, "zh-CN")
    );
  return candidates[0]?.value || "";
}

function getRecordDisplayNameValue(record: ResourceImportRecord) {
  return String(
    record.name
    || record.attributes?.name
    || record.analysisAttributes?.name
    || record.attributes?.middleware_name
    || record.analysisAttributes?.middleware_name
    || record.attributes?.db_instance
    || record.analysisAttributes?.db_instance
    || record.attributes?.serverName
    || record.analysisAttributes?.serverName
    || record.attributes?.dev_name
    || record.analysisAttributes?.dev_name
    || record.attributes?.hostname
    || record.analysisAttributes?.hostname
    || record.attributes?.vserver_name
    || record.analysisAttributes?.vserver_name
    || getSemanticSourceAttributeValue(record, "name", "name", "名称")
    || "",
  ).trim();
}

function getSemanticResolvedUniqueKeyValue(
  record: ResourceImportRecord,
  uniqueKey: string,
  uniqueKeyLabel: string,
) {
  const directValue = getRecordFieldValue(record, uniqueKey);
  if (directValue) {
    return directValue;
  }
  const semanticKind = getUniqueKeySemanticKind(uniqueKey, uniqueKeyLabel);
  if (semanticKind === "name") {
    return getRecordDisplayNameValue(record) || getSemanticSourceAttributeValue(record, "name", uniqueKey, uniqueKeyLabel);
  }
  if (semanticKind === "ip") {
    return String(
      record.attributes?.manage_ip
      || record.analysisAttributes?.manage_ip
      || record.attributes?.private_ip
      || record.analysisAttributes?.private_ip
      || record.attributes?.host_ip
      || record.analysisAttributes?.host_ip
      || getSemanticSourceAttributeValue(record, "ip", uniqueKey, uniqueKeyLabel)
      || "",
    ).trim();
  }
  if (semanticKind === "code") {
    return String(
      record.attributes?.asset_code
      || record.analysisAttributes?.asset_code
      || record.attributes?.property_no
      || record.analysisAttributes?.property_no
      || record.attributes?.dev_no
      || record.analysisAttributes?.dev_no
      || record.attributes?.id
      || record.analysisAttributes?.id
      || getSemanticSourceAttributeValue(record, "code", uniqueKey, uniqueKeyLabel)
      || "",
    ).trim();
  }
  return "";
}

function getFieldSemanticKind(field: string, label = "") {
  const merged = `${field} ${label}`.trim();
  if (isCodeLikeUniqueKey(merged)) {
    return "code";
  }
  if (isIpLikeUniqueKey(merged)) {
    return "ip";
  }
  if (isNameLikeUniqueKey(merged)) {
    return "name";
  }
  return "unknown";
}

function getSemanticTerms(value: string) {
  return splitSemanticTokens(value)
    .filter((item) => item && (item.length >= 2 || /[\u4e00-\u9fff]/.test(item)));
}

function getUniqueKeySemanticSimilarity(uniqueKey: string, uniqueKeyLabel: string, field: string, fieldLabel: string) {
  const uniqueMerged = `${uniqueKey} ${uniqueKeyLabel}`.trim();
  const fieldMerged = `${field} ${fieldLabel}`.trim();
  const normalizedUnique = normalizeFieldToken(uniqueMerged);
  const normalizedField = normalizeFieldToken(fieldMerged);
  if (!normalizedUnique || !normalizedField) {
    return 0;
  }
  if (normalizedUnique === normalizedField) {
    return 100;
  }
  if (
    normalizedUnique.length >= 4
    && normalizedField.length >= 4
    && (normalizedUnique.includes(normalizedField) || normalizedField.includes(normalizedUnique))
  ) {
    return 82;
  }
  const uniqueTerms = new Set(getSemanticTerms(uniqueMerged));
  const fieldTerms = new Set(getSemanticTerms(fieldMerged));
  const overlap = Array.from(uniqueTerms).filter((item) => fieldTerms.has(item));
  if (overlap.length) {
    return 56 + Math.min(20, overlap.length * 10);
  }
  return 0;
}

function getUniqueKeyCandidatePriority(
  uniqueKey: string,
  uniqueKeyLabel: string,
  field: string,
  fieldLabel: string,
  fieldSemanticKind: string,
) {
  if (field === uniqueKey) {
    return -1;
  }
  const uniqueSemanticKind = getUniqueKeySemanticKind(uniqueKey, uniqueKeyLabel);
  const similarity = getUniqueKeySemanticSimilarity(uniqueKey, uniqueKeyLabel, field, fieldLabel);
  if (uniqueSemanticKind !== "unknown" && fieldSemanticKind === uniqueSemanticKind) {
    return Math.max(0, 8 - Math.floor(similarity / 15));
  }
  if (similarity >= 56) {
    return 12 - Math.floor(similarity / 20);
  }
  return 20;
}

function getUniqueKeyCandidateCompatibility(
  uniqueKey: string,
  uniqueKeyLabel: string,
  field: string,
  fieldLabel: string,
  fieldSemanticKind: string,
) {
  const uniqueSemanticKind = getUniqueKeySemanticKind(uniqueKey, uniqueKeyLabel);
  const similarity = getUniqueKeySemanticSimilarity(uniqueKey, uniqueKeyLabel, field, fieldLabel);
  if (field === uniqueKey) {
    return 6;
  }
  if (uniqueSemanticKind === "unknown") {
    return similarity >= 70 ? 3 : similarity >= 56 ? 2 : 0;
  }
  if (fieldSemanticKind !== uniqueSemanticKind) {
    return similarity >= 86 ? 2 : 0;
  }
  if (uniqueSemanticKind === "name") {
    if (field === "name") {
      return 5;
    }
    return similarity >= 70 ? 5 : 4;
  }
  if (uniqueSemanticKind === "ip") {
    return similarity >= 70 ? 5 : 4;
  }
  if (uniqueSemanticKind === "code") {
    return similarity >= 70 ? 5 : 4;
  }
  return similarity >= 70 ? 4 : 3;
}

function getUniqueKeyResolutionPlans(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
) {
  return groups
    .map((group) => {
      const typeMeta = getCiTypeMeta(preview, group.ciType);
      const uniqueKey = String(typeMeta?.unique_key || "").trim();
      const uniqueKeyLabel = getUniqueKeyLabel(preview, group.ciType);
      if (!uniqueKey || isSystemGeneratedUniqueKey(preview, group.ciType)) {
        return null;
      }
      const selectedRecords = group.records.filter((record) => record.selected);
      const missingRecords = selectedRecords.filter((record) =>
        isEmptyValue(getSemanticResolvedUniqueKeyValue(record, uniqueKey, uniqueKeyLabel)),
      );
      if (!missingRecords.length) {
        return null;
      }

      const candidateMap = new Map<string, {
        field: string;
        label: string;
        count: number;
        examples: string[];
        priority: number;
        compatibility: number;
        semanticKind: string;
        similarity: number;
        values: Set<string>;
      }>();

      const registerCandidateValue = (field: string, value: string) => {
        if (!field || field === uniqueKey || field === "ci_type" || field.startsWith("_")) {
          return;
        }
        const cleanedValue = String(value || "").trim();
        if (!cleanedValue) {
          return;
        }
        const label = getAttributeLabel(field);
        const semanticKind = getFieldSemanticKind(field, label);
        const similarity = getUniqueKeySemanticSimilarity(uniqueKey, uniqueKeyLabel, field, label);
        const current = candidateMap.get(field);
        if (current) {
          current.count += 1;
          current.values.add(cleanedValue);
          if (current.examples.length < 2 && !current.examples.includes(cleanedValue)) {
            current.examples.push(cleanedValue);
          }
          return;
        }
        candidateMap.set(field, {
          field,
          label,
          count: 1,
          examples: [cleanedValue],
          priority: getUniqueKeyCandidatePriority(uniqueKey, uniqueKeyLabel, field, label, semanticKind),
          compatibility: getUniqueKeyCandidateCompatibility(uniqueKey, uniqueKeyLabel, field, label, semanticKind),
          semanticKind,
          similarity,
          values: new Set([cleanedValue]),
        });
      };

      missingRecords.forEach((record) => {
        const fields = new Set<string>([
          "name",
          ...Object.keys(record.attributes || {}),
          ...Object.keys(record.analysisAttributes || {}),
          ...Object.keys(record.sourceAttributes || {}),
        ]);
        registerCandidateValue("name", getRecordDisplayNameValue(record));
        fields.forEach((field) => {
          registerCandidateValue(field, getRecordFieldValue(record, field));
        });
      });

      const candidates = Array.from(candidateMap.values())
        .sort((left, right) =>
          right.compatibility - left.compatibility
          || right.similarity - left.similarity
          || left.priority - right.priority
          || right.values.size - left.values.size
          || right.count - left.count
          || left.label.localeCompare(right.label, "zh-CN")
        )
        .map((item) => ({
          field: item.field,
          label: item.label,
          count: item.count,
          coverage: Math.round((item.count / missingRecords.length) * 100),
          distinctCount: item.values.size,
          distinctCoverage: Math.round((item.values.size / missingRecords.length) * 100),
          duplicateCount: Math.max(0, item.count - item.values.size),
          compatibility: item.compatibility,
          priority: item.priority,
          semanticKind: item.semanticKind,
          similarity: item.similarity,
          recommended: item.compatibility >= 3,
          examples: item.examples,
        }));

      const uniqueSemanticKind = getUniqueKeySemanticKind(uniqueKey, uniqueKeyLabel);
      const compatibleCandidates = candidates.filter((item) => {
        if (item.compatibility <= 0) {
          return false;
        }
        if (uniqueSemanticKind === "unknown") {
          return true;
        }
        return item.semanticKind === uniqueSemanticKind || item.similarity >= 86;
      });
      const finalCandidates = compatibleCandidates.length ? compatibleCandidates : candidates;

      return {
        ciType: group.ciType,
        label: group.label,
        uniqueKey,
        uniqueKeyLabel,
        uniqueKeyDisplay: getUniqueKeyDisplay(preview, group.ciType),
        missingCount: missingRecords.length,
        totalCount: selectedRecords.length,
        candidates: finalCandidates,
      };
    })
    .filter(Boolean);
}

function getSystemGeneratedUniqueKeyPlans(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
) {
  return groups
    .map((group) => {
      const typeMeta = getCiTypeMeta(preview, group.ciType);
      const uniqueKey = String(typeMeta?.unique_key || "").trim();
      if (!uniqueKey || !isSystemGeneratedUniqueKey(preview, group.ciType)) {
        return null;
      }
      const selectedRecords = group.records.filter((record) => record.selected);
      const missingRecords = selectedRecords.filter((record) =>
        isEmptyValue(getSemanticResolvedUniqueKeyValue(record, uniqueKey, getUniqueKeyLabel(preview, group.ciType))),
      );
      if (!missingRecords.length) {
        return null;
      }
      return {
        ciType: group.ciType,
        label: group.label,
        uniqueKey,
        uniqueKeyDisplay: getUniqueKeyDisplay(preview, group.ciType) || uniqueKey,
        missingCount: missingRecords.length,
        totalCount: selectedRecords.length,
      };
    })
    .filter(Boolean);
}

function shouldAutoApplyUniqueKeyPlan(plan: {
  candidates: Array<{ field: string; coverage: number; distinctCoverage: number; recommended: boolean; compatibility: number; priority: number }>;
}) {
  const [first, second] = plan.candidates;
  if (!first || !first.field) {
    return false;
  }
  if (!first.recommended) {
    return false;
  }
  if (first.coverage < 100) {
    return false;
  }
  if (first.distinctCoverage < 100) {
    return false;
  }
  if (!second) {
    return true;
  }
  if (!second.recommended || second.distinctCoverage < 100) {
    return true;
  }
  if (first.compatibility > second.compatibility) {
    return true;
  }
  return first.priority + 2 <= second.priority;
}

function applyStructureSelectionsToPreview(
  preview: ResourceImportPreview | null | undefined,
  items: ResourceImportStructureItem[],
): {
  preview: ResourceImportPreview | null;
  resourceGroups: ResourceImportGroup[];
  relations: ResourceImportRelation[];
} {
  if (!preview) {
    return {
      preview: null,
      resourceGroups: [],
      relations: [],
    };
  }

  const itemMap = new Map(items.map((item) => [item.key, item]));
  const resourceGroups = (preview.resourceGroups || []).map((group) => {
    const structureItem = itemMap.get(group.ciType || group.label);
    if (!structureItem) {
      return group;
    }
    const nextCiType = structureItem.selectedModelName || group.ciType;
    const nextLabel = preview.ciTypeMetadata?.[nextCiType]?.alias || group.label;
    return {
      ...group,
      ciType: nextCiType,
      label: nextLabel,
      records: group.records.map((record) => ({
        ...record,
        ciType: nextCiType,
      })),
    };
  });
  const recordMap = new Map<string, ResourceImportRecord>();
  resourceGroups.forEach((group) => {
    group.records.forEach((record) => {
      recordMap.set(record.previewKey, record);
    });
  });

  const inferRelationTypeForModels = (sourceType: string, targetType: string) => {
    const targetMeta = preview.ciTypeMetadata?.[targetType];
    const matchingParent = (targetMeta?.parentTypes || []).find((item) => item.name === sourceType);
    if (matchingParent) {
      return String(matchingParent.relationType || "contain").trim() || "contain";
    }
    if (ROOT_RELATION_TYPES.has(sourceType)) {
      return "contain";
    }
    if (SOFTWARE_RESOURCE_TYPES.has(targetType) && RESOURCE_DEPLOY_TYPES.has(sourceType)) {
      return "deploy";
    }
    return "connect";
  };

  const relations = (preview.relations || []).map((relation) => {
    const sourceRecord = recordMap.get(relation.sourceKey);
    const targetRecord = recordMap.get(relation.targetKey);
    const sourceType = String(sourceRecord?.ciType || relation.sourceType || "").trim();
    const targetType = String(targetRecord?.ciType || relation.targetType || "").trim();
    const nextRelationType = sourceType && targetType
      ? inferRelationTypeForModels(sourceType, targetType)
      : relation.relationType;
    return {
      ...relation,
      relationType: nextRelationType,
      sourceType,
      targetType,
      sourceName: String(sourceRecord?.name || relation.sourceName || "").trim(),
      targetName: String(targetRecord?.name || relation.targetName || "").trim(),
    };
  });

  return {
    preview: {
      ...preview,
      resourceGroups,
      relations,
      structureAnalysis: {
        items,
      },
    },
    resourceGroups,
    relations,
  };
}

function syncPreviewWithCurrentData(
  preview: ResourceImportPreview | null | undefined,
  resourceGroups: ResourceImportGroup[],
  relations: ResourceImportRelation[],
): ResourceImportPreview | null {
  if (!preview) {
    return null;
  }
  return {
    ...preview,
    resourceGroups,
    relations,
  };
}

function sortAttributeKeys(keys: string[]) {
  return [...keys].sort((left, right) => {
    const leftIndex = ATTRIBUTE_FIELD_ORDER.indexOf(left as typeof ATTRIBUTE_FIELD_ORDER[number]);
    const rightIndex = ATTRIBUTE_FIELD_ORDER.indexOf(right as typeof ATTRIBUTE_FIELD_ORDER[number]);
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex);
    }
    return getAttributeLabel(left).localeCompare(getAttributeLabel(right), "zh-CN");
  });
}

function getBatchEditorColumns(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
) {
  const columnMap = new Map<string, { key: string; label: string }>();
  for (const group of groups) {
    for (const record of group.records) {
      const definitions = getVisibleAttributeDefinitions(preview, record.ciType, record);
      for (const definition of definitions) {
        columnMap.set(definition.name, {
          key: definition.name,
          label: definition.alias || getAttributeLabel(definition.name),
        });
      }
      for (const key of Object.keys(record.attributes || {})) {
        if (!columnMap.has(key)) {
          columnMap.set(key, {
            key,
            label: getAttributeLabel(key),
          });
        }
      }
    }
  }
  return sortAttributeKeys(Array.from(columnMap.keys())).map((key) => columnMap.get(key)!);
}

const EXPORT_FIELD_ORDER = [
  "ci_type",
  "name",
  "project",
  "platform",
  "private_ip",
  "manage_ip",
  "asset_code",
  "service_port",
  "status",
  "deploy_target",
  "host_name",
  "upstream_resource",
  "os_version",
  "version",
  "owner",
  "description",
  "selected",
  "import_action",
  "source_file",
  "source_sheet",
  "source_row",
] as const;

function sortExportFieldKeys(keys: string[]) {
  return [...keys].sort((left, right) => {
    const leftIndex = EXPORT_FIELD_ORDER.indexOf(left as typeof EXPORT_FIELD_ORDER[number]);
    const rightIndex = EXPORT_FIELD_ORDER.indexOf(right as typeof EXPORT_FIELD_ORDER[number]);
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex);
    }
    return left.localeCompare(right, "zh-CN");
  });
}

function sanitizeWorksheetName(name: string, usedNames: Set<string>) {
  const cleaned = String(name || "Sheet")
    .replace(/[\\/?*[\]:]/g, "-")
    .trim()
    .slice(0, 31) || "Sheet";
  let nextName = cleaned;
  let counter = 2;
  while (usedNames.has(nextName)) {
    const suffix = `-${counter}`;
    nextName = `${cleaned.slice(0, Math.max(0, 31 - suffix.length))}${suffix}`;
    counter += 1;
  }
  usedNames.add(nextName);
  return nextName;
}

function buildStandardExportRows(group: ResourceImportGroup) {
  return group.records.map((record) => {
    const sourceRow = record.sourceRows?.[0] || {};
    const base = Object.fromEntries(
      Object.entries(record.analysisAttributes || {})
        .filter(([key, value]) => key && !key.startsWith("_") && !isEmptyValue(value))
        .map(([key, value]) => [key, value]),
    ) as Record<string, unknown>;
    Object.entries(record.attributes || {}).forEach(([key, value]) => {
      if (key && !key.startsWith("_") && !isEmptyValue(value)) {
        base[key] = value;
      }
    });
    if (!isEmptyValue(record.name)) {
      base.name = record.name;
    }

    return {
      ci_type: record.ciType,
      ...base,
      selected: record.selected ? "是" : "否",
      import_action: record.importAction || "create",
      source_file: sourceRow.filename || "",
      source_sheet: sourceRow.sheet || "",
      source_row: sourceRow.rowIndex ?? "",
    };
  });
}

function getRequiredExportFieldKeys(
  preview: ResourceImportPreview | null | undefined,
  group: ResourceImportGroup,
) {
  const ciTypes = Array.from(
    new Set([group.ciType, ...group.records.map((record) => record.ciType)].filter(Boolean)),
  );
  return Array.from(
    new Set(
      ciTypes.flatMap((ciType) =>
        getRequiredAttributeDefinitions(preview, ciType)
          .map((definition) => definition.name)
          .filter(Boolean),
      ),
    ),
  );
}

function buildMissingRequiredExportRows(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
) {
  return getRequiredModelIssues(preview, groups).map((issue) => ({
    model: issue.ciType,
    record: issue.recordName,
    source: issue.sourceLabel,
    missing_field: issue.field,
    message: issue.message,
  }));
}

function buildWorkbookFieldDictionary(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
) {
  const seen = new Set<string>();
  return groups.flatMap((group) => {
    const meta = preview?.ciTypeMetadata?.[group.ciType];
    const definitions = meta?.attributeDefinitions || [];
    const rows = definitions
      .filter((definition) => {
        const name = String(definition.name || "").trim();
        if (!name || seen.has(`${group.ciType}:${name}`)) {
          return false;
        }
        seen.add(`${group.ciType}:${name}`);
        return true;
      })
      .map((definition) => ({
        model: group.ciType,
        model_alias: meta?.alias || group.label,
        field: definition.name,
        label: definition.alias || getAttributeLabel(definition.name),
        required: definition.required ? "是" : "否",
        default_value: getAttributeDefaultValue(definition),
        is_list: definition.is_list ? "是" : "否",
        is_choice: definition.is_choice ? "是" : "否",
      }));
    return rows;
  });
}

function downloadConfirmationData(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
) {
  const workbook = XLSX.utils.book_new();
  const usedSheetNames = new Set<string>();

  const instructions = [
    {
      title: "说明",
      content: "请直接在各资源 Sheet 中补充或修改标准字段后，再重新上传该 Excel。",
    },
    {
      title: "字段规则",
      content: "表头使用系统标准字段名，重新导入时匹配稳定性会明显更高。",
    },
    {
      title: "保留字段",
      content: "建议保留 ci_type、selected、import_action 这几列；source_* 仅作溯源参考。",
    },
  ];
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.json_to_sheet(instructions),
    sanitizeWorksheetName("导出说明", usedSheetNames),
  );

  for (const group of groups) {
    const rows = buildStandardExportRows(group);
    const fieldKeys = sortExportFieldKeys(
      Array.from(
        new Set([
          ...rows.flatMap((row) => Object.keys(row).filter((key) => !isEmptyValue(row[key]))),
          ...getRequiredExportFieldKeys(preview, group),
        ]),
      ),
    );
    const normalizedRows = rows.map((row) => Object.fromEntries(fieldKeys.map((key) => [key, row[key] ?? ""])));
    const worksheet = XLSX.utils.json_to_sheet(normalizedRows, {
      header: fieldKeys,
    });
    XLSX.utils.book_append_sheet(
      workbook,
      worksheet,
      sanitizeWorksheetName(`${group.label}-${group.ciType}`, usedSheetNames),
    );
  }

  const missingRequiredRows = buildMissingRequiredExportRows(preview, groups);
  if (missingRequiredRows.length) {
    XLSX.utils.book_append_sheet(
      workbook,
      XLSX.utils.json_to_sheet(missingRequiredRows),
      sanitizeWorksheetName("缺失必填字段", usedSheetNames),
    );
  }

  const dictionaryRows = buildWorkbookFieldDictionary(preview, groups);
  if (dictionaryRows.length) {
    XLSX.utils.book_append_sheet(
      workbook,
      XLSX.utils.json_to_sheet(dictionaryRows),
      sanitizeWorksheetName("字段字典", usedSheetNames),
    );
  }

  XLSX.writeFile(workbook, "resource-import-confirmation.xlsx");
}

function getRecordRequiredModelIssues(
  preview: ResourceImportPreview | null | undefined,
  record: ResourceImportRecord,
) {
  if (!record.selected || (record.importAction || "create") === "skip") {
    return [];
  }
  return getRequiredAttributeDefinitions(preview, record.ciType)
    .filter((definition) => requiredFieldNeedsManualValue(record, definition.name, definition))
    .map((definition): ResourceImportRecordIssue => ({
      field: definition.name,
      level: "blocking",
      message: `缺少必填字段：${definition.alias || getAttributeLabel(definition.name)}`,
    }));
}

function dedupeRecordIssues(issues: ResourceImportRecordIssue[]) {
  const seen = new Set<string>();
  return issues.filter((issue) => {
    const key = `${normalizeIssueFieldName(issue.field)}::${issue.message}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function getRecordIssues(
  record: ResourceImportRecord,
  preview?: ResourceImportPreview | null,
) {
  return dedupeRecordIssues([
    ...(record.issues || []),
    ...getRecordRequiredModelIssues(preview, record),
  ]);
}

function getRequiredModelIssues(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
): ResourceImportRequiredIssue[] {
  return groups.flatMap((group) =>
    group.records.flatMap((record) =>
      getRecordRequiredModelIssues(preview, record).map((issue) => ({
        ...issue,
        previewKey: record.previewKey,
        ciType: record.ciType || group.ciType,
        recordName: getDisplayName(record),
        sourceLabel: buildRecordSource(record),
      })),
    ),
  );
}

function getDefaultedRequiredModelIssues(
  preview: ResourceImportPreview | null | undefined,
  groups: ResourceImportGroup[],
): ResourceImportDefaultedRequiredIssue[] {
  return groups.flatMap((group) =>
    group.records.flatMap((record) =>
      getRequiredAttributeDefinitions(preview, record.ciType)
        .map((definition) => {
          const message = getRequiredDefaultMessage(record, definition.name, definition);
          if (!message) {
            return null;
          }
          return {
            field: definition.name,
            level: "info",
            message,
            previewKey: record.previewKey,
            ciType: record.ciType || group.ciType,
            recordName: getDisplayName(record),
            sourceLabel: buildRecordSource(record),
            defaultValue: getAttributeDefaultValue(definition),
          } satisfies ResourceImportDefaultedRequiredIssue;
        })
        .filter((item): item is ResourceImportDefaultedRequiredIssue => Boolean(item)),
    ),
  );
}

function getDefaultedRequiredModelMessage(issues: ResourceImportDefaultedRequiredIssue[]) {
  if (!issues.length) {
    return "";
  }
  const recordCount = new Set(issues.map((issue) => issue.previewKey)).size;
  return `有 ${recordCount} 条记录的 ${issues.length} 个必填字段将使用 CMDB 模型默认值。`;
}

function getRequiredModelBlockingMessage(issues: ResourceImportRequiredIssue[]) {
  if (!issues.length) {
    return "";
  }
  const recordCount = new Set(issues.map((issue) => issue.previewKey)).size;
  return `当前数据缺少 CMDB 模型必填字段：${recordCount} 条记录、${issues.length} 个字段需要补齐。`;
}

function getMetadataBlockingMessage(preview: ResourceImportPreview | null | undefined) {
  if (!preview || preview.metadataConnected !== false) {
    return "";
  }
  return "当前未连接实时 CMDB 模型，无法按目标环境校验必填字段。请恢复 CMDB 连接后重新解析文件。";
}

function normalizeIssueFieldName(field: string) {
  const cleaned = String(field || "").trim();
  if (!cleaned) {
    return "";
  }
  if (cleaned.startsWith("attributes.")) {
    return cleaned.slice("attributes.".length);
  }
  return cleaned;
}

function getFieldIssues(record: ResourceImportRecord, field: string) {
  const normalizedField = normalizeIssueFieldName(field);
  return getRecordIssues(record).filter(
    (issue) => normalizeIssueFieldName(issue.field) === normalizedField,
  );
}

function isEmptyValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  return String(value ?? "").trim() === "";
}

function hasAttentionField(record: ResourceImportRecord, field: string) {
  return (record.attentionFields || []).includes(field);
}

function fieldNeedsAttention(
  record: ResourceImportRecord,
  field: string,
  definition?: ResourceImportCiTypeAttributeDefinition | null,
) {
  if (hasAttentionField(record, field)) {
    return true;
  }
  if (getFieldIssues(record, field).length) {
    return true;
  }
  if (requiredFieldNeedsManualValue(record, field, definition)) {
    return true;
  }
  const value = field === "name" ? record.name : record.attributes?.[field];
  if (field === "name" && isEmptyValue(value)) {
    return true;
  }
  return false;
}

function getFieldAttentionMessage(
  record: ResourceImportRecord,
  field: string,
  definition?: ResourceImportCiTypeAttributeDefinition | null,
) {
  const issueMessage = getFieldIssues(record, field)[0]?.message;
  if (issueMessage) {
    return issueMessage;
  }
  if (requiredFieldNeedsManualValue(record, field, definition)) {
    return `${definition?.alias || getAttributeLabel(field)} 为空，请补充`;
  }
  const value = field === "name" ? record.name : record.attributes?.[field];
  if (field === "name" && isEmptyValue(value)) {
    return `${definition?.alias || getAttributeLabel(field)} 为空，请补充`;
  }
  return "";
}

function getImportActionOptions(record: ResourceImportRecord) {
  if (record.existingCi?.ciId !== undefined) {
    return [
      { value: "update", label: "更新已存在资源" },
      { value: "skip", label: "跳过该资源" },
    ];
  }
  return [
    { value: "create", label: "新建资源" },
    { value: "skip", label: "跳过该资源" },
  ];
}

function getImportActionLabel(record: ResourceImportRecord) {
  if ((record.importAction || "create") === "skip") {
    return "跳过";
  }
  if ((record.importAction || "create") === "update") {
    return "更新";
  }
  return "新建";
}

function getEditableAttributeKeys(record: ResourceImportRecord) {
  const keys = new Set<string>(["name", "status"]);
  ATTRIBUTE_FIELD_ORDER.forEach((key) => {
    if (key === "name") {
      keys.add(key);
      return;
    }
    if (record.attributes[key] || key === "description") {
      keys.add(key);
    }
  });
  Object.keys(record.attributes || {}).forEach((key) => {
    if (record.attributes[key]) {
      keys.add(key);
    }
  });
  return Array.from(keys);
}

function buildRecordSource(record: ResourceImportRecord) {
  const firstSource = record.sourceRows[0];
  if (!firstSource) {
    return "自动补全";
  }

  const fragments = [
    firstSource.filename,
    firstSource.sheet,
    firstSource.rowIndex ? `行 ${firstSource.rowIndex}` : "",
  ];
  return fragments.filter(Boolean).join(" / ") || "上传文件";
}

function getGroupIcon(group: ResourceImportGroup) {
  const ciType = group.ciType.toLowerCase();
  if (ciType.includes("server")) {
    return "🖥️";
  }
  if (ciType.includes("switch") || ciType.includes("router") || ciType.includes("firewall")) {
    return "🌐";
  }
  if (
    ciType.includes("mysql")
    || ciType.includes("redis")
    || ciType.includes("kafka")
    || ciType.includes("nginx")
  ) {
    return "🔧";
  }
  return "📦";
}

function getCurrentStep(stage: ResourceImportFlowStage) {
  if (stage === "intro") {
    return 1;
  }
  if (stage === "parsing") {
    return 2;
  }
  if (stage === "structure") {
    return 3;
  }
  if (stage === "confirm") {
    return 3;
  }
  if (stage === "topology") {
    return 4;
  }
  return 5;
}

function FlowSteps({
  stage,
  forceCompleted = false,
}: {
  stage: ResourceImportFlowStage;
  forceCompleted?: boolean;
}) {
  const currentStep = getCurrentStep(stage);

  return (
    <div className="resource-import-flow-steps">
      {FLOW_STEPS.map((flowStep) => {
        const status = forceCompleted
          ? "completed"
          : flowStep.index < currentStep
            ? "completed"
            : flowStep.index === currentStep
              ? "active"
              : "";
        return (
          <div key={flowStep.index} className={`resource-import-flow-step ${status}`.trim()}>
            <span className="resource-import-flow-step-icon">{flowStep.icon}</span>
            <span className="resource-import-flow-step-label">{flowStep.label}</span>
          </div>
        );
      })}
    </div>
  );
}

const CANONICAL_RESOURCE_IMPORT_COPY_BLOCKS: ResourceImportStartPayload["copyBlocks"] = [
  {
    title: "资源导入入口已准备好",
    paragraphs: [
      "请在下方上传资源清单文件，我会先解析字段、清洗数据并生成预览，确认无误后再导入 CMDB。",
    ],
  },
  {
    title: "我能处理的各种资料：",
    items: [
      "资源实例：服务器、虚拟机、容器、Kubernetes 节点、数据库、中间件、Nginx / Apache、网络设备。",
      "业务对象：产品、应用、服务、平台、负责人、环境、所属部门。",
      "网络与机房：IP 地址、子网、VLAN、机柜、机房、交换机端口。",
      "资源关系：服务器属于哪个应用、应用属于哪个产品、IP 与设备绑定、上下游依赖关系。",
    ],
  },
  {
    title: "建议清单中包含的字段：",
    items: [
      "基础字段：名称、资源类型、IP、环境、状态、所属应用或产品。",
      "可选字段：厂商、型号、序列号、系统版本、负责人、机房、机柜、备注。",
      "关系字段：应用名、产品名、父级资源、关联 IP、依赖服务。",
    ],
  },
  {
    title: "导入前会自动处理：",
    items: [
      "识别 Excel/CSV 表头并映射到 CMDB 字段。",
      "清洗名称、IP、状态、类型等不统一的数据。",
      "按命名、网段、应用字段推断资源拓扑关系。",
      "生成可编辑预览，确认后才会写入 CMDB。",
    ],
  },
  {
    title: "导入流程：",
    ordered: true,
    items: [
      "上传资源清单文件。",
      "AI 解析字段并清洗数据。",
      "确认资源和关系预览。",
      "查看推断拓扑。",
      "确认导入 CMDB。",
    ],
  },
  {
    title: "支持的文件：",
    items: [
      "Excel / CSV 资源台账优先支持。",
      "Word 文档、拓扑图片可上传，系统会尽量抽取结构化信息。",
      "可以一次上传多个客户或多个系统的清单，进入预览后再筛选。",
    ],
  },
];

function normalizeResourceImportStartPayload(
  payload: ResourceImportStartPayload | null,
  fallbackPayload: ResourceImportStartPayload,
): ResourceImportStartPayload {
  const sourcePayload = payload || fallbackPayload;

  return {
    ...sourcePayload,
    copyBlocks: CANONICAL_RESOURCE_IMPORT_COPY_BLOCKS,
    supportedFormats: sourcePayload.supportedFormats?.length
      ? sourcePayload.supportedFormats
      : fallbackPayload.supportedFormats,
  };
}

function IntroStage({
  agentId,
  flow,
  flowId,
  messageId,
  onUploadFiles,
  onReturnToUpload,
  onStartParse,
}: {
  agentId?: string | null;
  flow: ResourceImportFlowPayload;
  flowId: string;
  messageId: string;
  onUploadFiles: ResourceImportConversationCardProps["onUploadFiles"];
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
  onStartParse: ResourceImportConversationCardProps["onStartParse"];
}) {
  const [metadata, setMetadata] = useState<ResourceImportMetadata | null>(null);
  const [startPayload, setStartPayload] = useState<ResourceImportStartPayload | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const fallbackStartPayload: ResourceImportStartPayload = {
    copyBlocks: CANONICAL_RESOURCE_IMPORT_COPY_BLOCKS,
    supportedFormats: ["Excel", "CSV", "Word", "图片"],
  };

  useEffect(() => {
    let cancelled = false;
    void getResourceImportMetadata(agentId || undefined)
      .then((response) => {
        if (!cancelled) {
          setMetadata(response);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.warn("[resource-import] CMDB metadata load failed; using fallback intro copy", err);
        }
      });
    void getResourceImportStart(agentId || undefined)
      .then((response) => {
        if (!cancelled) {
          setStartPayload(response);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStartPayload(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [agentId]);

  const handleFiles = (nextFiles: FileList | File[] | null) => {
    const normalized = nextFiles ? Array.from(nextFiles).filter((file) => file.size > 0) : [];
    if (!normalized.length) {
      return;
    }
    onUploadFiles({
      sourceMessageId: messageId,
      flowId,
      files: normalized,
    });
  };

  const introPayload = normalizeResourceImportStartPayload(startPayload, fallbackStartPayload);
  const supportedFormats = metadata?.supportedFormats?.length
    ? metadata.supportedFormats
    : introPayload.supportedFormats;

  return (
    <div
      className={dragActive ? "resource-import-conversation-card drag-active" : "resource-import-conversation-card"}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragActive(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (!dragActive) {
          setDragActive(true);
        }
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        const nextTarget = event.relatedTarget as Node | null;
        if (!event.currentTarget.contains(nextTarget)) {
          setDragActive(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragActive(false);
        handleFiles(event.dataTransfer.files);
      }}
    >
      <div className="resource-import-stage">
        {introPayload.copyBlocks.map((block) => (
          <div key={block.title} className="resource-import-copy-block">
            <strong>{block.title}</strong>
            {block.ordered ? (
              <ol>
                {(block.items || []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            ) : block.items?.length ? (
              <ul>
                {block.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
            {(block.paragraphs || []).map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </div>
        ))}

        <div className="resource-import-dropzone">
          <label className="resource-import-dropzone-inner">
            <input
              type="file"
              hidden
              multiple
              accept={supportedFormats.join(",")}
              onChange={(event) => handleFiles(event.target.files)}
            />
            <div className="resource-import-dropzone-icon">📂</div>
            <div className="resource-import-dropzone-title">拖拽文件到此处，或点击选择文件</div>
            <div className="resource-import-dropzone-hint">
              支持 Excel、CSV、Word、图片，可一次上传多个文件
            </div>
          </label>
        </div>

        {flow.files?.length ? (
          <div className="resource-import-file-stack">
            {flow.files.map((file) => (
              <div key={`${file.name}-${file.size}`} className="resource-import-file-chip">
                <span>{getFileEmoji(file.name)}</span>
                <div>
                  <strong>{file.name}</strong>
                  <small>{formatFileSize(file.size)}</small>
                </div>
              </div>
            ))}
          </div>
        ) : null}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() => onReturnToUpload({ flowId, sourceMessageId: messageId })}
          >
            清空文件
          </button>
          <button
            type="button"
            className="primary"
            disabled={!flow.files?.length}
            onClick={() =>
              onStartParse({
                messageId,
                flowId,
              })
            }
          >
            开始智能解析
          </button>
        </div>
      </div>
    </div>
  );
}

function ParsingStage({
  agentId,
  flow,
  messageId,
  resolveFiles,
  releaseFiles,
  onParseResolved,
  onParseFailed,
  onReturnToUpload,
}: {
  agentId?: string | null;
  flow: ResourceImportFlowPayload;
  messageId: string;
  resolveFiles: ResourceImportConversationCardProps["resolveFiles"];
  releaseFiles: ResourceImportConversationCardProps["releaseFiles"];
  onParseResolved: ResourceImportConversationCardProps["onParseResolved"];
  onParseFailed: ResourceImportConversationCardProps["onParseFailed"];
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
}) {
  const startedRef = useRef(false);
  const [displayedLogs, setDisplayedLogs] = useState<string[]>(flow.preview?.logs || []);
  const [parsePercent, setParsePercent] = useState(flow.status === "completed" ? 100 : 8);

  useEffect(() => {
    if (flow.preview?.logs?.length) {
      setDisplayedLogs(flow.preview.logs);
    }
    if (flow.status === "completed") {
      setParsePercent(100);
    }
  }, [flow.preview?.logs, flow.status]);

  useEffect(() => {
    if (flow.status !== "running" || startedRef.current) {
      return;
    }

    const files = resolveFiles(flow.flowId);
    if (!files.length) {
      onParseFailed({
        messageId,
        flowId: flow.flowId,
        error: "未找到待解析的上传文件，请重新上传。",
      });
      return;
    }

    startedRef.current = true;
    let cancelled = false;
    const defaultLogs = [...DEFAULT_PARSE_LOGS];
    setDisplayedLogs(defaultLogs.slice(0, 2));
    setParsePercent(8);

    void previewResourceImport(files, agentId || undefined, {
      onProgress: (job: ResourceImportPreviewJob) => {
        if (cancelled) {
          return;
        }
        const progressLogs = (job.progressEvents || [])
          .map((event) => String(event.message || "").trim())
          .filter(Boolean);
        startTransition(() => {
          setDisplayedLogs(progressLogs.length ? progressLogs : defaultLogs);
          setParsePercent(
            typeof job.progressPercent === "number"
              ? Math.max(8, Math.min(100, job.progressPercent))
              : 12,
          );
        });
      },
      maxWaitMs: 20 * 60 * 1000,
    })
      .then((preview) => {
        if (cancelled) {
          return;
        }
        const finalLogs = preview.logs.length ? preview.logs : defaultLogs;
        startTransition(() => {
          setDisplayedLogs(finalLogs);
          setParsePercent(100);
        });
        releaseFiles(flow.flowId);
        window.setTimeout(() => {
          if (!cancelled) {
            onParseResolved({
              messageId,
              flowId: flow.flowId,
              preview,
            });
          }
        }, 220);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        releaseFiles(flow.flowId);
        onParseFailed({
          messageId,
          flowId: flow.flowId,
          error: extractErrorMessage(error) || "资源解析失败",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [
    agentId,
    flow.flowId,
    flow.status,
    messageId,
    onParseFailed,
    onParseResolved,
    releaseFiles,
    resolveFiles,
  ]);

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="parsing" forceCompleted={flow.status === "completed"} />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}

      <div className="resource-import-stage">
        <div className="resource-import-file-stack">
          {(flow.files || []).map((file) => (
            <div key={`${file.name}-${file.size}`} className="resource-import-file-chip">
              <span>{getFileEmoji(file.name)}</span>
              <div>
                <strong>{file.name}</strong>
                <small>{formatFileSize(file.size)}</small>
              </div>
            </div>
          ))}
        </div>

        <div className="resource-import-parse-card">
          <div className="resource-import-parse-header">
            <strong>🔍 正在智能解析文件...</strong>
            <span>{flow.status === "error" ? "失败" : `${parsePercent}%`}</span>
          </div>
          <div className="resource-import-parse-bar">
            <div className="resource-import-parse-bar-fill" style={{ width: `${parsePercent}%` }} />
          </div>
          <div className="resource-import-parse-status">
            {flow.status === "completed"
              ? "解析完成"
              : flow.status === "error"
                ? "解析失败"
                : "解析中..."}
          </div>
          <div className="resource-import-parse-log">
            {(displayedLogs.length ? displayedLogs : ["→ 等待解析开始..."]).map((logLine, index) => (
              <div key={`${logLine}-${index}`} className="resource-import-log-line">
                {logLine}
              </div>
            ))}
          </div>
        </div>

        {flow.status === "error" ? (
          <div className="resource-import-action-row">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                onReturnToUpload({
                  flowId: flow.flowId,
                  sourceMessageId: messageId,
                })
              }
            >
              重新上传
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StructureStage({
  agentId,
  flow,
  messageId,
  onReturnToUpload,
  onConfirmStructure,
}: {
  agentId?: string | null;
  flow: ResourceImportFlowPayload;
  messageId: string;
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
  onConfirmStructure: ResourceImportConversationCardProps["onConfirmStructure"];
}) {
  const [metadata, setMetadata] = useState<ResourceImportMetadata | null>(null);
  const [items, setItems] = useState<ResourceImportStructureItem[]>(
    flow.preview?.structureAnalysis?.items || [],
  );
  const [error, setError] = useState("");
  const [editingItemKey, setEditingItemKey] = useState<string | null>(null);
  const [modelDraft, setModelDraft] = useState<{
    groupName: string;
    name: string;
    alias: string;
    inheritFrom: string;
    uniqueKey: string;
  }>({
    groupName: "",
    name: "",
    alias: "",
    inheritFrom: "",
    uniqueKey: "",
  });

  useEffect(() => {
    setItems(flow.preview?.structureAnalysis?.items || []);
  }, [flow.preview]);

  useEffect(() => {
    let cancelled = false;
    void getResourceImportMetadata(agentId || undefined)
      .then((response) => {
        if (!cancelled) {
          setMetadata(response);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(extractErrorMessage(err) || "CMDB 元数据加载失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  const updateItem = (
    key: string,
    updater: (item: ResourceImportStructureItem) => ResourceImportStructureItem,
  ) => {
    setItems((current) => current.map((item) => (item.key === key ? updater(item) : item)));
  };

  const openModelConfig = (item: ResourceImportStructureItem) => {
    const nextDraft = {
      groupName: item.selectedGroupName || item.suggestedGroupName || "",
      name: item.modelDraft?.name || item.selectedModelName || item.suggestedModelName || item.resourceCiType || "",
      alias: item.modelDraft?.alias || item.resourceLabel || "",
      inheritFrom: item.modelDraft?.inheritFrom || "",
      uniqueKey: item.modelDraft?.uniqueKey || "",
    };
    setEditingItemKey(item.key);
    setModelDraft({
      ...nextDraft,
      uniqueKey: nextDraft.uniqueKey || getSuggestedUniqueKey(flow.preview, item, metadata, nextDraft),
    });
  };

  const editingItem = editingItemKey
    ? items.find((item) => item.key === editingItemKey) || null
    : null;
  const editingGroupOptions = editingItem ? getStructureGroupOptions(editingItem, metadata) : [];
  const editingModelOptions = editingItem
    ? getStructureModelOptions(editingItem, metadata, modelDraft.groupName || "")
    : [];
  const editingGroupExists = editingItem
    ? isExistingStructureGroup(editingItem, metadata, modelDraft.groupName || "")
    : false;
  const editingModelExists = editingItem
    ? editingModelOptions.some((option) => option.existing && option.name === modelDraft.name)
    : false;
  const editingGroupSelectValue = getStructureSelectValue(modelDraft.groupName, editingGroupOptions);
  const editingModelSelectValue = getStructureSelectValue(modelDraft.name, editingModelOptions);
  const blockingAnalysisIssues = getBlockingAnalysisIssues(flow.preview);
  const blockingAnalysisMessage = getBlockingAnalysisMessage(flow.preview);

  const validationError = items.find((item) => {
    const existingGroupSelected = isExistingStructureGroup(
      item,
      metadata,
      item.selectedGroupName || "",
    );
    const existingModelSelected = isExistingStructureModel(item, metadata);
    const requiresGroupCreate = !existingGroupSelected;
    const requiresModelDraft = !existingModelSelected;
    const hasValidModelDraft = item.modelDraft?.name === item.selectedModelName && Boolean(item.modelDraft?.uniqueKey);
    if (requiresGroupCreate && !item.createGroupApproved) {
      return true;
    }
    if (requiresModelDraft && !item.createModelApproved) {
      return true;
    }
    if (requiresModelDraft && !hasValidModelDraft) {
      return true;
    }
    return !(item.selectedGroupName && item.selectedModelName);
  })
    ? "请先完成当前资源的分组/模型确认。"
    : blockingAnalysisMessage;

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="structure" />

      <div className="resource-import-stage">
        <section className="resource-import-section">
          <div className="resource-import-section-header">
            <div className="resource-import-section-title">分组与模型预检查</div>
            <span className="resource-import-section-subtitle">
              解析后先判断分组和模型，再进入数据确认
            </span>
          </div>

          {error ? <div className="resource-import-inline-error">{error}</div> : null}
          {blockingAnalysisIssues.length ? (
            <div className="resource-import-inline-error">
              <strong>本次解析结果不完整，已禁止继续导入。</strong>
              <ul className="resource-import-issue-list">
                {blockingAnalysisIssues.map((issue, index) => (
                  <li key={`${issue.fileName || issue.sheetName || "issue"}-${index}`}>{issue.message}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="resource-import-structure-list">
            {items.map((item) => {
              const groupOptions = getStructureGroupOptions(item, metadata);
              const modelOptions = getStructureModelOptions(
                item,
                metadata,
                item.selectedGroupName || "",
              );
              const existingGroupSelected = isExistingStructureGroup(
                item,
                metadata,
                item.selectedGroupName || "",
              );
              const existingModelSelected = isExistingStructureModel(item, metadata);
              const requiresGroupCreate = !existingGroupSelected;
              const requiresModelDraft = !existingModelSelected;
              const groupSelectValue = getStructureSelectValue(item.selectedGroupName || "", groupOptions);
              const modelSelectValue = getStructureSelectValue(item.selectedModelName || "", modelOptions);
              const originalTypeText = String(
                item.originalTypeText
                || item.rawTypeHints?.[0]
                || item.resourceCiType
                || item.resourceLabel
                || "",
              ).trim();
              const selectedModelOption = modelOptions.find((option) => option.name === item.selectedModelName);
              const selectedModelDisplayName = selectedModelOption?.alias
                ? `${selectedModelOption.alias} (${selectedModelOption.name})`
                : String(item.selectedModelName || "").trim();
              const selectedGroupDisplayName = String(item.selectedGroupName || "").trim();

              return (
                <div key={item.key} className="resource-import-structure-card">
                  <div className="resource-import-structure-header">
                    <div>
                      <strong>{item.resourceLabel}</strong>
                      <small>{item.recordCount} 条记录</small>
                    </div>
                    <span className={`resource-import-structure-badge ${item.status}`.trim()}>
                      {getStructureStatusLabel(item.status)}
                    </span>
                  </div>

                  {item.reason ? <p className="resource-import-structure-reason">{item.reason}</p> : null}

                  <div className="resource-import-structure-mapping">
                    <div><span>原文类型</span>{originalTypeText || "未提供"}</div>
                    <div>
                      <span>当前映射</span>
                      {selectedGroupDisplayName || selectedModelDisplayName
                        ? `${selectedGroupDisplayName || "未定分组"} / ${selectedModelDisplayName || "未定模型"}`
                        : "待确认"}
                    </div>
                    <div><span>匹配置信度</span>{getStructureConfidenceLabel(item.semanticConfidence)}</div>
                  </div>

                  {item.rawTypeHints?.length ? (
                    <div className="resource-import-structure-hints">
                      原始类型提示：{item.rawTypeHints.join(" / ")}
                    </div>
                  ) : null}

                  <div className="resource-import-structure-grid">
                    <label className="resource-import-structure-field">
                      <span>目标分组</span>
                      <select
                        value={groupSelectValue}
                        onChange={(event) => {
                          const selectedValue = event.target.value;
                          updateItem(item.key, (current) => {
                            const nextGroupName = selectedValue === CUSTOM_STRUCTURE_OPTION_VALUE
                              ? (isExistingStructureGroup(current, metadata, current.selectedGroupName || "")
                                ? ""
                                : String(current.selectedGroupName || "").trim())
                              : selectedValue;
                            const nextModelOptions = getStructureModelOptions(current, metadata, nextGroupName);
                            const nextModelName = nextModelOptions.some(
                              (option) => option.name === current.selectedModelName,
                            )
                              ? current.selectedModelName
                              : (nextModelOptions[0]?.name || current.selectedModelName);
                            const nextGroupExists = isExistingStructureGroup(current, metadata, nextGroupName);
                            return {
                              ...current,
                              selectedGroupName: nextGroupName,
                              selectedModelName: nextModelName,
                              createGroupApproved: nextGroupExists ? false : current.createGroupApproved,
                              createModelApproved: nextModelOptions.some(
                                (option) => option.existing && option.name === nextModelName,
                              )
                                ? false
                                : current.createModelApproved,
                              modelDraft: current.modelDraft?.name === nextModelName
                                ? current.modelDraft
                                : undefined,
                            };
                          });
                        }}
                      >
                        {groupOptions.map((option) => (
                          <option key={option.name} value={option.name}>
                            {option.name}
                          </option>
                        ))}
                        <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新分组...</option>
                      </select>
                      {groupSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                        <input
                          type="text"
                          value={item.selectedGroupName || ""}
                          onChange={(event) => {
                            const nextGroupName = event.target.value;
                            updateItem(item.key, (current) => {
                              const nextModelOptions = getStructureModelOptions(current, metadata, nextGroupName);
                              const nextModelName = nextModelOptions.some(
                                (option) => option.name === current.selectedModelName,
                              )
                                ? current.selectedModelName
                                : "";
                              const nextGroupExists = isExistingStructureGroup(current, metadata, nextGroupName);
                              return {
                                ...current,
                                selectedGroupName: nextGroupName,
                                selectedModelName: nextModelName,
                                createGroupApproved: nextGroupExists ? false : current.createGroupApproved,
                                createModelApproved: nextModelOptions.some(
                                  (option) => option.existing && option.name === nextModelName,
                                )
                                  ? false
                                  : current.createModelApproved,
                                modelDraft: current.modelDraft?.name === nextModelName
                                  ? current.modelDraft
                                  : undefined,
                              };
                            });
                          }}
                          placeholder="输入新分组名称"
                        />
                      ) : null}
                    </label>

                    <label className="resource-import-structure-field">
                      <span>目标模型</span>
                      <select
                        value={modelSelectValue}
                        onChange={(event) =>
                          updateItem(item.key, (current) => ({
                            ...current,
                            selectedModelName: event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                              ? (isExistingStructureModel(current, metadata)
                                ? ""
                                : String(current.selectedModelName || "").trim())
                              : event.target.value,
                            createModelApproved: event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                              ? current.createModelApproved
                              : false,
                            modelDraft: undefined,
                          }))}
                      >
                        {modelOptions.map((option) => (
                          <option key={option.name} value={option.name}>
                            {option.alias ? `${option.alias} (${option.name})` : option.name}
                          </option>
                        ))}
                        <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新模型...</option>
                      </select>
                      {modelSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                        <input
                          type="text"
                          value={item.selectedModelName || ""}
                          onChange={(event) =>
                            updateItem(item.key, (current) => ({
                              ...current,
                              selectedModelName: event.target.value,
                              createModelApproved: false,
                              modelDraft: undefined,
                            }))}
                          placeholder="输入新模型名称"
                        />
                      ) : null}
                    </label>
                  </div>

                  {requiresGroupCreate ? (
                    <label className="resource-import-structure-check">
                      <input
                        type="checkbox"
                        checked={existingGroupSelected ? false : Boolean(item.createGroupApproved)}
                        disabled={existingGroupSelected}
                        onChange={(event) =>
                          updateItem(item.key, (current) => ({
                            ...current,
                            createGroupApproved: event.target.checked,
                          }))}
                      />
                      <span>{existingGroupSelected ? "当前已选择现有分组，无需创建" : "若当前分组不存在，确认后续创建该分组"}</span>
                    </label>
                  ) : null}

                  {requiresModelDraft ? (
                    <label className="resource-import-structure-check">
                      <input
                        type="checkbox"
                        checked={Boolean(item.createModelApproved)}
                        onChange={(event) =>
                          updateItem(item.key, (current) => ({
                            ...current,
                            createModelApproved: event.target.checked,
                          }))}
                      />
                      <span>确认后续创建该模型，并补齐模型必填参数</span>
                    </label>
                  ) : null}

                  {requiresModelDraft ? (
                    <div className="resource-import-structure-draft">
                      <div>
                        <strong>
                          {item.modelDraft?.alias || item.modelDraft?.name || "尚未配置新模型"}
                        </strong>
                        <small>
                          模型名: {item.modelDraft?.name || "未填写"}
                          {" · "}继承: {item.modelDraft?.inheritFrom || "无"}
                          {" · "}唯一标识: {item.modelDraft?.uniqueKey || "未选择"}
                        </small>
                      </div>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => openModelConfig(item)}
                      >
                        配置新模型
                      </button>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>

        {validationError ? (
          <div className="resource-import-inline-error">{validationError}</div>
        ) : null}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() =>
              onReturnToUpload({
                flowId: flow.flowId,
                sourceMessageId: messageId,
              })}
          >
            结束本次导入
          </button>
          <button
            type="button"
            className="primary"
            disabled={Boolean(validationError)}
            onClick={() => {
              const next = applyStructureSelectionsToPreview(flow.preview, items);
              onConfirmStructure({
                messageId,
                flowId: flow.flowId,
                preview: next.preview,
                resourceGroups: next.resourceGroups,
                relations: next.relations,
              });
            }}
          >
            进入数据确认
          </button>
        </div>
      </div>

      {editingItem ? (
        <div className="resource-import-modal-backdrop" onClick={() => setEditingItemKey(null)}>
          <div className="resource-import-modal" onClick={(event) => event.stopPropagation()}>
            <div className="resource-import-modal-header">
              <div>
                <h3>配置新模型</h3>
                <p>
                  为 {editingItem.resourceLabel} 补充模型创建参数。这里只采集参数，真正创建动作仍需用户确认。
                </p>
              </div>
              <button type="button" className="secondary" onClick={() => setEditingItemKey(null)}>
                关闭
              </button>
            </div>

            <div className="resource-import-modal-grid">
              <label className="resource-import-field">
                <span>所属分组</span>
                <select
                  value={editingGroupSelectValue}
                  onChange={(event) =>
                    setModelDraft((current) => {
                      const nextGroupName = event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                        ? (editingGroupExists ? "" : String(current.groupName || "").trim())
                        : event.target.value;
                      const nextModelOptions = editingItem
                        ? getStructureModelOptions(editingItem, metadata, nextGroupName)
                        : [];
                      const nextModelName = nextModelOptions.some((option) => option.name === current.name)
                        ? current.name
                        : "";
                      return {
                        ...current,
                        groupName: nextGroupName,
                        name: nextModelName,
                      };
                    })}
                >
                  {editingGroupOptions.map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.name}
                    </option>
                  ))}
                  <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新分组...</option>
                </select>
                {editingGroupSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                  <input
                    type="text"
                    value={modelDraft.groupName}
                    onChange={(event) =>
                      setModelDraft((current) => ({
                        ...current,
                        groupName: event.target.value,
                        name: "",
                      }))}
                    placeholder="输入新分组名称"
                  />
                ) : null}
              </label>

              <label className="resource-import-field">
                <span>模型名</span>
                <select
                  value={editingModelSelectValue}
                  onChange={(event) =>
                    setModelDraft((current) => ({
                      ...current,
                      name: event.target.value === CUSTOM_STRUCTURE_OPTION_VALUE
                        ? (editingModelExists ? "" : String(current.name || "").trim())
                        : event.target.value,
                    }))}
                >
                  {editingModelOptions.map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.alias ? `${option.alias} (${option.name})` : option.name}
                    </option>
                  ))}
                  <option value={CUSTOM_STRUCTURE_OPTION_VALUE}>自定义新模型...</option>
                </select>
                {editingModelSelectValue === CUSTOM_STRUCTURE_OPTION_VALUE ? (
                  <input
                    value={modelDraft.name}
                    onChange={(event) =>
                      setModelDraft((current) => ({
                        ...current,
                        name: event.target.value,
                      }))}
                    placeholder="输入新模型名称"
                  />
                ) : null}
              </label>

              <label className="resource-import-field">
                <span>模型别名</span>
                <input
                  value={modelDraft.alias}
                  onChange={(event) =>
                    setModelDraft((current) => ({
                      ...current,
                      alias: event.target.value,
                    }))}
                  placeholder="例如 网络设备扩展模型"
                />
              </label>

              <label className="resource-import-field">
                <span>继承模型</span>
                <select
                  value={modelDraft.inheritFrom}
                  onChange={(event) =>
                    setModelDraft((current) => {
                      const nextDraft = {
                        ...current,
                        inheritFrom: event.target.value,
                      };
                      const nextOptions = getStructureUniqueKeyOptions(
                        flow.preview,
                        editingItem,
                        metadata,
                        nextDraft,
                      );
                      return {
                        ...nextDraft,
                        uniqueKey: nextOptions.some((option) => option.name === nextDraft.uniqueKey)
                          ? nextDraft.uniqueKey
                          : (nextOptions[0]?.name || ""),
                      };
                    })}
                >
                  <option value="">不继承</option>
                  {getStructureInheritanceOptions(metadata, editingItem).map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.alias ? `${option.alias} (${option.name})` : option.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="resource-import-field">
                <span>唯一标识</span>
                <select
                  value={modelDraft.uniqueKey}
                  onChange={(event) =>
                    setModelDraft((current) => ({
                      ...current,
                      uniqueKey: event.target.value,
                    }))}
                >
                  <option value="">请选择唯一标识字段</option>
                  {getStructureUniqueKeyOptions(flow.preview, editingItem, metadata, modelDraft).map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.label} ({option.name}) {option.coverage ? `· 覆盖 ${option.coverage}%` : ""}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="resource-import-modal-footer">
              <button type="button" className="secondary" onClick={() => setEditingItemKey(null)}>
                取消
              </button>
              <button
                type="button"
                className="primary"
                disabled={!modelDraft.groupName || !modelDraft.name || (!editingModelExists && !modelDraft.uniqueKey)}
                onClick={() => {
                  updateItem(editingItem.key, (current) => ({
                    ...current,
                    selectedGroupName: modelDraft.groupName,
                    selectedModelName: modelDraft.name,
                    createGroupApproved: editingGroupExists ? false : current.createGroupApproved,
                    createModelApproved: editingModelExists ? false : true,
                    modelDraft: {
                      name: modelDraft.name,
                      alias: modelDraft.alias,
                      inheritFrom: modelDraft.inheritFrom,
                      uniqueKey: modelDraft.uniqueKey,
                    },
                  }));
                  setEditingItemKey(null);
                }}
              >
                保存模型配置
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ConfirmStage({
  flow,
  messageId,
  onReturnToUpload,
  onBuildTopology,
}: {
  flow: ResourceImportFlowPayload;
  messageId: string;
  onReturnToUpload: ResourceImportConversationCardProps["onReturnToUpload"];
  onBuildTopology: ResourceImportConversationCardProps["onBuildTopology"];
}) {
  const [resourceGroups, setResourceGroups] = useState<ResourceImportGroup[]>(flow.resourceGroups || []);
  const [relations, setRelations] = useState<ResourceImportRelation[]>(flow.relations || []);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorFocusPreviewKey, setEditorFocusPreviewKey] = useState<string | null>(null);
  const [uniqueKeySelections, setUniqueKeySelections] = useState<Record<string, string>>({});
  const [autoResolvedUniqueKeys, setAutoResolvedUniqueKeys] = useState<Array<{
    ciType: string;
    label: string;
    uniqueKey: string;
    uniqueKeyLabel: string;
    uniqueKeyDisplay: string;
    sourceField: string;
    sourceLabel: string;
  }>>([]);
  const [batchEditorScrollWidth, setBatchEditorScrollWidth] = useState(0);
  const [batchEditorViewportWidth, setBatchEditorViewportWidth] = useState(0);
  const batchEditorWrapRef = useRef<HTMLDivElement | null>(null);
  const batchEditorTopScrollbarRef = useRef<HTMLDivElement | null>(null);
  const autoAppliedUniqueKeyPlansRef = useRef<Set<string>>(new Set());
  const blockingAnalysisIssues = getBlockingAnalysisIssues(flow.preview);
  const blockingAnalysisMessage = getBlockingAnalysisMessage(flow.preview);

  useEffect(() => {
    setResourceGroups(flow.resourceGroups || []);
    setRelations(flow.relations || []);
  }, [flow.resourceGroups, flow.relations, messageId]);

  const updateRecord = (
    previewKey: string,
    updater: (record: ResourceImportRecord) => ResourceImportRecord,
  ) => {
    setResourceGroups((current) =>
      current.map((group) => ({
        ...group,
        records: group.records.map((record) =>
          record.previewKey === previewKey ? updater(record) : record,
        ),
      })),
    );
  };

  const selectedCount = useMemo(
    () => countSelectedRecords(resourceGroups),
    [resourceGroups],
  );
  const ambiguousMappings = useMemo(
    () => (flow.preview?.mappingSummary || []).filter((item) => item.status === "needs_confirmation" || item.needsConfirmation),
    [flow.preview],
  );
  const aggregatedAmbiguousMappings = useMemo(
    () => buildAggregatedAmbiguousMappings(flow.preview?.mappingSummary || []),
    [flow.preview],
  );
  const ciTypeOptions = useMemo(
    () => Array.from(new Set(resourceGroups.map((group) => group.ciType).filter(Boolean))),
    [resourceGroups],
  );
  const batchEditorColumns = useMemo(
    () => getBatchEditorColumns(flow.preview || null, resourceGroups),
    [flow.preview, resourceGroups],
  );
  const batchColumnAttentionMap = useMemo(() => {
    const entries = batchEditorColumns.map((column) => {
      const needsAttention = resourceGroups.some((group) =>
        group.records.some((record) => {
          const definition = getVisibleAttributeDefinitions(flow.preview || null, record.ciType, record)
            .find((item) => item.name === column.key);
          return fieldNeedsAttention(record, column.key, definition);
        }),
      );
      return [column.key, needsAttention] as const;
    });
    return new Map(entries);
  }, [batchEditorColumns, flow.preview, resourceGroups]);
  const batchColumnDefaultMap = useMemo(() => {
    const entries = batchEditorColumns.map((column) => {
      const usesDefault = resourceGroups.some((group) =>
        group.records.some((record) => {
          const definition = getVisibleAttributeDefinitions(flow.preview || null, record.ciType, record)
            .find((item) => item.name === column.key);
          return Boolean(getRequiredDefaultMessage(record, column.key, definition));
        }),
      );
      return [column.key, usesDefault] as const;
    });
    return new Map(entries);
  }, [batchEditorColumns, flow.preview, resourceGroups]);
  const uniqueKeyPlans = useMemo(
    () => getUniqueKeyResolutionPlans(flow.preview || null, resourceGroups),
    [flow.preview, resourceGroups],
  );
  const systemGeneratedUniqueKeyPlans = useMemo(
    () => getSystemGeneratedUniqueKeyPlans(flow.preview || null, resourceGroups),
    [flow.preview, resourceGroups],
  );
  const unresolvedUniqueKeyCount = useMemo(
    () => uniqueKeyPlans.reduce((total, item) => total + item.missingCount, 0),
    [uniqueKeyPlans],
  );
  const unresolvedUniqueKeyMessage = unresolvedUniqueKeyCount
    ? "请先补全模型唯一标识后再继续，避免最后导入时报错。"
    : "";
  const requiredModelIssues = useMemo(
    () => getRequiredModelIssues(flow.preview || null, resourceGroups),
    [flow.preview, resourceGroups],
  );
  const requiredModelBlockingMessage = getRequiredModelBlockingMessage(requiredModelIssues);
  const defaultedRequiredIssues = useMemo(
    () => getDefaultedRequiredModelIssues(flow.preview || null, resourceGroups),
    [flow.preview, resourceGroups],
  );
  const defaultedRequiredMessage = getDefaultedRequiredModelMessage(defaultedRequiredIssues);
  const metadataBlockingMessage = getMetadataBlockingMessage(flow.preview || null);

  useEffect(() => {
    if (!editorOpen || !editorFocusPreviewKey) {
      return;
    }
    const rafId = window.requestAnimationFrame(() => {
      document
        .querySelector(`[data-editor-preview-key="${editorFocusPreviewKey}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    });
    return () => window.cancelAnimationFrame(rafId);
  }, [editorFocusPreviewKey, editorOpen]);

  const openBatchEditor = (previewKey?: string) => {
    setEditorOpen(true);
    setEditorFocusPreviewKey(previewKey || null);
  };

  const closeBatchEditor = () => {
    setEditorOpen(false);
    setEditorFocusPreviewKey(null);
  };

  useEffect(() => {
    autoAppliedUniqueKeyPlansRef.current = new Set();
    setAutoResolvedUniqueKeys([]);
  }, [messageId]);

  useEffect(() => {
    setUniqueKeySelections((current) => {
      const next: Record<string, string> = {};
      uniqueKeyPlans.forEach((item) => {
        const key = `${item.ciType}::${item.uniqueKey}`;
        const currentValue = current[key];
        const recommendedField = item.candidates.find((candidate) => candidate.recommended)?.field || "";
        next[key] = item.candidates.some((candidate) => candidate.field === currentValue)
          ? currentValue
          : recommendedField;
      });
      return next;
    });
  }, [uniqueKeyPlans, messageId]);

  useEffect(() => {
    if (!editorOpen) {
      return;
    }
    const wrap = batchEditorWrapRef.current;
    const topScrollbar = batchEditorTopScrollbarRef.current;
    if (!wrap || !topScrollbar) {
      return;
    }

    const syncDimensions = () => {
      setBatchEditorScrollWidth(wrap.scrollWidth);
      setBatchEditorViewportWidth(wrap.clientWidth);
      topScrollbar.scrollLeft = wrap.scrollLeft;
    };
    const syncFromWrap = () => {
      if (topScrollbar.scrollLeft !== wrap.scrollLeft) {
        topScrollbar.scrollLeft = wrap.scrollLeft;
      }
    };
    const syncFromTop = () => {
      if (wrap.scrollLeft !== topScrollbar.scrollLeft) {
        wrap.scrollLeft = topScrollbar.scrollLeft;
      }
    };

    syncDimensions();
    wrap.addEventListener("scroll", syncFromWrap);
    topScrollbar.addEventListener("scroll", syncFromTop);
    window.addEventListener("resize", syncDimensions);
    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => syncDimensions())
      : null;
    resizeObserver?.observe(wrap);
    const table = wrap.querySelector("table");
    if (table) {
      resizeObserver?.observe(table);
    }
    const rafId = window.requestAnimationFrame(syncDimensions);

    return () => {
      window.cancelAnimationFrame(rafId);
      wrap.removeEventListener("scroll", syncFromWrap);
      topScrollbar.removeEventListener("scroll", syncFromTop);
      window.removeEventListener("resize", syncDimensions);
      resizeObserver?.disconnect();
    };
  }, [batchEditorColumns.length, editorOpen, resourceGroups]);

  const applyUniqueKeySelection = (ciType: string, uniqueKey: string, sourceField: string) => {
    const uniqueKeyLabel = getUniqueKeyLabel(flow.preview || null, ciType) || getAttributeLabel(uniqueKey);
    const sourceLabel = getAttributeLabel(sourceField);
    setResourceGroups((current) =>
      current.map((group) => {
        if (group.ciType !== ciType) {
          return group;
        }
        return {
          ...group,
          records: group.records.map((record) => {
            if (!record.selected) {
              return record;
            }
            const sourceValue = getRecordFieldValue(record, sourceField);
            if (!sourceValue) {
              return record;
            }
            const remainingIssues = (record.issues || []).filter(
              (issue) => !String(issue.message || "").includes("唯一标识"),
            );
            const nextAttributes = {
              ...record.attributes,
              [uniqueKey]: sourceValue,
            };
            return {
              ...record,
              name: uniqueKey === "name" ? sourceValue : record.name,
              attributes: nextAttributes,
              issues: remainingIssues,
              attentionFields: remainingIssues
                .map((issue) => normalizeIssueFieldName(issue.field))
                .filter(Boolean),
              autoFilledHints: Array.from(new Set([
                ...(record.autoFilledHints || []),
                `${uniqueKeyLabel}已按${sourceLabel}批量补全`,
              ])),
            };
          }),
        };
      }),
    );
  };

  useEffect(() => {
    const plansToApply = uniqueKeyPlans.filter((item) => shouldAutoApplyUniqueKeyPlan(item));
    if (!plansToApply.length) {
      return;
    }
    const pendingPlans = plansToApply.filter((item) => {
      const key = `${item.ciType}::${item.uniqueKey}`;
      return !autoAppliedUniqueKeyPlansRef.current.has(key);
    });
    if (!pendingPlans.length) {
      return;
    }

    pendingPlans.forEach((item) => {
      const sourceField = item.candidates[0]?.field;
      if (!sourceField) {
        return;
      }
      autoAppliedUniqueKeyPlansRef.current.add(`${item.ciType}::${item.uniqueKey}`);
      applyUniqueKeySelection(item.ciType, item.uniqueKey, sourceField);
      setAutoResolvedUniqueKeys((current) => {
        const key = `${item.ciType}::${item.uniqueKey}`;
        if (current.some((entry) => `${entry.ciType}::${entry.uniqueKey}` === key)) {
          return current;
        }
        return [
          ...current,
          {
            ciType: item.ciType,
            label: item.label,
            uniqueKey: item.uniqueKey,
            uniqueKeyLabel: item.uniqueKeyLabel || item.uniqueKey,
            uniqueKeyDisplay: item.uniqueKeyDisplay || item.uniqueKeyLabel || item.uniqueKey,
            sourceField,
            sourceLabel: item.candidates[0]?.label || getAttributeLabel(sourceField),
          },
        ];
      });
    });
  }, [uniqueKeyPlans]);

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="confirm" />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}
      {blockingAnalysisIssues.length ? (
        <div className="resource-import-inline-error">
          <strong>{blockingAnalysisMessage}</strong>
          <ul className="resource-import-issue-list">
            {blockingAnalysisIssues.map((issue, index) => (
              <li key={`${issue.fileName || issue.sheetName || "issue"}-${index}`}>{issue.message}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {requiredModelIssues.length ? (
        <div className="resource-import-inline-error">
          <strong>{requiredModelBlockingMessage}</strong>
          <ul className="resource-import-issue-list">
            {requiredModelIssues.slice(0, 10).map((issue, index) => (
              <li key={`${issue.previewKey}-${issue.field}-${index}`}>
                {issue.sourceLabel} / {issue.recordName}：{issue.message}
              </li>
            ))}
          </ul>
          {requiredModelIssues.length > 10 ? (
            <div>还有 {requiredModelIssues.length - 10} 个缺失字段，请在“统一编辑全部数据”中补齐。</div>
          ) : null}
        </div>
      ) : null}
      {defaultedRequiredIssues.length ? (
        <div className="resource-import-inline-notice resource-import-inline-notice-default">
          <strong>{defaultedRequiredMessage}</strong>
          <ul className="resource-import-issue-list">
            {defaultedRequiredIssues.slice(0, 5).map((issue, index) => (
              <li key={`${issue.previewKey}-${issue.field}-default-${index}`}>
                {issue.sourceLabel} / {issue.recordName}：{getAttributeLabel(issue.field)} {issue.message}
              </li>
            ))}
          </ul>
          {defaultedRequiredIssues.length > 5 ? (
            <div>还有 {defaultedRequiredIssues.length - 5} 个默认值字段已在“统一编辑全部数据”中标注。</div>
          ) : null}
        </div>
      ) : null}
      {metadataBlockingMessage ? (
        <div className="resource-import-inline-error">
          <strong>{metadataBlockingMessage}</strong>
          {flow.preview?.metadataMessage ? <div>{flow.preview.metadataMessage}</div> : null}
        </div>
      ) : null}

      <div className="resource-import-stage">
        <div className="resource-import-stat-grid">
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.resourceCount ?? 0}</strong>
            <span>资产记录数</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.autoCleaned ?? 0}</strong>
            <span>自动清洗</span>
          </div>
          <div className="resource-import-stat-card warning">
            <strong>{flow.preview?.summary.needsConfirmation ?? 0}</strong>
            <span>需要确认</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.qualityScore ?? 0}%</strong>
            <span>数据质量</span>
          </div>
        </div>

        <section className="resource-import-section">
          <div className="resource-import-section-title">🔗 智能字段映射</div>
          {ambiguousMappings.length ? (
            <div className="resource-import-mapping-alert">
              <div className="resource-import-inline-error">
                以下字段同时命中了多个语义候选，系统已暂停自动写入这些列。请核对后继续；如确需保留其值，请在“统一编辑全部数据”中手动补到正确字段。
              </div>
              <div className="resource-import-ambiguous-list">
                {aggregatedAmbiguousMappings.map((item, index) => (
                  <div
                    key={`${item.sourceField}-${item.candidates.map((candidate) => candidate.targetField).join("-")}-${index}`}
                    className="resource-import-ambiguous-item"
                  >
                    <div className="resource-import-ambiguous-header">
                      <strong>{item.sourceField}</strong>
                      <span>{item.scopes.length} 个位置</span>
                    </div>
                    <p>{item.message || "该字段存在多语义候选，需人工确认。"}</p>
                    <div className="resource-import-ambiguous-scopes">
                      {item.scopes.map((scope) => (
                        <span key={`${scope.fileName}-${scope.sheetName}`}>
                          {scope.fileName ? `${scope.fileName} / ${scope.sheetName}` : scope.sheetName}
                        </span>
                      ))}
                    </div>
                    <div className="resource-import-ambiguous-candidates">
                      {(item.candidates || []).map((candidate) => (
                        <span key={`${item.sourceField}-${candidate.targetField}`}>
                          {candidate.targetField} · {candidate.confidence}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="resource-import-action-row">
                <button
                  type="button"
                  className="resource-import-highlight-action"
                  onClick={() => openBatchEditor()}
                >
                  去统一编辑歧义字段
                </button>
              </div>
              <div className="resource-import-inline-notice resource-import-inline-notice-attention">
                歧义列不会自动写入。需要保留原值时，请在统一编辑中补到正确字段；不需要的内容可直接忽略。
              </div>
            </div>
          ) : null}
          <div className="resource-import-mapping-grid">
            {(flow.preview?.mappingSummary || []).slice(0, 8).map((item) => (
              <div
                key={`${item.fileName || "file"}-${item.sheetName || "sheet"}-${item.sourceField}-${item.targetField || item.suggestedTargetField || "unknown"}`}
                className={`resource-import-mapping-item ${item.status || "mapped"}`.trim()}
              >
                <span>{item.fileName ? `${item.sheetName || "Sheet1"} / ${item.sourceField}` : item.sourceField}</span>
                <strong>{item.status === "needs_confirmation" ? (item.suggestedTargetField || "待确认") : item.targetField}</strong>
                <small>
                  {getMappingStatusLabel(item.status)}
                  {item.resolvedBy ? ` · ${item.resolvedBy}` : ""}
                  {item.confidence ? ` · ${item.confidence}` : ""}
                </small>
              </div>
            ))}
          </div>
        </section>

        {uniqueKeyPlans.length || systemGeneratedUniqueKeyPlans.length ? (
          <section className="resource-import-section">
            <div className="resource-import-section-title">🔑 模型唯一标识处理</div>
            <div className="resource-import-inline-notice">
              CMDB 按模型定义唯一标识字段。业务主键会在这里按模型一次性补全；如果当前模型使用系统自增主键，会直接说明，无需你从源文件里选择来源列。
            </div>
            {autoResolvedUniqueKeys.length ? (
              <div className="resource-import-inline-notice">
                已自动识别并补全：
                {autoResolvedUniqueKeys.map((item) => (
                  ` ${item.label} 使用 ${item.sourceLabel}(${item.sourceField}) -> ${item.uniqueKeyDisplay}`
                )).join("；")}
              </div>
            ) : null}
            {unresolvedUniqueKeyMessage ? (
              <div className="resource-import-inline-error">{unresolvedUniqueKeyMessage}</div>
            ) : null}
            <div className="resource-import-unique-key-list">
              {systemGeneratedUniqueKeyPlans.map((item) => (
                <div key={`${item.ciType}::${item.uniqueKey}::system`} className="resource-import-unique-key-card">
                  <div className="resource-import-unique-key-header">
                    <div>
                      <strong>{item.label}</strong>
                      <small>
                        当前模型唯一标识：{item.uniqueKeyDisplay}
                        {" · "}待补全 {item.missingCount}/{item.totalCount} 条
                      </small>
                    </div>
                  </div>
                  <div className="resource-import-inline-notice">
                    该字段属于 CMDB 系统自增主键，本次导入不会从 Excel 补它；新建资源时会由 CMDB 自动生成。
                  </div>
                </div>
              ))}
              {uniqueKeyPlans.map((item) => {
                const selectionKey = `${item.ciType}::${item.uniqueKey}`;
                const selectedSourceField = uniqueKeySelections[selectionKey] || "";
                return (
                  <div key={selectionKey} className="resource-import-unique-key-card">
                    <div className="resource-import-unique-key-header">
                      <div>
                        <strong>{item.label}</strong>
                        <small>
                          当前模型唯一标识：{item.uniqueKeyDisplay || item.uniqueKeyLabel || item.uniqueKey}
                          {" · "}待补全 {item.missingCount}/{item.totalCount} 条
                        </small>
                      </div>
                    </div>
                    {item.candidates.length === 1 && item.candidates[0]?.recommended ? (
                      <div className="resource-import-inline-notice">
                        已自动识别最合理来源：{item.candidates[0].label} ({item.candidates[0].field})，
                        将用于补全 {item.uniqueKeyDisplay || item.uniqueKeyLabel || item.uniqueKey}。
                      </div>
                    ) : null}
                    <div className="resource-import-unique-key-row">
                      {item.candidates.length === 1 && item.candidates[0]?.recommended ? (
                        <div className="resource-import-unique-key-auto">
                          <strong>{item.candidates[0].label} ({item.candidates[0].field})</strong>
                          <span>{`覆盖 ${item.candidates[0].coverage}% · 唯一 ${item.candidates[0].distinctCoverage}%`}</span>
                        </div>
                      ) : (
                        <>
                          <select
                            value={selectedSourceField}
                            onChange={(event) =>
                              setUniqueKeySelections((current) => ({
                                ...current,
                                [selectionKey]: event.target.value,
                              }))}
                          >
                            <option value="">请选择来源列</option>
                            {item.candidates.map((candidate) => (
                              <option key={`${selectionKey}-${candidate.field}`} value={candidate.field}>
                                {candidate.recommended ? "推荐 · " : ""}
                                {candidate.label} ({candidate.field})
                                {` · 覆盖 ${candidate.coverage}% · 唯一 ${candidate.distinctCoverage}%`}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="secondary"
                            disabled={!selectedSourceField}
                            onClick={() => applyUniqueKeySelection(item.ciType, item.uniqueKey, selectedSourceField)}
                          >
                            一键补全本模型
                          </button>
                        </>
                      )}
                    </div>
                    {item.candidates.length ? (
                      <div className="resource-import-unique-key-hints">
                        {item.candidates.slice(0, 3).map((candidate) => (
                          <span
                            key={`${selectionKey}-${candidate.field}-hint`}
                            className={candidate.recommended ? "recommended" : ""}
                          >
                            {candidate.recommended ? "推荐 · " : ""}
                            {candidate.label}
                            {` · 覆盖 ${candidate.coverage}% · 唯一 ${candidate.distinctCoverage}%`}
                            {candidate.duplicateCount > 0 ? ` · 重复 ${candidate.duplicateCount} 条` : ""}
                            {candidate.examples[0] ? ` · 例如 ${candidate.examples[0]}` : ""}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="resource-import-inline-error">
                        当前模型唯一标识是 {item.uniqueKeyDisplay || item.uniqueKeyLabel || item.uniqueKey}。
                        系统未找到足够高置信的来源列，请手动选择最接近的来源。
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ) : null}

        <section className="resource-import-section cleaning">
          <div className="resource-import-section-title">✅ 数据清洗与标准化报告</div>
          <div className="resource-import-cleaning-list">
            {(flow.preview?.cleaningSummary || []).map((item) => (
              <div key={item.label} className="resource-import-cleaning-item">
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="resource-import-section">
          <div className="resource-import-section-header">
            <div className="resource-import-section-title">📦 当前纳管范围</div>
            <span className="resource-import-section-subtitle">{selectedCount} 条已勾选</span>
          </div>
          <div className="resource-import-inline-notice">
            这里先看摘要，红色表示记录仍不完整。点击编辑后会进入统一的大表格页面，一次性核对全部字段。
          </div>
          <div className="resource-import-action-row">
            <button
              type="button"
              className="secondary"
              onClick={() => downloadConfirmationData(flow.preview || null, resourceGroups)}
            >
              导出标准Excel
            </button>
            <button
              type="button"
              className="resource-import-highlight-action"
              onClick={() => openBatchEditor()}
            >
              统一编辑全部数据
            </button>
          </div>
        </section>

        {resourceGroups.map((group) => (
          <section key={group.ciType} className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">
                {getGroupIcon(group)} {group.label}（{group.records.length}条）
              </div>
              <span className="resource-import-section-subtitle">{group.ciType}</span>
            </div>
            <div className="resource-import-table-wrap">
              <table className="resource-import-table">
                <thead>
                  <tr>
                    <th>纳入</th>
                    <th>名称</th>
                    <th>地址/主机</th>
                    <th>类型</th>
                    <th>状态</th>
                    <th>导入策略</th>
                    <th>来源</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {group.records.map((record) => {
                    const recordIssues = getRecordIssues(record, flow.preview || null);
                    const recordDefaultedIssues = getDefaultedRequiredModelIssues(flow.preview || null, [{
                      ...group,
                      records: [record],
                    }]);
                    return (
                      <tr
                        key={record.previewKey}
                        className={`${record.selected ? "" : "muted"} ${recordIssues.length ? "needs-attention" : ""}`.trim()}
                      >
                        <td>
                          <input
                            type="checkbox"
                            checked={record.selected}
                            onChange={(event) =>
                              updateRecord(record.previewKey, (current) => ({
                                ...current,
                                selected: event.target.checked,
                              }))
                            }
                          />
                        </td>
                        <td>
                          <div className="resource-import-cell-main">
                            <strong>{getDisplayName(record)}</strong>
                            {record.generated ? <small>系统补全</small> : null}
                            <div className="resource-import-inline-tags">
                              {record.existingCi?.ciId !== undefined ? (
                                <span className="resource-import-alert-tag warning">
                                  已存在
                                </span>
                              ) : null}
                              {recordIssues.length ? (
                                <span className="resource-import-alert-tag danger">
                                  数据不完整 {recordIssues.length}
                                </span>
                              ) : null}
                              {recordDefaultedIssues.length ? (
                                <span className="resource-import-alert-tag info">
                                  默认值 {recordDefaultedIssues.length}
                                </span>
                              ) : null}
                            </div>
                            {recordIssues.length ? (
                              <small className="resource-import-inline-issue">
                                {recordIssues[0]?.message || "字段待确认，请点编辑补齐"}
                              </small>
                            ) : null}
                            {record.autoFilledHints?.length ? (
                              <small className="resource-import-inline-autofill">
                                {formatAutoFilledHint(record.autoFilledHints)}
                              </small>
                            ) : null}
                            {recordDefaultedIssues.length ? (
                              <small className="resource-import-inline-default">
                                {recordDefaultedIssues[0]?.field} {recordDefaultedIssues[0]?.message}
                              </small>
                            ) : null}
                          </div>
                        </td>
                        <td>{getRecordAddress(record)}</td>
                        <td>{record.ciType}</td>
                        <td>
                          <span className={`resource-import-status-pill ${hasAttentionField(record, "status") || hasAttentionField(record, "alarm_status") ? "attention" : ""}`.trim()}>
                            {getDisplayStatus(record)}
                          </span>
                        </td>
                        <td>
                          <span className={`resource-import-action-pill ${(record.importAction || "create") === "skip" ? "muted" : record.existingCi?.ciId !== undefined ? "warning" : "success"}`.trim()}>
                            {getImportActionLabel(record)}
                          </span>
                        </td>
                        <td>{buildRecordSource(record)}</td>
                        <td>
                          <div className="resource-import-row-actions">
                            <button
                              type="button"
                              onClick={() =>
                                updateRecord(record.previewKey, (current) => ({
                                  ...current,
                                  selected: !current.selected,
                                }))
                              }
                            >
                              {record.selected ? "排除" : "恢复"}
                            </button>
                            <button
                              type="button"
                              onClick={() => openBatchEditor(record.previewKey)}
                            >
                              编辑
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ))}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() => onReturnToUpload({ flowId: flow.flowId, sourceMessageId: messageId })}
          >
            返回上传
          </button>
          <button
            type="button"
            className="primary"
            disabled={flow.locked || Boolean(blockingAnalysisMessage) || Boolean(unresolvedUniqueKeyMessage) || Boolean(requiredModelBlockingMessage) || Boolean(metadataBlockingMessage)}
            onClick={() => {
              const nextPreview = syncPreviewWithCurrentData(flow.preview || null, resourceGroups, relations);
              onBuildTopology({
                messageId,
                flowId: flow.flowId,
                preview: nextPreview,
                resourceGroups,
                relations,
              });
            }}
          >
            {flow.locked
              ? "已生成关系卡片"
              : blockingAnalysisMessage
                ? "当前解析不完整，禁止继续"
                : unresolvedUniqueKeyMessage
                  ? "请先补全唯一标识"
                  : requiredModelBlockingMessage
                    ? "请先补齐必填字段"
                    : metadataBlockingMessage
                      ? "请先连接 CMDB 模型"
                      : "确认数据，建立关系 →"}
          </button>
        </div>
      </div>

      {editorOpen ? (
        <div className="resource-import-modal-backdrop" onClick={closeBatchEditor}>
          <div className="resource-import-modal wide" onClick={(event) => event.stopPropagation()}>
            <div className="resource-import-modal-header">
              <div>
                <h3>批量编辑导入数据</h3>
                <p>按 Excel 表格方式统一核对全部记录，横向滚动可查看更多字段。</p>
              </div>
              <button type="button" className="secondary" onClick={closeBatchEditor}>
                关闭
              </button>
            </div>

            <div className="resource-import-batch-editor">
              {requiredModelIssues.length ? (
                <div className="resource-import-inline-error resource-import-editor-issue-summary">
                  <strong>{requiredModelBlockingMessage}</strong>
                  <ul className="resource-import-issue-list">
                    {requiredModelIssues.slice(0, 5).map((issue, index) => (
                      <li key={`editor-${issue.previewKey}-${issue.field}-${index}`}>
                        {issue.sourceLabel} / {issue.recordName}：{issue.message}
                      </li>
                    ))}
                  </ul>
                  {requiredModelIssues.length > 5 ? (
                    <div>还有 {requiredModelIssues.length - 5} 个字段已在下方红色单元格标出。</div>
                  ) : null}
                </div>
              ) : null}
              {defaultedRequiredIssues.length ? (
                <div className="resource-import-inline-notice resource-import-inline-notice-default resource-import-editor-issue-summary">
                  <strong>{defaultedRequiredMessage}</strong>
                  <ul className="resource-import-issue-list">
                    {defaultedRequiredIssues.slice(0, 5).map((issue, index) => (
                      <li key={`editor-${issue.previewKey}-${issue.field}-default-${index}`}>
                        {issue.sourceLabel} / {issue.recordName}：{getAttributeLabel(issue.field)} {issue.message}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {batchEditorScrollWidth > batchEditorViewportWidth ? (
                <div className="resource-import-batch-editor-scroll-tip">
                  左右字段较多，可直接拖动下方横向滚动条查看右侧列。
                </div>
              ) : null}
              {batchEditorScrollWidth > batchEditorViewportWidth ? (
                <div
                  ref={batchEditorTopScrollbarRef}
                  className="resource-import-batch-editor-top-scroll"
                  aria-hidden="true"
                >
                  <div
                    className="resource-import-batch-editor-top-scroll-inner"
                    style={{ width: `${batchEditorScrollWidth}px` }}
                  />
                </div>
              ) : null}
              <div ref={batchEditorWrapRef} className="resource-import-batch-editor-wrap">
                <table className="resource-import-batch-editor-table">
                  <thead>
                    <tr>
                      <th>纳入</th>
                      <th>分组</th>
                      <th>资源类型</th>
                      <th>导入策略</th>
                      <th className={batchColumnAttentionMap.get("name") ? "attention-head" : batchColumnDefaultMap.get("name") ? "default-head" : ""}>名称</th>
                      {batchEditorColumns
                        .filter((column) => column.key !== "name")
                        .map((column) => (
                          <th
                            key={column.key}
                            className={batchColumnAttentionMap.get(column.key) ? "attention-head" : batchColumnDefaultMap.get(column.key) ? "default-head" : ""}
                          >
                            {column.label}
                            {batchColumnDefaultMap.get(column.key) ? <span>默认</span> : null}
                          </th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {resourceGroups.flatMap((group) =>
                      group.records.map((record) => {
                        const attributeDefinitions = getVisibleAttributeDefinitions(
                          flow.preview || null,
                          record.ciType,
                          record,
                        );
                        const definitionMap = new Map(attributeDefinitions.map((item) => [item.name, item]));
                        const recordIssues = getRecordIssues(record, flow.preview || null);
                        return (
                          <tr
                            key={`editor-${record.previewKey}`}
                            data-editor-preview-key={record.previewKey}
                            className={`${record.selected ? "" : "muted"} ${recordIssues.length ? "needs-attention" : ""} ${editorFocusPreviewKey === record.previewKey ? "focused" : ""}`.trim()}
                          >
                            <td>
                              <input
                                type="checkbox"
                                checked={record.selected}
                                onChange={(event) =>
                                  updateRecord(record.previewKey, (current) => ({
                                    ...current,
                                    selected: event.target.checked,
                                  }))
                                }
                              />
                            </td>
                            <td>{group.label}</td>
                            <td>
                              <select
                                value={record.ciType}
                                onChange={(event) =>
                                  updateRecord(record.previewKey, (current) => ({
                                    ...current,
                                    ciType: event.target.value,
                                  }))
                                }
                              >
                                {Array.from(new Set([...ciTypeOptions, record.ciType])).map((ciType) => (
                                  <option key={ciType} value={ciType}>
                                    {ciType}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td>
                              <select
                                value={record.importAction || (record.existingCi?.ciId !== undefined ? "update" : "create")}
                                onChange={(event) =>
                                  updateRecord(record.previewKey, (current) => ({
                                    ...current,
                                    importAction: event.target.value as "create" | "update" | "skip",
                                  }))
                                }
                              >
                                {getImportActionOptions(record).map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td className={fieldNeedsAttention(record, "name") ? "attention-cell" : ""}>
                              <input
                                value={record.name || ""}
                                title={getFieldAttentionMessage(record, "name")}
                                onChange={(event) =>
                                  updateRecord(record.previewKey, (current) => ({
                                    ...current,
                                    name: event.target.value,
                                  }))
                                }
                              />
                              {getFieldAttentionMessage(record, "name") ? (
                                <div className="resource-import-cell-issue">{getFieldAttentionMessage(record, "name")}</div>
                              ) : null}
                            </td>
                            {batchEditorColumns
                              .filter((column) => column.key !== "name")
                              .map((column) => {
                                const definition = definitionMap.get(column.key);
                                const choiceOptions = getChoiceOptions(definition);
                                const currentValue = record.attributes[column.key] || "";
                                const isAttention = fieldNeedsAttention(record, column.key, definition);
                                const attentionMessage = getFieldAttentionMessage(record, column.key, definition);
                                const defaultMessage = getRequiredDefaultMessage(record, column.key, definition);
                                return (
                                  <td key={`${record.previewKey}-${column.key}`} className={isAttention ? "attention-cell" : defaultMessage ? "default-cell" : ""}>
                                    {choiceOptions.length ? (
                                      <select
                                        value={currentValue}
                                        title={attentionMessage || defaultMessage}
                                        onChange={(event) =>
                                          updateRecord(record.previewKey, (current) => ({
                                            ...current,
                                            attributes: {
                                              ...current.attributes,
                                              [column.key]: event.target.value,
                                            },
                                          }))
                                        }
                                      >
                                        <option value="">请选择</option>
                                        {choiceOptions.map((option) => (
                                          <option key={`${column.key}-${option.value}`} value={option.value}>
                                            {option.label || option.value}
                                          </option>
                                        ))}
                                      </select>
                                    ) : (
                                      <input
                                        value={currentValue}
                                        title={attentionMessage || defaultMessage}
                                        onChange={(event) =>
                                          updateRecord(record.previewKey, (current) => ({
                                            ...current,
                                            attributes: {
                                              ...current.attributes,
                                              [column.key]: event.target.value,
                                            },
                                          }))
                                        }
                                      />
                                    )}
                                    {attentionMessage ? (
                                      <div className="resource-import-cell-issue">{attentionMessage}</div>
                                    ) : null}
                                    {!attentionMessage && defaultMessage ? (
                                      <div className="resource-import-cell-default">{defaultMessage}</div>
                                    ) : null}
                                  </td>
                                );
                              })}
                          </tr>
                        );
                      }),
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="resource-import-modal-footer">
              <div className="resource-import-inline-notice">
                红色单元格表示当前字段仍需确认。顶部滚动条可直接横向查看表头；若缺少主键，请优先在上方“模型唯一标识补全”里一次性处理。
              </div>
              <button type="button" className="primary" onClick={closeBatchEditor}>
                完成编辑
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TopologyStage({
  flow,
  messageId,
  onBackToConfirm,
  onSubmitImport,
}: {
  flow: ResourceImportFlowPayload;
  messageId: string;
  onBackToConfirm: ResourceImportConversationCardProps["onBackToConfirm"];
  onSubmitImport: ResourceImportConversationCardProps["onSubmitImport"];
}) {
  const [relations, setRelations] = useState<ResourceImportRelation[]>(flow.relations || []);
  const blockingAnalysisIssues = getBlockingAnalysisIssues(flow.preview);
  const blockingAnalysisMessage = getBlockingAnalysisMessage(flow.preview);
  const requiredModelIssues = useMemo(
    () => getRequiredModelIssues(flow.preview || null, flow.resourceGroups || []),
    [flow.preview, flow.resourceGroups],
  );
  const requiredModelBlockingMessage = getRequiredModelBlockingMessage(requiredModelIssues);
  const metadataBlockingMessage = getMetadataBlockingMessage(flow.preview || null);
  const [topologyFullscreen, setTopologyFullscreen] = useState(false);

  useEffect(() => {
    setRelations(flow.relations || []);
  }, [flow.relations, messageId]);

  const selectedRecordCount = useMemo(
    () => countSelectedRecords(flow.resourceGroups || []),
    [flow.resourceGroups],
  );
  const selectedRelationCount = useMemo(
    () => relations.filter((relation) => relation.selected).length,
    [relations],
  );
  const skippedRelationHints = useMemo(
    () => (flow.preview?.logs || []).filter((item) =>
      String(item || "").includes("关系")
      && (String(item || "").includes("跳过") || String(item || "").includes("未配置") || String(item || "").includes("不支持")),
    ).slice(-4),
    [flow.preview?.logs],
  );

  const topologyInsights = useMemo(() => {
    const selectedRelations = relations.filter((relation) => relation.selected);
    if (!selectedRelations.length) {
      return [
        {
          key: "topology-insight-default",
          text: "已根据网段、命名和部署信息推断关系。",
        },
      ];
    }
    return selectedRelations.slice(0, 4).map((relation, index) => {
      const confidenceLabel =
        relation.confidence === "high"
          ? "高"
          : relation.confidence === "medium"
            ? "中"
            : "低";
      return {
        key: `${relation.sourceKey}-${relation.targetKey}-${relation.relationType}-${index}`,
        text: `${relation.reason || `${relation.sourceKey} → ${relation.targetKey}`}（${confidenceLabel}置信度）`,
      };
    });
  }, [relations]);

  const chartOption = useMemo(() => {
    const { chartData, rootChildren } = buildTopologyTreeData(flow.resourceGroups || [], relations, {
      collapsedDepth: 1,
    });

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        formatter: (params: any) => {
          const relationText = params?.data?.relationTypeFromParent
            ? `<br/>关系: ${params.data.relationTypeFromParent}`
            : "";
          const descendantText = params?.data?.descendantCount
            ? `<br/>下游资源: ${params.data.descendantCount}`
            : "";
          return `${params.data.name}<br/>${params.data.value || ""}${relationText}${descendantText}`;
        },
      },
      series: [
        {
          type: "tree",
          roam: true,
          data: [chartData],
          top: "6%",
          left: "4%",
          bottom: "6%",
          right: "28%",
          orient: "LR",
          symbol: "circle",
          symbolSize: 9,
          edgeShape: "polyline",
          edgeForkPosition: "50%",
          initialTreeDepth: 2,
          expandAndCollapse: true,
          animationDuration: 500,
          animationDurationUpdate: 750,
          label: {
            show: true,
            position: "right",
            verticalAlign: "middle",
            align: "left",
            offset: [0, 0],
          },
          lineStyle: {
            color: "#cbd5e1",
            width: 1.2,
            curveness: 0.12,
          },
          leaves: {
            label: {
              position: "right",
              align: "left",
            },
          },
          emphasis: {
            focus: "descendant",
          },
        },
      ],
      graphic: !rootChildren.length ? [
        {
          type: "text",
          left: "center",
          top: "middle",
          style: {
            text: "暂无可展示的拓扑树",
            fill: "#64748b",
            fontSize: 14,
          },
        },
      ] : [],
    };
  }, [flow.resourceGroups, relations]);

  const fullscreenChartOption = useMemo(() => {
    const { chartData, rootChildren } = buildTopologyTreeData(flow.resourceGroups || [], relations, {
      collapsedDepth: 2,
    });

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        formatter: (params: any) => {
          const relationText = params?.data?.relationTypeFromParent
            ? `<br/>关系: ${params.data.relationTypeFromParent}`
            : "";
          const descendantText = params?.data?.descendantCount
            ? `<br/>下游资源: ${params.data.descendantCount}`
            : "";
          return `${params.data.name}<br/>${params.data.value || ""}${relationText}${descendantText}`;
        },
      },
      series: [
        {
          type: "tree",
          roam: true,
          data: [chartData],
          top: "6%",
          left: "4%",
          bottom: "6%",
          right: "28%",
          orient: "LR",
          symbol: "circle",
          symbolSize: 9,
          edgeShape: "polyline",
          edgeForkPosition: "50%",
          initialTreeDepth: 3,
          expandAndCollapse: true,
          animationDuration: 500,
          animationDurationUpdate: 750,
          label: {
            show: true,
            position: "right",
            verticalAlign: "middle",
            align: "left",
            offset: [0, 0],
          },
          lineStyle: {
            color: "#cbd5e1",
            width: 1.2,
            curveness: 0.12,
          },
          leaves: {
            label: {
              position: "right",
              align: "left",
            },
          },
          emphasis: {
            focus: "descendant",
          },
        },
      ],
      graphic: !rootChildren.length ? [
        {
          type: "text",
          left: "center",
          top: "middle",
          style: {
            text: "暂无可展示的拓扑树",
            fill: "#64748b",
            fontSize: 14,
          },
        },
      ] : [],
    };
  }, [flow.resourceGroups, relations]);

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="topology" />

      <div className="resource-import-stage">
        {blockingAnalysisIssues.length ? (
          <div className="resource-import-inline-error">
            <strong>{blockingAnalysisMessage}</strong>
            <ul className="resource-import-issue-list">
              {blockingAnalysisIssues.map((issue, index) => (
                <li key={`${issue.fileName || issue.sheetName || "issue"}-${index}`}>{issue.message}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {requiredModelIssues.length ? (
          <div className="resource-import-inline-error">
            <strong>{requiredModelBlockingMessage}</strong>
            <ul className="resource-import-issue-list">
              {requiredModelIssues.slice(0, 10).map((issue, index) => (
                <li key={`${issue.previewKey}-${issue.field}-${index}`}>
                  {issue.sourceLabel} / {issue.recordName}：{issue.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {metadataBlockingMessage ? (
          <div className="resource-import-inline-error">
            <strong>{metadataBlockingMessage}</strong>
            {flow.preview?.metadataMessage ? <div>{flow.preview.metadataMessage}</div> : null}
          </div>
        ) : null}
        <section className="resource-import-section topology">
          <div className="resource-import-section-title">🧠 智能拓扑推断</div>
          <div className="resource-import-topology-summary">
            <div>已选资源：{selectedRecordCount} 条</div>
            <div>推断关系：{selectedRelationCount} 条</div>
            <div>推断质量：{flow.preview?.summary.qualityScore ?? 0}%</div>
          </div>
          <ul className="resource-import-insight-list">
            {topologyInsights.map((item) => (
              <li key={item.key}>{item.text}</li>
            ))}
          </ul>
        </section>

        <section className="resource-import-section">
          <div className="resource-import-section-header">
            <div className="resource-import-section-title">🔗 资源拓扑关系</div>
            <span className="resource-import-section-subtitle">{selectedRelationCount} 条关系</span>
          </div>
          <div className="resource-import-action-row">
            <span className="resource-import-section-subtitle">默认仅展开主干，点击节点可继续展开分支</span>
            <button
              type="button"
              className="secondary"
              onClick={() => setTopologyFullscreen(true)}
            >
              全屏查看树状拓扑
            </button>
          </div>
          <div className="resource-import-topology-chart">
            <ReactECharts option={chartOption} style={{ height: "100%", width: "100%" }} notMerge lazyUpdate />
          </div>
        </section>

        <section className="resource-import-section">
          <div className="resource-import-section-title">推断的关系列表</div>
          {!relations.length ? (
            <div className="resource-import-inline-notice">
              当前没有生成可展示的关系。
              {skippedRelationHints.length ? ` 可能原因：${skippedRelationHints.join("；")}` : " 可能是本次数据缺少足够的关联线索，或相关模型关系在 CMDB 中尚未配置。"}
            </div>
          ) : null}
          <div className="resource-import-relation-list">
            {relations.map((relation) => (
              <label
                key={`${relation.sourceKey}-${relation.targetKey}-${relation.relationType}`}
                className="resource-import-relation-item"
              >
                <input
                  type="checkbox"
                  checked={relation.selected}
                  disabled={flow.readonly}
                  onChange={(event) =>
                    setRelations((current) =>
                      current.map((item) =>
                        item.sourceKey === relation.sourceKey
                        && item.targetKey === relation.targetKey
                        && item.relationType === relation.relationType
                          ? {
                              ...item,
                              selected: event.target.checked,
                            }
                          : item,
                      ),
                    )
                  }
                />
                <div>
                  <strong>
                    {relation.sourceKey} → {relation.targetKey}
                  </strong>
                  <p>
                    {relation.relationType}
                    {relation.requiresModelRelation ? " · 需先创建模型关系" : ""}
                    {" · "}
                    {relation.reason || "AI 自动推断"}
                  </p>
                </div>
              </label>
            ))}
          </div>
        </section>

        {flow.readonly ? (
          <div className="resource-import-inline-notice">这是已导入任务的拓扑快照，仅用于回看。</div>
        ) : null}

        <div className="resource-import-action-row">
          {!flow.readonly ? (
            <button
              type="button"
              className="secondary"
              onClick={() =>
                onBackToConfirm({
                  messageId,
                  flowId: flow.flowId,
                })
              }
            >
              返回修改
            </button>
          ) : null}
          {!flow.readonly ? (
            <button
              type="button"
              className="primary"
              disabled={flow.locked || Boolean(blockingAnalysisMessage) || Boolean(requiredModelBlockingMessage) || Boolean(metadataBlockingMessage)}
              onClick={() => {
                const nextPreview = syncPreviewWithCurrentData(flow.preview || null, flow.resourceGroups || [], relations);
                onSubmitImport({
                  messageId,
                  flowId: flow.flowId,
                  preview: nextPreview,
                  resourceGroups: flow.resourceGroups || [],
                  relations,
                });
              }}
            >
              {flow.locked
                ? "导入任务已启动"
                : blockingAnalysisMessage
                  ? "当前解析不完整，禁止导入"
                  : requiredModelBlockingMessage
                    ? "请先补齐必填字段"
                    : metadataBlockingMessage
                      ? "请先连接 CMDB 模型"
                      : "确认导入CMDB"}
            </button>
          ) : null}
        </div>
      </div>

      {topologyFullscreen ? (
        <div className="resource-import-modal-backdrop" onClick={() => setTopologyFullscreen(false)}>
          <div className="resource-import-modal wide resource-import-topology-modal" onClick={(event) => event.stopPropagation()}>
            <div className="resource-import-modal-header">
              <div>
                <h3>树状资源拓扑</h3>
                <p>可拖拽、缩放查看完整层级关系。</p>
              </div>
              <button type="button" className="secondary" onClick={() => setTopologyFullscreen(false)}>
                关闭
              </button>
            </div>
            <div className="resource-import-topology-chart fullscreen">
              <ReactECharts option={fullscreenChartOption} style={{ height: "100%", width: "100%" }} notMerge lazyUpdate />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ImportingStage({
  flow,
}: {
  flow: ResourceImportFlowPayload;
}) {
  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="importing" />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}

      <div className="resource-import-section resource-import-importing-card">
        <div className="resource-import-result-icon">⏳</div>
        <div className="resource-import-importing-title">正在将资源写入 CMDB 系统，请稍候...</div>
        <div className="resource-import-parse-bar">
          <div className="resource-import-parse-bar-fill resource-import-importing-fill" />
        </div>
        <div className="resource-import-parse-status">
          {flow.status === "error" ? "导入失败" : "导入中..."}
        </div>
      </div>
    </div>
  );
}

function ResultStage({
  flow,
  onContinueImport,
  onOpenSystemTopology,
  onScrollToStage,
}: {
  flow: ResourceImportFlowPayload;
  onContinueImport: ResourceImportConversationCardProps["onContinueImport"];
  onOpenSystemTopology: ResourceImportConversationCardProps["onOpenSystemTopology"];
  onScrollToStage: ResourceImportConversationCardProps["onScrollToStage"];
}) {
  const structureResults = flow.result?.structureResults || [];
  const resourceResults = flow.result?.resourceResults || [];
  const relationResults = flow.result?.relationResults || [];
  const recordMap = useMemo(
    () => new Map(
      (flow.resourceGroups || [])
        .flatMap((group) => group.records || [])
        .map((record) => [String(record.previewKey || ""), record] as const),
    ),
    [flow.resourceGroups],
  );

  return (
    <div className="resource-import-conversation-card">
      <FlowSteps stage="result" />

      {flow.error ? <div className="resource-import-inline-error">{flow.error}</div> : null}

      <div className="resource-import-stage">
        <div className="resource-import-result">
          <div className="resource-import-result-icon">
            {flow.result?.status === "success" ? "✅" : "⚠️"}
          </div>
          <h3>{flow.result?.status === "success" ? "导入成功！" : "导入完成"}</h3>
          <p>
            {flow.result?.status === "success"
              ? "资源已成功录入 CMDB，后续可继续追加新的清单。"
              : "导入已执行完成，请根据结果检查失败与跳过项。"}
          </p>
        </div>

        <div className="resource-import-stat-grid">
          <div className="resource-import-stat-card success">
            <strong>{flow.result?.created ?? 0}</strong>
            <span>CI实例</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.result?.relationsCreated ?? 0}</strong>
            <span>关系建立</span>
          </div>
          <div className="resource-import-stat-card warning">
            <strong>{flow.result?.skipped ?? 0}</strong>
            <span>跳过项</span>
          </div>
          <div className="resource-import-stat-card success">
            <strong>{flow.preview?.summary.qualityScore ?? 0}%</strong>
            <span>数据完整性</span>
          </div>
        </div>

        {flow.result?.error ? (
          <div className="resource-import-inline-error">
            {flow.result.error}
          </div>
        ) : null}

        {structureResults.length ? (
          <section className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">结构处理结果</div>
              <span className="resource-import-section-subtitle">{structureResults.length} 条</span>
            </div>
            <div className="resource-import-result-list">
              {structureResults.map((item, index) => (
                <div
                  key={`${item.kind}-${item.sourceType || item.groupName || item.modelName || item.name || index}`}
                  className={`resource-import-result-item ${item.status || "success"}`.trim()}
                >
                  <div>
                    <strong>
                      {item.kind === "relation-config"
                        ? `${item.sourceType} → ${item.relationType} → ${item.targetType}`
                        : item.groupName || item.modelName || item.name || item.kind}
                    </strong>
                    <p>{item.message}</p>
                  </div>
                  <div className="resource-import-result-meta">
                    <span>{item.status || "success"}</span>
                    {item.ctrId !== undefined ? <code>CTR ID: {item.ctrId}</code> : null}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {resourceResults.length ? (
          <section className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">资源导入结果</div>
              <span className="resource-import-section-subtitle">{resourceResults.length} 条</span>
            </div>
            <div className="resource-import-result-list">
              {resourceResults.map((item) => (
                <div key={item.previewKey} className={`resource-import-result-item ${item.status}`.trim()}>
                  <div>
                    <strong>{getResultItemTitle(item, recordMap)}</strong>
                    <p>{item.message}</p>
                  </div>
                  <div className="resource-import-result-meta">
                    <span>{item.status}</span>
                    {item.ciId !== undefined ? <code>CI ID: {item.ciId}</code> : null}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {relationResults.length ? (
          <section className="resource-import-section">
            <div className="resource-import-section-header">
              <div className="resource-import-section-title">关系导入结果</div>
              <span className="resource-import-section-subtitle">{relationResults.length} 条</span>
            </div>
            <div className="resource-import-result-list">
              {relationResults.map((item, index) => (
                <div
                  key={`${item.sourceKey}-${item.targetKey}-${index}`}
                  className={`resource-import-result-item ${item.status}`.trim()}
                >
                  <div>
                    <strong>{item.sourceKey} → {item.targetKey}</strong>
                    <p>{item.message}</p>
                  </div>
                  <div className="resource-import-result-meta">
                    <span>{item.status}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <div className="resource-import-action-row">
          <button
            type="button"
            className="secondary"
            onClick={() => onContinueImport({ flowId: flow.flowId })}
          >
            继续导入
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => onOpenSystemTopology({ flowId: flow.flowId })}
          >
            查看本次导入拓扑
          </button>
        </div>
      </div>
    </div>
  );
}

export function ResourceImportConversationCard({
  agentId,
  message,
  onUploadFiles,
  onStartParse,
  onParseResolved,
  onParseFailed,
  onReturnToUpload,
  onBuildTopology,
  onConfirmStructure,
  onBackToConfirm,
  onSubmitImport,
  onContinueImport,
  onOpenSystemTopology,
  onScrollToStage,
  resolveFiles,
  releaseFiles,
}: ResourceImportConversationCardProps) {
  const flow = message.resourceImportFlow;
  if (!flow) {
    return null;
  }

  if (flow.stage === "intro") {
    return (
      <IntroStage
        agentId={agentId}
        flow={flow}
        flowId={flow.flowId}
        messageId={message.id}
        onUploadFiles={onUploadFiles}
        onReturnToUpload={onReturnToUpload}
        onStartParse={onStartParse}
      />
    );
  }

  if (flow.stage === "parsing") {
    return (
      <ParsingStage
        agentId={agentId}
        flow={flow}
        messageId={message.id}
        resolveFiles={resolveFiles}
        releaseFiles={releaseFiles}
        onParseResolved={onParseResolved}
        onParseFailed={onParseFailed}
        onReturnToUpload={onReturnToUpload}
      />
    );
  }

  if (flow.stage === "structure") {
    return (
      <StructureStage
        agentId={agentId}
        flow={flow}
        messageId={message.id}
        onReturnToUpload={onReturnToUpload}
        onConfirmStructure={onConfirmStructure}
      />
    );
  }

  if (flow.stage === "confirm") {
    return (
      <ConfirmStage
        flow={flow}
        messageId={message.id}
        onReturnToUpload={onReturnToUpload}
        onBuildTopology={onBuildTopology}
      />
    );
  }

  if (flow.stage === "topology") {
    return (
      <TopologyStage
        flow={flow}
        messageId={message.id}
        onBackToConfirm={onBackToConfirm}
        onSubmitImport={onSubmitImport}
      />
    );
  }

  if (flow.stage === "importing") {
    return <ImportingStage flow={flow} />;
  }

  return (
    <ResultStage
      flow={flow}
      onContinueImport={onContinueImport}
      onOpenSystemTopology={onOpenSystemTopology}
      onScrollToStage={onScrollToStage}
    />
  );
}
