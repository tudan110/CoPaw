import { digitalEmployees } from "../../data/portalData.ts";

const TIMEOUT_ALARM_TITLE = "应用接口响应超时";
export const ALARM_WORKORDER_ENTRY = "alarm-workorders";
export const ALARM_WORKORDER_LIMIT = 5;
export const PORTAL_FAULT_WORKORDER_MARKER = "# PORTAL FAULT WORKORDER MODE";
export const PORTAL_ALARM_ANALYST_CARD_MARKER = "# PORTAL ALARM ANALYST CARD MODE";
export const PORTAL_INSPECTION_CARD_MARKER = "# PORTAL INSPECTION CARD MODE";
export const PORTAL_VIEW_OPTIONS = ["chat", "overview", "dashboard", "tasks"] as const;
export const PORTAL_ADVANCED_PANEL_OPTIONS = ["model-config", "token-usage", "ops-expert", "mcp", "skill-pool", "fde-workbench", "knowledge-base", "inspiration", "resource-import", "nl-customization", "app-market", "cli", "traces", "settings", "alarm-registry", "channels", "inbox"] as const;
export const PORTAL_ROUTE_SECTION_OPTIONS = [
  "overview",
  "dashboard",
  "tasks",
  "model-config",
  "token-usage",
  "ops-expert",
  "mcp",
  "skill-pool",
  "fde-workbench",
  "knowledge-base",
  "inspiration",
  "resource-import",
  "nl-customization",
  "app-market",
  "cli",
  "traces",
  "settings",
  "alarm-registry",
  "channels",
  "inbox",
] as const;

export type PortalView = (typeof PORTAL_VIEW_OPTIONS)[number];
export type PortalAdvancedPanel = (typeof PORTAL_ADVANCED_PANEL_OPTIONS)[number];
export type PortalRouteSection = (typeof PORTAL_ROUTE_SECTION_OPTIONS)[number];

export type VisualBlock = {
  type: "echarts" | "portal-visualization";
  raw: string;
};

function looksLikeEChartsConfig(raw: string) {
  const text = String(raw || "").trim();
  if (!text.startsWith("{") || !text.endsWith("}")) {
    return false;
  }

  const hasEChartsSignal =
    /(^|[,{]\s*)(series|xAxis|yAxis|tooltip|legend|dataset|graphic|grid|title|radar|visualMap)\s*:/.test(text)
    || /(^|[,{]\s*)["'](series|xAxis|yAxis|tooltip|legend|dataset|graphic|grid|title|radar|visualMap)["']\s*:/.test(text);
  if (!hasEChartsSignal) {
    return false;
  }

  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    return Boolean(
      parsed
      && typeof parsed === "object"
      && (
        Array.isArray(parsed.series)
        || Array.isArray((parsed as { xAxis?: { data?: unknown[] } }).xAxis?.data)
        || Array.isArray((parsed as { yAxis?: unknown[] }).yAxis)
        || "title" in parsed
        || "tooltip" in parsed
        || "__mockStream" in parsed
      ),
    );
  } catch {
    return hasEChartsSignal;
  }
}

export function selectAlarmWorkbenchVisibleWorkorders(workorders: any[] = []) {
  if (!Array.isArray(workorders) || !workorders.length) {
    return [];
  }

  const timeoutEntries = workorders.filter((item) =>
    String(item?.title || "").includes(TIMEOUT_ALARM_TITLE),
  );

  if (timeoutEntries.length) {
    return timeoutEntries.slice(0, 1);
  }

  return workorders.slice(0, 1);
}

export function mergeStreamingText(currentText: string, incomingText: string) {
  const current = String(currentText || "");
  const incoming = String(incomingText || "");

  if (!incoming) {
    return current;
  }
  if (!current) {
    return incoming;
  }
  if (incoming.startsWith(current)) {
    return incoming;
  }
  if (current.endsWith(incoming)) {
    return current;
  }

  const maxOverlap = Math.min(current.length, incoming.length);
  for (let size = maxOverlap; size > 0; size -= 1) {
    if (current.slice(-size) === incoming.slice(0, size)) {
      return `${current}${incoming.slice(size)}`;
    }
  }

  return `${current}${incoming}`;
}

export function parsePortalView(value: string | null | undefined): PortalView {
  return PORTAL_VIEW_OPTIONS.includes(value as PortalView) ? (value as PortalView) : "chat";
}

export function parsePortalAdvancedPanel(
  value: string | null | undefined,
): PortalAdvancedPanel | null {
  return PORTAL_ADVANCED_PANEL_OPTIONS.includes(value as PortalAdvancedPanel)
    ? (value as PortalAdvancedPanel)
    : null;
}

export function isPortalRouteSection(
  value: string | null | undefined,
): value is PortalRouteSection {
  return PORTAL_ROUTE_SECTION_OPTIONS.includes(value as PortalRouteSection);
}

export function buildPortalRouteSection(options: {
  view?: PortalView;
  panel?: PortalAdvancedPanel | null;
}): PortalRouteSection | null {
  if (options.panel) {
    return options.panel;
  }

  if (options.view && options.view !== "chat") {
    return options.view;
  }

  return null;
}

export function buildPortalSectionPath(
  section: PortalRouteSection,
  options: {
    entry?: string | null;
    employeeId?: string | null;
  } = {},
) {
  const params = new URLSearchParams();

  if (options.entry) {
    params.set("entry", options.entry);
  }

  if (options.employeeId) {
    params.set("employee", options.employeeId);
  }

  const query = params.toString();
  const pathname = `/${section}`;
  return query ? `${pathname}?${query}` : pathname;
}

export function buildPortalHomePath(
  options: {
    entry?: string | null;
    view?: PortalView;
    panel?: PortalAdvancedPanel | null;
  } = {},
) {
  const section = buildPortalRouteSection(options);
  if (section) {
    return buildPortalSectionPath(section, {
      entry: options.entry,
    });
  }

  const params = new URLSearchParams();
  if (options.entry) {
    params.set("entry", options.entry);
  }

  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export function buildEmployeePagePath(
  employee: any,
  options: {
    entry?: string | null;
    view?: PortalView;
    panel?: PortalAdvancedPanel | null;
  } = {},
) {
  const params = new URLSearchParams();
  const entry = options.entry ?? null;

  if (entry) {
    params.set("entry", entry);
  }

  const query = params.toString();
  const section = buildPortalRouteSection(options);
  if (section) {
    return buildPortalSectionPath(section, {
      entry,
      employeeId: options.panel ? employee.id : null,
    });
  }

  const pathname = `/employee/${employee.id}`;
  return query ? `${pathname}?${query}` : pathname;
}

export function getSeverityClassName(severityLevel: any) {
  if (String(severityLevel) === "1") {
    return "severity-critical";
  }
  if (String(severityLevel) === "2") {
    return "severity-major";
  }
  if (String(severityLevel) === "3") {
    return "severity-minor";
  }
  return "severity-info";
}

export function createWelcomeMessage(employee: any) {
  const welcomeContent = String(employee?.welcome || "").trim();
  if (!welcomeContent) {
    return null;
  }
  return createAgentMessage(employee, {
    id: `welcome-${employee.id}-${Date.now()}`,
    content: welcomeContent,
  });
}

export function createInitialMessages(employee: any) {
  const welcomeMessage = createWelcomeMessage(employee);
  return welcomeMessage ? [welcomeMessage] : [];
}

export function createAgentMessage(employee: any, overrides: Record<string, any> = {}) {
  return {
    id: `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: "agent",
    icon: employee.icon,
    gradient: "linear-gradient(135deg, var(--primary), var(--purple))",
    content: "",
    processBlocks: [],
    backendMessageId: "",
    enhancementSourceMessageId: "",
    ...overrides,
  };
}

export function normalizeDisposalOperationPayload(action: any) {
  if (!action) {
    return null;
  }

  const rawStatus = String(action.status || "").trim().toLowerCase();
  let normalizedStatus = rawStatus || "ready";

  if (["completed", "complete", "done", "executed", "finished", "success"].includes(rawStatus)) {
    normalizedStatus = "success";
  } else if (["running", "in_progress", "in-progress", "pending_execution"].includes(rawStatus)) {
    normalizedStatus = "running";
  } else if (!rawStatus && (action.recoveryVerified || action.executedAt)) {
    normalizedStatus = "success";
  }

  return {
    ...action,
    status: normalizedStatus,
  };
}

export function buildAgentMessageFromPayload(
  payload: any,
  { employee, id }: { employee?: any; id?: string } = {},
) {
  if (!employee || !payload) {
    return null;
  }

  return createAgentMessage(employee, {
    id: id || `fault-disposal-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    content: payload.content || "",
    processBlocks: payload.processBlocks || [],
    disposalOperation: normalizeDisposalOperationPayload(payload.action),
    streaming: false,
  });
}

export function createAlarmWorkorderMessage(employee: any, overrides: Record<string, any> = {}) {
  return createAgentMessage(employee, {
    content: "",
    workorders: [],
    workordersLoading: false,
    workordersError: "",
    ...overrides,
  });
}

export function createUserMessage(content: string) {
  return {
    id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: "user",
    content,
  };
}

export function createRemoteSessionId(employeeId: string) {
  return `${getPortalSessionPrefix(employeeId)}${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function buildFaultWorkbenchVisiblePrompt(workorder: any) {
  return `去处置工单 ${workorder.workorderNo}：${workorder.title}`;
}

export function buildFaultWorkbenchChatName(workorder: any) {
  return `故障处置 · ${workorder.title} · ${workorder.workorderNo}`.slice(0, 80);
}

export function buildFaultWorkbenchChatMeta(workorder: any) {
  return {
    source: "portal-fault-workorder",
    workorderNo: workorder.workorderNo,
    title: workorder.title,
  };
}

export function buildFaultWorkbenchContextPayload(
  workorder: any,
  workorders: any[],
  extras: Record<string, any> = {},
) {
  const compactWorkorders = selectRelevantWorkordersForSkill(workorder, workorders).map(
    compactWorkorderForSkill,
  );
  return {
    entryWorkorder: compactWorkorderForSkill(workorder),
    workorders: compactWorkorders,
    tags: ["portal", "fault-disposal", "workorder-driven"],
    source: "portal-chat",
    ...extras,
  };
}

export function buildFaultWorkbenchDiagnosePrompt(workorder: any, workorders: any[]) {
  return [
    PORTAL_FAULT_WORKORDER_MARKER,
    "请按标准故障处置流程继续当前工单分析，优先调用 fault-disposal skill。",
    "要求：保持在当前聊天会话中完成，不要创建子会话；先完成根因分析与处置建议，暂时不要直接执行动作；输出精炼 markdown，并保留 portal-action 代码块。",
    "强约束：如果结论是存在可执行的下一步动作，最终回复末尾必须追加唯一一个 ```portal-action 代码块；不要只写“请回复执行建议动作”这类文字而不附 action。",
    "portal-action 必须是合法 JSON，至少包含：id、type、title、summary、status、riskLevel、sessionId、sqlId、sourceWorkorderNo、rootCauseWorkorderNo、deviceName、manageIp、locateName。",
    "如果建议动作是终止异常慢 SQL 会话，则 type 固定为 kill-slow-sql，title 固定使用“建议执行：终止异常慢 SQL 会话”。缺少 portal-action 视为无效回复，需要先补齐再输出。",
    "执行约束：不要把脚本命令原样回复给用户；如果已识别为工单驱动故障处置，直接进入 skill 分析；不要先查询实时告警列表或重复做无关信息收集。",
    "",
    "【工单上下文(JSON)】",
    "```json",
    JSON.stringify(buildFaultWorkbenchContextPayload(workorder, workorders), null, 2),
    "```",
    "",
    "---",
    buildFaultWorkbenchVisiblePrompt(workorder),
  ].join("\n");
}

export function buildFaultWorkbenchExecutePrompt(workorder: any, workorders: any[], action: any) {
  return [
    PORTAL_FAULT_WORKORDER_MARKER,
    "请按标准故障处置流程继续当前工单，并执行已经确认的建议动作，优先调用 fault-disposal skill。",
    "要求：保持在当前聊天会话中执行，不要创建子会话；完成动作后返回恢复验证结论，正文保持精炼 markdown。",
    "执行约束：不要把脚本命令原样回复给用户；不要重复查询无关告警列表；基于下方建议动作和工单上下文完成执行与验证。",
    "",
    "【建议动作(JSON)】",
    "```json",
    JSON.stringify(compactActionForSkill(action || {}), null, 2),
    "```",
    "",
    "【工单上下文(JSON)】",
    "```json",
    JSON.stringify(
      buildFaultWorkbenchContextPayload(workorder, workorders, {
        confirmedAction: action || {},
      }),
      null,
      2,
    ),
    "```",
    "",
    "---",
    `执行建议动作：${action?.title || "故障处置动作"}`,
  ].join("\n");
}

function compactWorkorderForSkill(workorder: any) {
  if (!workorder || typeof workorder !== "object") {
    return {};
  }
  return {
    id: workorder.id,
    workorderNo: workorder.workorderNo,
    title: workorder.title,
    description: workorder.description,
    deviceName: workorder.deviceName,
    manageIp: workorder.manageIp,
    locateName: workorder.locateName,
    eventTime: workorder.eventTime,
    severity: workorder.severity,
    severityLevel: workorder.severityLevel,
    status: workorder.status,
    speciality: workorder.speciality,
    region: workorder.region,
    actionCount: workorder.actionCount,
    alarmText: workorder.alarmText,
  };
}

function compactActionForSkill(action: any) {
  if (!action || typeof action !== "object") {
    return {};
  }
  return {
    id: action.id,
    type: action.type,
    title: action.title,
    summary: action.summary,
    status: action.status,
    riskLevel: action.riskLevel || action.risk_level,
    sessionId: action.sessionId,
    sqlId: action.sqlId,
    targetSummary: action.targetSummary,
    sourceWorkorderNo: action.sourceWorkorderNo,
    rootCauseWorkorderNo: action.rootCauseWorkorderNo,
    deviceName: action.deviceName,
    manageIp: action.manageIp,
    locateName: action.locateName,
  };
}

function selectRelevantWorkordersForSkill(entryWorkorder: any, workorders: any[] = []) {
  const list = Array.isArray(workorders) ? workorders : [];
  const result = [];
  const seen = new Set<string>();

  const push = (item: any) => {
    const key = String(item?.workorderNo || item?.id || "");
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    result.push(item);
  };

  push(entryWorkorder);
  list
    .filter((item) => String(item?.title || "").includes("慢SQL"))
    .slice(0, 1)
    .forEach(push);

  list.slice(0, 2).forEach(push);
  return result;
}

export function buildRemoteChatName(employeeName: string, firstMessage: string) {
  const trimmed = (firstMessage || "").trim();
  if (!trimmed) {
    return `${employeeName} · ${new Date().toLocaleString("zh-CN")}`;
  }
  return trimmed.slice(0, 24);
}

export function normalizeRemoteSessions(
  chats: any[] = [],
  employeeId: string,
  { fallbackToAllChats = false }: { fallbackToAllChats?: boolean } = {},
) {
  const allChats = Array.isArray(chats) ? chats : [];
  const matchedChats = allChats.filter((chat) => isRemoteSessionForEmployee(chat, employeeId));
  const scopedChats = [...(
    matchedChats.length || !fallbackToAllChats ? matchedChats : allChats
  )]
    .sort((left, right) => {
      const leftTime = new Date(left.updated_at || left.created_at || 0).getTime();
      const rightTime = new Date(right.updated_at || right.created_at || 0).getTime();
      return rightTime - leftTime;
    });

  const dedupedChats = [];
  const seenKeys = new Set();

  for (const chat of scopedChats) {
    const dedupeKey = buildRemoteSessionDedupeKey(chat, employeeId);
    if (seenKeys.has(dedupeKey)) {
      continue;
    }
    seenKeys.add(dedupeKey);
    dedupedChats.push(chat);
  }

  return dedupedChats.map((chat) => ({
    id: chat.id,
    sessionId: chat.session_id,
    title: buildRemoteSessionTitle(chat, employeeId),
    updatedAt: chat.updated_at || chat.created_at || new Date().toISOString(),
    status: chat.status || "idle",
    detail: buildRemoteSessionDetail(chat),
    tag: chat.status === "running" ? "进行中" : "历史记录",
    meta: chat.meta || {},
  }));
}

export function normalizeRemoteHistoryMessages(
  historyMessages: any[] = [],
  employee: any,
  session: any,
) {
  const normalizedMessages = [];
  let activeAgentMessage = null;

  for (const message of historyMessages || []) {
    if (message.role === "user" && (!message.type || message.type === "message")) {
      const rawText = sanitizeRemoteUserText(extractCopawMessageText(message));
      if (!rawText) {
        continue;
      }
      activeAgentMessage = null;
      normalizedMessages.push({
        id: message.id || `user-${normalizedMessages.length}`,
        type: "user",
        content: rawText,
      });
      continue;
    }

    if (!activeAgentMessage) {
      activeAgentMessage = createAgentMessage(employee, {
        id: message.id || `agent-${normalizedMessages.length}`,
        content: "",
        processBlocks: [],
        backendMessageId: message.id || "",
      });
      normalizedMessages.push(activeAgentMessage);
    }

    if (isCopawReasoningMessage(message)) {
      const block = buildThinkingBlock(message);
      if (block.content) {
        activeAgentMessage.processBlocks = mergeProcessBlocks(
          activeAgentMessage.processBlocks,
          [block],
        );
      }
      continue;
    }

    if (message.type === "plugin_call" || message.type === "plugin_call_output") {
      const block = buildToolBlock(message);
      if (block.content) {
        activeAgentMessage.processBlocks = mergeProcessBlocks(
          activeAgentMessage.processBlocks,
          [block],
        );
      }
      continue;
    }

    if (message.role === "assistant" && (!message.type || message.type === "message")) {
      const textContent = extractCopawMessageText(message);
      if (!textContent) {
        continue;
      }
      activeAgentMessage.backendMessageId = activeAgentMessage.backendMessageId || message.id || "";
      activeAgentMessage.enhancementSourceMessageId = message.id || "";
      const responseBlock = buildResponseBlock(message, textContent);
      activeAgentMessage.processBlocks = mergeProcessBlocks(
        activeAgentMessage.processBlocks,
        [responseBlock],
      );
    }
  }

  return normalizedMessages.filter((message) => {
    if (message.type === "user") {
      return Boolean(message.content);
    }
    return Boolean(message.content || message.processBlocks?.length);
  });
}

export function extractCopawMessageText(message: any) {
  return normalizeContentToText(message?.content).trim();
}

export function extractCopawReasoningText(message: any) {
  if (message?.type === "reasoning") {
    return extractCopawMessageText(message);
  }
  return normalizeContentToText(message?.content, "thinking").trim();
}

export function isCopawReasoningMessage(message: any) {
  return message?.role === "assistant"
    && (
      message?.type === "reasoning"
      || Boolean(extractCopawReasoningText(message))
    );
}

export function buildThinkingBlock(
  message: any,
  options: { replaceContent?: boolean } = {},
) {
  return {
    id: message.id || `thinking-${Date.now()}`,
    kind: "thinking",
    title: "Thinking",
    subtitle: "思考过程",
    icon: "fa-brain",
    content: extractCopawReasoningText(message),
    replaceContent: options.replaceContent ?? false,
  };
}

export function buildResponseBlock(
  message: any,
  contentOverride?: string,
  options: { preserveWhitespace?: boolean } = {},
) {
  const rawContent = String(contentOverride ?? extractCopawMessageText(message) ?? "");
  const content = options.preserveWhitespace ? rawContent : rawContent.trim();

  return {
    id: message.id || `response-${Date.now()}`,
    kind: "response",
    content,
  };
}

export function buildToolBlock(message: any) {
  const payload = extractMessageDataPayload(message);
  const toolName = payload?.name || "tool";
  const toolCallId = payload?.call_id || payload?.tool_call_id || payload?.id || "";
  const inputContent =
    message.type === "plugin_call" ? normalizeToolPayload(payload?.arguments) : "";
  const outputContent =
    message.type === "plugin_call_output" ? normalizeToolPayload(payload?.output) : "";

  return {
    id: message.id || `${message.type}-${Date.now()}`,
    kind: "tool",
    title: toolName,
    subtitle: "工具调用",
    icon: "fa-screwdriver-wrench",
    toolName,
    toolCallId,
    inputContent,
    outputContent,
    content: inputContent || outputContent || toolName,
  };
}

function extractMessageDataPayload(message: any) {
  const content = Array.isArray(message?.content) ? message.content : [];
  const dataItem = content.find((item: any) => item?.type === "data");
  return dataItem?.data || null;
}

export function mergeProcessBlocks(existingBlocks: any[] = [], incomingBlocks: any[] = []) {
  return incomingBlocks.reduce((mergedBlocks, incomingBlock) => {
    if (!incomingBlock) {
      return mergedBlocks;
    }

    if (incomingBlock.kind === "response") {
      const existingIndex = mergedBlocks.findIndex(
        (item) => item?.kind === "response" && item.id === incomingBlock.id,
      );
      if (existingIndex === -1) {
        return [...mergedBlocks, incomingBlock];
      }

      const nextBlocks = [...mergedBlocks];
      nextBlocks[existingIndex] = mergeResponseTraceBlock(
        nextBlocks[existingIndex],
        incomingBlock,
      );
      return nextBlocks;
    }

    if (incomingBlock.kind === "thinking") {
      const existingIndex = mergedBlocks.findIndex(
        (item) => item?.kind === "thinking" && item.id === incomingBlock.id,
      );
      if (existingIndex === -1) {
        return [...mergedBlocks, incomingBlock];
      }

      const nextBlocks = [...mergedBlocks];
      nextBlocks[existingIndex] = mergeThinkingTraceBlock(
        nextBlocks[existingIndex],
        incomingBlock,
      );
      return nextBlocks;
    }

    if (incomingBlock.kind !== "tool") {
      return mergedBlocks.some((item) => item.id === incomingBlock.id)
        ? mergedBlocks
        : [...mergedBlocks, incomingBlock];
    }

    const targetIndex = findMatchingToolBlockIndex(mergedBlocks, incomingBlock);
    if (targetIndex === -1) {
      return mergedBlocks.some((item) => item.id === incomingBlock.id)
        ? mergedBlocks
        : [...mergedBlocks, incomingBlock];
    }

    const nextBlocks = [...mergedBlocks];
    nextBlocks[targetIndex] = mergeToolTraceBlock(nextBlocks[targetIndex], incomingBlock);
    return nextBlocks;
  }, [...existingBlocks]);
}

function mergeResponseTraceBlock(existingBlock: any, incomingBlock: any) {
  if (incomingBlock.replaceContent) {
    return {
      ...existingBlock,
      ...incomingBlock,
      content: incomingBlock.content || "",
    };
  }

  return {
    ...existingBlock,
    content: mergeStreamingText(existingBlock.content || "", incomingBlock.content || ""),
  };
}

function mergeThinkingTraceBlock(existingBlock: any, incomingBlock: any) {
  if (incomingBlock.replaceContent) {
    return {
      ...existingBlock,
      ...incomingBlock,
      content: incomingBlock.content || "",
    };
  }

  return {
    ...existingBlock,
    ...incomingBlock,
    content: mergeStreamingText(existingBlock.content || "", incomingBlock.content || ""),
  };
}

function findMatchingToolBlockIndex(blocks: any[], incomingBlock: any) {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const candidate = blocks[index];
    if (candidate?.kind !== "tool") {
      continue;
    }

    const candidateKey = candidate.toolCallId || candidate.toolName || candidate.title;
    const incomingKey =
      incomingBlock.toolCallId || incomingBlock.toolName || incomingBlock.title;
    if (!candidateKey || !incomingKey || candidateKey !== incomingKey) {
      continue;
    }

    if (incomingBlock.inputContent && candidate.inputContent) {
      continue;
    }
    if (incomingBlock.outputContent && candidate.outputContent) {
      continue;
    }

    return index;
  }

  return -1;
}

function mergeToolTraceBlock(existingBlock: any, incomingBlock: any) {
  const inputContent = existingBlock.inputContent || incomingBlock.inputContent || "";
  const outputContent = existingBlock.outputContent || incomingBlock.outputContent || "";

  return {
    ...existingBlock,
    title: existingBlock.title || incomingBlock.title,
    subtitle: "工具调用",
    icon: "fa-screwdriver-wrench",
    toolName: existingBlock.toolName || incomingBlock.toolName,
    toolCallId: existingBlock.toolCallId || incomingBlock.toolCallId,
    inputContent,
    outputContent,
    content: inputContent || outputContent || existingBlock.content || incomingBlock.content,
  };
}

function normalizeToolPayload(rawValue: any) {
  if (!rawValue) {
    return "";
  }

  if (typeof rawValue !== "string") {
    return `\`\`\`json\n${JSON.stringify(rawValue, null, 2)}\n\`\`\``;
  }

  const trimmed = rawValue.trim();
  if (!trimmed) {
    return "";
  }

  const parsed = parseJsonSafely(trimmed);
  if (!parsed) {
    return `\`\`\`\n${trimmed}\n\`\`\``;
  }

  if (Array.isArray(parsed)) {
    const textContent = parsed
      .map((item: any) => (item?.type === "text" && item?.text ? item.text : ""))
      .filter(Boolean)
      .join("\n\n")
      .trim();
    if (textContent) {
      return textContent;
    }
  }

  return `\`\`\`json\n${JSON.stringify(parsed, null, 2)}\n\`\`\``;
}

function parseJsonSafely(rawValue: string) {
  try {
    return JSON.parse(rawValue);
  } catch {
    return null;
  }
}

function normalizeContentToText(
  content: any,
  target: "text" | "thinking" = "text",
): string {
  if (!content) {
    return "";
  }
  if (typeof content === "string") {
    return target === "text" ? content : "";
  }
  if (Array.isArray(content)) {
    return content
      .map((item) => normalizeContentToText(item, target))
      .filter((item) => item !== "")
      .join("\n");
  }
  if (typeof content === "object") {
    if (target === "thinking" && typeof content.thinking === "string") {
      return content.thinking;
    }
    if (typeof content.text === "string") {
      return target === "text" ? content.text : "";
    }
    if (typeof content.content === "string") {
      return target === "text" ? content.content : "";
    }
    if (Array.isArray(content.content)) {
      return normalizeContentToText(content.content, target);
    }
  }
  return "";
}

function sanitizeRemoteUserText(content: string) {
  const normalized = String(content || "");
  if (
    normalized.includes(PORTAL_FAULT_WORKORDER_MARKER) &&
    normalized.includes("\n---\n")
  ) {
    const segments = normalized.split(/\n---\n/);
    const candidate = segments[segments.length - 1]?.trim();
    return candidate || normalized;
  }

  if (
    normalized.includes(PORTAL_ALARM_ANALYST_CARD_MARKER) &&
    normalized.includes("\n---\n")
  ) {
    const segments = normalized.split(/\n---\n/);
    const candidate = segments[segments.length - 1]?.trim();
    return candidate || normalized;
  }

  if (!normalized.includes("# BOOTSTRAP MODE") || !normalized.includes("\n---")) {
    return normalized;
  }

  const segments = normalized.split(/\n---\n/);
  const candidate = segments[segments.length - 1]?.trim();
  return candidate || normalized;
}

export function extractPortalActionPayload(content: string) {
  const rawContent = unwrapOuterMarkdownFence(String(content || ""));
  const match = rawContent.match(/```portal-action\s*([\s\S]*?)```/i);
  if (match?.[1]) {
    try {
      return normalizeDisposalOperationPayload(JSON.parse(match[1].trim()));
    } catch {
      return null;
    }
  }

  return inferFaultDisposalActionFromContent(rawContent);
}

export function unwrapPortalInspectionCardContent(content: string) {
  const normalized = String(content || "");
  if (
    normalized.includes(PORTAL_INSPECTION_CARD_MARKER)
    && normalized.includes("\n---\n")
  ) {
    const segments = normalized.split(/\n---\n/);
    const markerIndex = segments.findIndex((segment) => segment.includes(PORTAL_INSPECTION_CARD_MARKER));
    if (markerIndex !== -1) {
      let fallback = "";
      for (const segment of segments.slice(markerIndex + 1)) {
        const candidate = segment.trim();
        if (!candidate) {
          continue;
        }
        if (!fallback) {
          fallback = candidate;
        }
        if (
          /(?:^|\n)##+\s*.*巡检结果/u.test(candidate)
          || /(?:^|\n)##+\s*.*健康状态评估/u.test(candidate)
        ) {
          return candidate;
        }
      }
      const combined = segments
        .slice(markerIndex + 1)
        .map((segment) => segment.trim())
        .filter(Boolean)
        .join("\n\n---\n\n");
      if (combined) {
        return combined;
      }
      if (fallback) {
        return fallback;
      }
    }
  }
  return normalized;
}

export function unwrapPortalAlarmAnalystCardContent(content: string) {
  const normalized = String(content || "");
  if (
    normalized.includes(PORTAL_ALARM_ANALYST_CARD_MARKER)
    && normalized.includes("\n---\n")
  ) {
    const segments = normalized.split(/\n---\n/);
    const markerIndex = segments.findIndex((segment) => segment.includes(PORTAL_ALARM_ANALYST_CARD_MARKER));
    if (markerIndex !== -1) {
      const afterMarker = segments.slice(markerIndex + 1).filter((s) => s.trim());
      if (afterMarker.length > 0) {
        // Look for a segment that contains the report heading
        const reportIdx = afterMarker.findIndex((s) => /(?:^|\n)##+\s*.*告警分析报告/u.test(s));
        if (reportIdx !== -1) {
          // Join from the report heading segment onwards so the
          // summary table (which may be in a later segment) is kept.
          return afterMarker.slice(reportIdx).join("\n\n");
        }
        // No explicit report heading — rejoin all segments after marker
        return afterMarker.join("\n\n");
      }
    }
  }
  return normalized;
}

function inferFaultDisposalActionFromContent(content: string) {
  const normalized = String(content || "");
  if (!/终止异常慢\s*SQL\s*会话|终止慢\s*SQL\s*会话|杀掉慢\s*SQL/iu.test(normalized)) {
    return null;
  }

  const rootCauseWorkorderNo =
    extractLabeledValue(normalized, ["根因工单", "关联工单"]) || "";
  const sqlId = extractLabeledValue(normalized, ["SQL_ID", "SQL ID", "SQLId"]) || "";
  const sessionId = extractLabeledValue(normalized, ["会话ID", "会话 Id", "Session ID"]) || "";
  const locateName = extractLabeledValue(normalized, ["实例", "定位对象"]) || "";
  const deviceName = extractLabeledValue(normalized, ["设备", "设备名称"]) || "";
  const manageIp = extractLabeledValue(normalized, ["管理 IP", "设备 IP", "IP"]) || "";
  const targetSummary =
    extractLabeledValue(normalized, ["处置对象", "目标对象"]) || "数据库核心业务查询慢 SQL 会话";

  if (!rootCauseWorkorderNo || !sqlId || !sessionId) {
    return null;
  }

  return normalizeDisposalOperationPayload({
    id: `kill-slow-sql-${rootCauseWorkorderNo}`,
    type: "kill-slow-sql",
    title: "建议执行：终止异常慢 SQL 会话",
    summary:
      "慢 SQL 会话持续占用数据库连接，已经造成应用实例连接池排队。建议先终止异常会话，再继续观察接口时延和连接池恢复情况。",
    status: "ready",
    riskLevel: "medium",
    sessionId,
    sqlId,
    targetSummary,
    sourceWorkorderNo: "",
    rootCauseWorkorderNo,
    deviceName,
    manageIp,
    locateName,
  });
}

function extractLabeledValue(content: string, labels: string[]) {
  for (const label of labels) {
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const patterns = [
      new RegExp(`${escaped}\\s*[：:]\\s*([^\\n|]+)`, "iu"),
      new RegExp(`\\|\\s*${escaped}\\s*\\|\\s*([^|\\n]+)`, "iu"),
    ];

    for (const pattern of patterns) {
      const match = content.match(pattern);
      const value = match?.[1]?.trim();
      if (value) {
        return value;
      }
    }
  }

  return "";
}

export function buildSessionTitle(employeeName: string, nextMessages: any[]) {
  const firstUserMessage = nextMessages.find((item) => item.type === "user");
  if (!firstUserMessage) {
    return `${employeeName} · ${new Date().toLocaleString("zh-CN")}`;
  }
  return `${employeeName} · ${firstUserMessage.content.slice(0, 24)}`;
}

export function formatChatStatus(status: string) {
  if (status === "running") {
    return "进行中";
  }
  if (status === "idle") {
    return "已完成";
  }
  return status || "未知";
}

export function getPortalSessionPrefix(employeeId: string) {
  return `portal-${employeeId}-`;
}

function isCrossAgentSessionForEmployee(chat: any, employeeId: string) {
  const segments = String(chat?.session_id || "").split(":");
  return segments.length >= 4 && segments[1] === "to" && segments[2] === employeeId;
}

function isRemoteSessionForEmployee(chat: any, employeeId: string) {
  const sessionId = String(chat?.session_id || "");
  return sessionId.startsWith(getPortalSessionPrefix(employeeId))
    || isCrossAgentSessionForEmployee(chat, employeeId);
}

function getEmployeeNameByAgentId(agentId: string) {
  const employee = digitalEmployees.find((item) => item.id === agentId);
  return employee?.name || agentId;
}

function buildRemoteSessionDedupeKey(chat: any, employeeId: string) {
  return String(chat?.session_id || chat?.id || Math.random());
}

function isFaultWorkbenchChat(chat: any) {
  return String(chat?.meta?.source || "") === "portal-fault-workorder";
}

function buildCrossAgentSessionTitle(chat: any, employeeId: string) {
  if (!isCrossAgentSessionForEmployee(chat, employeeId)) {
    return "";
  }

  const rawName = String(chat?.name || "").trim();
  if (!rawName) {
    return "";
  }

  const cleaned = rawName
    .replace(/^\[(?:Agent|来自智能体)\s+[^\]]+\]\s*/i, "")
    .replace(/^User explicitly asked to consult [\w-]+\.?\s*/i, "")
    .trim();

  if (cleaned && cleaned !== rawName) {
    return cleaned.slice(0, 24);
  }

  if (/^\[(?:Agent|来自智能体)\s+/i.test(rawName)) {
    const sourceAgentId = String(chat?.session_id || "").split(":")[0] || "";
    return `${getEmployeeNameByAgentId(sourceAgentId)}协同会话`;
  }

  return rawName;
}

function buildRemoteSessionTitle(chat: any, employeeId: string) {
  if (employeeId === "fault" && isFaultWorkbenchChat(chat)) {
    const workorderNo = String(chat?.meta?.workorderNo || "").trim();
    const title = String(chat?.meta?.title || "").trim();
    if (workorderNo && title) {
      return `故障处置 · ${title} · ${workorderNo}`;
    }
    if (workorderNo) {
      return `故障处置 · ${workorderNo}`;
    }
  }
  const collaborationTitle = buildCrossAgentSessionTitle(chat, employeeId);
  if (collaborationTitle) {
    return collaborationTitle;
  }
  return chat?.name || "未命名会话";
}

function buildRemoteSessionDetail(chat: any) {
  const statusLabel = formatChatStatus(chat?.status);
  const workorderNo = String(chat?.meta?.workorderNo || "").trim();
  if (workorderNo) {
    return `工单：${workorderNo} · 状态：${statusLabel}`;
  }
  return `状态：${statusLabel}`;
}

export function normalizeMarkdownDisplayContent(
  content: string,
  { isStreaming = false }: { isStreaming?: boolean } = {},
) {
  let normalized = normalizeOperationalMarkdownSections(
    unwrapOuterMarkdownFence(String(content || "")),
  )
    .replace(/```portal-action\s*[\s\S]*?```/gi, "")
    .replace(/<br\s*\/?>\s*<br\s*\/?>/gi, "\n\n")
    .replace(/<br\s*\/?>/gi, "  \n")
    .replace(/\n{3,}/g, "\n\n");

  if (isStreaming) {
    normalized = normalized
      .replace(/```echarts\s*[\s\S]*?```/gi, "")
      .replace(/```portal-visualization\s*[\s\S]*?```/gi, "")
      .replace(/```portal-action[\s\S]*$/i, "")
      .replace(/```(?:json|js|javascript|ts|typescript)\s*([\s\S]*?)```/gi, (fullMatch, raw) =>
        looksLikeEChartsConfig(raw) ? "" : fullMatch,
      )
      .replace(/```echarts[\s\S]*$/i, "\n\n> 图表加载中，正在生成可视化配置...\n\n")
      .replace(/```portal-visualization[\s\S]*$/i, "\n\n> 图表加载中，正在生成可视化配置...\n\n");
  } else {
    normalized = normalized.replace(/```(?:echarts|portal-visualization)\s*[\s\S]*?```/gi, "");
    normalized = normalized.replace(/```(?:json|js|javascript|ts|typescript)\s*([\s\S]*?)```/gi, (fullMatch, raw) => {
      return looksLikeEChartsConfig(raw) ? "" : fullMatch;
    });
  }

  return normalized;
}

function normalizeMarkdownStructure(
  content: string,
  { isStreaming = false }: { isStreaming?: boolean } = {},
) {
  const segments = splitMarkdownByCodeFence(content);
  const normalized = segments
    .map((segment) =>
      segment.type === "code"
        ? segment.content
        : normalizeMarkdownTextSegment(segment.content, { isStreaming }),
    )
    .join("");

  return isStreaming ? closeUnbalancedMarkdownFence(normalized) : normalized;
}

function splitMarkdownByCodeFence(content: string) {
  const lines = String(content || "").split("\n");
  const segments: Array<{ type: "text" | "code"; content: string }> = [];
  const textBuffer: string[] = [];
  const codeBuffer: string[] = [];
  let activeFence = "";

  const flushText = () => {
    if (!textBuffer.length) {
      return;
    }
    segments.push({ type: "text", content: `${textBuffer.join("\n")}\n` });
    textBuffer.length = 0;
  };

  const flushCode = () => {
    if (!codeBuffer.length) {
      return;
    }
    segments.push({ type: "code", content: `${codeBuffer.join("\n")}\n` });
    codeBuffer.length = 0;
  };

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    const fenceMatch = trimmed.match(/^(`{3,}|~{3,})/);

    if (activeFence) {
      codeBuffer.push(line);
      if (fenceMatch && trimmed.startsWith(activeFence)) {
        activeFence = "";
        flushCode();
      }
      return;
    }

    if (fenceMatch) {
      flushText();
      activeFence = fenceMatch[1];
      codeBuffer.push(line);
      if (index === lines.length - 1 && !activeFence) {
        flushCode();
      }
      return;
    }

    textBuffer.push(line);
  });

  if (codeBuffer.length) {
    flushCode();
  }
  if (textBuffer.length) {
    flushText();
  }

  return segments;
}

function normalizeMarkdownTextSegment(
  content: string,
  { isStreaming = false }: { isStreaming?: boolean } = {},
) {
  let normalized = String(content || "").replace(/\r\n?/g, "\n");

  normalized = normalized
    .replace(/([^\n])((?:#{1,6})(?=\s*[^\s#]))/g, "$1\n\n$2")
    .replace(/([^\n])((?:[-*+]\s+[^\s]|\d+\.\s+[^\s]))/g, "$1\n$2")
    .replace(/([^\n])(```)/g, "$1\n\n$2")
    .replace(/(^|\n)(#{1,6})(?=\S)/g, "$1$2 ")
    .replace(/(^|\n)([-*+])(?=\S)/g, "$1$2 ")
    .replace(/(^|\n)(\d+)\.(?=\S)/g, "$1$2. ");

  if (isStreaming) {
    normalized = normalized.replace(/\n{4,}/g, "\n\n\n");
  }

  return normalized;
}

function closeUnbalancedMarkdownFence(content: string) {
  const lines = String(content || "").split("\n");
  let activeFence = "";

  for (const line of lines) {
    const trimmed = line.trim();
    const fenceMatch = trimmed.match(/^(`{3,}|~{3,})/);
    if (!fenceMatch) {
      continue;
    }

    const fence = fenceMatch[1];
    if (activeFence && trimmed.startsWith(activeFence)) {
      activeFence = "";
      continue;
    }

    if (!activeFence) {
      activeFence = fence;
    }
  }

  if (!activeFence) {
    return content;
  }

  const suffix = content.endsWith("\n") ? "" : "\n";
  return `${content}${suffix}${activeFence}`;
}

function normalizeOperationalMarkdownSections(content: string) {
  let normalized = String(content || "");
  normalized = normalizeEvidencePipeTable(normalized);
  return normalized;
}

function normalizeEvidencePipeTable(content: string) {
  const lines = String(content || "").split("\n");
  const result: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    result.push(line);

    if (!/^\s*[*#>\-0-9.\s]*关键证据\s*$/u.test(line.trim())) {
      continue;
    }

    const sectionLines: string[] = [];
    let cursor = index + 1;
    while (cursor < lines.length) {
      const candidate = lines[cursor];
      const trimmed = candidate.trim();
      if (!trimmed) {
        sectionLines.push(candidate);
        cursor += 1;
        continue;
      }
      if (/^\s*[*#>\-0-9.\s]*[\u{1F300}-\u{1FAFF}\u2600-\u27BF]?\s*[^\s].*$/u.test(trimmed) && !trimmed.includes("|") && sectionLines.length) {
        break;
      }
      if (/^\s*[*#>\-0-9.\s]*故障链路\s*$/u.test(trimmed) || /^\s*[*#>\-0-9.\s]*下一步\s*$/u.test(trimmed)) {
        break;
      }
      sectionLines.push(candidate);
      cursor += 1;
    }

    const flattened = sectionLines
      .map((item) => item.trim())
      .filter(Boolean)
      .join(" ");
    const tableMarkdown = buildPipeEvidenceTable(flattened);
    if (!tableMarkdown) {
      continue;
    }

    result.push("");
    result.push(tableMarkdown);
    result.push("");
    index = cursor - 1;
  }

  return result.join("\n");
}

function buildPipeEvidenceTable(content: string) {
  const raw = String(content || "").trim();
  if (!raw || !raw.includes("|")) {
    return "";
  }

  const tokens = raw
    .split("|")
    .map((item) => item.replace(/\s+/g, " ").trim())
    .filter((item) => item && !/^-+$/.test(item));

  if (tokens.length < 6) {
    return "";
  }

  const headerCount =
    tokens[0] === "指标" && tokens[1] === "观测值" && tokens[2] === "状态"
      ? 3
      : 0;
  if (!headerCount) {
    return "";
  }

  const rows = [];
  for (let index = headerCount; index < tokens.length; index += 3) {
    const row = tokens.slice(index, index + 3);
    if (row.length < 3) {
      break;
    }
    rows.push(`| ${row[0]} | ${row[1]} | ${row[2]} |`);
  }

  if (!rows.length) {
    return "";
  }

  return [
    "| 指标 | 观测值 | 状态 |",
    "| --- | --- | --- |",
    ...rows,
  ].join("\n");
}

export function extractVisualBlocks(content: string): VisualBlock[] {
  const normalized = unwrapOuterMarkdownFence(String(content || ""));
  const matches = normalized.matchAll(/```([\w-]+)?\s*([\s\S]*?)```/gi);
  const blocks: VisualBlock[] = [];

  for (const match of matches) {
    const type = String(match[1] || "").toLowerCase();
    const raw = String(match[2] || "").trim();
    if (!raw) {
      continue;
    }
    if (
      type === "echarts"
      || (
        ["json", "js", "javascript", "ts", "typescript"].includes(type)
        && looksLikeEChartsConfig(raw)
      )
    ) {
      blocks.push({
        type: "echarts",
        raw,
      });
      continue;
    }
    if (type === "portal-visualization") {
      blocks.push({
        type: "portal-visualization",
        raw,
      });
    }
  }

  return blocks;
}

export type RenderableContentSegment =
  | {
      type: "markdown";
      content: string;
    }
  | ({
      type: "echarts" | "portal-visualization";
    } & VisualBlock);

export function extractRenderableContentSegments(content: string): RenderableContentSegment[] {
  const normalized = unwrapOuterMarkdownFence(String(content || ""));
  const segments = splitMarkdownByCodeFence(normalized);
  const result: RenderableContentSegment[] = [];

  const pushMarkdown = (segmentContent: string) => {
    if (!segmentContent) {
      return;
    }

    const previous = result[result.length - 1];
    if (previous?.type === "markdown") {
      previous.content += segmentContent;
      return;
    }

    result.push({
      type: "markdown",
      content: segmentContent,
    });
  };

  segments.forEach((segment) => {
    if (segment.type === "text") {
      pushMarkdown(segment.content);
      return;
    }

    const visualBlock = extractVisualBlockFromFence(segment.content);
    if (visualBlock) {
      result.push(visualBlock);
      return;
    }

    pushMarkdown(segment.content);
  });

  return result;
}

function extractVisualBlockFromFence(content: string): VisualBlock | null {
  const normalized = String(content || "").trim();
  if (!normalized) {
    return null;
  }

  const fenceMatch = normalized.match(
    /^(`{3,}|~{3,})([\w-]+)?\s*\n([\s\S]*?)\n\1\s*$/i,
  );
  if (!fenceMatch) {
    return null;
  }

  const type = String(fenceMatch[2] || "").toLowerCase();
  const raw = String(fenceMatch[3] || "").trim();
  if (!raw) {
    return null;
  }

  if (type === "echarts" || (type === "json" && looksLikeEChartsConfig(raw))) {
    return {
      type: "echarts",
      raw,
    };
  }

  if (type === "portal-visualization") {
    return {
      type: "portal-visualization",
      raw,
    };
  }

  return null;
}

function unwrapOuterMarkdownFence(content: string) {
  const normalized = String(content || "").trim();
  if (!normalized) {
    return "";
  }

  const lines = normalized.split("\n");
  const openingLine = lines[0]?.trim() || "";
  const openingMatch = openingLine.match(/^(`{3,}|~{3,})(?:markdown|md|text)?\s*$/i);
  if (!openingMatch) {
    return normalized;
  }

  const fence = openingMatch[1];
  const bodyLines = lines.slice(1);
  const lastLine = bodyLines[bodyLines.length - 1]?.trim() || "";
  if (lastLine === fence) {
    bodyLines.pop();
  }

  return bodyLines.join("\n").trim();
}
