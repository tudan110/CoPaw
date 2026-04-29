import { memo, useMemo } from "react";

import { DeferredEChartsBlock } from "../../components/DeferredVisualizationBlocks";
import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import {
  normalizeMarkdownDisplayContent,
  unwrapPortalInspectionCardContent,
} from "./helpers";

type InspectionCardTone = "good" | "warning" | "danger" | "neutral";

type InspectionStat = {
  label: string;
  value: string;
  tone?: InspectionCardTone;
};

type InspectionMetricCard = {
  label: string;
  value: string;
  detail?: string;
  tone?: InspectionCardTone;
};

type InspectionFindingItem = {
  label: string;
  value: string;
  detail?: string;
};

type InspectionFindingSection = {
  title: string;
  tone: InspectionCardTone;
  items: InspectionFindingItem[];
};

type InspectionRecommendation = {
  label: string;
  value: string;
  detail?: string;
};

type InspectionDisplayModel = {
  title: string;
  eyebrow: string;
  lead: string;
  badges: string[];
  targetText: string;
  stats: InspectionStat[];
  metrics: InspectionMetricCard[];
  findingSections: InspectionFindingSection[];
  recommendations: InspectionRecommendation[];
  topologyChart: string;
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
  const end = targetIndex + 1 < headingMatches.length
    ? (headingMatches[targetIndex + 1].index || normalized.length)
    : normalized.length;
  return normalized.slice(start, end).trim();
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
      line &&
      !/^\s*[：:]?\s*(?:[\p{Extended_Pictographic}]\s*)?.*?\d+\s*\/\s*10\s*$/u.test(line) &&
      !line.startsWith("---") &&
      !line.startsWith("|"),
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
  if (/命中率/u.test(normalizedLabel) && !Number.isNaN(numeric) && numeric >= 99) {
    return "good";
  }
  if (/慢查询|锁/u.test(normalizedLabel) && /^0(?:\.0+)?$/u.test(normalizedValue)) {
    return "good";
  }
  if (/使用率/u.test(normalizedLabel) && !Number.isNaN(numeric) && numeric >= 80) {
    return "warning";
  }
  if (/读请求/u.test(normalizedLabel) || /连接/u.test(normalizedLabel)) {
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
    /QPS/u,
    /TPS/u,
    /读请求/u,
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

function buildInspectionReportModel(content: string): InspectionDisplayModel {
  const basicInfoSection = extractMarkdownSection(content, ["基本信息"]);
  const basicInfoMap = rowsToKeyValueMap(extractFirstTable(basicInfoSection).rows);
  const metricsSection = extractMarkdownSection(content, ["指标数据"]);
  const metrics = selectMetricRows(extractFirstTable(metricsSection).rows);
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
    metrics,
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
    findingSections: [healthySection, warningSection, criticalSection].filter(
      (item): item is InspectionFindingSection => Boolean(item),
    ),
    recommendations,
    topologyChart: "",
  };
}

function buildInspectionDisplayModel(content: string): InspectionDisplayModel | null {
  const normalizedContent = unwrapPortalInspectionCardContent(content);
  if (/健康状态评估/u.test(normalizedContent)) {
    return buildHealthAssessmentModel(normalizedContent);
  }
  if (/巡检结果/u.test(normalizedContent)) {
    return buildInspectionReportModel(normalizedContent);
  }
  return null;
}

function InspectionMarkdown({ content }: { content: string }) {
  const isDarkTheme =
    typeof document !== "undefined"
    && document.querySelector(".portal-digital-employee")?.classList.contains("theme-dark");
  const markdownThemeClass = isDarkTheme ? "x-markdown-dark" : "x-markdown-light";
  const normalizedContent = unwrapPortalInspectionCardContent(
    normalizeMarkdownDisplayContent(content),
  );

  return (
    <PortalQwenPawMarkdown
      className={`portal-x-markdown ${markdownThemeClass}`}
      content={normalizedContent}
      isStreaming={false}
    />
  );
}

export const InspectionAnalystCardPanel = memo(function InspectionAnalystCardPanel({
  content,
}: {
  content: string;
}) {
  const display = useMemo(() => buildInspectionDisplayModel(content), [content]);

  if (!display) {
    return null;
  }

  return (
    <div className="inspection-analyst-card-stack">
      <details className="inspection-analyst-raw-report inspection-analyst-raw-report-priority">
        <summary>
          <span>查看完整巡检报告</span>
          <small>展开当前完整回复</small>
        </summary>
        <div className="message-bubble markdown-bubble inspection-analyst-raw-report-body">
          <InspectionMarkdown content={content} />
        </div>
      </details>

      <section className="inspection-analyst-card inspection-analyst-summary-card">
        <div className="inspection-analyst-card-header">
          <div>
            <div className="inspection-analyst-card-eyebrow">{display.eyebrow}</div>
            <h3>{display.title}</h3>
          </div>
          {display.badges.length ? (
            <div className="inspection-analyst-summary-badges">
              {display.badges.map((badge) => (
                <span key={badge} className="inspection-analyst-badge">
                  {badge}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        {display.lead ? (
          <p className="inspection-analyst-summary-lead">{display.lead}</p>
        ) : null}

        {display.targetText ? (
          <div className="inspection-analyst-target">
            <span>巡检对象</span>
            <strong>{display.targetText}</strong>
          </div>
        ) : null}

        {display.stats.length ? (
          <div className="inspection-analyst-stat-grid">
            {display.stats.map((item) => (
              <article
                key={item.label}
                className={`inspection-analyst-stat-card ${item.tone || "neutral"}`}
              >
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      {display.metrics.length ? (
        <section className="inspection-analyst-card">
          <div className="inspection-analyst-section-header">
            <div className="inspection-analyst-card-eyebrow">关键指标</div>
          </div>
          <div className="inspection-analyst-metric-grid">
            {display.metrics.map((item) => (
              <article
                key={item.label}
                className={`inspection-analyst-metric-card ${item.tone || "neutral"}`}
              >
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                {item.detail ? <p>{item.detail}</p> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {display.findingSections.length ? (
        <section className="inspection-analyst-card">
          <div className="inspection-analyst-section-header">
            <div className="inspection-analyst-card-eyebrow">健康结论</div>
          </div>
          <div className="inspection-analyst-finding-grid">
            {display.findingSections.map((section) => (
              <article
                key={section.title}
                className={`inspection-analyst-finding-card ${section.tone}`}
              >
                <h4>{section.title}</h4>
                <div className="inspection-analyst-finding-list">
                  {section.items.map((item) => (
                    <div key={`${section.title}-${item.label}`} className="inspection-analyst-finding-item">
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                      {item.detail ? <p>{item.detail}</p> : null}
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {display.recommendations.length ? (
        <section className="inspection-analyst-card">
          <div className="inspection-analyst-section-header">
            <div className="inspection-analyst-card-eyebrow">建议优先级</div>
          </div>
          <div className="inspection-analyst-recommendation-grid">
            {display.recommendations.map((item) => (
              <article key={`${item.label}-${item.value}`} className="inspection-analyst-recommendation-card">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                {item.detail ? <p>{item.detail}</p> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {display.topologyChart ? (
        <section className="inspection-analyst-card">
          <div className="inspection-analyst-topology-header">
            <div>
              <div className="inspection-analyst-card-eyebrow">拓扑确认</div>
              <p className="inspection-analyst-topology-hint">优先展示巡检对象所在的实时拓扑确认结果</p>
            </div>
          </div>
          <div className="inspection-analyst-topology-panel">
            <DeferredEChartsBlock
              chart={display.topologyChart}
              style={{ height: 360 }}
              fallbackMinHeight={360}
            />
          </div>
        </section>
      ) : null}
    </div>
  );
});
