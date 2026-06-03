import { memo, useMemo, useState } from "react";

import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import {
  buildInspectionSummaryDisplayModel,
  type SummaryConclusionSection,
  type SummaryResourceGroup,
  type SummaryResourceItem,
} from "../../inspection-analyst/summaryDisplayModel";
import {
  normalizeMarkdownDisplayContent,
  unwrapPortalInspectionCardContent,
} from "./helpers";

/* ------------------------------------------------------------------ */
/*  Markdown helper (reuse existing theme logic)                       */
/* ------------------------------------------------------------------ */

function SummaryMarkdown({ content }: { content: string }) {
  const isDarkTheme =
    typeof document !== "undefined" &&
    document
      .querySelector(".portal-digital-employee")
      ?.classList.contains("theme-dark");
  const markdownThemeClass = isDarkTheme
    ? "x-markdown-dark"
    : "x-markdown-light";
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

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

const TONE_ICON: Record<string, string> = {
  danger: "🔴",
  warning: "🟡",
  good: "🟢",
  neutral: "⚪",
};

const TONE_LABEL: Record<string, string> = {
  danger: "异常",
  warning: "需关注",
  good: "正常",
  neutral: "",
};

function ResourceItemCard({ item }: { item: SummaryResourceItem }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="isummary-resource-item">
      <div
        className="isummary-resource-item-header"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="isummary-resource-item-name">
          <strong>{item.name}</strong>
          {item.resourceType && (
            <span className="isummary-resource-type">{item.resourceType}</span>
          )}
        </div>
        {item.ip && <span className="isummary-resource-ip">{item.ip}</span>}
        <i
          className={`fas fa-chevron-${expanded ? "up" : "down"} isummary-chevron`}
        />
      </div>
      {expanded && (
        <div className="isummary-resource-item-body">
          {item.verdict && (
            <p className="isummary-resource-verdict">{item.verdict}</p>
          )}
          {item.details.length > 0 && (
            <ul className="isummary-resource-details">
              {item.details.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function ResourceGroupCard({ group }: { group: SummaryResourceGroup }) {
  return (
    <div className={`isummary-resource-group tone-${group.tone}`}>
      <div className="isummary-resource-group-header">
        <span className="isummary-resource-group-icon">
          {TONE_ICON[group.tone] || "⚪"}
        </span>
        <h4>{group.title}</h4>
        <span className="isummary-resource-group-count">{group.count}个</span>
      </div>
      <div className="isummary-resource-group-items">
        {group.items.map((item) => (
          <ResourceItemCard key={item.name} item={item} />
        ))}
      </div>
    </div>
  );
}

function ConclusionCard({ section }: { section: SummaryConclusionSection }) {
  return (
    <div className={`isummary-conclusion-section tone-${section.tone}`}>
      <h4>
        <span className="isummary-conclusion-icon">
          {TONE_ICON[section.tone] || "⚪"}
        </span>
        {section.title}
      </h4>
      <ol className="isummary-conclusion-list">
        {section.items.map((item, i) => (
          <li key={i}>{item.text}</li>
        ))}
      </ol>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export const InspectionSummaryCardPanel = memo(
  function InspectionSummaryCardPanel({ content }: { content: string }) {
    const display = useMemo(
      () => buildInspectionSummaryDisplayModel(content),
      [content],
    );

    if (!display) return null;

    // Calculate totals from overview stats
    const dangerCount =
      display.overviewStats.find((s) => s.label === "异常")?.value || "0";
    const warningCount =
      display.overviewStats.find((s) => s.label === "需关注")?.value || "0";
    const goodCount =
      display.overviewStats.find((s) => s.label === "正常")?.value || "0";
    const totalResources =
      display.overviewStats.find((s) => s.label.includes("资源数"))?.value ||
      "?";

    return (
      <div className="isummary-card-stack">
        {/* Raw report toggle */}
        <details className="inspection-analyst-raw-report inspection-analyst-raw-report-priority">
          <summary>
            <span>查看完整巡检报告</span>
            <small>展开当前完整回复</small>
          </summary>
          <div className="inspection-analyst-raw-report-body">
            <SummaryMarkdown content={content} />
          </div>
        </details>

        {/* Header card */}
        <section className="isummary-card isummary-header-card">
          <div className="isummary-header-top">
            <div>
              <div className="isummary-eyebrow">系统巡检汇总</div>
              <h3 className="isummary-title">{display.reportTitle}</h3>
              {display.inspectionTime && (
                <span className="isummary-time">
                  <i className="fas fa-clock" /> {display.inspectionTime}
                </span>
              )}
            </div>
          </div>

          {/* Stats dashboard */}
          <div className="isummary-stats-ring">
            <div className="isummary-stat-total">
              <strong>{totalResources}</strong>
              <span>资源总数</span>
            </div>
            <div className="isummary-stat-pills">
              <span className="isummary-pill danger">
                <i className="fas fa-times-circle" /> 异常 {dangerCount}
              </span>
              <span className="isummary-pill warning">
                <i className="fas fa-exclamation-triangle" /> 关注 {warningCount}
              </span>
              <span className="isummary-pill good">
                <i className="fas fa-check-circle" /> 正常 {goodCount}
              </span>
            </div>
          </div>

          {/* Overview stats table */}
          {display.overviewStats.length > 0 && (
            <div className="isummary-overview-grid">
              {display.overviewStats
                .filter(
                  (s) =>
                    !["异常", "需关注", "正常"].includes(s.label) &&
                    !s.label.includes("资源数"),
                )
                .map((stat) => (
                  <div key={stat.label} className="isummary-overview-item">
                    <span className="isummary-overview-label">{stat.label}</span>
                    <span className="isummary-overview-value">{stat.value}</span>
                  </div>
                ))}
            </div>
          )}
        </section>

        {/* Resource groups */}
        {display.resourceGroups.length > 0 && (
          <section className="isummary-card isummary-resources-card">
            <div className="isummary-section-header">
              <div className="isummary-eyebrow">资源巡检明细</div>
            </div>
            {display.resourceGroups.map((group) => (
              <ResourceGroupCard key={group.title} group={group} />
            ))}
          </section>
        )}

        {/* Conclusions */}
        {display.conclusionSections.length > 0 && (
          <section className="isummary-card isummary-conclusion-card">
            <div className="isummary-section-header">
              <div className="isummary-eyebrow">巡检结论</div>
            </div>
            {display.conclusionSections.map((section) => (
              <ConclusionCard key={section.title} section={section} />
            ))}
          </section>
        )}

        {/* Overall assessment */}
        {display.overallAssessment && (
          <section className="isummary-card isummary-assessment-card">
            <div className="isummary-section-header">
              <div className="isummary-eyebrow">总体评估</div>
            </div>
            <blockquote className="isummary-assessment">
              {display.overallAssessment}
            </blockquote>
          </section>
        )}

        {/* Topology */}
        {display.topology && (
          <section className="isummary-card isummary-topology-card">
            <div className="isummary-section-header">
              <div className="isummary-eyebrow">CMDB 拓扑关系</div>
            </div>
            <pre className="isummary-topology-pre">
              <code>{display.topology}</code>
            </pre>
          </section>
        )}
      </div>
    );
  },
);

export default InspectionSummaryCardPanel;
