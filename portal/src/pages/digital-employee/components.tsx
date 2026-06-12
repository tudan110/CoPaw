import { memo, Suspense, useEffect, useRef, useState, type ComponentProps } from "react";
import { employeeStepDescriptions } from "../../data/portalData";
import { DeferredEChartsBlock } from "../../components/DeferredVisualizationBlocks";
import { PortalVisualizationBlock } from "../../components/PortalVisualizationBlock";
import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import {
  getPortalOrderDetailMarkdownContent,
  hasPortalOrderDetailPayloadContent,
  parsePortalOrderDetailPayload,
  PortalOrderDetailReport,
} from "../../components/PortalOrderDetailReport";
import {
  createKnowledgeManualEntry,
  type KnowledgeEvidence,
  type KnowledgeQueryResponse,
} from "../../api/knowledgeBase";
import { lazyNamed } from "../../utils/lazyNamed";
import {
  extractVisualBlocks,
  extractRenderableContentSegments,
  extractPortalActionPayload,
  getSeverityClassName,
  normalizeMarkdownDisplayContent,
  unwrapPortalAlarmAnalystCardContent,
  PORTAL_INSPECTION_CARD_MARKER,
  unwrapPortalInspectionCardContent,
} from "./helpers";
import { looksLikeInspectionSummaryReport } from "../../inspection-analyst/summaryDisplayModel";
import {
  CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_CHANGED_EVENT,
  readConversationProcessRecordDisplayMode,
} from "./conversationSettings";
import { FaultScenarioResultCard } from "./faultScenarioComponents";

const ResourceImportConversationCard = lazyNamed(
  () => import("./resourceImportConversationCard"),
  "ResourceImportConversationCard",
);
const KnowledgeBaseConversationCard = lazyNamed(
  () => import("./knowledgeBaseConversationCard"),
  "KnowledgeBaseConversationCard",
);
const AlarmAnalystCardPanel = lazyNamed(
  () => import("./alarmAnalystCardComponents"),
  "AlarmAnalystCardPanel",
);
const InspectionAnalystCardPanel = lazyNamed(
  () => import("./inspectionAnalystCardComponents"),
  "InspectionAnalystCardPanel",
);
const InspectionSummaryCardPanel = lazyNamed(
  () => import("./inspectionSummaryCardComponents"),
  "InspectionSummaryCardPanel",
);

const deferredMessageCardFallback = (
  <div className="history-empty" style={{ minHeight: 180 }}>
    <i className="fas fa-spinner fa-spin" />
    <p>正在加载内容...</p>
  </div>
);

function looksLikeInspectionReportCardContent(content: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  return (
    (
      normalized.includes(PORTAL_INSPECTION_CARD_MARKER)
      || /(?:^|\n)##+\s*.*巡检结果/um.test(normalized)
    )
    && /(?:^|\n)##+\s*.*基本信息/um.test(normalized)
    && /(?:^|\n)##+\s*.*指标数据/um.test(normalized)
  );
}

function looksLikeInspectionHealthAssessmentCardContent(content: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  return (
    /(?:^|\n)##+\s*.*健康状态评估/um.test(normalized)
    && /总体评分/u.test(normalized)
    && /(健康项|亚健康项|病理项|建议优先级)/u.test(normalized)
  );
}

function shouldRenderInspectionAnalystCard(content: string) {
  return (
    looksLikeInspectionReportCardContent(content)
    || looksLikeInspectionHealthAssessmentCardContent(content)
  );
}

export function AlarmWorkorderBoard({
  workorders,
  loading,
  error,
  notice,
  onRefresh,
  onAction,
  inline = false,
}: any) {
  return (
    <div className={inline ? "alarm-workorder-board inline" : "alarm-workorder-board"}>
      <div className="alarm-workorder-toolbar">
        <div className="alarm-workorder-toolbar-text">
          <h3>以下是需要处置的告警工单</h3>
          <p>告警已触发故障分析专家，当前先展示待处置工单，后续可在此接入不同类型故障的处置流程。</p>
        </div>
        <button className="alarm-workorder-refresh" onClick={onRefresh} disabled={loading}>
          <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-rotate-right"}`} />
          刷新
        </button>
      </div>

      {notice ? <div className="alarm-workorder-notice">{notice}</div> : null}

      {loading ? (
        <div className="alarm-workorder-empty">
          <i className="fas fa-spinner fa-spin" />
          <p>正在查询 real-alarm 告警数据...</p>
        </div>
      ) : error ? (
        <div className="alarm-workorder-empty error">
          <i className="fas fa-triangle-exclamation" />
          <p>{error}</p>
        </div>
      ) : workorders.length ? (
        <div className="alarm-workorder-list">
          {workorders.map((workorder: any) => (
            <AlarmWorkorderCard
              key={workorder.id}
              onAction={onAction}
              workorder={workorder}
            />
          ))}
        </div>
      ) : (
        <div className="alarm-workorder-empty">
          <i className="fas fa-inbox" />
          <p>当前没有查询到待处置告警工单。</p>
        </div>
      )}
    </div>
  );
}

function AlarmWorkorderCard({ workorder, onAction }: any) {
  const severityClass = getSeverityClassName(workorder.severityLevel);
  const actionButtons = ["去处置", "转派", "升级", "回单"];

  return (
    <div className={`alarm-workorder-card ${severityClass}`}>
      <div className="alarm-workorder-card-header">
        <div className="alarm-workorder-title-group">
          <span className={`alarm-workorder-severity-dot ${severityClass}`} />
          <div>
            <h4>{`${workorder.severity} | ${workorder.title}`}</h4>
            <p>故障分析专家（告警驱动工单）</p>
          </div>
        </div>
        <span className="alarm-workorder-status">{workorder.status}</span>
      </div>

      <div className="alarm-workorder-meta-grid">
        <div>
          <span>工单号</span>
          <strong>{workorder.workorderNo}</strong>
        </div>
        <div>
          <span>创建时间</span>
          <strong>{workorder.eventTime}</strong>
        </div>
        <div>
          <span>设备 IP</span>
          <strong>{workorder.manageIp}</strong>
        </div>
        <div>
          <span>设备名称</span>
          <strong>{workorder.deviceName}</strong>
        </div>
      </div>

      <div className="alarm-workorder-description">
        <div className="alarm-workorder-description-label">故障描述</div>
        <p>{workorder.description}</p>
      </div>

      <div className="alarm-workorder-tags">
        <span>{workorder.severity}</span>
        <span>{workorder.status}</span>
        <span>{`定位对象：${workorder.locateName}`}</span>
        <span>{`专业：${workorder.speciality}`}</span>
        <span>{`区域：${workorder.region}`}</span>
        <span>{`告警次数：${workorder.actionCount}`}</span>
      </div>

      <div className="alarm-workorder-actions">
        {actionButtons.map((label, index) => (
          <button
            key={label}
            className={index === 0 ? "alarm-workorder-action primary" : "alarm-workorder-action"}
            onClick={() => onAction(label, workorder)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

const COPAW_API_BASE_URL = (
  (import.meta as any).env?.VITE_COPAW_API_BASE_URL || "/copaw-api/api"
).replace(/\/$/, "");

/**
 * Skill 作者通常写绝对路径 `/api/files/preview/...`（qwenpaw 后端视角）。
 * 经 nginx 时 Portal 这边的实际入口是 `/copaw-api/api/...`，这里统一兜底。
 * 已经是 http(s):// 或带 portal/copaw 前缀的链接保持原样。
 */
function resolveActionDownloadUrl(rawUrl: unknown): string {
  const url = String(rawUrl || "").trim();
  if (!url) {
    return "";
  }
  if (/^(?:https?:)?\/\//i.test(url)) {
    return url;
  }
  if (url.startsWith("/copaw-api/") || url.startsWith("/portal-api/")) {
    return url;
  }
  if (url.startsWith("/api/")) {
    return `${COPAW_API_BASE_URL}${url.slice(4)}`;
  }
  return url;
}

function isDownloadAction(action: any): boolean {
  const t = String(action?.type || "").toLowerCase();
  return t === "export.download" || t.startsWith("download.") || t === "download";
}

function isKillSlowSqlAction(action: any): boolean {
  const t = String(action?.type || "").toLowerCase();
  if (t === "kill-slow-sql" || t === "kill_slow_sql") {
    return true;
  }
  // Legacy / inferred actions: 无 type 但带慢 SQL 处置专属字段。
  return !t && Boolean(action?.sqlId || action?.sessionId);
}

function formatActionFileSize(bytes: unknown): string {
  const n = typeof bytes === "number" ? bytes : Number(bytes);
  if (!Number.isFinite(n) || n <= 0) {
    return "";
  }
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function DownloadActionCard({ action }: { action: any }) {
  const resolvedUrl = resolveActionDownloadUrl(action?.downloadUrl || action?.url);
  const fileName =
    String(action?.fileName || action?.filename || "").trim() ||
    (resolvedUrl ? resolvedUrl.split("/").pop() || "" : "");
  const recordCount = Number(action?.recordCount);
  const sizeText = formatActionFileSize(action?.fileSize ?? action?.size);
  const formatText = String(action?.exportFormat || action?.format || "").trim();
  const statusText =
    action?.status === "success"
      ? "已下载"
      : action?.status === "running"
      ? "下载中"
      : "待下载";
  const disabled = !resolvedUrl;
  return (
    <div className="disposal-operation-card download-action-card">
      <div className="disposal-operation-header">
        <div>
          <h4>{action?.title || "下载导出文件"}</h4>
          {action?.summary ? <p>{action.summary}</p> : null}
        </div>
        <span className={`disposal-operation-status ${action?.status || "ready"}`}>
          {statusText}
        </span>
      </div>
      <div className="disposal-operation-meta">
        {fileName ? (
          <div>
            <span>文件名</span>
            <strong>{fileName}</strong>
          </div>
        ) : null}
        {Number.isFinite(recordCount) && recordCount > 0 ? (
          <div>
            <span>记录数</span>
            <strong>{recordCount.toLocaleString("zh-CN")}</strong>
          </div>
        ) : null}
        {formatText ? (
          <div>
            <span>格式</span>
            <strong>{formatText.toUpperCase()}</strong>
          </div>
        ) : null}
        {sizeText ? (
          <div>
            <span>大小</span>
            <strong>{sizeText}</strong>
          </div>
        ) : null}
      </div>
      <div className="disposal-operation-actions">
        <a
          className="alarm-workorder-action primary"
          href={resolvedUrl || "#"}
          download={fileName || true}
          target="_blank"
          rel="noopener noreferrer"
          aria-disabled={disabled}
          onClick={(event) => {
            if (disabled) {
              event.preventDefault();
            }
          }}
        >
          <i className="fas fa-download" />{" "}
          {disabled ? "下载链接缺失" : "下载文件"}
        </a>
      </div>
    </div>
  );
}

function GenericActionCard({ action }: { action: any }) {
  const title = String(action?.title || "").trim();
  const summary = String(action?.summary || "").trim();
  if (!title && !summary) {
    return null;
  }
  return (
    <div className="disposal-operation-card generic-action-card">
      <div className="disposal-operation-header">
        <div>
          <h4>{title || action?.type || "Portal 动作"}</h4>
          {summary ? <p>{summary}</p> : null}
        </div>
        <span className="disposal-operation-status ready">
          {action?.type ? String(action.type) : "未知动作"}
        </span>
      </div>
    </div>
  );
}

export function DisposalOperationCard({ action, onExecute }: any) {
  if (!action) {
    return null;
  }

  if (isDownloadAction(action)) {
    return <DownloadActionCard action={action} />;
  }

  if (!isKillSlowSqlAction(action)) {
    // 未知 type：兜底渲染，避免被当成"杀掉慢SQL"误显示
    return <GenericActionCard action={action} />;
  }

  const statusText =
    action.status === "success"
      ? "已执行"
      : action.status === "running"
      ? "执行中"
      : "待确认";

  return (
    <div className="disposal-operation-card">
      <div className="disposal-operation-header">
        <div>
          <h4>{action.title}</h4>
          <p>{action.summary}</p>
        </div>
        <span className={`disposal-operation-status ${action.status || "ready"}`}>
          {statusText}
        </span>
      </div>
      <div className="disposal-operation-meta">
        <div>
          <span>根因工单</span>
          <strong>{action.rootCauseWorkorderNo}</strong>
        </div>
        <div>
          <span>SQL_ID</span>
          <strong>{action.sqlId}</strong>
        </div>
        <div>
          <span>会话ID</span>
          <strong>{action.sessionId}</strong>
        </div>
        <div>
          <span>实例</span>
          <strong>{action.locateName}</strong>
        </div>
        <div>
          <span>处置对象</span>
          <strong>{action.targetSummary || "数据库核心业务慢 SQL 会话"}</strong>
        </div>
      </div>
      <div className="disposal-operation-actions">
        <button
          className="alarm-workorder-action primary"
          disabled={action.status === "running" || action.status === "success"}
          onClick={onExecute}
        >
          <i
            className={`fas ${
              action.status === "running" ? "fa-spinner fa-spin" : "fa-bolt"
            }`}
          />{" "}
          {action.status === "success" ? "慢SQL已终止" : "杀掉慢SQL"}
        </button>
      </div>
    </div>
  );
}

type KnowledgeAnswerPayload = {
  query?: string;
  result?: KnowledgeQueryResponse;
  answer?: string;
  synthesis?: Record<string, any>;
};

function normalizeKnowledgeText(value?: string | null) {
  return String(value || "")
    .replace(/\\\|/g, "|")
    .replace(/\s+/g, " ")
    .trim();
}

function clipKnowledgeText(value?: string | null, maxLength = 160) {
  const text = normalizeKnowledgeText(value);
  if (text.length <= maxLength) {
    return text || "-";
  }
  return `${text.slice(0, maxLength - 1)}…`;
}

function formatKnowledgeConfidence(value?: number | string | null) {
  if (typeof value === "number") {
    return `${Math.round(value * 100)}%`;
  }
  const text = normalizeKnowledgeText(String(value || ""));
  return text || "-";
}

function extractKnowledgeSection(content: string, title: string) {
  const pattern = new RegExp(`####\\s*${title}\\s*\\n([\\s\\S]*?)(?=\\n####\\s|$)`, "u");
  return normalizeKnowledgeText(pattern.exec(content)?.[1] || "");
}

function parseKnowledgeAnswerContent(content: string): KnowledgeAnswerPayload | null {
  if (!/知识库检索|命中证据|结论摘要/u.test(content || "")) {
    return null;
  }

  const query = normalizeKnowledgeText(
    /\*\*问题[:：]\*\*\s*([^\n]+)/u.exec(content)?.[1]
    || /问题[:：]\s*([^\n]+)/u.exec(content)?.[1]
    || "",
  );
  const summary = extractKnowledgeSection(content, "结论摘要");
  const boundary = extractKnowledgeSection(content, "证据边界");
  const relevant_evidence = String(content || "")
    .split(/\n/u)
    .map((line) => line.trim())
    .filter((line) => /^\d+\s*\|/u.test(line))
    .map((line, index): KnowledgeEvidence => {
      const cells = line.split(/\s+\|\s+/u);
      return {
        evidence_id: `parsed-${index + 1}`,
        chunk_summary: normalizeKnowledgeText(cells[1] || `证据 ${index + 1}`),
        chunk_text: normalizeKnowledgeText(cells.slice(4).join(" | ")),
        confidence_level: normalizeKnowledgeText(cells[3] || ""),
        citation: {
          source_label: normalizeKnowledgeText(cells[1] || ""),
          locator: normalizeKnowledgeText(cells[2] || ""),
        },
      };
    });

  return {
    query,
    result: {
      summary,
      relevant_evidence,
      evidence_boundary_statement: boundary,
    },
  };
}

function KnowledgeAnswerReport({
  content,
  payload,
  onUploadRequest,
  onManagementOpen,
  defaultModelLabel,
}: {
  content: string;
  payload?: KnowledgeAnswerPayload | null;
  onUploadRequest?: () => void;
  onManagementOpen?: () => void;
  defaultModelLabel?: string;
}) {
  const parsedPayload = payload?.result ? payload : parseKnowledgeAnswerContent(content);
  const result = parsedPayload?.result;
  const evidence = result?.relevant_evidence || [];
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  if (!result) {
    return <MessageMarkdown content={content} />;
  }

  const retrievalSummary = result.summary || result.evidence_boundary_statement || "当前没有在知识库中找到足够相关的资料。";
  const synthesis = parsedPayload?.synthesis || payload?.synthesis || {};
  const aiAnswer = String(parsedPayload?.answer || payload?.answer || synthesis.answer || "").trim();
  const synthesisError = String(synthesis.error || "").trim();
  const synthesisSkipped = Boolean(synthesis.skipped);
  // Prefer the bare model name (e.g. "GLM-5.1") over model_label (which the
  // backend formats as "<provider> / <model>", e.g. "天翼云 / GLM-5.1").
  // Fall back to the page-level active model label so the "使用 …" hint is
  // populated immediately during the loading state, before synthesis returns.
  const synthesisModelLabel = String(
    synthesis.model_name
      || synthesis.model
      || synthesis.model_label
      || "",
  ).trim();
  const modelLabel = synthesisModelLabel || (defaultModelLabel || "").trim();
  const query = parsedPayload?.query || "";

  const handleSaveAnswer = async () => {
    const contentToSave = aiAnswer || retrievalSummary;
    if (!contentToSave || saveState === "saving") {
      return;
    }
    setSaveState("saving");
    try {
      await createKnowledgeManualEntry({
        title: `AI总结：${query || "知识库问答"}`.slice(0, 120),
        content: contentToSave,
        tags: ["AI总结", "运行时沉淀"],
      });
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  return (
    <div className="knowledge-answer-report">
      <header className="knowledge-answer-header">
        <div>
          <span className="knowledge-answer-kicker">知识库检索</span>
          <h3>{query || "检索结果"}</h3>
        </div>
        <span className={result.flags?.insufficient_evidence ? "knowledge-answer-badge warning" : "knowledge-answer-badge"}>
          {result.flags?.insufficient_evidence ? "证据不足" : `${evidence.length} 条证据`}
        </span>
      </header>

      <section className="knowledge-answer-section">
        <h4>检索结论</h4>
        <p>{retrievalSummary}</p>
      </section>

      {evidence.length ? (
        <section className="knowledge-answer-section">
          <h4>命中证据</h4>
          <div className="knowledge-evidence-table" role="table" aria-label="知识库命中证据">
            <div className="knowledge-evidence-row head" role="row">
              <span role="columnheader">来源</span>
              <span role="columnheader">位置</span>
              <span role="columnheader">置信度</span>
              <span role="columnheader">命中片段</span>
            </div>
            {evidence.slice(0, 8).map((item, index) => (
              <div key={item.evidence_id || `${item.citation?.source_label || "evidence"}-${index}`} className="knowledge-evidence-row" role="row">
                <span role="cell">
                  <strong>{clipKnowledgeText(item.citation?.source_label || item.chunk_summary || item.evidence_id, 72)}</strong>
                  {item.citation?.source_scope_label ? <small>{item.citation.source_scope_label}</small> : null}
                </span>
                <span role="cell">{clipKnowledgeText(item.citation?.locator || item.source_type || "-", 72)}</span>
                <span role="cell">
                  <mark>{formatKnowledgeConfidence(item.confidence_score ?? item.confidence_level)}</mark>
                </span>
                <span role="cell">{clipKnowledgeText(item.chunk_text || item.chunk_summary, 220)}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {result.evidence_boundary_statement ? (
        <aside className="knowledge-answer-boundary">
          <strong>证据边界</strong>
          <span>{result.evidence_boundary_statement}</span>
        </aside>
      ) : null}

      {!synthesisSkipped ? (
        <section className="knowledge-answer-ai">
          <div className="knowledge-answer-ai-title">
            <span>
              <i className="fas fa-magic" />
              AI 总结
            </span>
            <small>{modelLabel ? `使用 ${modelLabel}` : "使用当前模型"}</small>
          </div>
          {aiAnswer ? (
            <MessageMarkdown content={aiAnswer} />
          ) : synthesisError ? (
            <p className="knowledge-answer-ai-error">{synthesisError}</p>
          ) : (
            <p className="knowledge-answer-ai-loading">
              <i className="fas fa-spinner fa-spin" />
              正在生成总结...
            </p>
          )}
          <div className="knowledge-answer-actions">
            <button type="button" onClick={() => void handleSaveAnswer()} disabled={saveState === "saving" || !aiAnswer}>
              <i className={`fas ${saveState === "saved" ? "fa-check" : saveState === "saving" ? "fa-spinner fa-spin" : "fa-cloud-arrow-up"}`} />
              {saveState === "saved" ? "已上传知识库" : saveState === "saving" ? "上传中" : "将回答上传知识库"}
            </button>
            <button type="button" className="secondary" onClick={onUploadRequest}>
              <i className="fas fa-file-arrow-up" />
              不满意，手动上传文档
            </button>
            {saveState === "saved" && onManagementOpen ? (
              <button type="button" className="secondary" onClick={onManagementOpen}>
                <i className="fas fa-table-list" />
                去知识库管理查看
              </button>
            ) : null}
          </div>
          {saveState === "error" ? <p className="knowledge-answer-action-error">上传失败，请稍后重试。</p> : null}
        </section>
      ) : null}
    </div>
  );
}

export const ChatMessageItem = memo(function ChatMessageItem({
  agentId,
  currentEmployee,
  isStreamingMessage,
  message,
  onDisposalAction,
  onResourceImportBackToConfirm,
  onResourceImportBuildTopology,
  onResourceImportConfirmStructure,
  onResourceImportContinue,
  onResourceImportOpenSystemTopology,
  onResourceImportParseFailed,
  onResourceImportParseResolved,
  onResourceImportReturnToUpload,
  onResourceImportStartParse,
  onResourceImportScrollToStage,
  onResourceImportSubmitImport,
  onResourceImportUploadFiles,
  onResourceImportGuideOpen,
  onKnowledgeBaseFlowUpdate,
  onKnowledgeBaseUploadRequest,
  onKnowledgeBaseManagementOpen,
  releaseResourceImportFiles,
  resolveResourceImportFiles,
  pageTheme,
  onTicketAction,
  onTicketRefresh,
  ticketActionNotice,
  activeModelLabel,
}: any) {
  const allBlocks = message.processBlocks || [];
  const condensedBlocks = condenseBackgroundPollingBlocks(allBlocks);
  const hasInterleavedResponses = allBlocks.some(
    (block: any) => block?.kind === "response" && block.content,
  );
  const liveMessageContent = String(message.content || "");
  const normalizedLiveMessageContent = liveMessageContent.trim();

  // Interleaved mode: response blocks exist in processBlocks (loaded history)
  // Legacy mode: no response blocks, text lives in message.content (streaming)
  const displayBlocks = hasInterleavedResponses
    ? condensedBlocks
    : condensedBlocks.filter((block: any) => block?.kind !== "response");
  const hasWorkorders =
    Boolean(message.workorders?.length) ||
    Boolean(message.workordersLoading) ||
    Boolean(message.workordersError);
  const hasResourceImportFlow = Boolean(message.resourceImportFlow);
  const hasKnowledgeBaseFlow = Boolean(message.knowledgeBaseFlow);
  const hasKnowledgeAnswer = Boolean(message.knowledgeAnswer);
  const alarmAnalystCard = message.type === "agent" ? message.alarmAnalystCard : null;
  const hasAlarmAnalystCard = Boolean(alarmAnalystCard);
  const faultScenarioResult = message.faultScenarioResult;
  const primaryResponseBlock =
    [...displayBlocks].reverse().find((block: any) => block?.kind === "response" && block.content) || null;
  const auxiliaryTraceBlocks = displayBlocks.filter(
    (block: any) => !(primaryResponseBlock && block?.kind === "response" && block.id === primaryResponseBlock.id),
  );
  const trailingResponseContent = [...displayBlocks].reverse().find(
    (block: any) => block?.kind === "response" && block.id !== primaryResponseBlock?.id && block.content,
  )?.content || "";
  const liveContentDuplicatesTrace = Boolean(normalizedLiveMessageContent) && auxiliaryTraceBlocks.some(
    (block: any) => {
      const normalizedBlockContent = String(block?.content || "").trim();
      return normalizedBlockContent && (
        normalizedBlockContent === normalizedLiveMessageContent
        || normalizedBlockContent.endsWith(normalizedLiveMessageContent)
        || normalizedLiveMessageContent.endsWith(normalizedBlockContent)
      );
    },
  );
  const renderedMessageContent = primaryResponseBlock
    ? (
        isStreamingMessage
          ? (liveMessageContent || primaryResponseBlock.content || "")
          : String(primaryResponseBlock.content || liveMessageContent || "")
      )
    : (
        liveContentDuplicatesTrace
          ? trailingResponseContent
          : (liveMessageContent || trailingResponseContent)
      );
  const shouldShowResourceImportGuide = Boolean(
    message.resourceImportGuide
    && message.type === "agent"
    && !isStreamingMessage
    && !hasResourceImportFlow
    && renderedMessageContent
    && onResourceImportGuideOpen,
  );
  const effectiveDisposalOperation =
    message.disposalOperation ||
    extractPortalActionPayload(renderedMessageContent || message.content || "");
  const shouldShowDisposalOperation =
    Boolean(effectiveDisposalOperation) &&
    effectiveDisposalOperation.status !== "success" &&
    !message.hideDisposalOperation;
  const isInspectionAnalystCardCandidate =
    message.type === "agent"
    && (
      currentEmployee?.id === "inspection"
      || currentEmployee?.id === "gateway"
      || currentEmployee?.id === "portal-home"
    )
    && !isStreamingMessage
    && shouldRenderInspectionAnalystCard(renderedMessageContent);
  const isInspectionSummaryCardCandidate =
    message.type === "agent"
    && (
      currentEmployee?.id === "inspection"
      || currentEmployee?.id === "gateway"
      || currentEmployee?.id === "portal-home"
    )
    && !isStreamingMessage
    && !isInspectionAnalystCardCandidate
    && looksLikeInspectionSummaryReport(renderedMessageContent);
  const orderDetailPayload = !isStreamingMessage
    ? parsePortalOrderDetailPayload(renderedMessageContent, allBlocks)
    : null;
  const orderDetailMarkdown = orderDetailPayload
    ? getPortalOrderDetailMarkdownContent(renderedMessageContent, allBlocks)
    : "";
  const shouldRenderOrderDetailCard = orderDetailPayload
    ? hasPortalOrderDetailPayloadContent(orderDetailPayload)
    : false;
  const copyableContent = String(
    renderedMessageContent || alarmAnalystCard?.rawReportMarkdown || "",
  ).trim();
  const traceBundleSubtitle = buildTraceBundleSubtitle(auxiliaryTraceBlocks);
  const showTraceBundleStreamingIndicator = isStreamingMessage && auxiliaryTraceBlocks.length > 0;
  // 是否处于"思考阶段"：正在流式产出、有过程块、但最终答案尚未开始渲染。
  // 用于让过程记录在思考时自动展开（像主流模型那样实时显示思考），
  // 一旦答案开始就自动收起，保持答案区清爽。
  const hasAnswerStarted = Boolean(String(renderedMessageContent || "").trim());
  const isTraceThinkingPhase =
    isStreamingMessage && auxiliaryTraceBlocks.length > 0 && !hasAnswerStarted;
  const [traceBundleDisplayMode, setTraceBundleDisplayMode] = useState(() =>
    readConversationProcessRecordDisplayMode(),
  );
  const traceBundleDefaultOpen = traceBundleDisplayMode === "expanded";
  const [isTraceBundleOpen, setIsTraceBundleOpen] = useState(() => traceBundleDefaultOpen);
  const hasManualTraceBundleToggleRef = useRef(false);
  const pendingManualTraceBundleToggleRef = useRef(false);

  useEffect(() => {
    const handleProcessRecordDisplayModeChanged = () => {
      setTraceBundleDisplayMode(readConversationProcessRecordDisplayMode());
    };

    window.addEventListener(
      CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_CHANGED_EVENT,
      handleProcessRecordDisplayModeChanged,
    );
    return () => {
      window.removeEventListener(
        CONVERSATION_PROCESS_RECORD_DISPLAY_MODE_CHANGED_EVENT,
        handleProcessRecordDisplayModeChanged,
      );
    };
  }, []);

  useEffect(() => {
    if (!auxiliaryTraceBlocks.length) {
      hasManualTraceBundleToggleRef.current = false;
      pendingManualTraceBundleToggleRef.current = false;
      setIsTraceBundleOpen(false);
      return;
    }

    if (hasManualTraceBundleToggleRef.current) {
      return;
    }

    // 思考阶段自动展开，让用户看到实时思考过程，避免"无响应"既视感；
    // 答案一旦开始渲染则收起到默认（通常折叠），保持答案区清爽。
    if (isTraceThinkingPhase) {
      setIsTraceBundleOpen(true);
    } else {
      setIsTraceBundleOpen(traceBundleDefaultOpen);
    }
  }, [auxiliaryTraceBlocks.length, traceBundleDefaultOpen, isTraceThinkingPhase]);
  return (
    <div
      id={`message-${message.id}`}
      className={message.type === "user" ? "message user" : "message agent"}
    >
      <div
        className="message-avatar"
        style={message.type === "agent" ? { background: message.gradient } : {}}
      >
        <i className={`fas ${message.type === "user" ? "fa-user" : message.icon}`} />
      </div>
        <div className="message-content">
          {auxiliaryTraceBlocks.length ? (
          <details
            className="trace-block trace-bundle"
            open={isTraceBundleOpen}
            onToggle={(event) => {
              if (pendingManualTraceBundleToggleRef.current) {
                hasManualTraceBundleToggleRef.current = true;
                pendingManualTraceBundleToggleRef.current = false;
              }
              setIsTraceBundleOpen(event.currentTarget.open);
            }}
          >
            <summary
              className="trace-summary"
              onClick={() => {
                pendingManualTraceBundleToggleRef.current = true;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  pendingManualTraceBundleToggleRef.current = true;
                }
              }}
            >
              <span className="trace-label">
                <i className={`fas ${isTraceThinkingPhase ? "fa-brain" : "fa-layer-group"}`} />
                {isTraceThinkingPhase ? "正在思考…" : "过程记录"}
              </span>
              {showTraceBundleStreamingIndicator || traceBundleSubtitle ? (
                <span className="trace-summary-meta">
                  {showTraceBundleStreamingIndicator ? (
                    <span className="trace-status-indicator" aria-label="过程记录生成中">
                      <i className="fas fa-spinner fa-spin" aria-hidden="true" />
                      <span>生成中</span>
                    </span>
                  ) : null}
                  {traceBundleSubtitle ? (
                    <span className="trace-subtitle">{traceBundleSubtitle}</span>
                  ) : null}
                </span>
              ) : null}
            </summary>
            <div className="trace-body trace-bundle-body">
              {auxiliaryTraceBlocks.map((block: any, index: number) => (
                <TraceEntry
                  key={block.id || `${block.kind}-${index}`}
                  block={block}
                  defaultOpen={traceBundleDefaultOpen}
                  isStreaming={isStreamingMessage}
                  open={
                    isTraceThinkingPhase
                      ? index === auxiliaryTraceBlocks.length - 1
                      : undefined
                  }
                />
              ))}
            </div>
          </details>
        ) : null}

        {hasWorkorders ? (
          <div className="message-bubble markdown-bubble workorder-bubble">
            {message.content ? (
              <div className="workorder-intro">
                <MessageMarkdown content={message.content} />
              </div>
            ) : null}
            <AlarmWorkorderBoard
              error={message.workordersError}
              inline
              loading={message.workordersLoading}
              notice={ticketActionNotice}
              onAction={onTicketAction}
              onRefresh={onTicketRefresh}
              workorders={message.workorders || []}
            />
          </div>
        ) : hasResourceImportFlow ? (
          <div className="message-bubble markdown-bubble resource-import-flow-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <ResourceImportConversationCard
                agentId={agentId}
                message={message}
                onBackToConfirm={onResourceImportBackToConfirm}
                onBuildTopology={onResourceImportBuildTopology}
                onConfirmStructure={onResourceImportConfirmStructure}
                onContinueImport={onResourceImportContinue}
                onOpenSystemTopology={onResourceImportOpenSystemTopology}
                onParseFailed={onResourceImportParseFailed}
                onParseResolved={onResourceImportParseResolved}
                onReturnToUpload={onResourceImportReturnToUpload}
                onStartParse={onResourceImportStartParse}
                onScrollToStage={onResourceImportScrollToStage}
                onSubmitImport={onResourceImportSubmitImport}
                onUploadFiles={onResourceImportUploadFiles}
                releaseFiles={releaseResourceImportFiles}
                resolveFiles={resolveResourceImportFiles}
              />
            </Suspense>
          </div>
        ) : hasKnowledgeBaseFlow ? (
          <div className="message-bubble markdown-bubble knowledge-base-flow-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <KnowledgeBaseConversationCard
                message={message}
                onFlowUpdate={onKnowledgeBaseFlowUpdate}
                onManagementOpen={onKnowledgeBaseManagementOpen}
              />
            </Suspense>
          </div>
        ) : hasAlarmAnalystCard ? (
          <div className="message-bubble markdown-bubble alarm-analyst-card-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <AlarmAnalystCardPanel card={alarmAnalystCard} />
            </Suspense>
          </div>
        ) : isInspectionAnalystCardCandidate && !isStreamingMessage ? (
          <div className="message-bubble markdown-bubble inspection-analyst-card-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <InspectionAnalystCardPanel content={renderedMessageContent} />
            </Suspense>
          </div>
        ) : isInspectionSummaryCardCandidate ? (
          <div className="message-bubble markdown-bubble inspection-analyst-card-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <InspectionSummaryCardPanel content={renderedMessageContent} />
            </Suspense>
          </div>
        ) : renderedMessageContent ? (
          <div
            className={
              isStreamingMessage
                ? `message-bubble streaming-bubble markdown-bubble${hasKnowledgeAnswer ? " knowledge-answer-bubble" : ""}`
                : `message-bubble markdown-bubble${hasKnowledgeAnswer ? " knowledge-answer-bubble" : ""}`
            }
          >
            {orderDetailPayload ? (
              <div className="order-detail-composite">
                {orderDetailMarkdown ? (
                  <div className="order-detail-markdown">
                    <MessageMarkdown content={orderDetailMarkdown} />
                  </div>
                ) : null}
                {shouldRenderOrderDetailCard ? (
                  <PortalOrderDetailReport payload={orderDetailPayload} />
                ) : null}
              </div>
            ) : hasKnowledgeAnswer && !isStreamingMessage ? (
              <KnowledgeAnswerReport
                content={renderedMessageContent}
                payload={message.knowledgeAnswerPayload}
                onUploadRequest={onKnowledgeBaseUploadRequest}
                onManagementOpen={onKnowledgeBaseManagementOpen}
                defaultModelLabel={activeModelLabel}
              />
            ) : (
              <MessageMarkdown
                content={renderedMessageContent}
                isStreaming={isStreamingMessage}
              />
            )}
            {isStreamingMessage ? <span className="streaming-cursor" /> : null}
          </div>
        ) : null}

        {shouldShowResourceImportGuide ? (
          <div className="resource-import-guide-row">
            <button
              type="button"
              className="resource-import-guide-button"
              onClick={() => onResourceImportGuideOpen()}
            >
              <i className="fas fa-file-import" aria-hidden="true" />
              <span>前往导入资源清单</span>
            </button>
            <span className="resource-import-guide-hint">
              支持上传 Excel/CSV 台账，先预览清洗结果，再确认导入 CMDB。
            </span>
          </div>
        ) : null}

        {message.type === "agent"
        && copyableContent
        && !hasWorkorders
        && !isStreamingMessage
        ? (
          <div className="message-copy-row">
            <CopyActionButton
              text={String(copyableContent || "").trim()}
              label="复制回复"
              buttonClassName="message-copy-btn"
              iconClassName="message-copy-icon"
            />
          </div>
        ) : null}

        {shouldShowDisposalOperation ? (
          <DisposalOperationCard
            action={effectiveDisposalOperation}
            onExecute={() => onDisposalAction(message.id, effectiveDisposalOperation)}
          />
        ) : null}

        {faultScenarioResult ? (
          <FaultScenarioResultCard pageTheme={pageTheme} result={faultScenarioResult} />
        ) : null}

        {message.workflow && !message.workflowDone ? (
          <div className="workflow-container">
            <div className="workflow-header">
              <div className="workflow-title">
                <i className="fas fa-cogs" /> 执行中...
              </div>
              <div className="workflow-progress">
                {Math.round(((message.currentStep + 1) / message.workflow.length) * 100)}
                %
              </div>
            </div>
            <div className="workflow-steps">
              {message.workflow.map((step: string, index: number) => (
                <div
                  key={step}
                  className={
                    index < message.currentStep
                      ? "workflow-step completed"
                      : index === message.currentStep
                      ? "workflow-step executing"
                      : "workflow-step"
                  }
                >
                  <div
                    className={
                      index < message.currentStep
                        ? "step-icon done"
                        : index === message.currentStep
                        ? "step-icon running"
                        : "step-icon pending"
                    }
                  >
                    <i
                      className={
                        index < message.currentStep
                          ? "fas fa-check"
                          : index === message.currentStep
                          ? "fas fa-spinner fa-spin"
                          : "fas fa-circle"
                      }
                    />
                  </div>
                  <div className="step-content">
                    <h4>{step}</h4>
                    <p>
                      {message.workflowDescriptions?.[index]
                        || employeeStepDescriptions[currentEmployee.id]?.[index]
                        || "处理中..."}
                    </p>
                  </div>
                  <div
                    className={
                      index < message.currentStep ? "step-time success" : "step-time"
                    }
                  >
                    {index < message.currentStep ? message.stepTimes[index] || "1s" : "--"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {message.result ? (
          <div className="result-card">
            <div className="result-header">
              <div className="result-title">
                <i className="fas fa-check-circle" /> {message.result.title}
              </div>
              <span className="result-badge">{message.result.badge}</span>
            </div>
            <div className="result-metrics">
              {message.result.metrics.map((metric: any) => (
                <div key={metric.label} className="metric-box">
                  <div className={metric.highlight ? "metric-value highlight" : "metric-value"}>
                    {metric.value}
                  </div>
                  <div className="metric-label">{metric.label}</div>
                </div>
              ))}
            </div>
            {message.result.resources?.length ? (
              <div className="resource-grid">
                {message.result.resources.map((resource: any) => (
                  <div key={resource.name} className="resource-item">
                    <div className={`resource-icon ${resource.type}`}>
                      <i className={`fas ${resource.icon}`} />
                    </div>
                    <div className="resource-info">
                      <h5>{resource.name}</h5>
                      <p>{resource.desc}</p>
                    </div>
                    <span className="resource-status">{resource.status}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
});

function condenseBackgroundPollingBlocks(blocks: any[] = []) {
  const condensed: any[] = [];

  for (let index = 0; index < blocks.length; index += 1) {
    const current = blocks[index];
    if (!isPollingToolBlock(current)) {
      condensed.push(current);
      continue;
    }

    const toolBlocks = [current];
    const waitingResponses: any[] = [];
    let cursor = index + 1;

    while (cursor < blocks.length) {
      const candidate = blocks[cursor];
      if (isWaitingPollingResponse(candidate)) {
        waitingResponses.push(candidate);
        cursor += 1;
        continue;
      }
      if (isPollingToolBlock(candidate)) {
        toolBlocks.push(candidate);
        cursor += 1;
        continue;
      }
      break;
    }

    if (toolBlocks.length === 1 && waitingResponses.length === 0) {
      condensed.push(current);
      continue;
    }

    condensed.push(buildPollingSummaryBlock(toolBlocks, waitingResponses));
    index = cursor - 1;
  }

  return condensed;
}

function isPollingToolBlock(block: any) {
  return block?.kind === "tool" && block?.toolName === "check_agent_task";
}

function isWaitingPollingResponse(block: any) {
  if (block?.kind !== "response") {
    return false;
  }
  const text = String(block.content || "").trim();
  if (!text || text.length > 120) {
    return false;
  }
  return /继续(等待|查询)|任务仍在(运行|处理)|稍后|轮询|查询任务状态|待查询结果|pending|running/i.test(text);
}

function buildPollingSummaryBlock(toolBlocks: any[], waitingResponses: any[]) {
  const latestTool = toolBlocks[toolBlocks.length - 1] || toolBlocks[0];
  const latestWaitingText = [...waitingResponses]
    .reverse()
    .map((item) => String(item.content || "").trim())
    .find(Boolean);
  const pollCount = toolBlocks.length;
  const foldedCount = Math.max(pollCount - 1, 0) + waitingResponses.length;
  const summaryLines = [
    `后台协同任务正在处理中，已自动轮询 ${pollCount} 次。`,
    foldedCount > 0 ? `中间 ${foldedCount} 条轮询日志已折叠显示。` : "",
    latestWaitingText ? `最近状态：${latestWaitingText}` : "最近状态：任务仍在运行，等待最终结果返回。",
  ].filter(Boolean);

  return {
    ...latestTool,
    id: `polling-summary-${toolBlocks[0]?.id || Date.now()}`,
    title: "后台协同轮询",
    subtitle: `已轮询 ${pollCount} 次`,
    icon: "fa-hourglass-half",
    inputContent: "",
    outputContent: summaryLines.join("\n"),
    content: summaryLines.join("\n"),
  };
}

function buildTraceBundleSubtitle(blocks: any[] = []) {
  if (!blocks.length) {
    return "";
  }

  const thinkingCount = blocks.filter((block) => block?.kind === "thinking").length;
  const toolCount = blocks.filter((block) => block?.kind === "tool").length;
  const responseCount = blocks.filter((block) => block?.kind === "response").length;
  const segments = [
    thinkingCount ? `思考 ${thinkingCount}` : "",
    toolCount ? `工具 ${toolCount}` : "",
    responseCount ? `中间回复 ${responseCount}` : "",
  ].filter(Boolean);

  return segments.join(" · ") || `${blocks.length} 条记录`;
}

function TraceEntry({
  block,
  defaultOpen = false,
  isStreaming = false,
  open,
}: {
  block: any;
  defaultOpen?: boolean;
  isStreaming?: boolean;
  // 受控开关：定义时优先级最高（思考阶段父层用它强制只展开最新一条）；
  // 为 undefined 时退回原有的 block.defaultOpen / defaultOpen 行为。
  open?: boolean;
}) {
  if (block?.kind === "response") {
    return (
      <section className="trace-entry response">
        <div className="trace-entry-caption">
          <span className="trace-label">
            <i className="fas fa-comment-dots" />
            中间回复
          </span>
          <span className="trace-subtitle">过程消息</span>
        </div>
        <ResponseTraceBlock block={block} isStreaming={isStreaming} />
      </section>
    );
  }

  return (
    <details
      className={`trace-block trace-entry ${block?.kind || "misc"}`}
      open={open ?? block?.defaultOpen ?? defaultOpen}
    >
      <summary className="trace-summary">
        <span className="trace-label">
          <i className={`fas ${block?.icon || "fa-bars-progress"}`} />
          {block?.title || (block?.kind === "thinking" ? "Thinking" : "过程记录")}
        </span>
        {block?.subtitle ? (
          <span className="trace-subtitle">{block.subtitle}</span>
        ) : null}
      </summary>
      <div className="trace-body">
        {block?.kind === "tool" ? (
          <ToolTraceBlock block={block} />
        ) : (
          <MessageMarkdown content={block?.content || ""} isStreaming={isStreaming} />
        )}
      </div>
    </details>
  );
}

function CopyGlyph({
  copied,
  className = "",
}: {
  copied: boolean;
  className?: string;
}) {
  if (copied) {
    return (
      <svg
        className={`${className} success`.trim()}
        viewBox="0 0 16 16"
        aria-hidden="true"
      >
        <path d="M3.5 8.25 6.25 11l6.25-6.25" />
      </svg>
    );
  }

  return (
    <svg
      className={`${className} copy`.trim()}
      viewBox="0 0 1024 1024"
      overflow="hidden"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M161.744 322.8864a69.6768 69.6768 0 0 1 15.6768-23.8656 69.6768 69.6768 0 0 1 23.8656-15.68A69.7824 69.7824 0 0 1 227.2 278.4h448c8.9504 0 17.5904 1.648 25.9136 4.944a69.6256 69.6256 0 0 1 23.8656 15.6768 69.664 69.664 0 0 1 15.6768 23.8656A69.7664 69.7664 0 0 1 745.6 348.8v448c0 8.9504-1.648 17.5904-4.944 25.9136a69.6128 69.6128 0 0 1-15.6768 23.8656 69.6736 69.6736 0 0 1-23.8656 15.6768A69.7728 69.7728 0 0 1 675.2 867.2H227.2c-8.9536 0-17.5904-1.648-25.9136-4.944a69.664 69.664 0 0 1-23.8656-15.6768 69.6256 69.6256 0 0 1-15.68-23.8656A69.7856 69.7856 0 0 1 156.8 796.8V348.8c0-8.9536 1.648-17.5904 4.944-25.9136zM227.2 803.2h448c1.7664 0 3.2736-0.624 4.5248-1.8752 1.2512-1.2512 1.8752-2.7584 1.8752-4.5248V348.8c0-1.7664-0.624-3.2768-1.8752-4.5248A6.1696 6.1696 0 0 0 675.2 342.4H227.2c-1.7664 0-3.2768 0.624-4.5248 1.8752-1.248 1.248-1.8752 2.7584-1.8752 4.5248v448c0 1.7664 0.624 3.2736 1.8752 4.5248 1.248 1.2512 2.7584 1.8752 4.5248 1.8752z" />
      <path d="M811.776 161.1584a95.1872 95.1872 0 0 1 30.5056 20.56 95.2096 95.2096 0 0 1 20.56 30.5056A94.96 94.96 0 0 1 870.4 249.6v390.4c0 17.6736-14.3264 32-32 32s-32-14.3264-32-32V249.6a31.76 31.76 0 0 0-9.3728-22.6272A31.8016 31.8016 0 0 0 774.4 217.6H384c-17.6736 0-32-14.3264-32-32s14.3264-32 32-32h390.4c13.008 0 25.4656 2.5184 37.376 7.5584z" />
    </svg>
  );
}

function CopyActionButton({
  text,
  label,
  buttonClassName,
  iconClassName,
}: {
  text: string;
  label: string;
  buttonClassName: string;
  iconClassName: string;
}) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
    },
    [],
  );

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
      resetTimerRef.current = window.setTimeout(() => {
        setCopied(false);
        resetTimerRef.current = null;
      }, 1600);
    } catch (error) {
      console.error("Failed to copy content:", error);
    }
  };

  return (
    <button
      type="button"
      className={buttonClassName}
      onClick={() => void handleCopy()}
      aria-label={copied ? "已复制" : label}
      title={copied ? "已复制" : label}
    >
      <CopyGlyph copied={copied} className={iconClassName} />
    </button>
  );
}

function ResponseTraceBlock({
  block,
  isStreaming = false,
}: {
  block: any;
  isStreaming?: boolean;
}) {
  const rich = isRichResponseContent(block.content);

  if (!rich) {
    return (
      <div className="response-trace-inline markdown-bubble">
        <MessageMarkdown content={block.content} isStreaming={isStreaming} />
        {isStreaming ? <span className="streaming-cursor" /> : null}
      </div>
    );
  }

  return (
    <div className="response-trace-rich">
      <div
        className={
          isStreaming
            ? "message-bubble streaming-bubble markdown-bubble response-trace-bubble"
            : "message-bubble markdown-bubble response-trace-bubble"
        }
      >
        <MessageMarkdown content={block.content} isStreaming={isStreaming} />
        {isStreaming ? <span className="streaming-cursor" /> : null}
      </div>
      {!isStreaming ? (
        <div className="message-copy-row">
          <CopyActionButton
            text={String(block.content || "").trim()}
            label="复制回复"
            buttonClassName="message-copy-btn"
            iconClassName="message-copy-icon"
          />
        </div>
      ) : null}
    </div>
  );
}

function isRichResponseContent(content: string) {
  const normalized = String(content || "");
  return (
    extractVisualBlocks(normalized).length > 0 ||
    /(^|\n)\s*#{1,6}\s+\S/m.test(normalized) ||
    /(^|\n)\s*\|.+\|/m.test(normalized) ||
    normalized.includes("```")
  );
}

function ToolTraceBlock({ block }: { block: any }) {
  const sections = [
    { key: "input", label: "Input", content: block.inputContent },
    { key: "output", label: "Output", content: block.outputContent },
  ].filter((section) => section.content);

  if (!sections.length) {
    return <MessageMarkdown content={block.content} />;
  }

  return (
    <div className="tool-trace-stack">
      {sections.map((section) => (
        <ToolTracePanel
          key={`${block.id}-${section.key}`}
          label={section.label}
          content={section.content}
          panelClassName={section.key}
        />
      ))}
    </div>
  );
}

function ToolTracePanel({
  label,
  content,
  panelClassName,
}: {
  label: string;
  content: string;
  panelClassName: string;
}) {
  const text = getToolTracePayloadText(content);

  return (
    <section className={`tool-trace-panel ${panelClassName}`}>
      <div className="tool-trace-panel-header">
        <span>{label}</span>
        <CopyActionButton
          text={text}
          label={`复制${label}`}
          buttonClassName="tool-trace-copy-btn"
          iconClassName="tool-trace-copy-icon"
        />
      </div>
      <div className="tool-trace-panel-body">
        <ToolTracePayload content={content} />
      </div>
    </section>
  );
}

function getToolTracePayloadText(content: string) {
  const normalized = String(content || "").trim();
  const fencedMatch = normalized.match(/^```([a-zA-Z0-9_-]+)?\n([\s\S]*?)\n```$/);
  return fencedMatch ? fencedMatch[2] : normalized;
}

function ToolTracePayload({ content }: { content: string }) {
  const text = getToolTracePayloadText(content);

  return (
    <pre className="tool-trace-code">
      <code>{text}</code>
    </pre>
  );
}

// 报告下载链接：report-export 技能让智能体在回复里输出
// `[下载报告：xxx](/api/portal/agents/{agentId}/reports/{file})`，
// 这里把它渲染成下载按钮（其余链接保持默认的新标签页行为）。
const REPORT_DOWNLOAD_HREF_RE =
  /^\/(?:api\/portal|portal-api)\/agents\/[A-Za-z0-9._-]+\/reports\/[^/?#]+$/;

function MarkdownChatAnchor({
  href,
  children,
  ...rest
}: {
  href?: string;
  children?: React.ReactNode;
  [key: string]: unknown;
}) {
  delete (rest as Record<string, unknown>).node;
  const url = String(href || "");
  if (REPORT_DOWNLOAD_HREF_RE.test(url)) {
    const resolved = url.startsWith("/portal-api/")
      ? url
      : resolveActionDownloadUrl(url);
    let fileName = url.split("/").pop() || "";
    try {
      fileName = decodeURIComponent(fileName);
    } catch {
      /* keep raw name */
    }
    return (
      <a
        {...rest}
        className="portal-report-download-link"
        href={resolved}
        download={fileName}
        title={fileName}
      >
        <i className="fas fa-download" aria-hidden="true" />
        <span>{children}</span>
      </a>
    );
  }
  return (
    <a {...rest} href={url} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

const chatMarkdownComponents: ComponentProps<
  typeof PortalQwenPawMarkdown
>["components"] = {
  a: MarkdownChatAnchor,
};

export const MessageMarkdown = memo(function MessageMarkdown({
  content,
  isStreaming = false,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  const isDarkTheme =
    typeof document !== "undefined"
    && document.querySelector(".portal-digital-employee")?.classList.contains("theme-dark");
  const markdownThemeClass = isDarkTheme ? "x-markdown-dark" : "x-markdown-light";
  const normalizedContent = stripFrontmatter(
    unwrapPortalInspectionCardContent(
      unwrapPortalAlarmAnalystCardContent(
        normalizeMarkdownDisplayContent(content, {
          isStreaming,
        }),
      ),
    ),
  );
  const streamingContent = String(content || "");

  if (isStreaming) {
    return (
      <PortalQwenPawMarkdown
        className={`portal-x-markdown ${markdownThemeClass}`}
        content={streamingContent}
        isStreaming={isStreaming}
        components={chatMarkdownComponents}
      />
    );
  }

  const renderableSegments = extractRenderableContentSegments(content);
  const hasVisualSegments = renderableSegments.some((segment) => segment.type !== "markdown");

  if (!hasVisualSegments) {
    return (
      <PortalQwenPawMarkdown
        className={`portal-x-markdown ${markdownThemeClass}`}
        content={normalizedContent}
        isStreaming={false}
        components={chatMarkdownComponents}
      />
    );
  }

  return (
    <>
      {renderableSegments.map((segment, index) => {
        if (segment.type === "markdown") {
          const segmentContent = stripFrontmatter(
            unwrapPortalInspectionCardContent(
              unwrapPortalAlarmAnalystCardContent(
                normalizeMarkdownDisplayContent(segment.content, {
                  isStreaming: false,
                }),
              ),
            ),
          );
          if (!segmentContent.trim()) {
            return null;
          }

          return (
            <PortalQwenPawMarkdown
              key={`markdown-${index}`}
              className={`portal-x-markdown ${markdownThemeClass}`}
              content={segmentContent}
              isStreaming={false}
              components={chatMarkdownComponents}
            />
          );
        }

        return (
          <div
            key={`${segment.type}-${index}`}
            style={{ display: "grid", gap: 16, margin: "16px 0" }}
          >
            {segment.type === "echarts" ? (
              <DeferredEChartsBlock chart={segment.raw} />
            ) : (
              <PortalVisualizationBlock raw={segment.raw} />
            )}
          </div>
        );
      })}
    </>
  );
});

function stripFrontmatter(content: string) {
  return String(content || "").replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
}
