import { memo, useMemo, type ComponentPropsWithoutRef } from "react";

import { DeferredEChartsBlock } from "../../components/DeferredVisualizationBlocks";
import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import { buildInspectionDisplayModel } from "../../inspection-analyst/displayModel";
import {
  normalizeMarkdownDisplayContent,
  unwrapPortalInspectionCardContent,
} from "./helpers";

function InspectionReportTable(props: ComponentPropsWithoutRef<"table">) {
  const { className, ...rest } = props;

  return (
    <div className="inspection-analyst-raw-report-table-scroll">
      <table {...rest} className={className} />
    </div>
  );
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
      components={{ table: InspectionReportTable }}
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

  const metricGroups = display.metricGroups.length
    ? display.metricGroups
    : display.metrics.length
      ? [{ title: "", metrics: display.metrics }]
      : [];

  return (
    <div className="inspection-analyst-card-stack">
      <details className="inspection-analyst-raw-report inspection-analyst-raw-report-priority">
        <summary>
          <span>查看完整巡检报告</span>
          <small>展开当前完整回复</small>
        </summary>
        <div className="inspection-analyst-raw-report-body">
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

      {metricGroups.length
        ? metricGroups.map((group, index) => (
          <section
            key={group.title || `inspection-metric-group-${index}`}
            className="inspection-analyst-card"
          >
            <div className="inspection-analyst-section-header inspection-analyst-metric-group-header">
              <div>
                <div className="inspection-analyst-card-eyebrow">
                  {metricGroups.length > 1 ? "资源关键指标" : "关键指标"}
                </div>
                {group.title ? <h4>{group.title}</h4> : null}
              </div>
            </div>
            {group.summary && group.metrics.length ? (
              <p className="inspection-analyst-metric-group-summary">{group.summary}</p>
            ) : null}
            {group.metrics.length ? (
              <div className="inspection-analyst-metric-grid">
                {group.metrics.map((item) => (
                  <article
                    key={`${group.title || "metrics"}-${item.label}`}
                    className={`inspection-analyst-metric-card ${item.tone || "neutral"}`}
                  >
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                    {item.detail ? <p>{item.detail}</p> : null}
                  </article>
                ))}
              </div>
            ) : (
              <p className="inspection-analyst-metric-group-empty">
                {group.summary || "当前未返回可展示的实时指标数据"}
              </p>
            )}
          </section>
        ))
        : null}

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
