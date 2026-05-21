import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type Dispatch,
  type KeyboardEvent,
  type MouseEvent,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import type { NavigateFunction } from "react-router-dom";
import {
  digitalEmployees,
  employeeResults,
  employeeWorkflows,
  getEmployeeById,
} from "../../data/portalData";
import type { DigitalEmployee } from "../../types/portal";
import {
  createConversationSession,
  saveConversationStore,
} from "../../lib/conversationStore";
import {
  buildSessionTitle,
  createAgentMessage,
  createInitialMessages,
  createUserMessage,
} from "./helpers";
import {
  ORDER_OWNER_ID,
  KNOWLEDGE_BASE_OWNER_ID,
  PORTAL_HOME_ID,
  RESOURCE_IMPORT_OWNER_ID,
  buildMentionCollaborationPrompt,
  buildPortalAssistantReply,
  buildResourceImportTopologyCollaborationRequest,
  ensureObjectArray,
  ensureSessionRecords,
  extractMentionQuery,
  extractMentionTarget,
  isKnowledgeBaseCardIntent,
  isKnowledgeBaseIntent,
  isResourceImportIntent,
  resolveEmployeeAgentId,
  resolveResourceImportTopologyScope,
  scoreMentionCandidate,
} from "./pageHelpers";
import type {
  ConversationStoreState,
  PortalLocationState,
  SessionRecord,
} from "./pageHelpers";

type MentionSuggestion = {
  employee: DigitalEmployee;
  score: number;
};

type ComposerSelectionEvent =
  | ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  | KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>
  | MouseEvent<HTMLInputElement | HTMLTextAreaElement>;

function isComposingInput(
  event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
) {
  const nativeEvent = event.nativeEvent as KeyboardEvent["nativeEvent"] & {
    isComposing?: boolean;
    keyCode?: number;
  };
  return Boolean(nativeEvent.isComposing || nativeEvent.keyCode === 229);
}

type NavigateToEmployeePage = (
  employee: any,
  options?: {
    entry?: string | null;
    view?: "chat" | "overview" | "dashboard" | "tasks";
    panel?: string | null;
    replace?: boolean;
    state?: PortalLocationState;
  },
) => void;

export function usePortalChatOrchestration({
  currentEmployee,
  selectedEmployee,
  employeesWithRuntimeStatus,
  isRemoteEmployee,
  remoteAgentId,
  currentSessionId,
  setCurrentSessionId,
  messages,
  setMessages,
  setConversationStore,
  isPortalHomeChat,
  portalHomeChatMode,
  setPortalHomeChatMode,
  isInteractionLocked,
  setActivePortalResourceImportSessionId,
  openResourceImport,
  openKnowledgeBaseConversation,
  searchKnowledgeBaseConversation,
  findResourceImportFlowById,
  navigate,
  navigateToEmployeePage,
  handleRemoteSendMessage,
  resetRemoteState,
  homeComposerRef,
  chatInputRef,
  locationState,
  locationPathname,
  locationSearch,
}: {
  currentEmployee: any;
  selectedEmployee: any;
  employeesWithRuntimeStatus: any[];
  isRemoteEmployee: boolean;
  remoteAgentId: string | null;
  currentSessionId: string;
  setCurrentSessionId: Dispatch<SetStateAction<string>>;
  messages: any[];
  setMessages: Dispatch<SetStateAction<any[]>>;
  setConversationStore: Dispatch<SetStateAction<ConversationStoreState>>;
  isPortalHomeChat: boolean;
  portalHomeChatMode: boolean;
  setPortalHomeChatMode: Dispatch<SetStateAction<boolean>>;
  isInteractionLocked: boolean;
  setActivePortalResourceImportSessionId: Dispatch<SetStateAction<string>>;
  openResourceImport: (visibleContent?: string) => void;
  openKnowledgeBaseConversation: (visibleContent?: string) => void;
  searchKnowledgeBaseConversation: (visibleContent?: string) => void;
  findResourceImportFlowById: (flowId: string) => any;
  navigate: NavigateFunction;
  navigateToEmployeePage: NavigateToEmployeePage;
  handleRemoteSendMessage: (
    content: string,
    options?: { visibleContent?: string; forceNewChat?: boolean },
  ) => Promise<boolean> | boolean;
  resetRemoteState: (options?: { initialMessages?: any[]; clearHistoryError?: boolean }) => void;
  homeComposerRef: MutableRefObject<HTMLTextAreaElement | null>;
  chatInputRef: MutableRefObject<HTMLTextAreaElement | null>;
  locationState: PortalLocationState | null;
  locationPathname: string;
  locationSearch: string;
}) {
  const [inputMessage, setInputMessage] = useState("");
  const [pendingPortalHomeMessage, setPendingPortalHomeMessage] = useState("");
  const [inputCursor, setInputCursor] = useState<number | null>(null);
  const [mentionActiveIndex, setMentionActiveIndex] = useState(0);
  const handledPendingDispatchRef = useRef("");
  const handledPendingResourceImportRef = useRef("");
  const handledPendingKnowledgeBaseRef = useRef("");
  const handledPendingKnowledgeSearchRef = useRef("");
  const pendingAlarmRegistryIdRef = useRef("");

  const safeMessageCount = useMemo(
    () => ensureObjectArray(messages).length,
    [messages],
  );
  const showPortalHomeHero = isPortalHomeChat && !portalHomeChatMode && safeMessageCount === 0;
  const mentionContext = useMemo(
    () => extractMentionQuery(inputMessage, inputCursor),
    [inputCursor, inputMessage],
  );
  const mentionSuggestions = useMemo<MentionSuggestion[]>(() => {
    if (!mentionContext) {
      return [];
    }

    return digitalEmployees
      .map((employee) => ({
        employee,
        score: scoreMentionCandidate(employee, mentionContext.query),
      }))
      .filter((item) => item.score > 0)
      .sort((left, right) => right.score - left.score)
      .slice(0, 5);
  }, [mentionContext]);
  const orderEmployee = useMemo(
    () =>
      employeesWithRuntimeStatus.find((item) => item.id === ORDER_OWNER_ID)
      || getEmployeeById(ORDER_OWNER_ID),
    [employeesWithRuntimeStatus],
  );

  const createAndActivateLocalSession = useCallback((employee: any, initialMessages: any[]) => {
    const nextSession = createConversationSession(employee, initialMessages) as SessionRecord;
    setConversationStore((prevStore) => {
      const previousSessions = ensureSessionRecords(prevStore[employee.id]);
      const nextStore: ConversationStoreState = {
        ...prevStore,
        [employee.id]: [nextSession, ...previousSessions],
      };
      saveConversationStore(nextStore);
      return nextStore;
    });
    setCurrentSessionId(nextSession.id);
    return nextSession.id;
  }, [setConversationStore, setCurrentSessionId]);

  const updateMessagesAndStore = useCallback((
    nextMessages: any[],
    {
      employee = currentEmployee,
      nextSessionId = currentSessionId,
    }: {
      employee?: any;
      nextSessionId?: string;
    } = {},
  ) => {
    setMessages(nextMessages);

    if (!employee || isRemoteEmployee) {
      return;
    }

    setConversationStore((prevStore) => {
      const previousSessions = ensureSessionRecords(prevStore[employee.id]);
      const nextStore: ConversationStoreState = {
        ...prevStore,
        [employee.id]: previousSessions.map((session) =>
          session.id === nextSessionId
            ? {
                ...session,
                messages: nextMessages,
                updatedAt: new Date().toISOString(),
                title: buildSessionTitle(employee.name, nextMessages),
              }
            : session,
        ),
      };
      saveConversationStore(nextStore);
      return nextStore;
    });
  }, [
    currentEmployee,
    currentSessionId,
    isRemoteEmployee,
    setConversationStore,
    setMessages,
  ]);

  const queueMentionDispatch = useCallback((
    employee: any,
    content: string,
    visibleContent: string,
  ) => {
    navigateToEmployeePage(employee, {
      entry: null,
      view: "chat",
      panel: null,
      state: {
        gatewayPresentationEmployeeId: employee.id,
        pendingPortalDispatch: {
          token: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          targetEmployeeId: employee.id,
          content,
          visibleContent,
        },
      },
    });
  }, [navigateToEmployeePage]);

  const runLocalEmployeeFlow = useCallback((
    employee: any,
    content: string,
    visibleContent: string,
    forceNewChat = false,
  ) => {
    const baseMessages = forceNewChat ? createInitialMessages(employee) : messages;
    let nextSessionId = forceNewChat ? "" : currentSessionId;
    if (!nextSessionId) {
      nextSessionId = createAndActivateLocalSession(
        employee,
        baseMessages.length ? baseMessages : createInitialMessages(employee),
      );
    }

    const userMessage = createUserMessage(visibleContent);
    const workflow =
      employeeWorkflows[employee.id as keyof typeof employeeWorkflows] || [];
    const result =
      employeeResults[employee.id as keyof typeof employeeResults] || null;
    const agentMessage = {
      ...createAgentMessage(employee, {
        id: `agent-${Date.now()}`,
        content: workflow.length ? "收到！我正在为您处理..." : buildPortalAssistantReply(content),
      }),
      workflow: [...workflow],
      currentStep: 0,
      workflowDone: false,
      stepTimes: [] as string[],
      result: null,
    };

    const initialQueue = [...baseMessages, userMessage, agentMessage];
    updateMessagesAndStore(initialQueue, {
      employee,
      nextSessionId,
    });

    if (!workflow.length) {
      return;
    }

    let step = 0;
    const interval = window.setInterval(() => {
      setMessages((prevMessages) => {
        const nextMessages = prevMessages.map((message) => {
          if (message.id !== agentMessage.id) {
            return message;
          }

          if (step < agentMessage.workflow.length) {
            return {
              ...message,
              currentStep: step,
              stepTimes: [
                ...(message.stepTimes || []),
                `${Math.floor(Math.random() * 2) + 1}s`,
              ],
            };
          }

          return {
            ...message,
            content: "",
            workflowDone: true,
            result,
          };
        });

        if (step >= agentMessage.workflow.length) {
          window.clearInterval(interval);
          window.setTimeout(() => {
            updateMessagesAndStore(nextMessages, {
              employee,
              nextSessionId,
            });
          }, 0);
        }

        return nextMessages;
      });
      step += 1;
    }, 800);
  }, [
    createAndActivateLocalSession,
    currentSessionId,
    messages,
    setMessages,
    updateMessagesAndStore,
  ]);

  const dispatchActiveMessage = useCallback(async (
    content: string,
    {
      visibleContent = content,
      targetEmployee = currentEmployee,
      forceNewChat = false,
    }: {
      visibleContent?: string;
      targetEmployee?: any;
      forceNewChat?: boolean;
    } = {},
  ) => {
    if (!content || !targetEmployee) {
      return false;
    }

    if (isRemoteEmployee && targetEmployee.id === currentEmployee?.id) {
      if (!isResourceImportIntent(visibleContent)) {
        setActivePortalResourceImportSessionId("");
      }
      return handleRemoteSendMessage(content, {
        visibleContent,
        forceNewChat,
      });
    }

    runLocalEmployeeFlow(targetEmployee, content, visibleContent, forceNewChat);
    return true;
  }, [
    currentEmployee,
    handleRemoteSendMessage,
    isRemoteEmployee,
    runLocalEmployeeFlow,
    setActivePortalResourceImportSessionId,
  ]);

  const dispatchOrderCollaboration = useCallback(async (
    content: string,
    visibleContent: string,
  ) => {
    if (!orderEmployee || !content.trim()) {
      return false;
    }

    const canCollaborateInCurrentChat = Boolean(
      isRemoteEmployee
      && remoteAgentId
      && currentEmployee?.id !== ORDER_OWNER_ID,
    );

    if (!canCollaborateInCurrentChat) {
      return false;
    }

    await dispatchActiveMessage(
      buildMentionCollaborationPrompt({
        currentEmployee,
        currentAgentId: remoteAgentId || resolveEmployeeAgentId(String(currentEmployee?.id || PORTAL_HOME_ID)),
        targetEmployee: orderEmployee,
        userRequest: content,
      }),
      {
        visibleContent,
      },
    );
    return true;
  }, [
    currentEmployee,
    dispatchActiveMessage,
    isRemoteEmployee,
    orderEmployee,
    remoteAgentId,
  ]);

  const handleResourceImportOpenSystemTopology = useCallback(
    async (payload: { flowId: string }) => {
      const flow = findResourceImportFlowById(payload.flowId);
      const scope = resolveResourceImportTopologyScope(flow);
      const visibleContent = scope.includesProject && scope.applicationName
        ? `查看${scope.applicationName}导入拓扑`
        : "查看本次导入拓扑";
      const queryEmployee = getEmployeeById("query");
      const collaborationPrompt = buildMentionCollaborationPrompt({
        currentEmployee,
        currentAgentId: remoteAgentId || resolveEmployeeAgentId(String(currentEmployee?.id || "")),
        targetEmployee: queryEmployee,
        userRequest: buildResourceImportTopologyCollaborationRequest(scope),
        preferBackground: true,
      });
      void dispatchActiveMessage(collaborationPrompt, {
        visibleContent,
      });
    },
    [currentEmployee, dispatchActiveMessage, findResourceImportFlowById, remoteAgentId],
  );

  useEffect(() => {
    const pendingDispatch = locationState?.pendingPortalDispatch;
    if (!pendingDispatch || !currentEmployee) {
      return;
    }

    if (pendingDispatch.targetEmployeeId !== currentEmployee.id) {
      return;
    }

    if (handledPendingDispatchRef.current === pendingDispatch.token) {
      return;
    }

    handledPendingDispatchRef.current = pendingDispatch.token;

    const pendingAlarmId = pendingDispatch.alarmId || "";
    pendingAlarmRegistryIdRef.current = pendingAlarmId;

    if (pendingDispatch.forceNewChat) {
      if (isRemoteEmployee) {
        resetRemoteState({
          initialMessages: isPortalHomeChat ? [] : createInitialMessages(currentEmployee),
        });
      }
      setPortalHomeChatMode(false);
    }

    navigate(`${locationPathname}${locationSearch}`, {
      replace: true,
      state: {
        gatewayPresentationEmployeeId: currentEmployee.id,
      } satisfies PortalLocationState,
    });

    window.setTimeout(() => {
      void dispatchActiveMessage(pendingDispatch.content, {
        visibleContent: pendingDispatch.visibleContent,
        forceNewChat: pendingDispatch.forceNewChat,
      });
    }, 0);
  }, [
    currentEmployee,
    dispatchActiveMessage,
    isPortalHomeChat,
    isRemoteEmployee,
    locationPathname,
    locationSearch,
    locationState,
    navigate,
    resetRemoteState,
    setPortalHomeChatMode,
  ]);

  useEffect(() => {
    const pendingResourceImport = locationState?.pendingResourceImport;
    if (!pendingResourceImport || !currentEmployee) {
      return;
    }

    if (pendingResourceImport.targetEmployeeId !== currentEmployee.id) {
      return;
    }

    if (handledPendingResourceImportRef.current === pendingResourceImport.token) {
      return;
    }

    handledPendingResourceImportRef.current = pendingResourceImport.token;

    navigate(`${locationPathname}${locationSearch}`, {
      replace: true,
      state: {
        gatewayPresentationEmployeeId: currentEmployee.id,
      } satisfies PortalLocationState,
    });

    window.setTimeout(() => {
      openResourceImport(pendingResourceImport.visibleContent);
    }, 0);
  }, [
    currentEmployee,
    locationPathname,
    locationSearch,
    locationState,
    navigate,
    openResourceImport,
  ]);

  useEffect(() => {
    const pendingKnowledgeBase = locationState?.pendingKnowledgeBase;
    if (!pendingKnowledgeBase || !currentEmployee) {
      return;
    }

    if (pendingKnowledgeBase.targetEmployeeId !== currentEmployee.id) {
      return;
    }

    if (handledPendingKnowledgeBaseRef.current === pendingKnowledgeBase.token) {
      return;
    }

    handledPendingKnowledgeBaseRef.current = pendingKnowledgeBase.token;

    navigate(`${locationPathname}${locationSearch}`, {
      replace: true,
      state: {
        gatewayPresentationEmployeeId: currentEmployee.id,
      } satisfies PortalLocationState,
    });

    window.setTimeout(() => {
      openKnowledgeBaseConversation(pendingKnowledgeBase.visibleContent);
    }, 0);
  }, [
    currentEmployee,
    locationPathname,
    locationSearch,
    locationState,
    navigate,
    openKnowledgeBaseConversation,
  ]);

  useEffect(() => {
    const pendingKnowledgeSearch = locationState?.pendingKnowledgeSearch;
    if (!pendingKnowledgeSearch || !currentEmployee) {
      return;
    }

    if (pendingKnowledgeSearch.targetEmployeeId !== currentEmployee.id) {
      return;
    }

    if (handledPendingKnowledgeSearchRef.current === pendingKnowledgeSearch.token) {
      return;
    }

    handledPendingKnowledgeSearchRef.current = pendingKnowledgeSearch.token;

    navigate(`${locationPathname}${locationSearch}`, {
      replace: true,
      state: {
        gatewayPresentationEmployeeId: currentEmployee.id,
      } satisfies PortalLocationState,
    });

    window.setTimeout(() => {
      searchKnowledgeBaseConversation(pendingKnowledgeSearch.visibleContent);
    }, 0);
  }, [
    currentEmployee,
    locationPathname,
    locationSearch,
    locationState,
    navigate,
    searchKnowledgeBaseConversation,
  ]);

  useEffect(() => {
    setMentionActiveIndex(0);
  }, [mentionContext?.query]);

  const focusActiveComposer = useCallback((nextCursor: number) => {
    window.requestAnimationFrame(() => {
      const activeInput = showPortalHomeHero ? homeComposerRef.current : chatInputRef.current;
      activeInput?.focus();
      activeInput?.setSelectionRange(nextCursor, nextCursor);
    });
  }, [chatInputRef, homeComposerRef, showPortalHomeHero]);

  const applyMentionSuggestion = useCallback((employeeName: string) => {
    if (!mentionContext) {
      return;
    }

    const nextValue = `${inputMessage.slice(0, mentionContext.start)}@${employeeName} ${inputMessage.slice(mentionContext.end)}`;
    const nextCursor = mentionContext.start + employeeName.length + 2;
    setInputMessage(nextValue);
    setInputCursor(nextCursor);
    focusActiveComposer(nextCursor);
  }, [focusActiveComposer, inputMessage, mentionContext]);

  const handleInputSelection = useCallback((event: ComposerSelectionEvent) => {
    const target = event.currentTarget;
    setInputCursor(target.selectionStart ?? target.value.length);
  }, []);

  const handleComposerBlur = useCallback(() => {
    window.setTimeout(() => {
      setInputCursor(null);
    }, 120);
  }, []);

  const updateComposerValue = useCallback((value: string, selectionStart: number | null) => {
    setInputMessage(value);
    setInputCursor(selectionStart ?? value.length);
  }, []);

  const handleHomeComposerChange = useCallback((event: ChangeEvent<HTMLTextAreaElement>) => {
    updateComposerValue(event.target.value, event.target.selectionStart);
  }, [updateComposerValue]);

  const handleChatComposerChange = useCallback((event: ChangeEvent<HTMLTextAreaElement>) => {
    updateComposerValue(event.target.value, event.target.selectionStart);
  }, [updateComposerValue]);

  const sendResolvedMessage = useCallback(async (rawContent: string) => {
    if (!rawContent || !currentEmployee) {
      return;
    }

    const mentionResult = extractMentionTarget(rawContent);
    if (mentionResult.employee) {
      if (
        mentionResult.employee.id === RESOURCE_IMPORT_OWNER_ID
        && isResourceImportIntent(mentionResult.cleanContent)
      ) {
        openResourceImport(mentionResult.visibleContent);
        return;
      }

      if (mentionResult.employee.id === KNOWLEDGE_BASE_OWNER_ID && mentionResult.cleanContent) {
        if (isKnowledgeBaseCardIntent(mentionResult.cleanContent)) {
          openKnowledgeBaseConversation(mentionResult.visibleContent);
          return;
        }
        searchKnowledgeBaseConversation(mentionResult.visibleContent);
        return;
      }

      const shouldUseAgentCollaboration = Boolean(
        selectedEmployee
        && isRemoteEmployee
        && remoteAgentId
        && mentionResult.employee.id !== currentEmployee.id,
      );

      if (shouldUseAgentCollaboration) {
        await dispatchActiveMessage(
          buildMentionCollaborationPrompt({
            currentEmployee,
            currentAgentId: remoteAgentId,
            targetEmployee: mentionResult.employee,
            userRequest: mentionResult.cleanContent,
          }),
          {
            visibleContent: mentionResult.visibleContent,
          },
        );
        return;
      }

      if (
        mentionResult.employee.id === ORDER_OWNER_ID
        && mentionResult.cleanContent
        && await dispatchOrderCollaboration(
          mentionResult.cleanContent,
          mentionResult.visibleContent,
        )
      ) {
        return;
      }

      if (!mentionResult.cleanContent) {
        navigateToEmployeePage(mentionResult.employee, {
          entry: null,
          view: "chat",
          panel: null,
        });
        return;
      }

      if (mentionResult.employee.id !== currentEmployee.id) {
        queueMentionDispatch(
          mentionResult.employee,
          mentionResult.cleanContent,
          mentionResult.visibleContent,
        );
        return;
      }

      await dispatchActiveMessage(mentionResult.cleanContent, {
        visibleContent: mentionResult.visibleContent,
      });
      return;
    }

    if (isResourceImportIntent(rawContent)) {
      openResourceImport(rawContent);
      return;
    }

    if (currentEmployee.id === KNOWLEDGE_BASE_OWNER_ID) {
      if (isKnowledgeBaseCardIntent(rawContent)) {
        openKnowledgeBaseConversation(rawContent);
        return;
      }
      searchKnowledgeBaseConversation(rawContent);
      return;
    }

    if (isKnowledgeBaseIntent(rawContent)) {
      if (isKnowledgeBaseCardIntent(rawContent)) {
        openKnowledgeBaseConversation(rawContent);
        return;
      }
      searchKnowledgeBaseConversation(rawContent);
      return;
    }

    await dispatchActiveMessage(rawContent);
  }, [
    currentEmployee,
    dispatchActiveMessage,
    dispatchOrderCollaboration,
    isRemoteEmployee,
    navigateToEmployeePage,
    openKnowledgeBaseConversation,
    openResourceImport,
    queueMentionDispatch,
    remoteAgentId,
    selectedEmployee,
    searchKnowledgeBaseConversation,
  ]);

  useEffect(() => {
    if (!pendingPortalHomeMessage || !isPortalHomeChat || !portalHomeChatMode) {
      return;
    }

    const nextMessage = pendingPortalHomeMessage;
    setPendingPortalHomeMessage("");
    void sendResolvedMessage(nextMessage);
  }, [
    isPortalHomeChat,
    pendingPortalHomeMessage,
    portalHomeChatMode,
    sendResolvedMessage,
  ]);

  const handleSendMessage = useCallback(async (preset = "") => {
    const rawContent = (preset || inputMessage).trim();
    if (!rawContent || !currentEmployee) {
      return;
    }

    if (!preset) {
      setInputMessage("");
    }

    if (showPortalHomeHero) {
      setPendingPortalHomeMessage(rawContent);
      setPortalHomeChatMode(true);
      return;
    }

    await sendResolvedMessage(rawContent);
  }, [
    currentEmployee,
    inputMessage,
    sendResolvedMessage,
    setPortalHomeChatMode,
    showPortalHomeHero,
  ]);

  const handleComposerKeyDown = useCallback((
    event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
    { multiline = false }: { multiline?: boolean } = {},
  ) => {
    if (isComposingInput(event)) {
      return;
    }

    if (mentionSuggestions.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setMentionActiveIndex((prev) => (prev + 1) % mentionSuggestions.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setMentionActiveIndex((prev) =>
          prev === 0 ? mentionSuggestions.length - 1 : prev - 1,
        );
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const candidate = mentionSuggestions[mentionActiveIndex]?.employee;
        if (candidate) {
          applyMentionSuggestion(candidate.name);
        }
        return;
      }
      if (event.key === "Escape") {
        setInputCursor(null);
        return;
      }
    }

    if (event.key === "Enter" && (!multiline || !event.shiftKey) && !isInteractionLocked) {
      event.preventDefault();
      void handleSendMessage();
    }
  }, [
    applyMentionSuggestion,
    handleSendMessage,
    isInteractionLocked,
    mentionActiveIndex,
    mentionSuggestions,
  ]);

  const handleHomeComposerKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>) => {
    handleComposerKeyDown(event, { multiline: true });
  }, [handleComposerKeyDown]);

  const handleChatComposerKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>) => {
    handleComposerKeyDown(event, { multiline: true });
  }, [handleComposerKeyDown]);

  return {
    inputMessage,
    setInputMessage,
    mentionSuggestions,
    mentionActiveIndex,
    showPortalHomeHero,
    createAndActivateLocalSession,
    applyMentionSuggestion,
    handleComposerBlur,
    handleInputSelection,
    handleHomeComposerChange,
    handleChatComposerChange,
    handleHomeComposerKeyDown,
    handleChatComposerKeyDown,
    handleSendMessage,
    handleResourceImportOpenSystemTopology,
    pendingAlarmRegistryIdRef,
  };
}
