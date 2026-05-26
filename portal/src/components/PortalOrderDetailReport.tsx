import type { ReactNode } from "react";

export function parsePortalOrderDetailPayload(
  content: string,
  processBlocks: any[] = [],
) {
  return (
    parseStructuredOrderDetailPayload(content)
    || parseOrderDetailPayloadFromProcessBlocks(processBlocks)
    || parseLegacyOrderDetailPayload(content)
  );
}

export function parsePortalOrderDetailPayloadFromRuntimeOutput(output: any[] = []) {
  for (const message of [...output].reverse()) {
    for (const content of [...(message?.content || [])].reverse()) {
      const candidates = [
        content?.text,
        content?.refusal,
        content?.data?.output,
        content?.data?.text,
        typeof content?.data === "string" ? content.data : "",
      ];
      for (const candidate of candidates) {
        const payload = parseStructuredOrderDetailPayload(String(candidate || ""));
        if (payload) {
          return payload;
        }
      }
    }
  }
  return null;
}

export function getPortalOrderDetailMarkdownContent(
  content: string,
  processBlocks: any[] = [],
) {
  return (
    extractOrderDetailMarkdown(content)
    || extractOrderDetailMarkdownFromProcessBlocks(processBlocks)
    || ""
  );
}

export function getPortalOrderDetailMarkdownContentFromRuntimeOutput(output: any[] = []) {
  for (const message of [...output].reverse()) {
    for (const content of [...(message?.content || [])].reverse()) {
      const candidates = [
        content?.text,
        content?.refusal,
        content?.data?.output,
        content?.data?.text,
        typeof content?.data === "string" ? content.data : "",
      ];
      for (const candidate of candidates) {
        const markdown = extractOrderDetailMarkdown(String(candidate || ""));
        if (markdown) {
          return markdown;
        }
      }
    }
  }
  return "";
}

export function hasPortalOrderDetailPayloadContent(payload: any) {
  const tabs = payload?.tabs || {};
  const records = Array.isArray(tabs?.records?.records) ? tabs.records.records : [];
  const trackingNodes = Array.isArray(tabs?.tracking?.nodes) ? tabs.tracking.nodes : [];
  const formSections = Array.isArray(tabs?.form?.sections) ? tabs.form.sections : [];
  const formFields = formSections.flatMap((section: any) =>
    Array.isArray(section?.fields) ? section.fields : [],
  );
  const summary = Array.isArray(payload?.summary) ? payload.summary : [];
  const hasSummaryValue = summary.some((item: any) => {
    const value = String(item?.value ?? "").trim();
    return value && value !== "-";
  });
  const processName = String(payload?.processName ?? "").trim();

  return (
    (processName && processName !== "-")
    || hasSummaryValue
    || formFields.length > 0
    || records.length > 0
    || trackingNodes.length > 0
  );
}

function parseStructuredOrderDetailPayload(content: string) {
  const normalized = String(content || "");
  const match = normalized.match(/```portal-order-detail\s*([\s\S]*?)```/i);
  if (!match?.[1]) {
    return null;
  }
  try {
    return JSON.parse(match[1].trim());
  } catch {
    return null;
  }
}

function extractOrderDetailMarkdown(content: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n").trim();
  if (!normalized || !/```portal-order-detail\s*[\s\S]*?```/i.test(normalized)) {
    return "";
  }

  const markdown = normalized
    .replace(/```portal-order-detail\s*[\s\S]*?```/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  if (!/工单详情/u.test(markdown) || !/(表单信息|流转记录|流程跟踪)/u.test(markdown)) {
    return "";
  }
  return markdown;
}

function extractOrderDetailMarkdownFromProcessBlocks(blocks: any[] = []) {
  for (const block of [...blocks].reverse()) {
    const candidates = [
      block?.outputContent,
      block?.content,
    ];
    for (const candidate of candidates) {
      const markdown = extractOrderDetailMarkdown(String(candidate || ""));
      if (markdown) {
        return markdown;
      }
    }
  }
  return "";
}

function parseOrderDetailPayloadFromProcessBlocks(blocks: any[] = []) {
  for (const block of [...blocks].reverse()) {
    const candidates = [
      block?.outputContent,
      block?.content,
    ];
    for (const candidate of candidates) {
      const payload = parseStructuredOrderDetailPayload(String(candidate || ""));
      if (payload) {
        return payload;
      }
    }
  }
  return null;
}

function parseLegacyOrderDetailPayload(content: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  if (!/工单详情/u.test(normalized) || !/(流转记录|流程跟踪)/u.test(normalized)) {
    return null;
  }

  const processName = normalized.match(/流程名称[：:]\s*\*\*([^*]+)\*\*/u)?.[1]?.trim()
    || normalized.match(/流程名称[：:]\s*([^\n]+)/u)?.[1]?.trim()
    || "故障处置工单";
  const summary = Array.from(normalized.matchAll(/^-+\s*([^：:\n]+)[：:]\s*\*\*([^*\n]+)\*\*/gmu))
    .map((item) => ({
      label: item[1]?.trim() || "-",
      value: item[2]?.trim() || "-",
    }))
    .filter((item) => item.label && item.value && item.label !== "流程名称")
    .slice(0, 4);

  const recordBlock = normalized.split(/###\s*流转记录/u)[1]?.split(/###\s*流程跟踪/u)[0] || "";
  const records = recordBlock
    .split("\n")
    .map((line, index) => parseLegacyOrderRecordLine(line, index))
    .filter(Boolean);

  const trackingBlock = normalized.split(/###\s*流程跟踪/u)[1]?.split(/如需|如果|```/u)[0] || "";
  const trackingNodes = parseLegacyOrderTrackingNodes(trackingBlock);

  if (!records.length && !trackingNodes.length) {
    return null;
  }

  return {
    processName,
    summary,
    tabs: {
      form: { sections: [] },
      records: { records },
      tracking: { nodes: trackingNodes },
    },
  };
}

function parseLegacyOrderRecordLine(line: string, index: number) {
  const trimmed = String(line || "").trim();
  if (!/^\d+\./.test(trimmed)) {
    return null;
  }
  const nodeLabel = trimmed.match(/^\d+\.\s*`?([^`|]+)`?/u)?.[1]?.trim() || `节点 ${index + 1}`;
  return {
    id: `legacy-record-${index}`,
    status: legacyOrderStatusToKey(extractLegacyOrderField(trimmed, "状态")),
    nodeLabel,
    assignee: extractLegacyOrderField(trimmed, "办理人"),
    receiveTime: extractLegacyOrderField(trimmed, "接收"),
    handleTime: extractLegacyOrderField(trimmed, "办理"),
    duration: extractLegacyOrderField(trimmed, "耗时"),
    comments: [],
  };
}

function extractLegacyOrderField(line: string, label: string) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = String(line || "").match(new RegExp(`${escaped}[：:]\\s*([^|]+)`, "u"));
  return match?.[1]?.trim() || "-";
}

function parseLegacyOrderTrackingNodes(block: string) {
  const text = String(block || "").trim();
  if (!text) {
    return [];
  }
  const numbered = text
    .split("\n")
    .map((line, index) => {
      const match = line.match(/^\s*\d+\.\s*`?([^`|]+)`?.*状态[：:]([^|]+)/u);
      if (!match) {
        return null;
      }
      return {
        id: `legacy-track-${index}`,
        label: match[1]?.trim() || `节点 ${index + 1}`,
        status: legacyOrderStatusToKey(match[2]?.trim()),
      };
    })
    .filter(Boolean);
  if (numbered.length) {
    return numbered;
  }

  return text
    .split(/\s*(?:->|→)\s*/u)
    .map((part, index) => {
      const match = part.match(/(.+?)（(.+?)）/u);
      const label = (match?.[1] || part).trim();
      const status = (match?.[2] || "").trim();
      return {
        id: `legacy-track-${index}`,
        label: label || `节点 ${index + 1}`,
        status: legacyOrderStatusToKey(status),
      };
    })
    .filter((item) => item.label);
}

function legacyOrderStatusToKey(value?: string) {
  const text = String(value || "").trim().toLowerCase();
  if (/完成|finished|success/.test(text)) {
    return "finished";
  }
  if (/处理|进行|active|running|当前/.test(text)) {
    return "active";
  }
  if (/驳回|拒绝|reject/.test(text)) {
    return "rejected";
  }
  return "pending";
}

function orderStatusLabel(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "finished") {
    return "已完成";
  }
  if (normalized === "active") {
    return "处理中";
  }
  if (normalized === "rejected") {
    return "已驳回";
  }
  if (normalized === "pending") {
    return "未到达";
  }
  return status || "-";
}

function orderStatusClass(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (["finished", "active", "rejected", "pending"].includes(normalized)) {
    return normalized;
  }
  return "pending";
}

function formatOrderMeta(value: unknown) {
  const text = String(value ?? "").trim();
  return text && text !== "-" ? text : "-";
}

export function PortalOrderDetailReport({ payload }: { payload: any }): ReactNode {
  const summary = Array.isArray(payload?.summary) ? payload.summary : [];
  const tabs = payload?.tabs || {};
  const records = Array.isArray(tabs?.records?.records) ? tabs.records.records : [];
  const trackingNodes = Array.isArray(tabs?.tracking?.nodes) ? tabs.tracking.nodes : [];
  const formSections = Array.isArray(tabs?.form?.sections) ? tabs.form.sections : [];
  const previewFields = formSections
    .flatMap((section: any) => Array.isArray(section?.fields) ? section.fields : [])
    .filter((field: any) => {
      const value = field?.value;
      return value !== undefined && value !== null && value !== "" && !(Array.isArray(value) && value.length === 0);
    })
    .slice(0, 8);

  return (
    <div className="order-detail-report">
      <header className="order-detail-header">
        <div>
          <span className="order-detail-kicker">工单详情</span>
          <h3>{payload?.processName || "故障处置工单"}</h3>
        </div>
        <div className="order-detail-counts">
          <span>{records.length} 条流转</span>
          <span>{trackingNodes.length} 个节点</span>
        </div>
      </header>

      {summary.length ? (
        <div className="order-detail-summary">
          {summary.map((item: any, index: number) => (
            <div key={`${item?.label || "summary"}-${index}`}>
              <span>{item?.label || "-"}</span>
              <strong>{formatOrderMeta(item?.value)}</strong>
            </div>
          ))}
        </div>
      ) : null}

      {previewFields.length ? (
        <section className="order-detail-section">
          <h4>表单信息</h4>
          <div className="order-detail-fields">
            {previewFields.map((field: any, index: number) => (
              <div key={`${field?.name || field?.label || "field"}-${index}`}>
                <span>{field?.label || field?.name || "-"}</span>
                <strong>{Array.isArray(field?.value) ? field.value.join("、") : formatOrderMeta(field?.value)}</strong>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="order-detail-section">
        <h4>流转记录</h4>
        {records.length ? (
          <div className="order-transfer-timeline">
            {records.map((record: any, index: number) => {
              const statusClass = orderStatusClass(record?.status);
              return (
                <article key={record?.id || `${record?.nodeLabel || "record"}-${index}`} className={`order-transfer-item ${statusClass}`}>
                  <div className="order-transfer-marker">
                    <span>{index + 1}</span>
                  </div>
                  <div className="order-transfer-body">
                    <div className="order-transfer-title">
                      <strong>{record?.nodeLabel || "-"}</strong>
                      <mark>{orderStatusLabel(record?.status)}</mark>
                    </div>
                    <div className="order-transfer-meta">
                      <span>办理人：{formatOrderMeta(record?.assignee)}</span>
                      <span>接收：{formatOrderMeta(record?.receiveTime)}</span>
                      <span>办理：{formatOrderMeta(record?.handleTime)}</span>
                      {formatOrderMeta(record?.duration) !== "-" ? <span>耗时：{record.duration}</span> : null}
                    </div>
                    {Array.isArray(record?.comments) && record.comments.length ? (
                      <p>{record.comments.join("；")}</p>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="order-detail-empty">当前没有流转记录。</div>
        )}
      </section>

      <section className="order-detail-section">
        <h4>流程跟踪</h4>
        {trackingNodes.length ? (
          <div className="order-flow-track">
            {trackingNodes.map((node: any, index: number) => {
              const statusClass = orderStatusClass(node?.status);
              return (
                <div key={node?.id || `${node?.label || "node"}-${index}`} className={`order-flow-node ${statusClass}`}>
                  <span className="order-flow-dot">
                    <i className={`fas ${statusClass === "finished" ? "fa-check" : statusClass === "active" ? "fa-spinner" : statusClass === "rejected" ? "fa-xmark" : "fa-clock"}`} />
                  </span>
                  <strong>{node?.label || "-"}</strong>
                  <small>{orderStatusLabel(node?.status)}</small>
                  {index < trackingNodes.length - 1 ? <b aria-hidden="true" /> : null}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="order-detail-empty">当前没有流程跟踪信息。</div>
        )}
      </section>
    </div>
  );
}
