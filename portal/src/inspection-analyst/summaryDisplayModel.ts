/**
 * Display model for multi-resource inspection summary reports.
 *
 * Handles the aggregated report format:
 *   # XXX巡检报告
 *   ## 巡检总览 (summary table)
 *   ## 异常资源 / 需关注资源 / 正常资源 (resource groups)
 *   ## 巡检结论 (conclusion sections)
 */

export type SeverityTone = "danger" | "warning" | "good" | "neutral";

export interface SummaryOverviewStat {
  label: string;
  value: string;
  tone?: SeverityTone;
}

export interface SummaryResourceItem {
  name: string;
  resourceType: string;
  ip: string;
  verdict: string;
  details: string[];
}

export interface SummaryResourceGroup {
  title: string;
  tone: SeverityTone;
  count: number;
  items: SummaryResourceItem[];
}

export interface SummaryConclusionItem {
  text: string;
}

export interface SummaryConclusionSection {
  title: string;
  tone: SeverityTone;
  items: SummaryConclusionItem[];
}

export interface InspectionSummaryDisplayModel {
  reportTitle: string;
  inspectionTime: string;
  overviewStats: SummaryOverviewStat[];
  resourceGroups: SummaryResourceGroup[];
  conclusionSections: SummaryConclusionSection[];
  overallAssessment: string;
  topology: string;
  rawContent: string;
}

/* ------------------------------------------------------------------ */
/*  Detection                                                          */
/* ------------------------------------------------------------------ */

export function looksLikeInspectionSummaryReport(content: string): boolean {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  const hasSummarySection = /(?:^|\n)##+\s*.*巡检总览/um.test(normalized);
  const hasReportTitle = /(?:^|\n)#\s+.*巡检报告/um.test(normalized);
  const hasResourceGroups =
    /(?:^|\n)##+\s*.*(?:异常资源|需关注资源|正常资源)/um.test(normalized);
  const hasConclusion = /(?:^|\n)##+\s*.*巡检结论/um.test(normalized);

  return (hasReportTitle || hasSummarySection) && hasResourceGroups && hasConclusion;
}

/* ------------------------------------------------------------------ */
/*  Parsing helpers                                                    */
/* ------------------------------------------------------------------ */

interface HeadingBlock {
  level: number;
  title: string;
  body: string;
}

function splitByHeadings(text: string, level: number): HeadingBlock[] {
  const re = new RegExp(`^(#{${level}})\\s+(.+)$`, "gm");
  const blocks: HeadingBlock[] = [];
  let lastIndex = 0;
  let lastTitle = "";
  let lastLevel = 0;
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    if (lastTitle) {
      blocks.push({
        level: lastLevel,
        title: lastTitle,
        body: text.slice(lastIndex, match.index).trim(),
      });
    }
    lastTitle = match[2].trim();
    lastLevel = match[1].length;
    lastIndex = match.index + match[0].length;
  }
  if (lastTitle) {
    blocks.push({
      level: lastLevel,
      title: lastTitle,
      body: text.slice(lastIndex).trim(),
    });
  }
  return blocks;
}

function extractTableRows(body: string): Record<string, string>[] {
  const lines = body.split("\n").filter((l) => l.trim().startsWith("|"));
  if (lines.length < 3) return [];
  const headers = lines[0]
    .split("|")
    .map((c) => c.trim())
    .filter(Boolean);
  const rows: Record<string, string>[] = [];
  for (let i = 2; i < lines.length; i++) {
    const cells = lines[i]
      .split("|")
      .map((c) => c.trim())
      .filter(Boolean);
    const row: Record<string, string> = {};
    headers.forEach((h, idx) => {
      row[h] = cells[idx] || "";
    });
    rows.push(row);
  }
  return rows;
}

function inferToneFromLabel(label: string, value: string): SeverityTone {
  const lbl = label.toLowerCase();
  const val = value.toLowerCase();
  if (lbl.includes("异常") || lbl.includes("严重")) return "danger";
  if (lbl.includes("需关注") || lbl.includes("中等")) return "warning";
  if (lbl.includes("正常") || lbl.includes("轻微")) return "good";
  if (val === "0" && (lbl.includes("异常") || lbl.includes("严重"))) return "good";
  return "neutral";
}

function cleanEmoji(text: string): string {
  return text.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "").trim();
}

/* ------------------------------------------------------------------ */
/*  Builder                                                            */
/* ------------------------------------------------------------------ */

export function buildInspectionSummaryDisplayModel(
  content: string,
): InspectionSummaryDisplayModel | null {
  if (!looksLikeInspectionSummaryReport(content)) return null;

  const normalized = String(content || "").replace(/\r\n/g, "\n");

  // Extract report title
  const titleMatch = /(?:^|\n)#\s+(.+巡检报告.*)/m.exec(normalized);
  const reportTitle = titleMatch ? titleMatch[1].trim() : "巡检汇总报告";

  // Extract inspection time
  const timeMatch = /\*{0,2}巡检时间[：:]\s*\*{0,2}\s*(.+)/m.exec(normalized);
  const inspectionTime = timeMatch ? timeMatch[1].trim() : "";

  // Parse overview stats from 巡检总览 table
  const overviewStats: SummaryOverviewStat[] = [];
  const overviewSection = normalized.match(
    /##\s*.*巡检总览[\s\S]*?(?=\n---|\n##|$)/,
  );
  if (overviewSection) {
    const rows = extractTableRows(overviewSection[0]);
    for (const row of rows) {
      const label = row["项目"] || row["指标"] || Object.values(row)[0] || "";
      const value = row["值"] || row["数量"] || Object.values(row)[1] || "";
      if (label && value) {
        overviewStats.push({ label, value, tone: inferToneFromLabel(label, value) });
      }
    }
  }

  // Parse resource groups
  const resourceGroups: SummaryResourceGroup[] = [];
  const groupPatterns: { pattern: RegExp; tone: SeverityTone }[] = [
    { pattern: /##\s*.*异常资源[（(](\d+)个[)）]/m, tone: "danger" },
    { pattern: /##\s*.*需关注资源[（(](\d+)个[)）]/m, tone: "warning" },
    { pattern: /##\s*.*正常资源[（(](\d+)个[)）]/m, tone: "good" },
  ];

  for (const { pattern, tone } of groupPatterns) {
    const groupMatch = pattern.exec(normalized);
    if (!groupMatch) continue;
    const count = parseInt(groupMatch[1], 10);
    const groupTitleClean = cleanEmoji(groupMatch[0].replace(/^#+\s*/, ""));

    // Find the section body (until next ## or ---)
    const startIdx = groupMatch.index + groupMatch[0].length;
    const nextSection = normalized.slice(startIdx).search(/\n---\n|\n##\s/);
    const sectionBody =
      nextSection >= 0
        ? normalized.slice(startIdx, startIdx + nextSection)
        : normalized.slice(startIdx);

    // Parse individual resources (### numbered items)
    const h3Blocks = splitByHeadings(sectionBody, 3);
    const items: SummaryResourceItem[] = [];
    for (const block of h3Blocks) {
      const name = block.title.replace(/^\d+\.\s*/, "").replace(/[✅⚠️❌]/g, "").trim();
      const rows = extractTableRows(block.body);
      let resourceType = "";
      let ip = "";
      let verdict = "";
      const details: string[] = [];

      for (const row of rows) {
        const key = row["项目"] || Object.keys(row)[0] || "";
        const val = row["详情"] || row["值"] || Object.values(row)[1] || "";
        if (/资源类型/i.test(key)) resourceType = val;
        else if (/管理\s*IP|IP/i.test(key)) ip = val;
        else if (/判定|整体状态/i.test(key)) verdict = val.replace(/^[⚠️✅❌\s]+/, "");
        else if (/异常项|正常指标|异常指标/i.test(key)) details.push(`${key}: ${val}`);
      }

      items.push({ name, resourceType, ip, verdict, details });
    }

    resourceGroups.push({ title: groupTitleClean, tone, count, items });
  }

  // Parse conclusions
  const conclusionSections: SummaryConclusionSection[] = [];
  const conclusionMatch = /##\s*.*巡检结论([\s\S]*?)(?=\n##\s|$)/.exec(normalized);
  if (conclusionMatch) {
    const conclusionBody = conclusionMatch[1];
    const h3Blocks = splitByHeadings(conclusionBody, 3);
    for (const block of h3Blocks) {
      const title = cleanEmoji(block.title);
      let tone: SeverityTone = "neutral";
      if (/严重|立即/i.test(title)) tone = "danger";
      else if (/中等|尽快/i.test(title)) tone = "warning";
      else if (/轻微|建议关注/i.test(title)) tone = "good";

      const items: SummaryConclusionItem[] = [];
      const lines = block.body.split("\n");
      for (const line of lines) {
        const m = line.match(/^\d+\.\s*\*{0,2}(.+)/);
        if (m) {
          items.push({ text: m[1].replace(/\*{0,2}$/, "").trim() });
        }
      }
      if (items.length) {
        conclusionSections.push({ title, tone, items });
      }
    }
  }

  // Extract overall assessment
  const assessmentMatch = />\s*(.*?总体评估.*|.*整体评估.*|天翼智观平台\s*\*{0,2}.*)/s.exec(
    normalized,
  );
  let overallAssessment = "";
  if (assessmentMatch) {
    overallAssessment = assessmentMatch[0]
      .replace(/^>\s*/gm, "")
      .replace(/\*{1,2}/g, "")
      .trim();
  }

  // Extract topology code block
  let topology = "";
  const topoMatch = /```[\s\S]*?```/.exec(
    (normalized.match(/##\s*.*拓扑[\s\S]*?(?=\n---|\n##(?!#)|$)/) || [""])[0],
  );
  if (topoMatch) {
    topology = topoMatch[0].replace(/^```\w*\n?/, "").replace(/\n?```$/, "").trim();
  }

  return {
    reportTitle,
    inspectionTime,
    overviewStats,
    resourceGroups,
    conclusionSections,
    overallAssessment,
    topology,
    rawContent: content,
  };
}
