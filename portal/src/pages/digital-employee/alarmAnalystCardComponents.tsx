import { memo, useEffect, useMemo, useState, type ComponentPropsWithoutRef } from "react";

import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import { DeferredEChartsBlock } from "../../components/DeferredVisualizationBlocks";
import type { AlarmAnalystCardV1 } from "../../alarm-analyst/shared";
import {
  normalizeMarkdownDisplayContent,
  unwrapPortalAlarmAnalystCardContent,
} from "./helpers";
import {
  FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_CHANGED_EVENT,
  readFaultAnalysisConfidenceVisible,
} from "./faultAnalysisSettings";

type AlarmAnalystSummaryRowTone = "accent" | "success" | "warning" | "neutral";

type AlarmAnalystSummaryRow = {
  label: string;
  value: string;
  tone?: AlarmAnalystSummaryRowTone;
};

type AlarmAnalystSpotlight = AlarmAnalystSummaryRow & {
  variant: "primary" | "secondary" | "action" | "status" | "warning";
};

type AlarmAnalystAutomationCard = {
  label: string;
  title: string;
  detail: string;
  items?: string[];
  variant: "workorder" | "notification";
};

type AlarmAnalystStatusItem = {
  label: string;
  detail?: string;
  state: "success" | "alert";
};

type AlarmAnalystDecisionCard = {
  label: string;
  value: string;
  accent?: boolean;
};

const SUMMARY_LABEL_ORDER = [
  "置信度",
  "故障性质",
  "根因方向",
  "影响范围",
  "优先动作",
  "关联资源告警查询状态",
  "关键提醒",
] as const;

const SUMMARY_LABEL_ALIASES: Record<string, string> = {
  影响面: "影响范围",
  根因结论: "根因方向",
  优先建议: "优先动作",
  关键问题: "关键提醒",
  关联告警查询: "关联资源告警查询状态",
  关联告警: "关联资源告警查询状态",
  关联资源告警查询: "关联资源告警查询状态",
  关联资源告警: "关联资源告警查询状态",
};

const GENERIC_FILLER_PATTERNS = [
  /^已完成故障根因分析[。.]?$/u,
  /^已完成根因分析[。.]?$/u,
  /^分析完成[。.]?$/u,
  /^无[。.]?$/u,
];

const AI_THINKING_RE =
  /^(?:我来分析|我先|先读取|先加载|先并行|先查|先执行|好的[，,。]|现在按|现在开始|现在继续|技能文档已|文档已读取|文档已加载|让我|让我们|资源确认为|资源确认完毕|很好[！!]|接下来|下一步|📋\s*Step|\d+\.\s*(?:查|读取|确认|执行)|拓扑关系中|指标值返回|关键发现|数据完整|数据非常|现在推送|分析报告已)/u;

function isAiThinkingText(value: string): boolean {
  const cleaned = String(value || "")
    .trim()
    .replace(/^[\W_]+/, "");
  if (!cleaned) return false;
  return AI_THINKING_RE.test(cleaned);
}

function normalizeChartToken(value: unknown) {
  return String(value || "")
    .replace(/[*_~`>#]/g, "")
    .replace(/\s+/g, "")
    .toLowerCase()
    .trim();
}

function isGenericFiller(value: string): boolean {
  const trimmed = String(value || "").trim();
  if (!trimmed) return true;
  return GENERIC_FILLER_PATTERNS.some((pattern) => pattern.test(trimmed));
}

function isJunkValue(value: string): boolean {
  return isGenericFiller(value) || isAiThinkingText(value);
}

function buildHighlightTokens(card: AlarmAnalystCardV1) {
  return [
    card.rootCause.resourceId,
    card.rootCause.resourceName,
    card.rootCause.ciId,
    ...card.impact.affectedApplications.map((item) => item.id || item.name || ""),
    ...card.impact.affectedResources.map((item) => item.id || item.name || ""),
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

function shouldHighlightNode(candidate: unknown, highlightTokens: string[]) {
  const normalizedCandidate = normalizeChartToken(candidate);
  if (!normalizedCandidate) {
    return false;
  }
  return highlightTokens.some((token) => {
    const normalizedToken = normalizeChartToken(token);
    return normalizedToken
      && (
        normalizedCandidate.includes(normalizedToken)
        || normalizedToken.includes(normalizedCandidate)
      );
  });
}

function buildStructuredTopologyChart(card: AlarmAnalystCardV1, highlightTokens: string[]) {
  const nodes = Array.isArray(card.topology?.nodes) ? card.topology.nodes : [];
  const edges = Array.isArray(card.topology?.edges) ? card.topology.edges : [];
  if (!nodes.length) {
    return "";
  }

  return JSON.stringify({
    title: { text: "影响拓扑" },
    tooltip: {},
    animationDurationUpdate: 300,
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        label: { show: true },
        force: {
          repulsion: 260,
          edgeLength: 120,
        },
        data: nodes.map((node: any) => ({
          ...node,
          value: node?.value || 1,
          category: node?.category || 0,
          symbolSize: node?.symbolSize || 42,
          itemStyle:
            card.topology.highlightedNodeIds?.includes(String(node?.id || node?.name || ""))
            || shouldHighlightNode(node?.id || node?.name || "", highlightTokens)
            ? { color: "#ef4444", borderColor: "#991b1b", borderWidth: 2 }
            : node?.itemStyle,
        })),
        links: edges.map((edge: any) => ({
          ...edge,
          lineStyle: edge?.lineStyle || { opacity: 0.8, width: 2 },
        })),
      },
    ],
  });
}

function extractRawTopologyChart(content: string) {
  const match = String(content || "").match(/```echarts\s*([\s\S]*?)```/i);
  return match?.[1]?.trim() || "";
}

function markTreeNodes(node: any, highlightTokens: string[]) {
  if (!node || typeof node !== "object") {
    return node;
  }

  const isHighlighted = shouldHighlightNode(node.name || node.id || "", highlightTokens);
  const children = Array.isArray(node.children)
    ? node.children.map((child) => markTreeNodes(child, highlightTokens))
    : node.children;

  return {
    ...node,
    children,
    itemStyle: isHighlighted
      ? {
          ...(node.itemStyle || {}),
          color: "#ef4444",
          borderColor: "#991b1b",
          borderWidth: 2,
        }
      : node.itemStyle,
    label: isHighlighted
      ? {
          ...(node.label || {}),
          color: "#991b1b",
          fontWeight: 700,
        }
      : node.label,
  };
}

function buildReportTopologyChart(card: AlarmAnalystCardV1, highlightTokens: string[]) {
  const rawChart = extractRawTopologyChart(
    unwrapPortalAlarmAnalystCardContent(card.rawReportMarkdown),
  );
  if (!rawChart) {
    return "";
  }

  try {
    const config = JSON.parse(rawChart) as Record<string, any>;
    const series = Array.isArray(config.series) ? config.series : [];
    const nextSeries = series.map((item: any) => ({
      ...item,
      data: Array.isArray(item?.data)
        ? item.data.map((node: any) => markTreeNodes(node, highlightTokens))
        : item?.data,
    }));
    return JSON.stringify({
      ...config,
      series: nextSeries,
    });
  } catch {
    return rawChart;
  }
}

function buildTopologyChart(card: AlarmAnalystCardV1) {
  const highlightTokens = buildHighlightTokens(card);
  return buildStructuredTopologyChart(card, highlightTokens)
    || buildReportTopologyChart(card, highlightTokens);
}

function AlarmAnalystReportTable(props: ComponentPropsWithoutRef<"table">) {
  const { className, ...rest } = props;

  return (
    <div className="alarm-analyst-raw-report-table-scroll">
      <table {...rest} className={className} />
    </div>
  );
}

function AlarmAnalystMarkdown({ content }: { content: string }) {
  const isDarkTheme =
    typeof document !== "undefined"
    && document.querySelector(".portal-digital-employee")?.classList.contains("theme-dark");
  const markdownThemeClass = isDarkTheme ? "x-markdown-dark" : "x-markdown-light";
  const normalizedContent = unwrapPortalAlarmAnalystCardContent(
    normalizeMarkdownDisplayContent(content),
  );

  return (
    <PortalQwenPawMarkdown
      className={`portal-x-markdown ${markdownThemeClass}`}
      content={normalizedContent}
      isStreaming={false}
      components={{ table: AlarmAnalystReportTable }}
    />
  );
}

function stripMarkdownInline(value: string) {
  return String(value || "")
    .replace(/[*_~`>#]/g, "")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/^\p{Extended_Pictographic}+\s*/u, "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeLabel(value: string) {
  const stripped = stripMarkdownInline(value).replace(/[：:]/g, "").trim();
  return SUMMARY_LABEL_ALIASES[stripped] || stripped;
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractMarkdownSection(content: string, titles: string[]) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  if (!normalized.trim()) {
    return "";
  }

  const headingMatches = [...normalized.matchAll(/^#{1,6}\s*(.+?)\s*$/gm)];
  if (!headingMatches.length) {
    return "";
  }

  const targetIndex = headingMatches.findIndex((match) => {
    const heading = stripMarkdownInline(match[1]);
    return titles.some((title) => heading.includes(title));
  });
  if (targetIndex === -1) {
    return "";
  }

  const startMatch = headingMatches[targetIndex];
  const start = (startMatch.index || 0) + startMatch[0].length;
  const currentLevel = (startMatch[0].match(/^#+/)?.[0].length) || 1;
  let end = normalized.length;
  for (const nextMatch of headingMatches.slice(targetIndex + 1)) {
    const nextLevel = (nextMatch[0].match(/^#+/)?.[0].length) || 1;
    if (nextLevel <= currentLevel) {
      end = nextMatch.index || normalized.length;
      break;
    }
  }
  return normalized.slice(start, end).trim();
}

function extractBulletEntries(content: string) {
  const rows: string[] = [];
  let current = "";

  for (const line of String(content || "").split("\n")) {
    const bulletMatch = line.match(/^\s*[-*•]\s+(.+)\s*$/u);
    if (bulletMatch) {
      if (current) {
        rows.push(current.trim());
      }
      current = bulletMatch[1].trim();
      continue;
    }

    // Parse markdown table rows: | **label** | value |
    const tableMatch = line.match(
      /^\s*\|\s*\*{0,2}([^|*]{1,30})\*{0,2}\s*\|\s*\*{0,2}(.+?)\*{0,2}\s*\|?\s*$/u,
    );
    if (tableMatch) {
      const label = stripMarkdownInline(tableMatch[1]).trim();
      const value = stripMarkdownInline(tableMatch[2]).trim();
      if (label && value && !/^[-:]+$/.test(label) && !/^[-:]+$/.test(value)) {
        if (current) {
          rows.push(current.trim());
        }
        current = `${label}：${value}`;
        continue;
      }
    }

    const trimmed = line.trim();
    if (!trimmed || /^[-]{3,}$/.test(trimmed)) {
      continue;
    }
    if (!current) {
      continue;
    }
    current = `${current} ${trimmed}`.trim();
  }

  if (current) {
    rows.push(current.trim());
  }

  return rows.map((row) => stripMarkdownInline(row)).filter(Boolean);
}

function buildSummaryRowsFromReport(card: AlarmAnalystCardV1): AlarmAnalystSummaryRow[] {
  const summarySection = extractMarkdownSection(
    unwrapPortalAlarmAnalystCardContent(card.rawReportMarkdown),
    ["总结"],
  );
  if (!summarySection) {
    return [];
  }

  const rowsByLabel = new Map<string, AlarmAnalystSummaryRow>();
  for (const entry of extractBulletEntries(summarySection)) {
    const match = entry.match(/^([^：:]{1,24})[：:]\s*(.+)$/u);
    if (!match) {
      continue;
    }
    const label = normalizeLabel(match[1]);
    const rawValue = stripMarkdownInline(match[2]);
    const value = label === "置信度" ? mapConfidenceLabel(rawValue) : rawValue;
    if (!label || !value || isJunkValue(value)) {
      continue;
    }
    rowsByLabel.set(label, {
      label,
      value,
      tone:
        label === "优先动作"
          ? "accent"
          : label === "关联资源告警查询状态"
          ? "success"
          : label === "关键提醒"
          ? "warning"
          : "neutral",
    });
  }

  return SUMMARY_LABEL_ORDER
    .map((label) => rowsByLabel.get(label))
    .filter((row): row is AlarmAnalystSummaryRow => Boolean(row));
}

function joinUnique(items: string[] = []) {
  return [...new Set(items.map((item) => item.trim()).filter(Boolean))].join("、");
}

function mapConfidenceLabel(value: unknown) {
  const raw = String(value || "").trim();
  const normalized = raw.toLowerCase();
  if (!normalized) {
    return "";
  }

  const percentMatch = normalized.match(/^(\d{1,3})(?:\.\d+)?\s*%$/);
  if (percentMatch) {
    const percent = Math.max(0, Math.min(100, Number(percentMatch[1])));
    return `${percent}%`;
  }

  const numericValue = Number(normalized);
  if (Number.isFinite(numericValue)) {
    const percent = numericValue <= 1
      ? Math.round(numericValue * 100)
      : Math.round(numericValue);
    return `${Math.max(0, Math.min(100, percent))}%`;
  }
  if (normalized === "high" || normalized === "高") {
    return "90%";
  }
  if (normalized === "medium" || normalized === "中") {
    return "70%";
  }
  if (normalized === "low" || normalized === "低") {
    return "50%";
  }
  return raw;
}

function mapStatusLabel(value: string) {
  if (value === "identified") {
    return "已定位";
  }
  if (value === "suspected") {
    return "待确认";
  }
  if (value === "unknown") {
    return "待分析";
  }
  return String(value || "").trim();
}

function mapSeverityLabel(value: string) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) {
    return "";
  }
  if (normalized === "critical" || normalized === "p0") {
    return "严重";
  }
  if (normalized === "major" || normalized === "p1") {
    return "高";
  }
  if (normalized === "minor" || normalized === "p2") {
    return "中";
  }
  return String(value).trim();
}

function extractReportTitle(card: AlarmAnalystCardV1) {
  const normalized = unwrapPortalAlarmAnalystCardContent(card.rawReportMarkdown)
    .replace(/\r\n/g, "\n");
  const match = normalized.match(/^##+\s*.*?告警分析报告[：:]\s*(.+?)\s*$/m);
  if (match?.[1]) {
    return stripMarkdownInline(match[1]);
  }
  const title = stripMarkdownInline(card.summary.title || "");
  if (title && !isAiThinkingText(title)) {
    return title;
  }
  return "故障根因分析";
}

function extractReportField(content: string, labels: string[]) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  for (const label of labels) {
    const escaped = escapeRegExp(label);
    const tablePattern = new RegExp(
      `\\|\\s*(?:\\*\\*)?${escaped}(?:\\*\\*)?\\s*\\|\\s*([^|\\n]+?)\\s*\\|`,
      "iu",
    );
    const linePattern = new RegExp(`(?:^|\\n)${escaped}\\s*[：:]\\s*([^\\n]+)`, "iu");
    const match = normalized.match(tablePattern) || normalized.match(linePattern);
    const value = stripMarkdownInline(match?.[1] || "").replace(/^自身$/u, "").trim();
    if (value) {
      return value;
    }
  }
  return "";
}

function extractReportLine(content: string, labels: string[]) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  for (const label of labels) {
    const escaped = escapeRegExp(label);
    const pattern = new RegExp(`(?:^|\\n)\\s*(?:[-*•]\\s*)?${escaped}\\s*[：:]\\s*([^\\n]+)`, "iu");
    const match = normalized.match(pattern);
    const value = stripMarkdownInline(match?.[1] || "").trim();
    if (value) {
      return value;
    }
  }
  return "";
}

function removeKnownLabelPrefixes(value: string, labels: string[]) {
  let next = String(value || "").trim();
  for (const label of labels) {
    const pattern = new RegExp(`^${escapeRegExp(label)}\\s*[：:]\\s*`, "iu");
    next = next.replace(pattern, "").trim();
  }
  return next;
}

function buildNotificationAutomationCard(reportText: string, notificationStatus: boolean, notificationPayload: string) {
  const notificationSection = extractMarkdownSection(reportText, ["飞书通知", "消息通知"]);
  const userId = extractReportLine(notificationSection, ["飞书用户 ID", "用户 ID", "通知对象"]);
  const conversationId = extractReportLine(notificationSection, ["飞书会话 ID", "会话 ID"]);
  const notificationTargets = joinUnique([
    userId ? `通知对象：${userId}` : "",
    conversationId ? `会话：${conversationId}` : "",
  ].filter(Boolean));

  const contentItems = (
    notificationPayload
      ? notificationPayload.split(/[、，,]/u)
      : extractBulletEntries(notificationSection)
          .filter((entry) => /通知内容包含|通知内容|发送内容/u.test(entry))
          .map((entry) =>
            removeKnownLabelPrefixes(entry, ["通知内容包含", "通知内容", "发送内容"]),
          )
          .flatMap((entry) => entry.split(/[、，,]/u))
  )
    .map((item) => stripMarkdownInline(item))
    .filter(Boolean);

  if (!notificationStatus && !notificationTargets && !contentItems.length) {
    return null;
  }

  return {
    label: "AI 自动通知",
    title: notificationStatus ? "已自动发送飞书通知" : "已准备通知内容",
    detail: notificationTargets || "通知内容已由 AI 自动整理并发送。",
    items: contentItems.length
      ? contentItems.map((item) => `通知包含：${item}`)
      : undefined,
    variant: "notification" as const,
  };
}

const RESOURCE_NAME_REJECT_VALUES = new Set([
  "ci id", "ciid", "ci_id", "ci", "resid", "res_id", "res id",
  "资源id", "资源 id", "无", "未知", "n/a", "-", "--", "未配置",
]);

function isValidResourceName(value: string): boolean {
  return Boolean(value) && !RESOURCE_NAME_REJECT_VALUES.has(value.toLowerCase().trim());
}

function buildAnchorText(card: AlarmAnalystCardV1) {
  const reportText = unwrapPortalAlarmAnalystCardContent(card.rawReportMarkdown);
  const candidateName = (
    card.rootCause.resourceName && card.rootCause.resourceName !== "自身"
      ? card.rootCause.resourceName
      : ""
  );
  const resourceName = isValidResourceName(candidateName)
    ? candidateName
    : extractReportField(reportText, ["设备名称", "资产编号", "资源名称", "实例", "根因资源"]);
  const manageIp = extractReportField(reportText, ["管理 IP", "设备 IP", "IP"]);

  return [isValidResourceName(resourceName) ? resourceName : "", manageIp]
    .map((item) => stripMarkdownInline(item))
    .filter(Boolean)
    .join(" · ");
}

function buildFallbackRows(card: AlarmAnalystCardV1): AlarmAnalystSummaryRow[] {
  const rows: AlarmAnalystSummaryRow[] = [];
  const confidence = mapConfidenceLabel(card.summary.confidence || "");
  if (confidence) {
    rows.push({ label: "置信度", value: confidence, tone: "neutral" });
  }

  const severity = mapSeverityLabel(card.summary.severity || "");
  const conclusionText = isJunkValue(card.summary.conclusion || "") ? "" : stripMarkdownInline(card.summary.conclusion || "");
  const faultNature = joinUnique([severity, conclusionText].filter(Boolean));
  if (faultNature) {
    rows.push({ label: "故障性质", value: faultNature, tone: "neutral" });
  }

  const reasonText = isJunkValue(card.rootCause.reason || "") ? "" : stripMarkdownInline(card.rootCause.reason || "");
  const rootCause = joinUnique([
    reasonText,
    stripMarkdownInline(
      [card.rootCause.resourceName || card.rootCause.resourceId]
        .filter(Boolean)
        .join(" · "),
    ),
  ].filter(Boolean));
  if (rootCause) {
    rows.push({ label: "根因方向", value: rootCause, tone: "neutral" });
  }

  const blastRadius = stripMarkdownInline(card.impact.blastRadiusText || "");
  const impactSegments = [
    isJunkValue(blastRadius) ? "" : blastRadius,
    card.impact.affectedApplications.length
      ? `受影响应用：${joinUnique(card.impact.affectedApplications.map((item) => item.name || ""))}`
      : "",
    card.impact.affectedResources.length
      ? `受影响资源：${joinUnique(card.impact.affectedResources.map((item) => item.name || ""))}`
      : "",
  ].filter(Boolean);
  if (impactSegments.length) {
    rows.push({ label: "影响范围", value: impactSegments.join("；"), tone: "neutral" });
  }

  const primaryRecommendation = card.recommendations[0];
  if (primaryRecommendation) {
    rows.push({
      label: "优先动作",
      value: stripMarkdownInline(primaryRecommendation.description || primaryRecommendation.title || ""),
      tone: "accent",
    });
  }

  const evidenceSummary = joinUnique(
    card.evidence.slice(0, 2)
      .map((item) => item.summary || item.title || "")
      .filter((item) => !isJunkValue(item))
  );
  if (evidenceSummary && !isJunkValue(evidenceSummary)) {
    rows.push({
      label: "关键提醒",
      value: stripMarkdownInline(evidenceSummary),
      tone: "warning",
    });
  }

  return rows;
}

function buildDisplayModel(card: AlarmAnalystCardV1, showConfidence: boolean) {
  const reportText = unwrapPortalAlarmAnalystCardContent(card.rawReportMarkdown);
  const reportSummaryRows = buildSummaryRowsFromReport(card);
  const summaryRows = (reportSummaryRows.length ? reportSummaryRows : buildFallbackRows(card))
    .filter((row) => showConfidence || row.label !== "置信度");
  const rowsByLabel = new Map(summaryRows.map((row) => [row.label, row]));

  const titleText = extractReportTitle(card);
  const leadCandidate = (
    rowsByLabel.get("故障性质")?.value ||
    rowsByLabel.get("根因方向")?.value ||
    stripMarkdownInline(card.summary.conclusion || "")
  );
  // Avoid showing the same text as both title and lead
  const lead = leadCandidate === titleText ? "" : leadCandidate;

  const confidenceLabel = showConfidence
    ? (rowsByLabel.get("置信度")?.value || mapConfidenceLabel(card.summary.confidence || ""))
    : "";
  const badges = [
    confidenceLabel ? `置信度 ${confidenceLabel}` : "",
    !reportSummaryRows.length ? mapStatusLabel(card.summary.status || "") : "",
    !reportSummaryRows.length ? mapSeverityLabel(card.summary.severity || "") : "",
  ].filter(Boolean);

  const anchorText = buildAnchorText(card);
  const workorderTitle = extractReportField(reportText, ["工单标题"]);
  const procInsId = extractReportField(reportText, ["procInsId"]);
  const notificationPayload = extractReportLine(reportText, ["通知内容包含"]);
  const notificationStatus = /飞书通知已发送成功|通知已发送成功/iu.test(reportText);

  const affectedEntities = [
    ...card.impact.affectedApplications.map((item) => item.name || item.id || ""),
    ...card.impact.affectedResources.map((item) => item.name || item.id || ""),
  ]
    .map((item) => stripMarkdownInline(item))
    .filter(Boolean);

  const spotlightSections: AlarmAnalystSpotlight[] = [
    rowsByLabel.get("故障性质")
      ? { ...rowsByLabel.get("故障性质")!, variant: "primary" }
      : null,
    rowsByLabel.get("根因方向")
      ? { ...rowsByLabel.get("根因方向")!, variant: "secondary" }
      : null,
    rowsByLabel.get("影响范围")
      ? { ...rowsByLabel.get("影响范围")!, variant: "secondary" }
      : null,
    rowsByLabel.get("优先动作")
      ? { ...rowsByLabel.get("优先动作")!, variant: "action" }
      : null,
    rowsByLabel.get("关联资源告警查询状态")
      ? { ...rowsByLabel.get("关联资源告警查询状态")!, variant: "status" }
      : null,
    rowsByLabel.get("关键提醒")
      ? { ...rowsByLabel.get("关键提醒")!, variant: "warning" }
      : null,
  ].filter((item): item is AlarmAnalystSpotlight => Boolean(item));

  const automationCards: AlarmAnalystAutomationCard[] = [
    workorderTitle || procInsId
      ? {
          label: "AI 自动建单",
          title: "已自动创建处置工单",
          detail: joinUnique([
            workorderTitle ? `工单：${workorderTitle}` : "",
            procInsId ? `流程号：${procInsId}` : "",
          ].filter(Boolean)),
          variant: "workorder",
        }
      : null,
    buildNotificationAutomationCard(reportText, notificationStatus, notificationPayload),
  ].filter((item): item is AlarmAnalystAutomationCard => Boolean(item));

  const statusChecklist: AlarmAnalystStatusItem[] = [
    rowsByLabel.get("关联资源告警查询状态")
      ? {
          label: rowsByLabel.get("关联资源告警查询状态")!.value,
          state: /完成|成功|正常|已清除/u.test(rowsByLabel.get("关联资源告警查询状态")!.value)
            ? "success"
            : "alert",
        }
      : null,
    automationCards.find((item) => item.variant === "workorder")
      ? {
          label: "AI 自动建单已完成",
          detail: automationCards.find((item) => item.variant === "workorder")!.title,
          state: "success",
        }
      : null,
    automationCards.find((item) => item.variant === "notification")
      ? {
          label: "AI 自动通知已完成",
          detail: automationCards.find((item) => item.variant === "notification")!.title,
          state: "success",
        }
      : null,
    rowsByLabel.get("关键提醒")
      ? {
          label: "关键提醒需优先处理",
          detail: rowsByLabel.get("关键提醒")!.value,
          state: "alert",
        }
      : null,
  ].filter((item): item is AlarmAnalystStatusItem => Boolean(item));

  const decisionCards: AlarmAnalystDecisionCard[] = [
    rowsByLabel.get("故障性质")?.value
      ? { label: "根因类型", value: rowsByLabel.get("故障性质")!.value }
      : null,
    anchorText
      ? { label: "根因对象", value: anchorText }
      : null,
    rowsByLabel.get("根因方向")?.value
      ? { label: "故障原因", value: rowsByLabel.get("根因方向")!.value }
      : null,
    confidenceLabel
      ? { label: "定位置信度", value: confidenceLabel, accent: true }
      : null,
  ].filter((item): item is AlarmAnalystDecisionCard => Boolean(item));

  // Ranked Top-N candidate root causes; per-candidate confidence obeys the
  // same visibility toggle as the main confidence badge.
  const rootCauseCandidates = (card.rootCause.candidates || [])
    .filter((item) => Boolean(item?.reason))
    .map((item) => ({
      rank: item.rank,
      reason: stripMarkdownInline(item.reason),
      resourceName: stripMarkdownInline(item.resourceName || ""),
      confidence: showConfidence
        ? stripMarkdownInline(item.confidence || "")
        : "",
      evidence: stripMarkdownInline(item.evidence || ""),
    }));

  return {
    title: titleText,
    lead,
    summaryRows,
    badges,
    anchorText,
    affectedEntities,
    spotlightSections,
    automationCards,
    statusChecklist,
    decisionCards,
    rootCauseCandidates,
  };
}

export const AlarmAnalystCardPanel = memo(function AlarmAnalystCardPanel({
  card,
}: {
  card: AlarmAnalystCardV1;
}) {
  const [showConfidence, setShowConfidence] = useState(() => readFaultAnalysisConfidenceVisible());

  useEffect(() => {
    const handleFaultAnalysisConfidenceVisibilityChanged = () => {
      setShowConfidence(readFaultAnalysisConfidenceVisible());
    };

    window.addEventListener(
      FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_CHANGED_EVENT,
      handleFaultAnalysisConfidenceVisibilityChanged,
    );
    return () => {
      window.removeEventListener(
        FAULT_ANALYSIS_CONFIDENCE_VISIBILITY_CHANGED_EVENT,
        handleFaultAnalysisConfidenceVisibilityChanged,
      );
    };
  }, []);

  const topologyChart = useMemo(() => buildTopologyChart(card), [card]);
  const display = useMemo(() => buildDisplayModel(card, showConfidence), [card, showConfidence]);

  return (
    <div className="alarm-analyst-card-stack">
      {card.rawReportMarkdown ? (
        <details className="alarm-analyst-raw-report alarm-analyst-raw-report-priority">
          <summary>
            <span>查看完整分析</span>
            <small>展开最后一次完整回复</small>
          </summary>
          <div className="alarm-analyst-raw-report-body">
            <AlarmAnalystMarkdown content={card.rawReportMarkdown} />
          </div>
        </details>
      ) : null}

      <section className="alarm-analyst-card alarm-analyst-summary-card">
        <div className="alarm-analyst-card-header">
          <div>
            <div className="alarm-analyst-card-eyebrow">根因分析总结</div>
            <h3>{display.title}</h3>
          </div>
          {display.badges.length ? (
            <div className="alarm-analyst-summary-badges">
              {display.badges.map((badge) => (
                <span key={badge} className="alarm-analyst-badge">
                  {badge}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        {display.lead ? (
          <p className="alarm-analyst-summary-text alarm-analyst-summary-lead">
            {display.lead}
          </p>
        ) : null}

        {display.anchorText ? (
          <div className="alarm-analyst-summary-anchor">
            <span>定位对象</span>
            <strong>{display.anchorText}</strong>
          </div>
        ) : null}

        {display.affectedEntities.length ? (
          <div className="alarm-analyst-affected-strip">
            <span className="alarm-analyst-affected-label">受影响对象</span>
            <div className="alarm-analyst-affected-list">
              {display.affectedEntities.map((item) => (
                <span key={item} className="alarm-analyst-affected-chip">
                  {item}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {display.spotlightSections.length ? (
          <div className="alarm-analyst-spotlight-grid">
            {display.spotlightSections.map((item) => (
              <article
                key={item.label}
                className={`alarm-analyst-spotlight-card ${item.variant} ${item.tone || "neutral"}`}
              >
                <div className="alarm-analyst-spotlight-label">{item.label}</div>
                <div className="alarm-analyst-spotlight-value">{item.value}</div>
              </article>
            ))}
          </div>
        ) : null}

        {display.rootCauseCandidates.length ? (
          <div className="alarm-analyst-candidate-strip">
            <div className="alarm-analyst-candidate-head">
              <span className="alarm-analyst-candidate-label">候选根因排序</span>
              <small>按置信度降序 Top-{display.rootCauseCandidates.length}</small>
            </div>
            <ol className="alarm-analyst-candidate-list">
              {display.rootCauseCandidates.map((item) => (
                <li
                  key={`${item.rank}-${item.reason}`}
                  className="alarm-analyst-candidate-item"
                >
                  <span className="alarm-analyst-candidate-rank">{item.rank}</span>
                  <div className="alarm-analyst-candidate-body">
                    <div className="alarm-analyst-candidate-main">
                      <strong>{item.reason}</strong>
                      {item.resourceName ? (
                        <span className="alarm-analyst-candidate-resource">
                          {item.resourceName}
                        </span>
                      ) : null}
                      {item.confidence ? (
                        <span className="alarm-analyst-candidate-confidence">
                          {item.confidence}
                        </span>
                      ) : null}
                    </div>
                    {item.evidence ? (
                      <p className="alarm-analyst-candidate-evidence">{item.evidence}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        {display.automationCards.length ? (
          <div className="alarm-analyst-automation-grid">
            {display.automationCards.map((item) => (
              <article
                key={item.label}
                className={`alarm-analyst-automation-card ${item.variant}`}
              >
                <div className="alarm-analyst-automation-label">{item.label}</div>
                <h4>{item.title}</h4>
                <p>{item.detail}</p>
                {item.variant !== "notification" && item.items?.length ? (
                  <div className="alarm-analyst-automation-list">
                    {item.items.map((detail) => (
                      <span key={detail} className="alarm-analyst-automation-pill">
                        {detail}
                      </span>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        ) : null}

        {display.statusChecklist.length ? (
          <div className="alarm-analyst-status-board">
            {display.statusChecklist.map((item) => (
              <div key={item.label} className={`alarm-analyst-status-item ${item.state}`}>
                <span className="alarm-analyst-status-icon">
                  {item.state === "success" ? "✓" : "✕"}
                </span>
                <div className="alarm-analyst-status-content">
                  <strong>{item.label}</strong>
                  {item.detail ? <span>{item.detail}</span> : null}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      {topologyChart ? (
        <section className="alarm-analyst-card">
          <div className="alarm-analyst-topology-header">
            <div>
              <div className="alarm-analyst-card-eyebrow">应用 / 资源拓扑</div>
              <p className="alarm-analyst-topology-hint">红色节点表示根因资源或已识别的受影响节点</p>
            </div>
            <span className="alarm-analyst-topology-legend">
              <span className="alarm-analyst-topology-legend-dot" />
              受影响节点
            </span>
          </div>
          <div className="alarm-analyst-topology-panel">
            <DeferredEChartsBlock
              chart={topologyChart}
              style={{ height: 360 }}
              fallbackMinHeight={360}
            />
          </div>
        </section>
      ) : null}

      {display.decisionCards.length ? (
        <section className="alarm-analyst-card alarm-analyst-decision-card">
          <div className="alarm-analyst-decision-header">
            <div className="alarm-analyst-card-eyebrow">根因确定</div>
          </div>
          <div className="alarm-analyst-decision-grid">
            {display.decisionCards.map((item) => (
              <article
                key={item.label}
                className={`alarm-analyst-decision-item ${item.accent ? "accent" : ""}`}
              >
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
});
