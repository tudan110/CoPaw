import { useCallback, useMemo, useRef, useState } from "react";
import { digitalEmployees } from "../../data/portalData";
import { saveConversationStore } from "../../lib/conversationStore";
import {
  queryKnowledgeBase,
  synthesizeKnowledgeAnswer,
  type KnowledgeEvidence,
  type KnowledgeQueryResponse,
} from "../../api/knowledgeBase";
import {
  type PortalAdvancedPanel,
  type PortalView,
} from "./helpers";
import {
  KNOWLEDGE_BASE_OWNER_ID,
  KNOWLEDGE_BASE_SEARCH_COMMAND,
  buildKnowledgeBaseSessionRecord,
  createKnowledgeBaseFlowId,
  ensureObjectArray,
  ensureSessionRecords,
  isKnowledgeBaseIntent,
} from "./pageHelpers";
import type {
  ConversationStoreState,
  PortalLocationState,
  SessionRecord,
} from "./pageHelpers";
import { readKnowledgeAiThresholdRatio } from "./knowledgeBaseSettings";

type MessageRecord = { id: string; knowledgeBaseFlow?: Record<string, any> } & Record<string, any>;
type KnowledgeBaseRun = {
  id: string;
  controller: AbortController;
  agentMessageId: string;
  sessionId: string;
  visibleContent: string;
};

type NavigateToEmployeePage = (
  employee: any,
  options?: {
    entry?: string | null;
    view?: PortalView;
    panel?: PortalAdvancedPanel | null;
    replace?: boolean;
    state?: PortalLocationState;
  },
) => void;

function resolveInitialMode(content: string): "upload" | "manual" {
  if (/手动|沉淀|记录|新增|保存经验|录入/.test(content)) {
    return "manual";
  }
  return "upload";
}

function resolveInitialQuery(content: string) {
  const normalized = String(content || "").trim();
  if (!normalized || isKnowledgeBaseIntent(normalized)) {
    return "";
  }
  return normalized.replace(/^@?知识专员\s*/u, "").trim();
}

function formatEvidence(evidence: KnowledgeEvidence, index: number) {
  const title = evidence.citation?.source_label || evidence.chunk_summary || evidence.evidence_id || `证据 ${index + 1}`;
  const locator = evidence.citation?.locator || evidence.citation?.source_scope_label || "-";
  const confidence = typeof evidence.confidence_score === "number"
    ? `${Math.round(evidence.confidence_score * 100)}%`
    : "-";
  const summary = evidence.chunk_text || evidence.chunk_summary || "暂无摘要";
  const normalizeCell = (value: string) => String(value || "-")
    .replace(/\|/g, "\\|")
    .replace(/\s+/g, " ")
    .trim();
  const clip = (value: string, maxLength: number) => {
    const text = normalizeCell(value);
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  };
  return [
    String(index + 1),
    clip(title, 34),
    clip(locator, 36),
    confidence,
    clip(summary, 96),
  ].join(" | ");
}

function formatKnowledgeResult(query: string, result: KnowledgeQueryResponse) {
  const lines = [
    "### 知识库检索",
    "",
    `**问题：** ${query}`,
    "",
    "#### 结论摘要",
    result.summary || result.evidence_boundary_statement || "当前没有在知识库中找到足够相关的资料。",
  ];
  const evidence = result.relevant_evidence || [];
  if (evidence.length) {
    lines.push(
      "",
      "#### 命中证据",
      "",
      "# | 来源 | 位置 | 置信度 | 命中片段",
      "--- | --- | --- | --- | ---",
      ...evidence.slice(0, 5).map(formatEvidence),
    );
  }
  if (result.evidence_boundary_statement) {
    lines.push("", "#### 证据边界", result.evidence_boundary_statement);
  }
  return lines.join("\n");
}

function resolveEvidenceIds(result: KnowledgeQueryResponse) {
  return (result.relevant_evidence || [])
    .map((item) => String(item.evidence_id || "").trim())
    .filter(Boolean);
}

function normalizeEvidenceConfidence(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 1 ? value / 100 : value;
  }
  const text = String(value ?? "").trim();
  if (!text) {
    return 0;
  }
  const matched = text.match(/(\d+(?:\.\d+)?)/);
  if (!matched) {
    return 0;
  }
  const parsed = Number(matched[1]);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return text.includes("%") || parsed > 1 ? parsed / 100 : parsed;
}

function hasHighConfidenceEvidence(result: KnowledgeQueryResponse, thresholdRatio: number) {
  return (result.relevant_evidence || []).some((item) => (
    normalizeEvidenceConfidence(item.confidence_score ?? item.confidence_level)
      >= thresholdRatio
  ));
}

export function usePortalKnowledgeBase({
  conversationStore,
  setConversationStore,
  messages,
  setMessages,
  selectedEmployeeId,
  navigateToEmployeePage,
  setCurrentChatId,
  createAgentMessage,
  createUserMessage,
}: {
  conversationStore: ConversationStoreState;
  setConversationStore: React.Dispatch<React.SetStateAction<ConversationStoreState>>;
  messages: MessageRecord[];
  setMessages: React.Dispatch<React.SetStateAction<MessageRecord[]>>;
  selectedEmployeeId?: string;
  navigateToEmployeePage: NavigateToEmployeePage;
  setCurrentChatId: React.Dispatch<React.SetStateAction<string>>;
  createAgentMessage: (employee: any, payload: Record<string, any>) => MessageRecord;
  createUserMessage: (content: string) => MessageRecord;
}) {
  const [activePortalKnowledgeBaseSessionId, setActivePortalKnowledgeBaseSessionId] = useState("");
  const [isKnowledgeBaseRunning, setIsKnowledgeBaseRunning] = useState(false);
  const activeKnowledgeBaseRunRef = useRef<KnowledgeBaseRun | null>(null);
  const isKnowledgeBaseRunningRef = useRef(false);
  const knowledgeBaseEmployee = useMemo(
    () => digitalEmployees.find((item) => item.id === KNOWLEDGE_BASE_OWNER_ID) || null,
    [],
  );
  const portalKnowledgeBaseSessions = useMemo(
    () => ensureSessionRecords(conversationStore[KNOWLEDGE_BASE_OWNER_ID]),
    [conversationStore],
  );

  const upsertPortalSession = useCallback((
    employeeId: string,
    nextSession: SessionRecord,
  ) => {
    setConversationStore((prevStore) => {
      const previousSessions = ensureSessionRecords(prevStore[employeeId]);
      const currentSession = previousSessions.find((session) => session.id === nextSession.id) || null;
      if (
        currentSession
        && currentSession.messages === nextSession.messages
        && currentSession.status === nextSession.status
        && currentSession.detail === nextSession.detail
        && currentSession.title === nextSession.title
        && currentSession.tag === nextSession.tag
        && currentSession.meta?.visibleContent === nextSession.meta?.visibleContent
      ) {
        return prevStore;
      }

      const nextSessions = [
        nextSession,
        ...previousSessions.filter((session) => session.id !== nextSession.id),
      ];
      const nextStore: ConversationStoreState = {
        ...prevStore,
        [employeeId]: nextSessions,
      };
      saveConversationStore(nextStore);
      return nextStore;
    });
  }, [setConversationStore]);

  const finishKnowledgeBaseRun = useCallback((runId: string) => {
    if (activeKnowledgeBaseRunRef.current?.id !== runId) {
      return false;
    }
    activeKnowledgeBaseRunRef.current = null;
    isKnowledgeBaseRunningRef.current = false;
    setIsKnowledgeBaseRunning(false);
    return true;
  }, []);

  const stopKnowledgeBaseTask = useCallback(() => {
    const activeRun = activeKnowledgeBaseRunRef.current;
    if (!activeRun) {
      return;
    }
    activeRun.controller.abort();
    activeKnowledgeBaseRunRef.current = null;
    isKnowledgeBaseRunningRef.current = false;
    setIsKnowledgeBaseRunning(false);

    if (!knowledgeBaseEmployee) {
      return;
    }

    setMessages((currentMessages) => {
      const nextMessages = ensureObjectArray<MessageRecord>(currentMessages).map((message) => (
        message.id === activeRun.agentMessageId
          ? {
              ...message,
              content: "本轮知识库任务已停止。你可以继续输入新的问题或重新发起检索。",
              knowledgeAnswer: false,
              knowledgeAnswerPayload: undefined,
            }
          : message
      ));
      const previousSessions = ensureSessionRecords(conversationStore[knowledgeBaseEmployee.id]);
      const previous = previousSessions.find((session) => session.id === activeRun.sessionId) || null;
      upsertPortalSession(
        knowledgeBaseEmployee.id,
        buildKnowledgeBaseSessionRecord(knowledgeBaseEmployee, nextMessages, {
          sessionId: activeRun.sessionId,
          previous,
          visibleContent: activeRun.visibleContent,
        }),
      );
      return nextMessages;
    });
  }, [
    conversationStore,
    knowledgeBaseEmployee,
    setMessages,
    upsertPortalSession,
  ]);

  const updateKnowledgeBaseFlowMessage = useCallback((
    messageId: string,
    patch: Record<string, any>,
  ) => {
    if (!knowledgeBaseEmployee) {
      return;
    }

    setMessages((currentMessages) => {
      const nextMessages = ensureObjectArray<MessageRecord>(currentMessages).map((message) => (
        message.id === messageId
          ? {
              ...message,
              knowledgeBaseFlow: {
                ...(message.knowledgeBaseFlow || {}),
                ...patch,
              },
            }
          : message
      ));
      const previousSessions = ensureSessionRecords(conversationStore[knowledgeBaseEmployee.id]);
      const previous = previousSessions.find((session) => session.id === activePortalKnowledgeBaseSessionId) || null;
      if (activePortalKnowledgeBaseSessionId || previous) {
        const nextSession = buildKnowledgeBaseSessionRecord(knowledgeBaseEmployee, nextMessages, {
          sessionId: activePortalKnowledgeBaseSessionId || previous?.id,
          previous,
        });
        upsertPortalSession(knowledgeBaseEmployee.id, nextSession);
      }
      return nextMessages;
    });
  }, [
    activePortalKnowledgeBaseSessionId,
    conversationStore,
    knowledgeBaseEmployee,
    setMessages,
    upsertPortalSession,
  ]);

  const searchKnowledgeBaseConversation = useCallback(async (visibleContent = KNOWLEDGE_BASE_SEARCH_COMMAND) => {
    if (!knowledgeBaseEmployee) {
      return;
    }

    if (isKnowledgeBaseRunningRef.current) {
      return;
    }

    if (selectedEmployeeId !== KNOWLEDGE_BASE_OWNER_ID) {
      navigateToEmployeePage(knowledgeBaseEmployee, {
        entry: null,
        view: "chat",
        panel: null,
        state: {
          gatewayPresentationEmployeeId: knowledgeBaseEmployee.id,
          pendingKnowledgeSearch: {
            token: `pending-knowledge-search-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            targetEmployeeId: knowledgeBaseEmployee.id,
            visibleContent,
          },
        } satisfies PortalLocationState,
      });
      return;
    }

    const query = resolveInitialQuery(visibleContent);
    const userMessage = createUserMessage(visibleContent);
    const agentMessage = createAgentMessage(knowledgeBaseEmployee, {
      content: query
        ? `正在检索知识库：**${query}**`
        : "• 知识上传 - 本地各类知识上传归档  \n" +
          "• 知识问答 - 回答各类运维技术问题  \n" +
          "• 方案推荐 - 基于历史案例推荐最佳处置方案  \n" +
          "• 故障案例 - 检索相似故障的处理经验  \n" +
          "• 最佳实践 - 提供各技术栈的最佳实践建议",
      knowledgeAnswer: Boolean(query),
    });
    const initialMessages = [
      ...ensureObjectArray<MessageRecord>(messages),
      userMessage,
      agentMessage,
    ];
    const initialSession = buildKnowledgeBaseSessionRecord(
      knowledgeBaseEmployee,
      initialMessages,
      { visibleContent },
    );
    setActivePortalKnowledgeBaseSessionId(initialSession.id);
    setCurrentChatId("");
    setMessages(initialMessages);
    upsertPortalSession(knowledgeBaseEmployee.id, initialSession);

    if (!query) {
      return;
    }

    const controller = new AbortController();
    const runId = `knowledge-run-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeKnowledgeBaseRunRef.current = {
      id: runId,
      controller,
      agentMessageId: agentMessage.id,
      sessionId: initialSession.id,
      visibleContent,
    };
    isKnowledgeBaseRunningRef.current = true;
    setIsKnowledgeBaseRunning(true);

    try {
      const result = await queryKnowledgeBase(query, {}, controller.signal);
      if (activeKnowledgeBaseRunRef.current?.id !== runId) {
        return;
      }
      const thresholdRatio = readKnowledgeAiThresholdRatio();
      const thresholdPercent = Math.round(thresholdRatio * 100);
      const hasConfidentEvidence = hasHighConfidenceEvidence(result, thresholdRatio);
      if (hasConfidentEvidence) {
        const completedMessages = initialMessages.map((message) => (
          message.id === agentMessage.id
            ? {
                ...message,
                content: formatKnowledgeResult(query, result),
                knowledgeAnswer: true,
                knowledgeAnswerPayload: {
                  query,
                  result,
                  synthesis: {
                    skipped: true,
                    reason: `命中证据置信度达到 ${thresholdPercent}%，已直接返回知识库检索结果。`,
                  },
                },
              }
            : message
        ));
        setMessages(completedMessages);
        upsertPortalSession(
          knowledgeBaseEmployee.id,
          buildKnowledgeBaseSessionRecord(knowledgeBaseEmployee, completedMessages, {
            sessionId: initialSession.id,
            previous: initialSession,
            visibleContent,
          }),
        );
        return;
      }

      const searchedMessages = initialMessages.map((message) => (
        message.id === agentMessage.id
          ? {
              ...message,
              content: `${formatKnowledgeResult(query, result)}\n\n#### AI 总结\n正在调用当前 active 模型生成总结...`,
              knowledgeAnswer: true,
              knowledgeAnswerPayload: {
                query,
                result,
              },
            }
          : message
      ));
      setMessages(searchedMessages);
      upsertPortalSession(
        knowledgeBaseEmployee.id,
        buildKnowledgeBaseSessionRecord(knowledgeBaseEmployee, searchedMessages, {
          sessionId: initialSession.id,
          previous: initialSession,
          visibleContent,
        }),
      );

      let synthesis: Record<string, any> = {};
      try {
        synthesis = await synthesizeKnowledgeAnswer(
          query,
          resolveEvidenceIds(result),
          KNOWLEDGE_BASE_OWNER_ID,
          controller.signal,
        );
      } catch (error) {
        if (controller.signal.aborted || activeKnowledgeBaseRunRef.current?.id !== runId) {
          return;
        }
        synthesis = {
          answer: "",
          error: error instanceof Error ? error.message : "AI 总结生成失败",
        };
      }
      const completedMessages = searchedMessages.map((message) => (
        message.id === agentMessage.id
          ? {
              ...message,
              content: formatKnowledgeResult(query, result),
              knowledgeAnswer: true,
              knowledgeAnswerPayload: {
                query,
                result,
                answer: String(synthesis.answer || ""),
                synthesis,
              },
            }
          : message
      ));
      setMessages(completedMessages);
      upsertPortalSession(
        knowledgeBaseEmployee.id,
        buildKnowledgeBaseSessionRecord(knowledgeBaseEmployee, completedMessages, {
          sessionId: initialSession.id,
          previous: initialSession,
          visibleContent,
        }),
      );
    } catch (error) {
      if (controller.signal.aborted || activeKnowledgeBaseRunRef.current?.id !== runId) {
        return;
      }
      const messageText = error instanceof Error ? error.message : "知识库检索失败";
      const failedMessages = initialMessages.map((message) => (
        message.id === agentMessage.id
          ? {
              ...message,
              content: `知识库检索失败：${messageText}`,
            }
          : message
      ));
      setMessages(failedMessages);
      upsertPortalSession(
        knowledgeBaseEmployee.id,
        buildKnowledgeBaseSessionRecord(knowledgeBaseEmployee, failedMessages, {
          sessionId: initialSession.id,
          previous: initialSession,
          visibleContent,
        }),
      );
    } finally {
      finishKnowledgeBaseRun(runId);
    }
  }, [
    createAgentMessage,
    createUserMessage,
    knowledgeBaseEmployee,
    messages,
    navigateToEmployeePage,
    selectedEmployeeId,
    setCurrentChatId,
    setMessages,
    finishKnowledgeBaseRun,
    upsertPortalSession,
  ]);

  const openKnowledgeBaseConversation = useCallback((visibleContent = KNOWLEDGE_BASE_SEARCH_COMMAND) => {
    if (!knowledgeBaseEmployee) {
      return;
    }

    if (selectedEmployeeId === KNOWLEDGE_BASE_OWNER_ID) {
      const flowId = createKnowledgeBaseFlowId();
      const initialMode = resolveInitialMode(visibleContent);
      const nextMessages = [
        ...ensureObjectArray<MessageRecord>(messages),
        createUserMessage(visibleContent),
        createAgentMessage(knowledgeBaseEmployee, {
          content: "",
          knowledgeBaseFlow: {
            flowId,
            stage: "intro",
            mode: initialMode,
            status: "idle",
            autoRun: false,
          },
        }),
      ];
      const nextSession = buildKnowledgeBaseSessionRecord(
        knowledgeBaseEmployee,
        nextMessages,
        { visibleContent },
      );
      setActivePortalKnowledgeBaseSessionId(nextSession.id);
      setCurrentChatId("");
      setMessages(nextMessages);
      upsertPortalSession(knowledgeBaseEmployee.id, nextSession);
      return;
    }

    navigateToEmployeePage(knowledgeBaseEmployee, {
      entry: null,
      view: "chat",
      panel: null,
      state: {
        gatewayPresentationEmployeeId: knowledgeBaseEmployee.id,
        pendingKnowledgeBase: {
          token: `pending-knowledge-base-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          targetEmployeeId: knowledgeBaseEmployee.id,
          visibleContent,
        },
      } satisfies PortalLocationState,
    });
  }, [
    createAgentMessage,
    createUserMessage,
    knowledgeBaseEmployee,
    messages,
    navigateToEmployeePage,
    selectedEmployeeId,
    setCurrentChatId,
    setMessages,
    upsertPortalSession,
  ]);

  return {
    knowledgeBaseEmployee,
    portalKnowledgeBaseSessions,
    activePortalKnowledgeBaseSessionId,
    isKnowledgeBaseRunning,
    setActivePortalKnowledgeBaseSessionId,
    stopKnowledgeBaseTask,
    openKnowledgeBaseConversation,
    searchKnowledgeBaseConversation,
    updateKnowledgeBaseFlowMessage,
  };
}
