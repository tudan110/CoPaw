import { unwrapPortalInspectionCardContent } from "../pages/digital-employee/helpers.ts";

export type InspectionCardTone = "good" | "warning" | "danger" | "neutral";

export type InspectionStat = {
  label: string;
  value: string;
  tone?: InspectionCardTone;
};

export type InspectionMetricCard = {
  label: string;
  value: string;
  detail?: string;
  tone?: InspectionCardTone;
};

export type InspectionMetricGroup = {
  title: string;
  summary?: string;
  metrics: InspectionMetricCard[];
};

export type InspectionFindingItem = {
  label: string;
  value: string;
  detail?: string;
};

export type InspectionFindingSection = {
  title: string;
  tone: InspectionCardTone;
  items: InspectionFindingItem[];
};

export type InspectionRecommendation = {
  label: string;
  value: string;
  detail?: string;
};

export type InspectionDisplayModel = {
  title: string;
  eyebrow: string;
  lead: string;
  badges: string[];
  targetText: string;
  stats: InspectionStat[];
  metrics: InspectionMetricCard[];
  metricGroups: InspectionMetricGroup[];
  findingSections: InspectionFindingSection[];
  recommendations: InspectionRecommendation[];
  topologyChart: string;
};

type MarkdownHeadingMatch = {
  title: string;
  raw: string;
  index: number;
  level: number;
};

function stripMarkdownInline(value: string) {
  return String(value || "")
    .replace(/[*_~`>#]/g, "")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/^\p{Extended_Pictographic}+\s*/u, "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeCardFieldValue(value: string) {
  const normalized = stripMarkdownInline(value);
  return normalized === "-" || normalized === "--" ? "" : normalized;
}

function buildMetricDetail(row: string[]) {
  const sampleTime = normalizeCardFieldValue(row[3] || "");
  const source = normalizeCardFieldValue(row[5] || "");
  const displaySource = source.toLowerCase() === "live" ? "" : source;
  return [sampleTime, displaySource].filter(Boolean).join(" · ");
}

function getMarkdownHeadingMatches(content: string): MarkdownHeadingMatch[] {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  return [...normalized.matchAll(/^(#{1,6})\s*(.+?)\s*$/gm)].map((match) => ({
    title: stripMarkdownInline(match[2]),
    raw: match[0],
    index: match.index || 0,
    level: match[1].length,
  }));
}

function extractMarkdownSection(content: string, titles: string[]) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  if (!normalized.trim()) {
    return "";
  }

  const headingMatches = getMarkdownHeadingMatches(normalized);
  if (!headingMatches.length) {
    return "";
  }

  const targetIndex = headingMatches.findIndex((match) =>
    titles.some((title) => match.title.includes(title)),
  );
  if (targetIndex === -1) {
    return "";
  }

  const startMatch = headingMatches[targetIndex];
  const start = startMatch.index + startMatch.raw.length;
  const nextMatch = headingMatches
    .slice(targetIndex + 1)
    .find((match) => match.level <= startMatch.level);
  const end = nextMatch ? nextMatch.index : normalized.length;
  return normalized.slice(start, end).trim();
}

function extractHeadingSections(content: string, level: number) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  const headings = getMarkdownHeadingMatches(normalized);
  const scopedHeadings = headings.filter((heading) => heading.level === level);

  return scopedHeadings.map((heading) => {
    const start = heading.index + heading.raw.length;
    const nextMatch = headings
      .filter((match) => match.index > heading.index)
      .find((match) => match.level <= heading.level);
    const end = nextMatch ? nextMatch.index : normalized.length;
    return {
      title: heading.title,
      body: normalized.slice(start, end).trim(),
    };
  });
}

function extractRawTopologyChart(content: string) {
  const match = String(content || "").match(/```echarts\s*([\s\S]*?)```/i);
  return match?.[1]?.trim() || "";
}

function parseTableLine(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => stripMarkdownInline(cell));
}

function isTableSeparator(cells: string[]) {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function extractFirstTable(content: string) {
  const lines = String(content || "").replace(/\r\n/g, "\n").split("\n");
  const tables: string[][] = [];
  let active: string[] = [];

  for (const line of lines) {
    if (line.trim().startsWith("|")) {
      active.push(line);
      continue;
    }
    if (active.length) {
      tables.push(active);
      active = [];
    }
  }
  if (active.length) {
    tables.push(active);
  }
  if (!tables.length) {
    return { headers: [] as string[], rows: [] as string[][] };
  }

  const rows = tables[0].map(parseTableLine).filter((row) => row.length > 1);
  if (!rows.length) {
    return { headers: [] as string[], rows: [] as string[][] };
  }

  const headers = rows[0];
  const body = rows.slice(1).filter((row) => !isTableSeparator(row));
  return { headers, rows: body };
}

function rowsToKeyValueMap(rows: string[][]) {
  const map = new Map<string, string>();
  rows.forEach((row) => {
    if (row.length < 2) {
      return;
    }
    const key = stripMarkdownInline(row[0]).replace(/[：:]$/, "");
    const value = stripMarkdownInline(row[1]);
    if (key && value) {
      map.set(key, value);
    }
  });
  return map;
}

function extractHeadingTitle(content: string, keyword: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  const match = normalized.match(new RegExp(`^##+\\s*.*?${keyword}[^\\n]*$`, "imu"));
  return stripMarkdownInline(match?.[0] || "");
}

function extractLeadParagraph(content: string, anchor: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  const index = normalized.indexOf(anchor);
  const sliced = index >= 0 ? normalized.slice(index + anchor.length) : normalized;
  const lines = sliced
    .split("\n")
    .map((line) => stripMarkdownInline(line))
    .filter((line) =>
      line
      && !/^\s*[：:]?\s*(?:[\p{Extended_Pictographic}]\s*)?.*?\d+\s*\/\s*10\s*$/u.test(line)
      && !line.startsWith("---")
      && !line.startsWith("|"),
    );
  return lines[0] || "";
}

function extractHealthScore(content: string) {
  const match = String(content || "").match(/总体评分[：:]\s*(.+)$/imu);
  const raw = stripMarkdownInline(match?.[1] || "");
  if (!raw) {
    return { verdict: "", score: "" };
  }

  const scoreMatch = raw.match(/(\d+\s*\/\s*10)/u);
  const score = scoreMatch?.[1]?.replace(/\s+/g, "") || "";
  const verdict = raw.replace(/^\S+\s*/, "").replace(/\(\d+\s*\/\s*10\)/u, "").trim() || raw;
  return {
    verdict: verdict.replace(/[()（）]/g, "").trim(),
    score,
  };
}

function getMetricTone(label: string, value: string): InspectionCardTone {
  const normalizedLabel = String(label || "");
  const normalizedValue = String(value || "");
  const percentMatch = normalizedValue.match(/(\d+(?:\.\d+)?)/);
  const numeric = percentMatch ? Number(percentMatch[1]) : Number.NaN;

  if (/失败|异常/u.test(normalizedLabel)) {
    return "danger";
  }
  if (/阻塞/u.test(normalizedLabel) && !Number.isNaN(numeric)) {
    return numeric > 0 ? "danger" : "good";
  }
  if (/内存碎片率/u.test(normalizedLabel) && !Number.isNaN(numeric)) {
    if (numeric >= 3) {
      return "danger";
    }
    if (numeric >= 1.5) {
      return "warning";
    }
    return "good";
  }
  if (/拒绝连接/u.test(normalizedLabel) && !Number.isNaN(numeric)) {
    return numeric > 0 ? "warning" : "good";
  }
  if (/服务状态|在线状态/u.test(normalizedLabel)) {
    if (/^(?:1|正常|在线)(?:\.0+)?$/u.test(normalizedValue)) {
      return "good";
    }
    return "warning";
  }
  if (/命中率/u.test(normalizedLabel) && !Number.isNaN(numeric) && numeric >= 99) {
    return "good";
  }
  if (/慢查询|锁/u.test(normalizedLabel) && /^0(?:\.0+)?$/u.test(normalizedValue)) {
    return "good";
  }
  if (/使用率/u.test(normalizedLabel) && !Number.isNaN(numeric) && numeric >= 80) {
    return "warning";
  }
  if (/读请求|OPS|QPS|TPS|连接/u.test(normalizedLabel)) {
    return "warning";
  }
  return "neutral";
}

function selectMetricRows(rows: string[][]) {
  const preferredPatterns = [
    /连接失败/u,
    /连接数使用率/u,
    /缓存池使用率/u,
    /缓存池命中率/u,
    /慢查询/u,
    /锁/u,
    /内存碎片率/u,
    /阻塞\s*Key/u,
    /拒绝连接/u,
    /服务状态|在线状态/u,
    /QPS/u,
    /TPS/u,
    /OPS/u,
    /读请求/u,
    /CPU 使用率/u,
    /连接/u,
  ];

  const picked: InspectionMetricCard[] = [];
  const seen = new Set<string>();

  preferredPatterns.forEach((pattern) => {
    const row = rows.find((item) => item[0] && pattern.test(item[0]));
    if (!row || seen.has(row[0])) {
      return;
    }
    seen.add(row[0]);
    picked.push({
      label: row[0],
      value: row[2] || row[1] || "",
      detail: buildMetricDetail(row),
      tone: getMetricTone(row[0], row[2] || row[1] || ""),
    });
  });

  if (picked.length >= 6) {
    return picked.slice(0, 6);
  }

  rows.forEach((row) => {
    if (picked.length >= 6 || !row[0] || seen.has(row[0])) {
      return;
    }
    seen.add(row[0]);
    picked.push({
      label: row[0],
      value: row[2] || row[1] || "",
      detail: buildMetricDetail(row),
      tone: getMetricTone(row[0], row[2] || row[1] || ""),
    });
  });

  return picked;
}

function extractSectionLeadText(content: string) {
  const lines = String(content || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("|") && !line.startsWith("#") && !line.startsWith("---"));
  return stripMarkdownInline(lines[0] || "");
}

function buildInspectionMetricGroups(metricsSection: string) {
  const groupedSections = extractHeadingSections(metricsSection, 3);
  if (groupedSections.length) {
    return groupedSections
      .map((section) => {
        const metrics = selectMetricRows(extractFirstTable(section.body).rows);
        const summary = extractSectionLeadText(section.body);
        return {
          title: section.title,
          summary,
          metrics,
        };
      })
      .filter((group) => group.metrics.length || group.summary);
  }

  const metrics = selectMetricRows(extractFirstTable(metricsSection).rows);
  return metrics.length
    ? [{ title: "", summary: "", metrics }]
    : [];
}

function buildInspectionReportModel(content: string): InspectionDisplayModel {
  const basicInfoSection = extractMarkdownSection(content, ["基本信息"]);
  const basicInfoMap = rowsToKeyValueMap(extractFirstTable(basicInfoSection).rows);
  const metricsSection = extractMarkdownSection(content, ["指标数据"]);
  const metricGroups = buildInspectionMetricGroups(metricsSection);
  const topologyChart = extractRawTopologyChart(content);

  const resourceName = normalizeCardFieldValue(basicInfoMap.get("资源名称") || "");
  const inspectionObject = normalizeCardFieldValue(basicInfoMap.get("巡检对象") || "");
  const resourceType = normalizeCardFieldValue(basicInfoMap.get("资源类型") || "");
  const manageIp = normalizeCardFieldValue(basicInfoMap.get("管理 IP") || "");
  const status = normalizeCardFieldValue(basicInfoMap.get("状态") || "");
  const metricsCount = normalizeCardFieldValue(basicInfoMap.get("指标总数") || "");
  const dataSource = normalizeCardFieldValue(basicInfoMap.get("数据来源") || "");
  const inspectionTime = normalizeCardFieldValue(basicInfoMap.get("巡检时间") || "");
  const title = extractHeadingTitle(content, "巡检结果") || "巡检结果";

  return {
    title,
    eyebrow: "巡检结果摘要",
    lead: [
      resourceName || inspectionObject,
      status ? `当前状态 ${status}` : "",
      metricsCount ? `已完成 ${metricsCount} 项指标采集` : "",
    ].filter(Boolean).join("，"),
    badges: [resourceType, status, dataSource].filter(Boolean),
    targetText: [inspectionObject, resourceName, manageIp].filter(Boolean).join(" · "),
    stats: [
      { label: "巡检时间", value: inspectionTime || "--" },
      { label: "指标总数", value: metricsCount || "--" },
      { label: "资源类型", value: resourceType || "--" },
      {
        label: "在线状态",
        value: status || "--",
        tone: /在线|正常/u.test(status) ? "good" : "warning",
      },
    ],
    metrics: metricGroups.length === 1 ? metricGroups[0].metrics : [],
    metricGroups,
    findingSections: [],
    recommendations: [],
    topologyChart,
  };
}

function buildFindingSection(
  title: string,
  sectionText: string,
  tone: InspectionCardTone,
  valueKey: string,
  detailKey: string,
) {
  const table = extractFirstTable(sectionText);
  if (!table.rows.length) {
    return null;
  }

  const headerIndex = new Map(table.headers.map((header, index) => [header, index]));
  const dimensionIndex = headerIndex.get("维度") ?? 0;
  const metricIndex = headerIndex.get("指标") ?? 1;
  const valueIndex = headerIndex.get(valueKey) ?? 2;
  const detailIndex = headerIndex.get(detailKey) ?? 3;

  const items = table.rows.map((row) => ({
    label: [row[dimensionIndex], row[metricIndex]].filter(Boolean).join(" · "),
    value: row[valueIndex] || "",
    detail: row[detailIndex] || "",
  })).filter((item) => item.label && item.value);

  return items.length
    ? {
        title,
        tone,
        items,
      }
    : null;
}

function buildRecommendationItems(sectionText: string) {
  const table = extractFirstTable(sectionText);
  if (!table.rows.length) {
    return [];
  }
  return table.rows.map((row) => ({
    label: row[0] || "建议",
    value: row[1] || "",
    detail: row[2] || "",
  })).filter((item) => item.value);
}

function buildHealthAssessmentModel(content: string): InspectionDisplayModel {
  const { verdict, score } = extractHealthScore(content);
  const title = extractHeadingTitle(content, "健康状态评估") || "健康状态评估";
  const targetText = stripMarkdownInline(title)
    .replace(/健康状态评估/gu, "")
    .replace(/^[-—\s]+|[-—\s]+$/gu, "")
    .trim();
  const lead = extractLeadParagraph(content, "总体评分");

  const healthySection = buildFindingSection(
    "健康项",
    extractMarkdownSection(content, ["健康项"]),
    "good",
    "值",
    "评价",
  );
  const warningSection = buildFindingSection(
    "亚健康项",
    extractMarkdownSection(content, ["亚健康项"]),
    "warning",
    "值",
    "风险",
  );
  const criticalSection = buildFindingSection(
    "病理项",
    extractMarkdownSection(content, ["病理项"]),
    "danger",
    "值",
    "严重程度",
  );
  const recommendations = buildRecommendationItems(extractMarkdownSection(content, ["建议优先级"]));

  return {
    title,
    eyebrow: "健康评估摘要",
    lead,
    badges: [verdict, score].filter(Boolean),
    targetText,
    stats: [
      { label: "综合评分", value: score || "--", tone: "warning" },
      { label: "当前结论", value: verdict || "--", tone: "warning" },
      { label: "健康项", value: String(healthySection?.items.length || 0), tone: "good" },
      { label: "风险项", value: String((warningSection?.items.length || 0) + (criticalSection?.items.length || 0)), tone: "danger" },
    ],
    metrics: [],
    metricGroups: [],
    findingSections: [healthySection, warningSection, criticalSection].filter(
      (item): item is InspectionFindingSection => Boolean(item),
    ),
    recommendations,
    topologyChart: "",
  };
}

export function buildInspectionDisplayModel(content: string): InspectionDisplayModel | null {
  const normalizedContent = unwrapPortalInspectionCardContent(content);
  if (/健康状态评估/u.test(normalizedContent)) {
    return buildHealthAssessmentModel(normalizedContent);
  }
  if (/巡检结果/u.test(normalizedContent)) {
    return buildInspectionReportModel(normalizedContent);
  }
  return null;
}
