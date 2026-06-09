import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  createChat,
  getChatHistory,
  listChats,
  reconnectChat,
  stopChat,
  streamChat,
} from "../../api/copawChat";
import { getFaultDisposalHistory } from "../../api/faultDisposalBridge";
import {
  buildAlarmAnalystCardRequest,
  getAlarmAnalystReportMarkdown,
  mergeAlarmAnalystCards,
  shouldAttemptAlarmAnalystCardByContent,
  shouldEnableAlarmAnalystCards,
} from "../../alarm-analyst/shared";
import {
  buildThinkingBlock,
  buildResponseBlock,
  buildToolBlock,
  createAgentMessage,
  createRemoteSessionId,
  createUserMessage,
  extractCopawMessageText,
  isCopawReasoningMessage,
  mergeProcessBlocks,
  mergeStreamingText,
  normalizeRemoteHistoryMessages,
  normalizeRemoteSessions,
} from "./helpers";
import { isResourceImportIntent } from "./pageHelpers";
import { toFriendlyChatError } from "../../lib/chatErrorMessage";
import {
  createAlarmAnalystCard,
  listAlarmAnalystCards,
} from "../../api/alarmAnalystCards";
import {
  FAULT_SCENARIO_ANALYZING_PLACEHOLDER,
  maybeHandleFaultScenarioMessage,
} from "./faultScenario";

const COPAW_USER_ID = "default";
const COPAW_CHANNEL = "console";
const REMOTE_WAIT_BLOCK_ID = "portal-remote-waiting-status";

type FaultDisposalHistoryMessage = {
  id?: string;
  type?: string;
  content?: string;
  processBlocks?: unknown[];
  disposalOperation?: unknown;
  alarmAnalystCard?: unknown;
  backendMessageId?: string;
  enhancementSourceMessageId?: string;
  [key: string]: unknown;
};

type FaultDisposalHistory = {
  status?: string;
  messages?: FaultDisposalHistoryMessage[];
};

function normalizeRemoteChatErrorMessage(error: any) {
  return toFriendlyChatError(error);
}

function getPortalProgressSubtitle(stage: string) {
  switch (stage) {
    case "request_received":
      return "请求已进入后端";
    case "agent_started":
      return "Agent 已开始处理";
    case "waiting_first_event":
      return "等待首个模型事件";
    case "waiting_next_event":
      return "等待后续模型事件";
    default:
      return stage || "后端进度";
  }
}

function isRunningRemoteStatus(status: unknown) {
  return String(status || "").toLowerCase() === "running";
}

function findLastAgentMessage(messages: any[] = []) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.type === "agent") {
      return message;
    }
  }
  return null;
}

export function useRemoteChatSession({
  currentEmployee,
  isRemoteEmployee,
  remoteAgentId,
  setMessages,
}: {
  currentEmployee: any;
  isRemoteEmployee: boolean;
  remoteAgentId: string | null;
  setMessages: Dispatch<SetStateAction<any[]>>;
}) {
  const [currentSessionId, setCurrentSessionId] = useState("");
  const [currentChatId, setCurrentChatId] = useState("");
  const [currentChatStatus, setCurrentChatStatus] = useState("idle");
  const [historyVisible, setHistoryVisible] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [remoteSessions, setRemoteSessions] = useState<any[]>([]);
  const [isCreatingChat, setIsCreatingChat] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

  const streamAbortRef = useRef<AbortController | null>(null);
  const streamAbortNoticeModeRef = useRef<"show" | "silent" | null>(null);
  const activeAssistantMessageIdRef = useRef<string | null>(null);
  const streamAssistantMapRef = useRef(new Map());
  const streamMessageMetaRef = useRef(new Map());
  const streamPendingTextRef = useRef(new Map());
  const streamResponseTextRef = useRef(new Map());
  const remoteHistoryRequestIdRef = useRef(0);
  const pendingProcessBlocksRef = useRef(new Map());
  const streamProcessBlocksRef = useRef(new Map());
  const remoteWaitNoticeTimersRef = useRef<number[]>([]);
  const hasStreamOutputRef = useRef(false);
  const pendingResourceImportGuideRef = useRef(false);
  const flushTimerRef = useRef(0);
  const currentEmployeeRef = useRef(currentEmployee);
  const currentChatIdRef = useRef(currentChatId);
  const currentSessionIdRef = useRef(currentSessionId);
  const currentChatStatusRef = useRef(currentChatStatus);
  const currentChatMetaRef = useRef<any>(null);
  const isStreamingRef = useRef(isStreaming);
  const isCreatingChatRef = useRef(isCreatingChat);
  const remoteAgentIdRef = useRef(remoteAgentId);
  const isRemoteEmployeeRef = useRef(isRemoteEmployee);

  useEffect(
    () => () => {
      if (flushTimerRef.current) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = 0;
      }
      remoteWaitNoticeTimersRef.current.forEach((timer) => window.clearTimeout(timer));
      remoteWaitNoticeTimersRef.current = [];
      streamAbortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    currentEmployeeRef.current = currentEmployee;
  }, [currentEmployee]);

  useEffect(() => {
    currentChatIdRef.current = currentChatId;
  }, [currentChatId]);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  useEffect(() => {
    currentChatStatusRef.current = currentChatStatus;
  }, [currentChatStatus]);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    isCreatingChatRef.current = isCreatingChat;
  }, [isCreatingChat]);

  useEffect(() => {
    remoteAgentIdRef.current = remoteAgentId;
  }, [remoteAgentId]);

  useEffect(() => {
    isRemoteEmployeeRef.current = isRemoteEmployee;
  }, [isRemoteEmployee]);

  const ensureAgentContainer = (employee: any) => {
    let frontendMessageId = activeAssistantMessageIdRef.current;
    if (frontendMessageId) {
      return frontendMessageId;
    }

    frontendMessageId = `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeAssistantMessageIdRef.current = frontendMessageId;
    setMessages((prevMessages) => [
      ...prevMessages,
      createAgentMessage(employee, {
        id: frontendMessageId,
        content: "",
        resourceImportGuide: pendingResourceImportGuideRef.current,
      }),
    ]);
    streamResponseTextRef.current.set(frontendMessageId, new Map());
    streamProcessBlocksRef.current.set(frontendMessageId, []);
    return frontendMessageId;
  };

  const clearRemoteWaitNoticeTimers = () => {
    remoteWaitNoticeTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    remoteWaitNoticeTimersRef.current = [];
  };

  const stripRemoteWaitBlocks = (blocks: any[] = []) =>
    blocks.filter((block) => block?.id !== REMOTE_WAIT_BLOCK_ID);

  const setRemoteWaitNotice = (
    messageId: string,
    content: string,
    subtitle = "等待模型响应",
  ) => {
    const waitBlock = {
      id: REMOTE_WAIT_BLOCK_ID,
      kind: "thinking",
      title: "正在处理",
      subtitle,
      icon: "fa-spinner fa-spin",
      content,
      replaceContent: true,
      defaultOpen: true,
    };
    streamProcessBlocksRef.current.set(messageId, [
      ...stripRemoteWaitBlocks(streamProcessBlocksRef.current.get(messageId) || []),
      waitBlock,
    ]);
    setMessages((prevMessages) =>
      prevMessages.map((message) =>
        message.id === messageId
          ? {
              ...message,
              processBlocks: [
                ...stripRemoteWaitBlocks(message.processBlocks || []),
                waitBlock,
              ],
            }
          : message,
      ),
    );
  };

  const clearRemoteWaitNotice = (messageId = activeAssistantMessageIdRef.current) => {
    if (!messageId) {
      return;
    }
    const nextBlocks = stripRemoteWaitBlocks(
      streamProcessBlocksRef.current.get(messageId) || [],
    );
    streamProcessBlocksRef.current.set(messageId, nextBlocks);
    setMessages((prevMessages) =>
      prevMessages.map((message) =>
        message.id === messageId
          ? {
              ...message,
              processBlocks: stripRemoteWaitBlocks(message.processBlocks || []),
            }
          : message,
      ),
    );
  };

  const seedStreamStateFromMessages = (messages: any[] = []) => {
    streamAssistantMapRef.current = new Map();
    streamMessageMetaRef.current = new Map();
    streamPendingTextRef.current = new Map();
    streamResponseTextRef.current = new Map();
    streamProcessBlocksRef.current = new Map();
    pendingProcessBlocksRef.current = new Map();

    const lastAgentMessage = findLastAgentMessage(messages);
    if (!lastAgentMessage?.id) {
      activeAssistantMessageIdRef.current = null;
      hasStreamOutputRef.current = false;
      return null;
    }

    const frontendMessageId = String(lastAgentMessage.id);
    activeAssistantMessageIdRef.current = frontendMessageId;
    streamProcessBlocksRef.current.set(
      frontendMessageId,
      lastAgentMessage.processBlocks || [],
    );

    const responseTexts = new Map<string, string>();
    for (const block of lastAgentMessage.processBlocks || []) {
      if (block?.kind === "response" && block?.id && block?.content) {
        responseTexts.set(String(block.id), String(block.content));
      }
    }

    const backendMessageId = String(
      lastAgentMessage.enhancementSourceMessageId ||
      lastAgentMessage.backendMessageId ||
      "",
    );
    if (backendMessageId) {
      streamAssistantMapRef.current.set(backendMessageId, {
        frontendId: frontendMessageId,
      });
      if (lastAgentMessage.content && !responseTexts.has(backendMessageId)) {
        responseTexts.set(backendMessageId, String(lastAgentMessage.content));
      }
    }

    streamResponseTextRef.current.set(frontendMessageId, responseTexts);
    hasStreamOutputRef.current = Boolean(
      lastAgentMessage.content ||
      (lastAgentMessage.processBlocks || []).some((block: any) => block?.id !== REMOTE_WAIT_BLOCK_ID),
    );
    return frontendMessageId;
  };

  const scheduleRemoteWaitNotices = (messageId: string) => {
    clearRemoteWaitNoticeTimers();
    setRemoteWaitNotice(
      messageId,
      "已收到您的请求，正在创建会话并连接后端模型流。",
      "请求已提交",
    );
    remoteWaitNoticeTimersRef.current = [
      window.setTimeout(() => {
        setRemoteWaitNotice(
          messageId,
          "后端仍未返回模型内容，正在等待 LLM 建立响应或完成上游调用。",
          "等待超过 12 秒",
        );
      }, 12000),
      window.setTimeout(() => {
        setRemoteWaitNotice(
          messageId,
          "LLM 响应时间较长，可能正在等待上游模型、DNS 解析、工具调用或后端自动重试。",
          "等待超过 45 秒",
        );
      }, 45000),
      window.setTimeout(() => {
        setRemoteWaitNotice(
          messageId,
          "仍未收到新的模型内容，请继续等待或检查 LLM 服务、DNS 与网络状态；后端可能仍在重试。",
          "等待超过 90 秒",
        );
      }, 90000),
    ];
  };

  const ensureAssistantMessage = (backendMessageId: string, employee: any) => {
    const existingState = streamAssistantMapRef.current.get(backendMessageId);
    if (existingState) {
      return existingState;
    }

    const frontendMessageId = ensureAgentContainer(employee);
    const nextState = {
      frontendId: frontendMessageId,
    };
    streamAssistantMapRef.current.set(backendMessageId, nextState);
    return nextState;
  };

  const scheduleStreamFlush = () => {
    if (flushTimerRef.current) {
      return;
    }

    flushTimerRef.current = window.setTimeout(() => {
      flushTimerRef.current = 0;
      flushStreamUpdates();
    }, 32) as unknown as number;
  };

  const appendProcessBlock = (messageId: string, block: any) => {
    if (!block?.content?.trim()) {
      return;
    }

    if (block?.id !== REMOTE_WAIT_BLOCK_ID) {
      hasStreamOutputRef.current = true;
      clearRemoteWaitNoticeTimers();
      clearRemoteWaitNotice(messageId);
    }
    const queuedBlocks = pendingProcessBlocksRef.current.get(messageId) || [];
    pendingProcessBlocksRef.current.set(
      messageId,
      mergeProcessBlocks(queuedBlocks, [block]),
    );
    const currentBlocks = streamProcessBlocksRef.current.get(messageId) || [];
    streamProcessBlocksRef.current.set(
      messageId,
      mergeProcessBlocks(currentBlocks, [block]),
    );
    scheduleStreamFlush();
  };

  const appendAssistantResponseBlock = useCallback((
    messageId: string,
    responseId: string,
    incomingText: string,
    { replace = false }: { replace?: boolean } = {},
  ) => {
    const nextText = String(incomingText || "");
    if (!nextText) {
      return;
    }

    hasStreamOutputRef.current = true;
    clearRemoteWaitNoticeTimers();
    clearRemoteWaitNotice(messageId);
    const responseTexts = streamResponseTextRef.current.get(messageId) || new Map();
    const mergedText = replace
      ? nextText
      : mergeStreamingText(String(responseTexts.get(responseId) || ""), nextText);
    responseTexts.set(responseId, mergedText);
    streamResponseTextRef.current.set(messageId, responseTexts);
    const combinedText = Array.from(responseTexts.values())
      .map((value) => String(value || ""))
      .filter(Boolean)
      .join("\n\n");

    setMessages((prevMessages) =>
      prevMessages.map((message) => {
        if (message.id !== messageId) {
          return message;
        }

        return {
          ...message,
          content: combinedText,
          backendMessageId: message.backendMessageId || responseId,
          enhancementSourceMessageId: responseId,
          processBlocks: mergeProcessBlocks(message.processBlocks || [], [
            {
              ...buildResponseBlock({ id: responseId }, mergedText, { preserveWhitespace: true }),
              replaceContent: replace,
            },
          ]),
        };
      }),
    );
  }, [setMessages]);

  const reclassifyAssistantResponseAsReasoning = useCallback((backendMessageId: string) => {
    const assistantState = streamAssistantMapRef.current.get(backendMessageId);
    const frontendMessageId = assistantState?.frontendId;
    if (!frontendMessageId) {
      return;
    }

    const responseTexts = streamResponseTextRef.current.get(frontendMessageId);
    if (responseTexts?.has(backendMessageId)) {
      responseTexts.delete(backendMessageId);
      if (!responseTexts.size) {
        streamResponseTextRef.current.delete(frontendMessageId);
      }
    }

    const combinedText = Array.from(responseTexts?.values() || [])
      .map((value) => String(value || ""))
      .filter(Boolean)
      .join("\n\n");

    setMessages((prevMessages) =>
      prevMessages.map((message) => {
        if (message.id !== frontendMessageId) {
          return message;
        }

        return {
          ...message,
          content: combinedText,
          backendMessageId:
            message.backendMessageId === backendMessageId ? "" : message.backendMessageId,
          enhancementSourceMessageId:
            message.enhancementSourceMessageId === backendMessageId
              ? ""
              : message.enhancementSourceMessageId,
          processBlocks: (message.processBlocks || []).filter(
            (block: any) => !(block?.kind === "response" && block.id === backendMessageId),
          ),
        };
      }),
    );
  }, [setMessages]);

  const flushPendingAssistantText = useCallback((messageId: string, employee: any) => {
    const pendingText = String(streamPendingTextRef.current.get(messageId) || "");
    if (!pendingText) {
      return;
    }

    const streamMeta = streamMessageMetaRef.current.get(messageId);
    if (streamMeta?.role === "assistant" && streamMeta?.type === "reasoning") {
      const frontendMessageId = ensureAgentContainer(employee);
      appendProcessBlock(
        frontendMessageId,
        buildThinkingBlock({
          id: messageId,
          role: "assistant",
          type: "reasoning",
          content: [{ type: "text", text: pendingText }],
        }),
      );
      streamPendingTextRef.current.delete(messageId);
      return;
    }

    if (streamMeta?.role === "assistant" && streamMeta?.type === "message") {
      const assistantState = ensureAssistantMessage(messageId, employee);
      appendAssistantResponseBlock(assistantState.frontendId, messageId, pendingText);
      streamPendingTextRef.current.delete(messageId);
    }
  }, [appendAssistantResponseBlock]);

  const flushStreamUpdates = () => {
    if (flushTimerRef.current) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = 0;
    }

    if (pendingProcessBlocksRef.current.size === 0) {
      return;
    }

    const processBlockUpdates = pendingProcessBlocksRef.current;
    pendingProcessBlocksRef.current = new Map();

    setMessages((prevMessages) =>
      prevMessages.map((message) => {
        const nextBlocks = processBlockUpdates.get(message.id);

        if (!nextBlocks?.length) {
          return message;
        }

        const existingBlocks = message.processBlocks || [];
        const mergedBlocks = mergeProcessBlocks(existingBlocks, nextBlocks);
        return { ...message, processBlocks: mergedBlocks };
      }),
    );
  };

  const finalizePendingResponse = useCallback((fallbackText: string) => {
    flushStreamUpdates();

    if (!activeAssistantMessageIdRef.current) {
      if (fallbackText) {
        setMessages((prevMessages) => [
          ...prevMessages,
          createAgentMessage(currentEmployeeRef.current, {
            id: `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            content: fallbackText,
            resourceImportGuide: pendingResourceImportGuideRef.current,
          }),
        ]);
      }
      return;
    }

    const activeMessageId = activeAssistantMessageIdRef.current;
    setMessages((prevMessages) =>
      prevMessages.map((message) =>
        message.id === activeMessageId
          && (!message.content || message.content === FAULT_SCENARIO_ANALYZING_PLACEHOLDER)
        ? {
            ...message,
            content: fallbackText,
            processBlocks: stripRemoteWaitBlocks(message.processBlocks || []),
          }
        : message,
      ),
    );
  }, [setMessages]);

  const stopActiveStream = useCallback((
    requestStop = true,
    { silent = false }: { silent?: boolean } = {},
  ) => {
    const hadActiveStream = Boolean(
      streamAbortRef.current
      || activeAssistantMessageIdRef.current
      || isStreamingRef.current
      || currentChatStatusRef.current === "running",
    );
    if (requestStop && isRemoteEmployeeRef.current && currentChatIdRef.current) {
      stopChat(remoteAgentIdRef.current || undefined, currentChatIdRef.current).catch(
        () => {},
      );
    }
    streamAbortNoticeModeRef.current = silent ? "silent" : "show";
    flushStreamUpdates();
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    streamAssistantMapRef.current = new Map();
    streamMessageMetaRef.current = new Map();
    streamPendingTextRef.current = new Map();
    streamResponseTextRef.current = new Map();
    hasStreamOutputRef.current = false;
    pendingResourceImportGuideRef.current = false;
    clearRemoteWaitNoticeTimers();
    clearRemoteWaitNotice();
    if (!silent && hadActiveStream) {
      finalizePendingResponse("本轮对话已停止。");
    }
    activeAssistantMessageIdRef.current = null;
    streamProcessBlocksRef.current = new Map();
    setIsStreaming(false);
    setCurrentChatStatus("idle");
  }, [finalizePendingResponse]);

  const maybeEnhanceAlarmAnalystMessage = useCallback(async ({
    frontendMessageId,
    backendMessageId,
    finalText,
  }: {
    frontendMessageId: string;
    backendMessageId: string;
    finalText: string;
  }) => {
    const normalizedFinalText = String(finalText || "").trim();
    const shouldAttemptByContent = shouldAttemptAlarmAnalystCardByContent(normalizedFinalText);
    if (
      (
        !shouldEnableAlarmAnalystCards({
          employeeId: currentEmployeeRef.current?.id || "",
          session: currentChatMetaRef.current,
        })
        && !shouldAttemptByContent
      ) ||
      !currentChatIdRef.current ||
      !currentSessionIdRef.current ||
      !backendMessageId ||
      !normalizedFinalText
    ) {
      return;
    }

    const payload = buildAlarmAnalystCardRequest({
      chatId: currentChatIdRef.current,
      sessionId: currentSessionIdRef.current,
      employeeId: currentEmployeeRef.current.id,
      message: {
        id: frontendMessageId,
        content: normalizedFinalText,
        processBlocks: streamProcessBlocksRef.current.get(frontendMessageId) || [],
        backendMessageId,
        enhancementSourceMessageId: backendMessageId,
      },
    });
    if (!payload) {
      return;
    }

    try {
      const response = await createAlarmAnalystCard(payload, {
        agentId: remoteAgentIdRef.current || undefined,
      });
      if (!response?.matched || !response.card) {
        return;
      }
      setMessages((prevMessages) =>
        mergeAlarmAnalystCards(
          prevMessages.map((message) =>
            message.id === frontendMessageId
              ? {
                  ...message,
                  backendMessageId,
                  enhancementSourceMessageId: backendMessageId,
                }
              : message,
          ),
          [response.card as any],
        ),
      );
    } catch (error) {
      console.warn("Failed to create alarm analyst card:", error);
    }
  }, [setMessages]);

  const hydrateAlarmAnalystCardsForHistory = useCallback(async ({
    messages,
    chatId,
    sessionId,
    session,
    employeeId,
    agentId,
  }: {
    messages: any[];
    chatId: string;
    sessionId: string;
    session: any;
    employeeId: string;
    agentId?: string;
  }) => {
    const shouldEnableBySession = shouldEnableAlarmAnalystCards({
      employeeId,
      session,
    });
    if (!chatId || !sessionId) {
      return messages;
    }

    let nextMessages = messages;

    if (shouldEnableBySession) {
      try {
        const cardResponse = await listAlarmAnalystCards(chatId, {
          sessionId,
          agentId,
        });
        nextMessages = mergeAlarmAnalystCards(
          nextMessages || [],
          (cardResponse.cards || []) as any,
        );
      } catch (error) {
        console.warn("Failed to hydrate alarm analyst cards:", error);
      }
    }

    const payloadsByMessageId = new Map<
      string,
      NonNullable<ReturnType<typeof buildAlarmAnalystCardRequest>>
    >();
    for (const message of nextMessages || []) {
      if (message?.type !== "agent" || message?.alarmAnalystCard) {
        continue;
      }
      const reportMarkdown = getAlarmAnalystReportMarkdown(message);
      if (!shouldEnableBySession && !shouldAttemptAlarmAnalystCardByContent(reportMarkdown)) {
        continue;
      }
      const payload = buildAlarmAnalystCardRequest({
        chatId,
        sessionId,
        employeeId,
        message,
      });
      if (!payload || payloadsByMessageId.has(payload.messageId)) {
        continue;
      }
      payloadsByMessageId.set(payload.messageId, payload);
    }

    if (!payloadsByMessageId.size) {
      return nextMessages;
    }

    const createdCards = (
      await Promise.all(
        [...payloadsByMessageId.values()].map(async (payload) => {
          try {
            const response = await createAlarmAnalystCard(payload, { agentId });
            return response?.matched && response.card ? (response.card as any) : null;
          } catch (error) {
            console.warn("Failed to backfill alarm analyst card:", error);
            return null;
          }
        }),
      )
    ).filter(Boolean);

    if (!createdCards.length) {
      return nextMessages;
    }

    return mergeAlarmAnalystCards(nextMessages || [], createdCards);
  }, []);

  const refreshRemoteSessions = useCallback(async (showSpinner = true) => {
    const nextRemoteAgentId = remoteAgentIdRef.current;
    const nextEmployee = currentEmployeeRef.current;
    if (!isRemoteEmployeeRef.current || !nextRemoteAgentId || !nextEmployee) {
      return;
    }

    const requestId = Date.now();
    remoteHistoryRequestIdRef.current = requestId;
    if (showSpinner) {
      setHistoryLoading(true);
    }
    setHistoryError("");

    try {
      const chats = await listChats(nextRemoteAgentId, {
        user_id: COPAW_USER_ID,
        channel: COPAW_CHANNEL,
      });
      if (remoteHistoryRequestIdRef.current !== requestId) {
        return;
      }
      setRemoteSessions(
        normalizeRemoteSessions(chats, nextEmployee.id),
      );
    } catch (error: any) {
      if (remoteHistoryRequestIdRef.current !== requestId) {
        return;
      }
      setHistoryError(error.message || "获取聊天列表失败");
    } finally {
      if (remoteHistoryRequestIdRef.current === requestId && showSpinner) {
        setHistoryLoading(false);
      }
    }
  }, []);

  const handleOpenHistory = useCallback(async () => {
    setHistoryVisible(true);
    if (isRemoteEmployeeRef.current) {
      await refreshRemoteSessions(true);
    }
  }, [refreshRemoteSessions]);

  const reconnectRunningChat = useCallback(async ({
    agentId,
    employee,
    sessionId,
    chatId,
    messages,
  }: {
    agentId: string;
    employee: any;
    sessionId: string;
    chatId: string;
    messages: any[];
  }) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId || !agentId || !employee) {
      return;
    }

    const frontendMessageId = seedStreamStateFromMessages(messages);
    const controller = new AbortController();
    streamAbortRef.current = controller;
    streamAbortNoticeModeRef.current = null;
    currentChatIdRef.current = chatId;
    currentSessionIdRef.current = normalizedSessionId;
    isStreamingRef.current = true;
    currentChatStatusRef.current = "running";
    setIsStreaming(true);
    setCurrentChatStatus("running");

    if (frontendMessageId && !hasStreamOutputRef.current) {
      setRemoteWaitNotice(
        frontendMessageId,
        "已重新连接正在运行的对话，等待后续模型或工具事件。",
        "已重新连接",
      );
    }

    try {
      await reconnectChat(agentId, {
        sessionId: normalizedSessionId,
        signal: controller.signal,
        onEvent: (event) => handleRemoteStreamEvent(event, employee),
      });
      finalizePendingResponse("");
      setCurrentChatStatus("idle");
    } catch (error: any) {
      if (!controller.signal.aborted) {
        console.warn("Failed to reconnect running chat:", error);
        setCurrentChatStatus("idle");
      }
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      clearRemoteWaitNoticeTimers();
      isStreamingRef.current = false;
      setIsStreaming(false);
      streamAbortNoticeModeRef.current = null;
      streamMessageMetaRef.current = new Map();
      streamPendingTextRef.current = new Map();
      streamResponseTextRef.current = new Map();
      streamProcessBlocksRef.current = new Map();
      hasStreamOutputRef.current = false;
      await refreshRemoteSessions(false);
    }
  }, [finalizePendingResponse, refreshRemoteSessions]);

  const handleSelectRemoteHistory = useCallback(async (session: any) => {
    const nextEmployee = currentEmployeeRef.current;
    const nextRemoteAgentId = remoteAgentIdRef.current;
    if (!nextEmployee || !nextRemoteAgentId) {
      return;
    }

    stopActiveStream(false, { silent: true });
    setHistoryLoading(true);
    setHistoryError("");

    try {
      const isPortalFaultWorkbench =
        nextEmployee.id === "fault"
        && String(session?.meta?.source || "") === "portal-fault-workorder";
      let history = null;
      let nextMessages = null;
      let enhancementSessionId = String(session?.sessionId || "").trim();

      if (isPortalFaultWorkbench) {
        try {
          const portalHistory = await getFaultDisposalHistory(
            session.sessionId || "",
          ) as FaultDisposalHistory;
          const portalMessages = portalHistory.messages || [];
          if (portalMessages.length) {
            history = portalHistory;
            nextMessages = portalMessages.map((message) =>
              message?.type === "agent"
                ? createAgentMessage(nextEmployee, {
                    ...message,
                    content: message.content || "",
                    processBlocks: message.processBlocks || [],
                    disposalOperation: message.disposalOperation,
                    alarmAnalystCard: message.alarmAnalystCard,
                    backendMessageId: message.backendMessageId || "",
                    enhancementSourceMessageId: message.enhancementSourceMessageId || "",
                  })
                : {
                    id: message.id || `user-${Date.now()}`,
                    type: "user",
                    content: message.content || "",
                  },
            );
          }
        } catch {
          history = null;
        }
      }

      if (!history || !nextMessages) {
        history = await getChatHistory(nextRemoteAgentId, session.id);
        nextMessages = normalizeRemoteHistoryMessages(
          history.messages,
          nextEmployee,
          session,
        );
        enhancementSessionId = String(
          enhancementSessionId ||
          history.session_id ||
          history.sessionId ||
          "",
        ).trim();
      }

      if (enhancementSessionId) {
        nextMessages = await hydrateAlarmAnalystCardsForHistory({
          messages: nextMessages || [],
          chatId: session.id,
          sessionId: enhancementSessionId,
          session,
          employeeId: nextEmployee.id,
          agentId: nextRemoteAgentId,
        });
      }

      const selectedSessionId = enhancementSessionId || session.sessionId || "";
      const selectedStatus =
        isRunningRemoteStatus(history.status) || isRunningRemoteStatus(session.status)
          ? "running"
          : history.status || session.status || "idle";
      setCurrentChatId(session.id);
      setCurrentSessionId(selectedSessionId);
      setCurrentChatStatus(selectedStatus);
      currentChatMetaRef.current = session?.meta || history?.meta || null;
      setMessages(nextMessages);
      setHistoryVisible(false);

      if (isRunningRemoteStatus(selectedStatus)) {
        window.setTimeout(() => {
          void reconnectRunningChat({
            agentId: nextRemoteAgentId,
            employee: nextEmployee,
            sessionId: selectedSessionId,
            chatId: session.id,
            messages: nextMessages || [],
          });
        }, 0);
      }
    } catch (error: any) {
      setHistoryError(error.message || "获取聊天历史失败");
    } finally {
      setHistoryLoading(false);
    }
  }, [hydrateAlarmAnalystCardsForHistory, reconnectRunningChat, stopActiveStream]);

  const handleRemoteStreamEvent = (event: any, employee: any) => {
    if (event.object === "portal_progress") {
      const frontendMessageId = activeAssistantMessageIdRef.current || ensureAgentContainer(employee);
      clearRemoteWaitNoticeTimers();
      setRemoteWaitNotice(
        frontendMessageId,
        String(event.message || "后端正在处理请求。"),
        getPortalProgressSubtitle(String(event.stage || "")),
      );
      return;
    }

    if (event.object === "message" && event.id) {
      streamMessageMetaRef.current.set(event.id, {
        role: event.role,
        type: event.type,
      });
      flushPendingAssistantText(event.id, employee);
      if (event.role === "assistant" && event.type === "reasoning") {
        reclassifyAssistantResponseAsReasoning(event.id);
      }
    }

    if (event.object === "response" && event.status) {
      setCurrentChatStatus(
        event.status === "completed" ? "idle" : event.status,
      );
      if (
        activeAssistantMessageIdRef.current
        && event.status !== "completed"
        && !hasStreamOutputRef.current
      ) {
        setRemoteWaitNotice(
          activeAssistantMessageIdRef.current,
          "后端已建立流式请求，正在等待模型输出内容。",
          "后端已响应",
        );
      }
      return;
    }

    if (event.object === "message" && event.status === "completed") {
      if (isCopawReasoningMessage(event)) {
        streamPendingTextRef.current.delete(event.id);
        reclassifyAssistantResponseAsReasoning(event.id);
        const frontendMessageId = ensureAgentContainer(employee);
        appendProcessBlock(
          frontendMessageId,
          buildThinkingBlock(event, { replaceContent: true }),
        );
        return;
      }

      if (event.type === "plugin_call" || event.type === "plugin_call_output") {
        const frontendMessageId = ensureAgentContainer(employee);
        appendProcessBlock(frontendMessageId, buildToolBlock(event));
        return;
      }
    }

    if (
      event.object === "message" &&
      event.role === "assistant" &&
      event.type === "message"
    ) {
      const assistantState = ensureAssistantMessage(event.id, employee);
      const finalText = extractCopawMessageText(event);
      if (event.status === "completed") {
        const streamedText = String(
          streamResponseTextRef.current.get(assistantState.frontendId)?.get(event.id) || "",
        ).trim();
        const resolvedFinalText = finalText || streamedText;
        streamPendingTextRef.current.delete(event.id);
        if (finalText) {
          appendAssistantResponseBlock(assistantState.frontendId, event.id, finalText, {
            replace: true,
          });
        }
        if (resolvedFinalText) {
          void maybeEnhanceAlarmAnalystMessage({
            frontendMessageId: assistantState.frontendId,
            backendMessageId: event.id,
            finalText: resolvedFinalText,
          });
        }
      }
      return;
    }

    if (event.object === "content" && event.type === "text" && event.msg_id) {
      const streamMeta = streamMessageMetaRef.current.get(event.msg_id);
      if (streamMeta?.role === "assistant" && streamMeta?.type === "reasoning") {
        const frontendMessageId = ensureAgentContainer(employee);
        appendProcessBlock(
          frontendMessageId,
          buildThinkingBlock({
            id: event.msg_id,
            role: "assistant",
            type: "reasoning",
            content: [{ type: "text", text: event.text || "" }],
          }),
        );
        return;
      }

      if (streamMeta?.role === "assistant" && streamMeta?.type === "message") {
        const assistantState = ensureAssistantMessage(event.msg_id, employee);
        if (event.text) {
          appendAssistantResponseBlock(assistantState.frontendId, event.msg_id, event.text);
        }
        return;
      }

      if (event.text) {
        const currentPendingText = String(streamPendingTextRef.current.get(event.msg_id) || "");
        streamPendingTextRef.current.set(
          event.msg_id,
          mergeStreamingText(currentPendingText, event.text),
        );
      }
    }
  };

  const handleRemoteSendMessage = useCallback(async (
    content: string,
    {
      visibleContent = "",
      chatName = "",
      chatMeta = null,
      forceNewChat = false,
      sessionId = "",
    }: {
      visibleContent?: string;
      chatName?: string;
      chatMeta?: any;
      forceNewChat?: boolean;
      sessionId?: string;
    } = {},
  ) => {
    const nextEmployee = currentEmployeeRef.current;
    const nextRemoteAgentId = remoteAgentIdRef.current;
    if (
      !nextEmployee ||
      !nextRemoteAgentId ||
      isStreamingRef.current ||
      isCreatingChatRef.current
    ) {
      return false;
    }

    const normalizedVisibleContent = (visibleContent || content).trim();
    const userMessage = createUserMessage(normalizedVisibleContent);
    streamAbortNoticeModeRef.current = null;
    streamAssistantMapRef.current = new Map();
    streamMessageMetaRef.current = new Map();
    streamPendingTextRef.current = new Map();
    streamResponseTextRef.current = new Map();
    activeAssistantMessageIdRef.current = null;
    pendingResourceImportGuideRef.current = isResourceImportIntent(
      `${normalizedVisibleContent}\n${content}`,
    );
    hasStreamOutputRef.current = false;

    const controller = new AbortController();
    streamAbortRef.current = controller;
    isStreamingRef.current = true;
    currentChatStatusRef.current = "running";
    setIsStreaming(true);
    setCurrentChatStatus("running");

    let streamSucceeded = false;

    try {
      const scenarioResult = await maybeHandleFaultScenarioMessage({
        currentEmployee: nextEmployee,
        content,
        visibleContent: normalizedVisibleContent,
        sessionId: sessionId || currentSessionIdRef.current,
        signal: controller.signal,
        setActiveAssistantMessageId: (messageId: string | null) => {
          activeAssistantMessageIdRef.current = messageId;
        },
        setMessages,
      });
      if (scenarioResult.handled) {
        setIsStreaming(false);
        setCurrentChatStatus("idle");
        return scenarioResult.succeeded;
      }

      setMessages((prevMessages) => [...prevMessages, userMessage]);
      const waitingAssistantMessageId = ensureAgentContainer(nextEmployee);
      scheduleRemoteWaitNotices(waitingAssistantMessageId);

      let ensuredChat;
      if (!forceNewChat && currentChatIdRef.current && currentSessionIdRef.current) {
        ensuredChat = {
          id: currentChatIdRef.current,
          session_id: currentSessionIdRef.current,
        };
      } else {
        setIsCreatingChat(true);
        try {
          ensuredChat = await createChat(nextRemoteAgentId, {
            name: chatName || normalizedVisibleContent,
            session_id: sessionId || createRemoteSessionId(nextEmployee.id),
            user_id: COPAW_USER_ID,
            channel: COPAW_CHANNEL,
            meta: chatMeta || undefined,
          });
        } finally {
          setIsCreatingChat(false);
        }
      }

      setCurrentChatId(ensuredChat.id);
      setCurrentSessionId(ensuredChat.session_id);
      currentChatIdRef.current = ensuredChat.id;
      currentSessionIdRef.current = ensuredChat.session_id;
      currentChatMetaRef.current = chatMeta || ensuredChat.meta || currentChatMetaRef.current || null;

      await streamChat(
        nextRemoteAgentId,
        {
          input: [
            {
              role: "user",
              type: "message",
              content: [
                {
                  type: "text",
                  text: content,
                  status: "created",
                },
              ],
            },
          ],
          session_id: ensuredChat.session_id,
          user_id: COPAW_USER_ID,
          channel: COPAW_CHANNEL,
          stream: true,
        },
        {
          signal: controller.signal,
          onEvent: (event) => handleRemoteStreamEvent(event, nextEmployee),
        },
      );

      finalizePendingResponse("本轮对话未返回可展示内容。");
      setCurrentChatStatus("idle");
      streamSucceeded = true;
      streamProcessBlocksRef.current = new Map();
    } catch (error: any) {
      if (controller.signal.aborted) {
        if (streamAbortNoticeModeRef.current == null) {
          finalizePendingResponse("本轮对话已停止。");
        }
      } else {
        finalizePendingResponse(`对话失败：${normalizeRemoteChatErrorMessage(error)}`);
        setCurrentChatStatus("idle");
      }
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      clearRemoteWaitNoticeTimers();
      setIsCreatingChat(false);
      isStreamingRef.current = false;
      setIsStreaming(false);
      streamAbortNoticeModeRef.current = null;
      streamMessageMetaRef.current = new Map();
      streamPendingTextRef.current = new Map();
      streamResponseTextRef.current = new Map();
      streamProcessBlocksRef.current = new Map();
      hasStreamOutputRef.current = false;
      pendingResourceImportGuideRef.current = false;
      await refreshRemoteSessions(false);
    }

    return streamSucceeded;
  }, [refreshRemoteSessions]);

  const resetRemoteState = useCallback(({
    initialMessages = [],
    clearHistoryError = true,
  }: {
    initialMessages?: any[];
    clearHistoryError?: boolean;
  } = {}) => {
    stopActiveStream(false, { silent: true });
    setCurrentChatStatus("idle");
    setHistoryVisible(false);
    if (clearHistoryError) {
      setHistoryError("");
    }
    setRemoteSessions([]);
    setCurrentSessionId("");
    setCurrentChatId("");
    currentChatMetaRef.current = null;
    setIsCreatingChat(false);
    streamMessageMetaRef.current = new Map();
    streamPendingTextRef.current = new Map();
    streamResponseTextRef.current = new Map();
    streamProcessBlocksRef.current = new Map();
    hasStreamOutputRef.current = false;
    setMessages(initialMessages);
  }, [setMessages, stopActiveStream]);

  return {
    currentSessionId,
    setCurrentSessionId,
    currentChatId,
    setCurrentChatId,
    currentChatStatus,
    setCurrentChatStatus,
    historyVisible,
    setHistoryVisible,
    historyLoading,
    historyError,
    remoteSessions,
    isCreatingChat,
    isStreaming,
    activeAssistantMessageIdRef,
    flushTimerRef,
    handleRemoteSendMessage,
    stopActiveStream,
    refreshRemoteSessions,
    handleOpenHistory,
    handleSelectRemoteHistory,
    resetRemoteState,
  };
}
