import { useCallback, useEffect, useState, type MutableRefObject } from "react";
import { deleteChat, updateChat } from "../../api/copawChat";
import { saveConversationStore } from "../../lib/conversationStore";
import {
  buildPortalHomePath,
  createAlarmWorkorderMessage,
  createInitialMessages,
} from "./helpers";
import {
  KNOWLEDGE_BASE_OWNER_ID,
  RESOURCE_IMPORT_OWNER_ID,
  ensureObjectArray,
  ensureSessionRecords,
  isPortalKnowledgeBaseSession,
  isPortalResourceImportSession,
  mergeSessionRecords,
} from "./pageHelpers";
import type {
  ConversationStoreState,
  PortalLocationState,
  SessionRecord,
} from "./pageHelpers";

type MessageRecord = Record<string, any>;

export function usePortalSessionHistory({
  currentEmployee,
  isRemoteEmployee,
  isPortalHome,
  isPortalHomeChat,
  isAlarmWorkbenchMode,
  remoteAgentId,
  currentChatId,
  currentSessionId,
  activePortalResourceImportSessionId,
  activePortalKnowledgeBaseSessionId,
  conversationStore,
  setConversationStore,
  remoteSessions,
  portalResourceImportSessions,
  portalKnowledgeBaseSessions,
  historyVisible,
  setHistoryVisible,
  locationState,
  locationPathname,
  locationSearch,
  handledDashboardSessionOpenRef,
  setMessages,
  setCurrentSessionId,
  setCurrentChatId,
  setInputMessage,
  setExecutionVisible,
  setPortalHomeChatMode,
  setActivePortalResourceImportSessionId,
  setActivePortalKnowledgeBaseSessionId,
  stopActiveStream,
  refreshRemoteSessions,
  handleSelectRemoteHistory,
  resetRemoteState,
  resetAlarmWorkbench,
  loadAlarmWorkorders,
  createAndActivateLocalSession,
  navigate,
}: {
  currentEmployee: any;
  isRemoteEmployee: boolean;
  isPortalHome: boolean;
  isPortalHomeChat: boolean;
  isAlarmWorkbenchMode: boolean;
  remoteAgentId: string | null;
  currentChatId: string;
  currentSessionId: string;
  activePortalResourceImportSessionId: string;
  activePortalKnowledgeBaseSessionId: string;
  conversationStore: ConversationStoreState;
  setConversationStore: React.Dispatch<React.SetStateAction<ConversationStoreState>>;
  remoteSessions: SessionRecord[];
  portalResourceImportSessions: SessionRecord[];
  portalKnowledgeBaseSessions: SessionRecord[];
  historyVisible: boolean;
  setHistoryVisible: React.Dispatch<React.SetStateAction<boolean>>;
  locationState: PortalLocationState | null;
  locationPathname: string;
  locationSearch: string;
  handledDashboardSessionOpenRef: MutableRefObject<string>;
  setMessages: React.Dispatch<React.SetStateAction<MessageRecord[]>>;
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string>>;
  setCurrentChatId: React.Dispatch<React.SetStateAction<string>>;
  setInputMessage: React.Dispatch<React.SetStateAction<string>>;
  setExecutionVisible: React.Dispatch<React.SetStateAction<boolean>>;
  setPortalHomeChatMode: React.Dispatch<React.SetStateAction<boolean>>;
  setActivePortalResourceImportSessionId: React.Dispatch<React.SetStateAction<string>>;
  setActivePortalKnowledgeBaseSessionId: React.Dispatch<React.SetStateAction<string>>;
  stopActiveStream: (preserveAssistant?: boolean, options?: { silent?: boolean }) => void;
  refreshRemoteSessions: (preserveVisible?: boolean) => Promise<void> | void;
  handleSelectRemoteHistory: (session: SessionRecord) => Promise<void>;
  resetRemoteState: (options?: { initialMessages?: MessageRecord[]; clearHistoryError?: boolean }) => void;
  resetAlarmWorkbench: () => void;
  loadAlarmWorkorders: () => Promise<void> | void;
  createAndActivateLocalSession: (employee: any, initialMessages: MessageRecord[]) => string;
  navigate: (to: string, options?: { replace?: boolean; state?: PortalLocationState | {} | null }) => void;
}) {
  const [historyEditingId, setHistoryEditingId] = useState("");
  const [historyDraftTitle, setHistoryDraftTitle] = useState("");
  const [historyActionSessionId, setHistoryActionSessionId] = useState("");
  const [historyActionError, setHistoryActionError] = useState("");
  const scopedRemoteSessions = isRemoteEmployee && currentEmployee?.id === RESOURCE_IMPORT_OWNER_ID
    ? mergeSessionRecords(remoteSessions, portalResourceImportSessions)
    : isRemoteEmployee && currentEmployee?.id === KNOWLEDGE_BASE_OWNER_ID
      ? mergeSessionRecords(remoteSessions, portalKnowledgeBaseSessions)
      : remoteSessions;

  const persistLocalSessions = useCallback((employeeId: string, nextSessions: SessionRecord[]) => {
    const nextStore: ConversationStoreState = {
      ...conversationStore,
      [employeeId]: nextSessions,
    };
    saveConversationStore(nextStore);
    setConversationStore(nextStore);
    return nextStore;
  }, [conversationStore, setConversationStore]);

  useEffect(() => {
    if (historyVisible) {
      return;
    }
    setHistoryEditingId("");
    setHistoryDraftTitle("");
    setHistoryActionSessionId("");
    setHistoryActionError("");
  }, [historyVisible]);

  const handleSelectHistory = useCallback(async (session: SessionRecord) => {
    if (!currentEmployee) {
      return;
    }

    if (!isRemoteEmployee) {
      setActivePortalResourceImportSessionId(
        isPortalResourceImportSession(session) ? session.id : "",
      );
      setActivePortalKnowledgeBaseSessionId(
        isPortalKnowledgeBaseSession(session) ? session.id : "",
      );
      setCurrentSessionId(session.id);
      setMessages(session.messages || []);
      setPortalHomeChatMode(
        Boolean(session.messages?.length)
        || isPortalResourceImportSession(session)
        || isPortalKnowledgeBaseSession(session),
      );
      setHistoryVisible(false);
      return;
    }

    if (isPortalResourceImportSession(session) || isPortalKnowledgeBaseSession(session)) {
      stopActiveStream(false, { silent: true });
      setActivePortalResourceImportSessionId(isPortalResourceImportSession(session) ? session.id : "");
      setActivePortalKnowledgeBaseSessionId(isPortalKnowledgeBaseSession(session) ? session.id : "");
      setCurrentChatId("");
      setCurrentSessionId("");
      setMessages(ensureObjectArray(session.messages));
      setPortalHomeChatMode(true);
      setHistoryVisible(false);
      return;
    }

    setActivePortalResourceImportSessionId("");
    setActivePortalKnowledgeBaseSessionId("");
    setPortalHomeChatMode(true);
    await handleSelectRemoteHistory(session);
  }, [
    currentEmployee,
    handleSelectRemoteHistory,
    isRemoteEmployee,
    setActivePortalResourceImportSessionId,
    setActivePortalKnowledgeBaseSessionId,
    setCurrentChatId,
    setCurrentSessionId,
    setHistoryVisible,
    setMessages,
    setPortalHomeChatMode,
    stopActiveStream,
  ]);

  useEffect(() => {
    const openSession = locationState?.openSession;
    if (!openSession || !currentEmployee) {
      return;
    }

    if (openSession.employeeId !== currentEmployee.id) {
      return;
    }

    const openKey = `${openSession.employeeId}:${openSession.sessionId}`;
    const availableSessions = isRemoteEmployee
      ? scopedRemoteSessions
      : ensureSessionRecords(conversationStore[currentEmployee.id]);
    const targetSession = availableSessions.find(
      (session) =>
        session.id === openSession.chatId
        || session.id === openSession.sessionId
        || session.sessionId === openSession.sessionId,
    );

    if (targetSession) {
      handledDashboardSessionOpenRef.current = "";
      navigate(`${locationPathname}${locationSearch}`, {
        replace: true,
        state: {},
      });
      void handleSelectHistory(targetSession);
      return;
    }

    if (isRemoteEmployee && handledDashboardSessionOpenRef.current !== openKey) {
      handledDashboardSessionOpenRef.current = openKey;
      void refreshRemoteSessions(false);
    }
  }, [
    conversationStore,
    currentEmployee,
    handleSelectHistory,
    handledDashboardSessionOpenRef,
    isRemoteEmployee,
    locationPathname,
    locationSearch,
    locationState,
    navigate,
    refreshRemoteSessions,
    scopedRemoteSessions,
  ]);

  const handleStartNewConversation = useCallback(() => {
    if (!currentEmployee) {
      return;
    }

    setInputMessage("");
    setExecutionVisible(false);
    setActivePortalResourceImportSessionId("");
    setActivePortalKnowledgeBaseSessionId("");

    if (!isPortalHome) {
      resetAlarmWorkbench();
      resetRemoteState({
        initialMessages: [],
      });
      setPortalHomeChatMode(false);
      setHistoryVisible(false);
      navigate(buildPortalHomePath({ view: "chat" }), {
        state: null,
      });
      return;
    }

    if (isAlarmWorkbenchMode) {
      resetAlarmWorkbench();
      resetRemoteState({
        initialMessages: [
          createAlarmWorkorderMessage(currentEmployee, {
            content: "告警已触发，我正在为您查询待处置工单...",
            workorders: [],
            workordersLoading: true,
            workordersError: "",
          }),
        ],
      });
      void loadAlarmWorkorders();
      return;
    }

    if (isRemoteEmployee) {
      resetRemoteState({
        initialMessages: isPortalHome ? [] : createInitialMessages(currentEmployee),
      });
      setPortalHomeChatMode(false);
      return;
    }

    const initialMessages = createInitialMessages(currentEmployee);
    createAndActivateLocalSession(currentEmployee, initialMessages);
    setMessages(initialMessages);
    setPortalHomeChatMode(false);
    setHistoryVisible(false);
  }, [
    createAndActivateLocalSession,
    currentEmployee,
    isAlarmWorkbenchMode,
    isPortalHome,
    isRemoteEmployee,
    loadAlarmWorkorders,
    navigate,
    resetAlarmWorkbench,
    resetRemoteState,
    setActivePortalResourceImportSessionId,
    setActivePortalKnowledgeBaseSessionId,
    setExecutionVisible,
    setHistoryVisible,
    setInputMessage,
    setMessages,
    setPortalHomeChatMode,
  ]);

  const handleStartHistoryRename = useCallback((session: SessionRecord) => {
    setHistoryActionError("");
    setHistoryEditingId(session.id);
    setHistoryDraftTitle(session.title);
  }, []);

  const handleCancelHistoryRename = useCallback(() => {
    setHistoryEditingId("");
    setHistoryDraftTitle("");
    setHistoryActionError("");
  }, []);

  const handleSubmitHistoryRename = useCallback(async (session: SessionRecord) => {
    if (!currentEmployee) {
      return;
    }

    const nextTitle = historyDraftTitle.trim();
    if (!nextTitle) {
      setHistoryActionError("会话名称不能为空");
      return;
    }

    if (nextTitle === session.title) {
      handleCancelHistoryRename();
      return;
    }

    setHistoryActionSessionId(session.id);
    setHistoryActionError("");

    try {
      if (
        isRemoteEmployee
        && !isPortalResourceImportSession(session)
        && !isPortalKnowledgeBaseSession(session)
      ) {
        await updateChat(remoteAgentId || undefined, session.id, { name: nextTitle });
        await refreshRemoteSessions(false);
      } else {
        const previousSessions = ensureSessionRecords(conversationStore[currentEmployee.id]);
        const nextSessions = previousSessions.map((item) =>
          item.id === session.id
            ? {
                ...item,
                title: nextTitle,
                updatedAt: new Date().toISOString(),
              }
            : item,
        );
        persistLocalSessions(currentEmployee.id, nextSessions);
      }

      setHistoryEditingId("");
      setHistoryDraftTitle("");
    } catch (error: any) {
      setHistoryActionError(error?.message || "会话名称更新失败，请稍后重试");
    } finally {
      setHistoryActionSessionId("");
    }
  }, [
    conversationStore,
    currentEmployee,
    handleCancelHistoryRename,
    historyDraftTitle,
    isRemoteEmployee,
    persistLocalSessions,
    refreshRemoteSessions,
    remoteAgentId,
  ]);

  const handleDeleteHistorySession = useCallback(async (session: SessionRecord) => {
    if (!currentEmployee) {
      return;
    }

    if (!window.confirm(`确认删除“${session.title}”吗？`)) {
      return;
    }

    setHistoryActionSessionId(session.id);
    setHistoryActionError("");

    try {
      if (isPortalResourceImportSession(session) || isPortalKnowledgeBaseSession(session)) {
        const previousSessions = ensureSessionRecords(conversationStore[currentEmployee.id]);
        const nextSessions = previousSessions.filter((item) => item.id !== session.id);
        persistLocalSessions(currentEmployee.id, nextSessions);

        if (
          activePortalResourceImportSessionId === session.id
          || activePortalKnowledgeBaseSessionId === session.id
        ) {
          if (isPortalResourceImportSession(session)) {
            setActivePortalResourceImportSessionId("");
          }
          if (isPortalKnowledgeBaseSession(session)) {
            setActivePortalKnowledgeBaseSessionId("");
          }
          if (isRemoteEmployee) {
            resetRemoteState({
              initialMessages: createInitialMessages(currentEmployee),
            });
          } else if (session.id === currentSessionId) {
            const nextActiveSession = nextSessions[0];
            if (nextActiveSession) {
              setCurrentSessionId(nextActiveSession.id);
              setMessages(nextActiveSession.messages || []);
            } else {
              setCurrentSessionId("");
              setMessages(createInitialMessages(currentEmployee));
            }
          }
        }

        if (historyEditingId === session.id) {
          setHistoryEditingId("");
          setHistoryDraftTitle("");
        }
        return;
      }

      if (isRemoteEmployee) {
        const deletingCurrentSession = session.id === currentChatId;
        if (deletingCurrentSession) {
          stopActiveStream(false, { silent: true });
        }
        await deleteChat(remoteAgentId || undefined, session.id);
        if (deletingCurrentSession) {
          resetRemoteState({
            initialMessages: createInitialMessages(currentEmployee),
            clearHistoryError: false,
          });
          setHistoryVisible(true);
        }
        await refreshRemoteSessions(!deletingCurrentSession);
      } else {
        const previousSessions = ensureSessionRecords(conversationStore[currentEmployee.id]);
        const nextSessions = previousSessions.filter((item) => item.id !== session.id);
        persistLocalSessions(currentEmployee.id, nextSessions);

        if (session.id === currentSessionId) {
          const nextActiveSession = nextSessions[0];
          if (nextActiveSession) {
            setCurrentSessionId(nextActiveSession.id);
            setMessages(nextActiveSession.messages || []);
          } else {
            setCurrentSessionId("");
            setMessages(createInitialMessages(currentEmployee));
          }
        }
      }

      if (historyEditingId === session.id) {
        setHistoryEditingId("");
        setHistoryDraftTitle("");
      }
    } catch (error: any) {
      setHistoryActionError(error?.message || "删除会话失败，请稍后重试");
    } finally {
      setHistoryActionSessionId("");
    }
  }, [
    activePortalResourceImportSessionId,
    activePortalKnowledgeBaseSessionId,
    conversationStore,
    currentChatId,
    currentEmployee,
    currentSessionId,
    historyEditingId,
    isRemoteEmployee,
    persistLocalSessions,
    refreshRemoteSessions,
    remoteAgentId,
    resetRemoteState,
    setActivePortalResourceImportSessionId,
    setActivePortalKnowledgeBaseSessionId,
    setCurrentSessionId,
    setHistoryVisible,
    setMessages,
    stopActiveStream,
  ]);

  return {
    historyEditingId,
    historyDraftTitle,
    setHistoryDraftTitle,
    historyActionSessionId,
    historyActionError,
    handleSelectHistory,
    handleStartNewConversation,
    handleStartHistoryRename,
    handleCancelHistoryRename,
    handleSubmitHistoryRename,
    handleDeleteHistorySession,
  };
}
