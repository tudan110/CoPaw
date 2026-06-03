import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type WheelEvent,
} from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  digitalEmployees,
  executionHistory,
  getEmployeeById,
} from "../data/portalData";
import type { DigitalEmployee } from "../types/portal";
import {
  createConversationSession,
  loadConversationStore,
  saveConversationStore,
} from "../lib/conversationStore";
import {
  getPortalEmployeeStatuses,
  type PortalEmployeeRuntimeStatus,
} from "../api/portalEmployeeStatus";
import {
  AdvancedModelEntry,
  ChatModelSelector,
  ModelConfigModal,
} from "./digital-employee/modelControls";
import {
  DashboardPanel,
  DashboardHistoryModal,
  DigitalEmployeePageErrorBoundary,
  DisposalConfirmModal,
  EmployeeChatMainPanel,
  EmployeeChatSidebar,
  ExecutionHistoryModal,
  PortalAlertBell,
  PortalHomeHero,
  SessionHistoryModal,
  SidebarEmployeeCard,
} from "./digital-employee/pageFragments";
import {
  ALARM_WORKORDER_ENTRY,
  createAgentMessage,
  createAlarmWorkorderMessage,
  createInitialMessages,
  createUserMessage,
  parsePortalAdvancedPanel,
  parsePortalView,
  type PortalRouteSection,
} from "./digital-employee/helpers";
import { useAlarmWorkbench } from "./digital-employee/useAlarmWorkbench";
import { usePortalAlerts } from "./digital-employee/usePortalAlerts";
import { usePortalChatOrchestration } from "./digital-employee/usePortalChatOrchestration";
import { usePortalDashboard } from "./digital-employee/usePortalDashboard";
import { usePortalNavigationSidebar } from "./digital-employee/usePortalNavigationSidebar";
import { usePortalModels } from "./digital-employee/usePortalModels";
import { usePortalKnowledgeBase } from "./digital-employee/usePortalKnowledgeBase";
import { usePortalResourceImport } from "./digital-employee/usePortalResourceImport";
import { usePortalSessionHistory } from "./digital-employee/usePortalSessionHistory";
import { useRemoteChatSession } from "./digital-employee/useRemoteChatSession";
import { portalAppTitle } from "../config/portalBranding";
import portalLogo from "../assets/images/portal-logo.png";
import PortalTraditionalViewButton from "../components/PortalTraditionalViewButton";
import "./digital-employee.css";

import {
  REMOTE_AGENT_IDS,
  PORTAL_HOME_AGENT_ID,
  PORTAL_HOME_ID,
  RESOURCE_IMPORT_OWNER_ID,
  KNOWLEDGE_BASE_OWNER_ID,
  RESOURCE_IMPORT_COMMAND,
  KNOWLEDGE_BASE_SEARCH_COMMAND,
  CHAT_SCROLL_BOTTOM_THRESHOLD_PX,
  isPortalResourceImportSession,
  mergeSessionRecords,
  areEmployeeRuntimeStatusMapsEqual,
  formatEmployeeStatsLabel,
  getEmployeeProfileMotto,
  getChatSidebarActivities,
  PORTAL_HOME_EMPLOYEE,
  PORTAL_ALERT_LEVEL_LABELS,
  PORTAL_ALERT_LEVEL_COLORS,
  loadPageTheme,
  persistPageTheme,
  loadSidebarCollapsed,
  persistSidebarCollapsed,
  loadChatSidebarCollapsed,
  persistChatSidebarCollapsed,
  ensureSessionRecords,
  ensureObjectArray,
  ensureStringArray,
  isPortalKnowledgeBaseSession,
  isKnowledgeBaseCardIntent,
} from "./digital-employee/pageHelpers";
import { lazyNamed } from "../utils/lazyNamed";
import { updateAlarmRegistryStatus } from "../api/alarmRegistry";

const CronJobsPanel = lazyNamed(
  () => import("./digital-employee/cronJobsPanel"),
  "CronJobsPanel",
);
const CliTerminalPanel = lazyNamed(
  () => import("./digital-employee/cliTerminalPanel"),
  "CliTerminalPanel",
);
const InspirationPanel = lazyNamed(
  () => import("./digital-employee/inspirationPanel"),
  "InspirationPanel",
);
const McpPanel = lazyNamed(() => import("./digital-employee/mcpPanel"), "McpPanel");
const OverviewPanel = lazyNamed(
  () => import("./digital-employee/overviewPanel"),
  "OverviewPanel",
);
const ResourceImportPanel = lazyNamed(
  () => import("./digital-employee/resourceImportPanel"),
  "ResourceImportPanel",
);
const SettingsPanel = lazyNamed(
  () => import("./digital-employee/settingsPanel"),
  "SettingsPanel",
);
const SkillPoolPanel = lazyNamed(
  () => import("./digital-employee/skillPoolPanel"),
  "SkillPoolPanel",
);
const FdeWorkbenchPanel = lazyNamed(
  () => import("./digital-employee/fdeWorkbenchPanel"),
  "FdeWorkbenchPanel",
);
const KnowledgeBasePanel = lazyNamed(
  () => import("./digital-employee/knowledgeBasePanel"),
  "KnowledgeBasePanel",
);
const NaturalLanguageCustomizationPanel = lazyNamed(
  () => import("./digital-employee/naturalLanguageCustomizationPanel"),
  "NaturalLanguageCustomizationPanel",
);
const AppMarketPanel = lazyNamed(
  () => import("./digital-employee/appMarketPanel"),
  "AppMarketPanel",
);
const TokenUsagePanel = lazyNamed(
  () => import("./digital-employee/tokenUsagePanel"),
  "TokenUsagePanel",
);
const OpsExpertPanel = lazyNamed(
  () => import("./digital-employee/opsExpertPanel"),
  "OpsExpertPanel",
);
const TracesCenterPanel = lazyNamed(
  () => import("./digital-employee/tracesCenterPanel"),
  "TracesCenterPanel",
);
const AlarmRegistryPanel = lazyNamed(
  () => import("./digital-employee/alarmRegistryPanel"),
  "AlarmRegistryPanel",
);
const AppArtifactsPanel = lazyNamed(
  () => import("./digital-employee/appArtifactsPanel"),
  "AppArtifactsPanel",
);
const AppWorkbenchPanel = lazyNamed(
  () => import("./digital-employee/appWorkbenchPanel"),
  "AppWorkbenchPanel",
);
const DashboardAssemblyPanel = lazyNamed(
  () => import("./digital-employee/dashboardAssemblyPanel"),
  "DashboardAssemblyPanel",
);
const ChannelsPanel = lazyNamed(
  () => import("./digital-employee/channelsPanel"),
  "ChannelsPanel",
);
const InboxPanel = lazyNamed(() => import("./digital-employee/inboxPanel"), "InboxPanel");

const panelLoadingFallback = (
  <div className="history-empty" style={{ minHeight: 280 }}>
    <i className="fas fa-spinner fa-spin" />
    <p>正在加载页面内容...</p>
  </div>
);

function renderDeferredPanel(node: ReactNode) {
  return <Suspense fallback={panelLoadingFallback}>{node}</Suspense>;
}
import type {
  PortalLocationState,
  ChatSidebarSectionKey,
  SessionRecord,
  ConversationStoreState,
  ExecutionRecord
} from "./digital-employee/pageHelpers";


export default function DigitalEmployeePage({
  forcedSection,
}: {
  forcedSection?: PortalRouteSection;
}) {
  const { employeeId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const locationState = (location.state || null) as PortalLocationState | null;
  const routeSearchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );
  const selectedEmployee = useMemo(() => {
    const routeEmployeeId = employeeId || routeSearchParams.get("employee");
    if (!routeEmployeeId) {
      return null;
    }
    return digitalEmployees.find((item) => item.id === routeEmployeeId) || null;
  }, [employeeId, routeSearchParams]);
  const portalHomeEmployee = useMemo(() => ({ ...PORTAL_HOME_EMPLOYEE }), []);
  const routeSection = forcedSection || null;
  const remoteAgentId = selectedEmployee
    ? (REMOTE_AGENT_IDS[selectedEmployee.id] || null)
    : PORTAL_HOME_AGENT_ID;
  const isRemoteEmployee = Boolean(remoteAgentId);
  const currentEntry = routeSearchParams.get("entry");
  const currentView = parsePortalView(routeSection ?? routeSearchParams.get("view"));
  const activeAdvancedPanel = parsePortalAdvancedPanel(
    routeSection ?? routeSearchParams.get("panel"),
  );
  const isModelConfigMode = activeAdvancedPanel === "model-config";
  const isSettingsMode = activeAdvancedPanel === "settings";
  const isTokenUsageMode = activeAdvancedPanel === "token-usage";
  const isOpsExpertMode = activeAdvancedPanel === "ops-expert";
  const isMcpMode = activeAdvancedPanel === "mcp";
  const isSkillPoolMode = activeAdvancedPanel === "skill-pool";
  const isFdeWorkbenchMode = activeAdvancedPanel === "fde-workbench";
  const isKnowledgeBaseMode = activeAdvancedPanel === "knowledge-base";
  const isInspirationMode = activeAdvancedPanel === "inspiration";
  const isCliMode = activeAdvancedPanel === "cli";
  const isResourceImportMode = activeAdvancedPanel === "resource-import";
  const isNlCustomizationMode = activeAdvancedPanel === "nl-customization";
  const isAppMarketMode = activeAdvancedPanel === "app-market";
  const isTracesMode = activeAdvancedPanel === "traces";
  const isAlarmRegistryMode = activeAdvancedPanel === "alarm-registry";
  const isAppArtifactsMode = activeAdvancedPanel === "app-artifacts";
  const isAppWorkbenchMode = activeAdvancedPanel === "app-workbench";
  const isDashboardAssemblyMode = activeAdvancedPanel === "dashboard-assembly";
  const isChannelsMode = activeAdvancedPanel === "channels";
  const isInboxMode = activeAdvancedPanel === "inbox";
  const isPortalHome = !selectedEmployee;
  const isPortalHomeChat = isPortalHome && currentView === "chat" && !activeAdvancedPanel;
  const isAlarmWorkbenchMode = Boolean(
    selectedEmployee?.id === "fault" && currentEntry === ALARM_WORKORDER_ENTRY,
  );

  const [messages, setMessages] = useState<any[]>([]);
  const [portalHomeChatMode, setPortalHomeChatMode] = useState(false);
  const [conversationStore, setConversationStore] = useState<ConversationStoreState>(
    () => loadConversationStore() as ConversationStoreState,
  );
  const [executionVisible, setExecutionVisible] = useState(false);
  const [executionTitle, setExecutionTitle] = useState("执行历史");
  const [executionList, setExecutionList] = useState(executionHistory);
  const [pageTheme, setPageTheme] = useState<"light" | "dark">(loadPageTheme);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(loadSidebarCollapsed);
  const [chatSidebarCollapsed, setChatSidebarCollapsed] = useState<boolean>(loadChatSidebarCollapsed);
  const [chatSidebarCollapsedSections, setChatSidebarCollapsedSections] = useState<
    Record<ChatSidebarSectionKey, boolean>
  >({
    profile: false,
    activity: false,
    efficiency: false,
    collaboration: false,
  });
  const [employeeRuntimeStatusMap, setEmployeeRuntimeStatusMap] = useState<
    Record<string, PortalEmployeeRuntimeStatus>
  >({});
  const employeesWithRuntimeStatus = useMemo(
    () =>
      digitalEmployees.map((employee) => {
        const runtime = employeeRuntimeStatusMap[employee.id];
        return {
          ...employee,
          status: runtime?.status || employee.status,
          urgent: Boolean(runtime?.urgent),
          statusLabel:
            runtime?.stateLabel || (employee.urgent ? "紧急处理中" : employee.status === "running" ? "运行中" : "已停止"),
        };
      }),
    [employeeRuntimeStatusMap],
  );
  const selectedEmployeeRuntime = useMemo(() => {
    if (!selectedEmployee) {
      return null;
    }
    return (
      employeesWithRuntimeStatus.find((item) => item.id === selectedEmployee.id) ||
      selectedEmployee
    );
  }, [employeesWithRuntimeStatus, selectedEmployee]);
  const currentEmployeeBase = selectedEmployee || portalHomeEmployee;
  const currentEmployee = selectedEmployeeRuntime || portalHomeEmployee;
  const currentEmployeeActivities = useMemo(
    () => getChatSidebarActivities(currentEmployee.id),
    [currentEmployee.id],
  );
  const chatSidebarWorkload = useMemo(() => {
    const templates: Record<string, number[]> = {
      query: [58, 82, 64, 92, 76, 61, 88],
      fault: [72, 90, 68, 95, 84, 73, 87],
      resource: [45, 66, 57, 79, 74, 62, 70],
      inspection: [51, 63, 59, 77, 81, 67, 72],
      order: [60, 74, 69, 88, 92, 70, 78],
      knowledge: [48, 71, 65, 82, 75, 69, 80],
    };

    return templates[currentEmployee.id] || templates.query;
  }, [currentEmployee.id]);
  const chatSidebarEfficiency = useMemo(() => {
    const templates: Record<string, { completed: number; total: number; response: string; collaboration: number }> = {
      query: { completed: 23, total: 25, response: "1.2s", collaboration: 42 },
      fault: { completed: 18, total: 20, response: "0.8s", collaboration: 57 },
      resource: { completed: 16, total: 18, response: "1.4s", collaboration: 31 },
      inspection: { completed: 21, total: 21, response: "1.1s", collaboration: 28 },
      order: { completed: 19, total: 22, response: "1.0s", collaboration: 46 },
      knowledge: { completed: 24, total: 26, response: "0.9s", collaboration: 39 },
    };

    return templates[currentEmployee.id] || templates.query;
  }, [currentEmployee.id]);
  const chatSidebarCollaborators = useMemo(() => {
    const collaborationCountMap: Record<string, Record<string, number>> = {
      query: { fault: 18, resource: 13, knowledge: 24, inspection: 9, order: 11 },
      fault: { query: 18, order: 22, knowledge: 15, resource: 10, inspection: 8 },
      resource: { order: 16, query: 13, fault: 10, inspection: 12, knowledge: 7 },
      inspection: { knowledge: 14, query: 9, order: 8, resource: 12, fault: 8 },
      order: { fault: 22, resource: 16, query: 11, knowledge: 12, inspection: 8 },
      knowledge: { query: 24, fault: 15, inspection: 14, order: 12, resource: 7 },
    };

    return employeesWithRuntimeStatus
      .filter((employee) => employee.id !== currentEmployee.id)
      .slice(0, 3)
      .map((employee) => ({
        ...employee,
        collaborationCount: collaborationCountMap[currentEmployee.id]?.[employee.id] || 6,
      }));
  }, [currentEmployee.id, employeesWithRuntimeStatus]);
  const themeToggleIcon: ReactNode = pageTheme === "light" ? (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ) : (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
  const alertBellIcon: ReactNode = (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const handledDashboardSessionOpenRef = useRef("");
  const chatInputRef = useRef<HTMLTextAreaElement | null>(null);
  const homeComposerRef = useRef<HTMLTextAreaElement | null>(null);
  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const latestMessagesRef = useRef<any[]>([]);
  const pendingReplyFocusBaselineRef = useRef<Set<string> | null>(null);
  const pendingReplyFocusExpiryTimerRef = useRef(0);
  const replyFocusAlignmentHandlesRef = useRef<{ raf: number[]; timers: number[] }>({
    raf: [],
    timers: [],
  });
  const suppressAutoScrollStateUntilRef = useRef(0);
  const lastChatScrollTopRef = useRef(0);
  const lastChatScrollMaxTopRef = useRef(0);
  const clearReplyFocusAlignmentHandles = useCallback(() => {
    replyFocusAlignmentHandlesRef.current.raf.forEach((handle) => {
      window.cancelAnimationFrame(handle);
    });
    replyFocusAlignmentHandlesRef.current.timers.forEach((handle) => {
      window.clearTimeout(handle);
    });
    replyFocusAlignmentHandlesRef.current = { raf: [], timers: [] };
  }, []);
  const clearPendingReplyFocus = useCallback(() => {
    clearReplyFocusAlignmentHandles();
    pendingReplyFocusBaselineRef.current = null;
    if (pendingReplyFocusExpiryTimerRef.current) {
      window.clearTimeout(pendingReplyFocusExpiryTimerRef.current);
      pendingReplyFocusExpiryTimerRef.current = 0;
    }
  }, [clearReplyFocusAlignmentHandles]);
  const rememberChatScrollMetrics = useCallback(() => {
    const chatContainer = chatMessagesRef.current;
    if (!chatContainer) {
      return;
    }

    lastChatScrollTopRef.current = chatContainer.scrollTop;
    lastChatScrollMaxTopRef.current = Math.max(
      0,
      chatContainer.scrollHeight - chatContainer.clientHeight,
    );
  }, []);
  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const chatContainer = chatMessagesRef.current;
    if (!chatContainer) {
      return;
    }

    chatContainer.scrollTo({
      top: chatContainer.scrollHeight,
      behavior,
    });
    window.requestAnimationFrame(rememberChatScrollMetrics);
  }, [rememberChatScrollMetrics]);
  const requestReplyFocusOnNextAssistant = useCallback(() => {
    clearReplyFocusAlignmentHandles();
    if (pendingReplyFocusExpiryTimerRef.current) {
      window.clearTimeout(pendingReplyFocusExpiryTimerRef.current);
    }
    rememberChatScrollMetrics();
    pendingReplyFocusBaselineRef.current = new Set(
      latestMessagesRef.current
        .map((message) => String(message?.id || ""))
        .filter(Boolean),
    );
    shouldAutoScrollRef.current = false;
    pendingReplyFocusExpiryTimerRef.current = window.setTimeout(() => {
      pendingReplyFocusBaselineRef.current = null;
      pendingReplyFocusExpiryTimerRef.current = 0;
    }, 12000);
  }, [clearReplyFocusAlignmentHandles, rememberChatScrollMetrics]);

  const {
    currentSessionId,
    setCurrentSessionId,
    currentChatId,
    setCurrentChatId,
    currentChatStatus,
    historyVisible,
    setHistoryVisible,
    historyLoading,
    historyError,
    remoteSessions,
    isCreatingChat,
    isStreaming,
    activeAssistantMessageIdRef,
    handleRemoteSendMessage,
    stopActiveStream,
    refreshRemoteSessions,
    handleOpenHistory,
    handleSelectRemoteHistory,
    resetRemoteState,
  } = useRemoteChatSession({
    currentEmployee,
    isRemoteEmployee,
    remoteAgentId,
    setMessages,
  });
  const isRemoteConversationRunning = isStreaming || currentChatStatus === "running";

  const {
    alarmWorkorders,
    alarmWorkordersLoading,
    alarmWorkordersError,
    ticketActionNotice,
    faultDiagnosisBusy,
    pendingDisposalAction,
    isSubmittingDisposalAction,
    loadAlarmWorkorders,
    handleAlarmWorkbenchTicketAction,
    handleAlarmDisposalOperationRequest,
    handleCancelDisposalAction,
    handleConfirmDisposalAction,
    resetAlarmWorkbench,
  } = useAlarmWorkbench({
    currentEmployee,
    isAlarmWorkbenchMode,
    currentSessionId,
    handleRemoteSendMessage,
    messages,
    setMessages,
  });

  const modelAgentId = remoteAgentId || "default";
  const {
    displayProviders,
    eligibleProviders,
    activeProviderId,
    activeProviderName,
    activeModelId,
    activeModelLabel,
    globalActiveProviderId,
    globalActiveProviderName,
    globalActiveModelId,
    globalActiveModelLabel,
    usesGlobalDefault,
    loading: modelsLoading,
    switching: modelsSwitching,
    submitting: modelsSubmitting,
    notice: modelNotice,
    fetchModelState,
    handleSelectModel,
    handleSelectDefaultModel,
    handleSaveProvider,
    handleAddModel,
    handleDeleteProvider,
    handleRevokeProviderAuth,
    handleApplyBuiltinApiKey,
    handleRemoveModel,
    handleConfigureModel,
    handleTestProvider,
    handleTestModel,
    handleProbeMultimodal,
    handleDiscoverModels,
  } = usePortalModels({
    agentId: modelAgentId,
    enabled: Boolean(currentEmployee),
  });

  const {
    navigateToEmployeePage,
    navigateToPortalHome,
    updateCurrentEmployeeRoute,
    openSkillPool,
    openFdeWorkbench,
    openKnowledgeBase,
    openInspiration,
    openCli,
    switchMcpEmployee,
    openEmployeeChat,
    sidebarEmployees,
    currentSidebarEmployee,
    sidebarCardEmployee,
    getEmployeeStatusBadgeClassName,
    getEmployeeStatusLabel,
  } = usePortalNavigationSidebar({
    navigate,
    selectedEmployee,
    currentEntry,
    currentView,
    activeAdvancedPanel,
    employeesWithRuntimeStatus,
    portalHomeEmployee,
    isMcpMode,
  });

  const openModelConfig = () => {
    updateCurrentEmployeeRoute({
      panel: "model-config",
    });
  };

  const {
    resourceImportEmployee,
    activePortalResourceImportSessionId,
    setActivePortalResourceImportSessionId,
    portalResourceImportSessions,
    resolveResourceImportFiles,
    releaseResourceImportFiles,
    handleResourceImportUploadFiles,
    handleResourceImportStartParse,
    handleResourceImportParseResolved,
    handleResourceImportConfirmStructure,
    handleResourceImportParseFailed,
    handleResourceImportReturnToUpload,
    handleResourceImportBuildTopology,
    handleResourceImportBackToConfirm,
    handleResourceImportSubmitImport,
    handleResourceImportContinue,
    findResourceImportFlowById,
    handleResourceImportScrollToStage,
    openResourceImport,
  } = usePortalResourceImport({
    conversationStore,
    setConversationStore,
    messages,
    setMessages,
    selectedEmployeeId: selectedEmployee?.id,
    remoteAgentId,
    navigateToEmployeePage,
    setCurrentChatId,
    createAgentMessage,
    createUserMessage,
  });

  const {
    openKnowledgeBaseConversation,
    searchKnowledgeBaseConversation,
    updateKnowledgeBaseFlowMessage,
    portalKnowledgeBaseSessions,
    activePortalKnowledgeBaseSessionId,
    isKnowledgeBaseRunning,
    setActivePortalKnowledgeBaseSessionId,
    stopKnowledgeBaseTask,
  } = usePortalKnowledgeBase({
    conversationStore,
    setConversationStore,
    messages,
    setMessages,
    selectedEmployeeId: selectedEmployee?.id,
    navigateToEmployeePage,
    setCurrentChatId,
    createAgentMessage,
    createUserMessage,
  });
  const isConversationRunning = isRemoteConversationRunning || isKnowledgeBaseRunning;
  const isInteractionLocked = isCreatingChat || isConversationRunning;

  const {
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
  } = usePortalChatOrchestration({
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
    onConversationDispatchStart: requestReplyFocusOnNextAssistant,
    homeComposerRef,
    chatInputRef,
    locationState,
    locationPathname: location.pathname,
    locationSearch: location.search,
  });

  // Backfill chatId into alarm registry when a new chat is created for a bell-triggered alarm
  useEffect(() => {
    const alarmId = pendingAlarmRegistryIdRef.current;
    if (!alarmId || !currentChatId) return;
    pendingAlarmRegistryIdRef.current = "";
    void updateAlarmRegistryStatus(alarmId, "", currentChatId).catch(() => {});
  }, [currentChatId, pendingAlarmRegistryIdRef]);

  const handleQuickCommand = useCallback((command?: string) => {
    const normalizedCommand = String(command || "").trim();
    if (/知识库|知识检索|文档导入|资料入库|知识沉淀/.test(normalizedCommand)) {
      if (isKnowledgeBaseCardIntent(normalizedCommand)) {
        openKnowledgeBaseConversation(normalizedCommand || KNOWLEDGE_BASE_SEARCH_COMMAND);
        return;
      }
      searchKnowledgeBaseConversation(normalizedCommand || KNOWLEDGE_BASE_SEARCH_COMMAND);
      return;
    }
    void handleSendMessage(command);
  }, [handleSendMessage, openKnowledgeBaseConversation, searchKnowledgeBaseConversation]);

  const {
    sortedOpsAlerts,
    alertToast,
    alertPopupOpen,
    alertPopupPosition,
    alertPopupRef,
    activeAlertTriggerRef,
    handleClearOpsAlerts,
    handlePortalAlertAction,
    handleToggleAlertPopup,
  } = usePortalAlerts({
    employeesWithRuntimeStatus,
    navigateToEmployeePage,
    locationPathname: location.pathname,
    locationSearch: location.search,
    suspended: isKnowledgeBaseMode,
  });

  function renderAlertBell() {
    return (
      <PortalAlertBell
        pageTheme={pageTheme}
        alertBellIcon={alertBellIcon}
        sortedOpsAlerts={sortedOpsAlerts}
        alertToast={alertToast}
        alertPopupOpen={alertPopupOpen}
        alertPopupPosition={alertPopupPosition}
        alertPopupRef={alertPopupRef}
        activeAlertTriggerRef={activeAlertTriggerRef}
        employeesWithRuntimeStatus={employeesWithRuntimeStatus}
        alertLevelColors={PORTAL_ALERT_LEVEL_COLORS}
        alertLevelLabels={PORTAL_ALERT_LEVEL_LABELS}
        onClearOpsAlerts={handleClearOpsAlerts}
        onPortalAlertAction={handlePortalAlertAction}
        onToggleAlertPopup={handleToggleAlertPopup}
      />
    );
  }

  const toggleChatSidebarSection = useCallback((section: ChatSidebarSectionKey) => {
    setChatSidebarCollapsedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  }, []);

  useEffect(() => {
    if (
      activeAdvancedPanel === "resource-import" &&
      selectedEmployee?.id !== RESOURCE_IMPORT_OWNER_ID &&
      resourceImportEmployee
    ) {
      navigateToEmployeePage(resourceImportEmployee, {
        entry: null,
        view: "chat",
        panel: "resource-import",
        replace: true,
      });
      return;
    }

    if (!currentEmployeeBase) {
      return;
    }


    if (employeeId && !selectedEmployee) {
      navigate("/", { replace: true });
      return;
    }

    if (routeSearchParams.has("view") || routeSearchParams.has("panel")) {
      updateCurrentEmployeeRoute({
        entry: currentEntry,
        view: currentView,
        panel: activeAdvancedPanel,
        replace: true,
      });
    }
  }, [
    activeAdvancedPanel,
    currentEmployeeBase?.id,
    currentEntry,
    currentView,
    employeeId,
    navigate,
    navigateToEmployeePage,
    resourceImportEmployee,
    routeSearchParams,
    routeSection,
    selectedEmployee,
    updateCurrentEmployeeRoute,
  ]);

  useEffect(() => {
    if (!currentEmployeeBase) {
      return;
    }

    setInputMessage("");
    setExecutionVisible(false);
    resetAlarmWorkbench();

    if (isAlarmWorkbenchMode) {
      resetRemoteState({
        initialMessages: [
          createAlarmWorkorderMessage(currentEmployeeBase, {
            content: "告警已触发，我正在为您查询待处置工单...",
            workorders: [],
            workordersLoading: true,
            workordersError: "",
          }),
        ],
      });
      return;
    }

    if (!isRemoteEmployee) {
      setActivePortalResourceImportSessionId("");
      resetRemoteState();
      const initialMessages = isPortalHome ? [] : createInitialMessages(currentEmployeeBase);
      const nextSession = isPortalHome
        ? null
        : createConversationSession(currentEmployeeBase, initialMessages);

      if (nextSession) {
        setConversationStore((prevStore) => {
          const previousSessions = ensureSessionRecords(prevStore[currentEmployeeBase.id]);
          const nextStore: ConversationStoreState = {
            ...prevStore,
            [currentEmployeeBase.id]: [
              nextSession as SessionRecord,
              ...previousSessions,
            ],
          };
          saveConversationStore(nextStore);
          return nextStore;
        });
      }

      setCurrentSessionId(nextSession?.id || "");
      setMessages(initialMessages);
      setPortalHomeChatMode(false);
      return;
    }

    setActivePortalResourceImportSessionId("");
    resetRemoteState({
      initialMessages: isPortalHome ? [] : createInitialMessages(currentEmployeeBase),
    });
    setPortalHomeChatMode(false);
  }, [
    currentEmployeeBase?.id,
    isPortalHome,
    isAlarmWorkbenchMode,
    isRemoteEmployee,
    resetAlarmWorkbench,
    resetRemoteState,
    setActivePortalResourceImportSessionId,
    setCurrentSessionId,
  ]);

  useEffect(() => {
    latestMessagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    const baseline = pendingReplyFocusBaselineRef.current;
    if (!baseline) {
      return;
    }

    const nextAssistantMessage = messages.find((message) => {
      const messageId = String(message?.id || "");
      return messageId && message?.type !== "user" && !baseline.has(messageId);
    });
    if (!nextAssistantMessage?.id) {
      return;
    }

    pendingReplyFocusBaselineRef.current = null;
    if (pendingReplyFocusExpiryTimerRef.current) {
      window.clearTimeout(pendingReplyFocusExpiryTimerRef.current);
      pendingReplyFocusExpiryTimerRef.current = 0;
    }
    shouldAutoScrollRef.current = false;
    const targetId = String(nextAssistantMessage.id);
    clearReplyFocusAlignmentHandles();

    const alignToReply = () => {
      const targetElement = document.getElementById(`message-${targetId}`);
      const chatContainer = chatMessagesRef.current;
      if (!targetElement || !chatContainer?.contains(targetElement)) {
        return;
      }
      suppressAutoScrollStateUntilRef.current = window.performance.now() + 1100;
      const containerRect = chatContainer.getBoundingClientRect();
      const targetRect = targetElement.getBoundingClientRect();
      const targetTop = chatContainer.scrollTop + targetRect.top - containerRect.top;
      chatContainer.scrollTo({
        top: Math.max(0, targetTop),
        behavior: "auto",
      });
      rememberChatScrollMetrics();
    };

    const firstFrame = window.requestAnimationFrame(() => {
      alignToReply();
      const secondFrame = window.requestAnimationFrame(alignToReply);
      replyFocusAlignmentHandlesRef.current.raf.push(secondFrame);
    });
    const settleTimer = window.setTimeout(alignToReply, 120);
    const lateSettleTimer = window.setTimeout(alignToReply, 360);
    replyFocusAlignmentHandlesRef.current = {
      raf: [firstFrame],
      timers: [settleTimer, lateSettleTimer],
    };
  }, [clearReplyFocusAlignmentHandles, messages, rememberChatScrollMetrics]);

  useEffect(() => (
    () => {
      clearReplyFocusAlignmentHandles();
      if (pendingReplyFocusExpiryTimerRef.current) {
        window.clearTimeout(pendingReplyFocusExpiryTimerRef.current);
      }
    }
  ), [clearReplyFocusAlignmentHandles]);

  useEffect(() => {
    const chatContainer = chatMessagesRef.current;
    if (!chatContainer) {
      return;
    }
    if (!shouldAutoScrollRef.current) {
      return;
    }
    const timerId = window.requestAnimationFrame(() => {
      scrollMessagesToBottom(isStreaming ? "auto" : "smooth");
    });

    return () => {
      window.cancelAnimationFrame(timerId);
    };
  }, [isStreaming, messages, scrollMessagesToBottom]);

  useEffect(() => {
    if (pendingReplyFocusBaselineRef.current) {
      return;
    }
    shouldAutoScrollRef.current = true;
    const timerId = window.requestAnimationFrame(() => {
      scrollMessagesToBottom("auto");
    });
    return () => {
      window.cancelAnimationFrame(timerId);
    };
  }, [currentSessionId, scrollMessagesToBottom]);

  useEffect(() => {
    const chatContainer = chatMessagesRef.current;
    if (!chatContainer || typeof MutationObserver === "undefined") {
      return;
    }

    let rafId = 0;
    const scheduleScroll = () => {
      if (!shouldAutoScrollRef.current) {
        return;
      }
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
      rafId = window.requestAnimationFrame(() => {
        scrollMessagesToBottom(isStreaming ? "auto" : "smooth");
      });
    };

    const observer = new MutationObserver(scheduleScroll);
    observer.observe(chatContainer, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    return () => {
      observer.disconnect();
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, [currentSessionId, isStreaming, scrollMessagesToBottom]);

  const handleChatMessagesScroll = useCallback(() => {
    const element = chatMessagesRef.current;
    if (!element) {
      return;
    }
    if (window.performance.now() < suppressAutoScrollStateUntilRef.current) {
      shouldAutoScrollRef.current = false;
      return;
    }
    const maxScrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
    const distanceToBottom = maxScrollTop - element.scrollTop;
    const isNearBottom = distanceToBottom <= CHAT_SCROLL_BOTTOM_THRESHOLD_PX;
    const isScrollingDown = element.scrollTop > lastChatScrollTopRef.current + 1;
    if (isScrollingDown) {
      clearPendingReplyFocus();
    }
    const reachedPreviousBottom =
      isStreaming &&
      isScrollingDown &&
      lastChatScrollMaxTopRef.current > 0 &&
      element.scrollTop >= lastChatScrollMaxTopRef.current - CHAT_SCROLL_BOTTOM_THRESHOLD_PX;

    shouldAutoScrollRef.current = isNearBottom || reachedPreviousBottom;
    lastChatScrollTopRef.current = element.scrollTop;
    lastChatScrollMaxTopRef.current = maxScrollTop;

    if (reachedPreviousBottom && !isNearBottom) {
      window.requestAnimationFrame(() => {
        scrollMessagesToBottom("auto");
      });
    }
  }, [clearPendingReplyFocus, isStreaming, scrollMessagesToBottom]);

  const handleChatMessagesWheelCapture = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      const element = chatMessagesRef.current;
      if (!element || !event.deltaY || event.shiftKey) {
        return;
      }

      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("textarea,input,select,[contenteditable='true']")) {
        return;
      }

      const maxScrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
      const distanceToBottom = maxScrollTop - element.scrollTop;
      const isNearBottom = distanceToBottom <= CHAT_SCROLL_BOTTOM_THRESHOLD_PX;
      clearPendingReplyFocus();

      if (event.deltaY > 0 && isNearBottom) {
        shouldAutoScrollRef.current = true;
        return;
      }

      shouldAutoScrollRef.current = false;
    },
    [clearPendingReplyFocus],
  );

  useEffect(() => {
    persistPageTheme(pageTheme);
  }, [pageTheme]);

  useEffect(() => {
    persistSidebarCollapsed(sidebarCollapsed);
  }, [sidebarCollapsed]);

  useEffect(() => {
    persistChatSidebarCollapsed(chatSidebarCollapsed);
  }, [chatSidebarCollapsed]);

  useEffect(() => {
    if (isInteractionLocked) {
      return;
    }

    let cancelled = false;
    let loading = false;

    const loadEmployeeStatuses = async () => {
      if (loading) {
        return;
      }

      loading = true;
      try {
        const response = await getPortalEmployeeStatuses({
          includeAlertCount: !isKnowledgeBaseMode,
        });
        if (cancelled) {
          return;
        }
        const nextStatusMap = Object.fromEntries(
          (response.employees || []).map((status) => [status.employeeId, status]),
        );
        setEmployeeRuntimeStatusMap((previousMap) =>
          areEmployeeRuntimeStatusMapsEqual(previousMap, nextStatusMap)
            ? previousMap
            : nextStatusMap,
        );
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load portal employee statuses:", error);
        }
      } finally {
        loading = false;
      }
    };

    void loadEmployeeStatuses();
    const timerId = window.setInterval(() => {
      void loadEmployeeStatuses();
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timerId);
    };
  }, [isInteractionLocked, isKnowledgeBaseMode]);

  const safeMessages = useMemo(
    () => ensureObjectArray<any>(messages),
    [messages],
  );
  const safeExecutionList = ensureObjectArray<ExecutionRecord>(executionList);
  const safeCapabilities = ensureStringArray(currentEmployee?.capabilities);
  const safeQuickCommands = ensureStringArray(currentEmployee?.quickCommands);
  const showModelSelector = currentView === "chat";
  const isGatewayPresentedChildView = Boolean(
    selectedEmployee?.id
    && locationState?.gatewayPresentationEmployeeId === selectedEmployee.id,
  );
  const effectiveMcpEmployee = isMcpMode ? (selectedEmployee || currentSidebarEmployee) : selectedEmployee;
  const effectiveMcpAgentId = effectiveMcpEmployee
    ? (REMOTE_AGENT_IDS[effectiveMcpEmployee.id] || "default")
    : "default";
  const scopedRemoteSessions = currentEmployee?.id === RESOURCE_IMPORT_OWNER_ID
    ? mergeSessionRecords(remoteSessions, portalResourceImportSessions)
    : currentEmployee?.id === KNOWLEDGE_BASE_OWNER_ID
      ? mergeSessionRecords(remoteSessions, portalKnowledgeBaseSessions)
    : remoteSessions;
  const sessionList = (
    isRemoteEmployee
      ? scopedRemoteSessions
      : ensureSessionRecords(conversationStore[currentEmployee?.id || ""])
  ) as SessionRecord[];
  const isKnowledgeBaseEmployee = currentEmployee?.id === KNOWLEDGE_BASE_OWNER_ID;

  const {
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
  } = usePortalSessionHistory({
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
    locationPathname: location.pathname,
    locationSearch: location.search,
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
  });

  const handlePortalLogoClick = useCallback(() => {
    if (isPortalHomeChat) {
      handleStartNewConversation();
      return;
    }

    navigateToPortalHome({
      entry: null,
      view: "chat",
      panel: null,
    });
  }, [handleStartNewConversation, isPortalHomeChat, navigateToPortalHome]);

  useEffect(() => {
    const openHistoryForEmployeeId = locationState?.openHistoryForEmployeeId;
    if (!openHistoryForEmployeeId || !currentEmployee) {
      return;
    }

    if (openHistoryForEmployeeId !== currentEmployee.id) {
      return;
    }

    navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: {},
    });
    void handleOpenHistory();
  }, [
    currentEmployee,
    handleOpenHistory,
    location.pathname,
    location.search,
    locationState,
    navigate,
  ]);

  const handleOpenExecutionHistory = (type: "executions" | "running" | "success") => {
    if (type === "executions") {
      setExecutionTitle("执行历史 - 全部任务");
      setExecutionList(executionHistory);
    } else if (type === "running") {
      setExecutionTitle("执行历史 - 进行中");
      setExecutionList(
        executionHistory.filter((item) => item.status === "running"),
      );
    } else {
      setExecutionTitle("执行历史 - 成功率");
      setExecutionList(
        executionHistory.filter((item) => item.status === "success"),
      );
    }
    setExecutionVisible(true);
  };

  const handleOpenTaskEmployeeChat = (employeeId: string, session?: SessionRecord | null) => {
    const employee = getEmployeeById(employeeId);
    if (!employee) {
      return;
    }
    navigateToEmployeePage(employee, {
      view: "chat",
      panel: null,
      state: session
        ? {
            openSession: {
              employeeId,
              sessionId: session.id,
            },
          }
        : undefined,
    });
  };

  const {
    kanbanMode,
    setKanbanMode,
    kanbanFilter,
    setKanbanFilter,
    dashboardClock,
    dashboardHistoryVisible,
    setDashboardHistoryVisible,
    dashboardHistoryEmployeeId,
    dashboardHistoryEmployee,
    dashboardHistorySessions,
    dashboardHistoryLoading,
    dashboardHistoryError,
    dashboardLatestSessions,
    kanbanFilterLabels,
    filteredDashboardWorkColumns,
    filteredDashboardEmployeeSnapshots,
    handleOpenDashboardEmployeeHistory,
    handleSelectDashboardHistory,
  } = usePortalDashboard({
    employeesWithRuntimeStatus,
    employeeRuntimeStatusMap,
    conversationStore,
    currentView,
    currentChatId,
    remoteSessionsLength: remoteSessions.length,
    onOpenTaskEmployeeChat: handleOpenTaskEmployeeChat,
  });

  if (!currentEmployee) {
    return null;
  }

  const currentEmployeeModelLabel = activeModelLabel || "默认模型";
  const visibleEmployee = isGatewayPresentedChildView ? portalHomeEmployee : currentEmployee;
  const visibleEmployeeStatusLabel = getEmployeeStatusLabel(visibleEmployee);
  const visibleEmployeeStatsLabel = formatEmployeeStatsLabel(
    isGatewayPresentedChildView ? portalHomeEmployee : currentEmployeeBase,
  );
  const visibleEmployeeMotto = getEmployeeProfileMotto(visibleEmployee.id, visibleEmployee.desc);
  const visibleEmployeeActivities = isGatewayPresentedChildView
    ? getChatSidebarActivities(PORTAL_HOME_ID)
    : currentEmployeeActivities;
  const visibleEmployeeWorkload = isGatewayPresentedChildView
    ? [44, 63, 58, 81, 76, 54, 67]
    : chatSidebarWorkload;
  const visibleEmployeeEfficiency = isGatewayPresentedChildView
    ? { completed: 17, total: 18, response: "1.0s", collaboration: 12 }
    : chatSidebarEfficiency;
  const visibleEmployeeCollaborators = isGatewayPresentedChildView
    ? employeesWithRuntimeStatus
      .filter((employee) => employee.id !== selectedEmployee?.id)
      .slice(0, 3)
      .map((employee) => ({
        ...employee,
        collaborationCount: ({
          query: 14,
          fault: 8,
          knowledge: 11,
          inspection: 6,
          order: 9,
        } as Record<string, number>)[employee.id] || 6,
      }))
    : chatSidebarCollaborators;
  const showChatSidebarToggle = Boolean(!isPortalHomeChat && selectedEmployee);
  const sidebarToggleButton = (
    <button
      type="button"
      className="sidebar-collapse-btn"
      onClick={() => setSidebarCollapsed((value) => !value)}
      title={sidebarCollapsed ? "展开左侧面板" : "收起左侧面板"}
      aria-label={sidebarCollapsed ? "展开左侧面板" : "收起左侧面板"}
    >
      <i className={sidebarCollapsed ? "fas fa-chevron-right" : "fas fa-chevron-left"} />
    </button>
  );
  const chatSidebarToggleButton = showChatSidebarToggle ? (
    <button
      type="button"
      className="history-btn chat-sidebar-header-toggle"
      onClick={() => setChatSidebarCollapsed((value) => !value)}
      title={chatSidebarCollapsed ? "展开右侧信息栏" : "收起右侧信息栏"}
      aria-label={chatSidebarCollapsed ? "展开右侧信息栏" : "收起右侧信息栏"}
    >
      <i className={chatSidebarCollapsed ? "fas fa-chevron-left" : "fas fa-chevron-right"} />
    </button>
  ) : null;
  const chatHeaderStatusLabel = !isRemoteEmployee && isAlarmWorkbenchMode ? "告警触发" : null;
  const chatHeaderActions = (
    <>
      {showModelSelector ? (
        <ChatModelSelector
          activeModelLabel={activeModelLabel}
          activeProviderId={activeProviderId}
          activeModelId={activeModelId}
          eligibleProviders={eligibleProviders}
          loading={modelsLoading}
          switching={modelsSwitching}
          disabled={isInteractionLocked}
          notice={modelNotice}
          onSelectModel={handleSelectModel}
          onOpenConfig={openModelConfig}
        />
      ) : null}
      <>
        <button className="history-btn" onClick={() => void handleOpenHistory()}>
          <i className="fas fa-history" /> 已处理任务
        </button>
        <button className="history-btn new-chat-btn" onClick={handleStartNewConversation}>
          <i className="fas fa-plus" /> 新对话
        </button>
      </>
      {chatSidebarToggleButton}
    </>
  );

  return (
    <DigitalEmployeePageErrorBoundary>
      <div
        className={
          pageTheme === "dark" ? "portal-digital-employee theme-dark" : "portal-digital-employee"
        }
      >
      <div className="bg-effects">
        <div className="bg-gradient" />
        <div className="grid-bg" />
      </div>

      <div className="app-container">
        <div className={sidebarCollapsed ? "sidebar sidebar-collapsed" : "sidebar"}>
          {sidebarToggleButton}
          <button
            type="button"
            className={isPortalHomeChat ? "logo active" : "logo"}
            onClick={handlePortalLogoClick}
          >
            <div className="logo-icon">
              <img src={portalLogo} alt={portalAppTitle} className="logo-icon-image" />
            </div>
            <div className="logo-text">
              <h1>{portalAppTitle}</h1>
              <span>智能 · 高效 · 自动化</span>
            </div>
          </button>

          <div className="view-tabs">
            <button
              className={currentView === "overview" ? "view-tab active" : "view-tab"}
              onClick={() => {
                updateCurrentEmployeeRoute({
                  view: "overview",
                  panel: null,
                });
              }}
            >
              <i className="fas fa-chart-line" />
              <span>总览</span>
            </button>
            <button
              className={currentView === "dashboard" ? "view-tab active" : "view-tab"}
              onClick={() => {
                updateCurrentEmployeeRoute({
                  view: "dashboard",
                  panel: null,
                });
              }}
            >
              <i className="fas fa-chart-pie" />
              <span>看板</span>
            </button>
          </div>

          <div className="agents-title">
            <span className="agents-title-copy">
              <i className="fas fa-comments" />
              统一入口
            </span>
          </div>

          <div className="agent-list">
            {sidebarCardEmployee ? (
              <SidebarEmployeeCard
                employee={sidebarCardEmployee}
                active
                onClick={() => {
                  navigateToPortalHome({
                    view: "chat",
                    panel: null,
                  });
                }}
                getEmployeeStatusBadgeClassName={getEmployeeStatusBadgeClassName}
                getEmployeeStatusLabel={getEmployeeStatusLabel}
              />
            ) : null}
          </div>

          <AdvancedModelEntry
            activeModelLabel={activeModelLabel}
            activeProviderName={activeProviderName}
            isActive={isModelConfigMode}
            isSettingsActive={isSettingsMode}
            isCronJobsActive={currentView === "tasks"}
            isTokenUsageActive={isTokenUsageMode}
            isOpsExpertActive={isOpsExpertMode}
            isMcpActive={isMcpMode}
            isSkillPoolActive={isSkillPoolMode}
            isFdeWorkbenchActive={isFdeWorkbenchMode}
            isKnowledgeBaseActive={isKnowledgeBaseMode}
            isInspirationActive={isInspirationMode}
            isCliActive={isCliMode}
            isNlCustomizationActive={isNlCustomizationMode}
            isAppMarketActive={isAppMarketMode}
            isTracesActive={isTracesMode}
            isAlarmRegistryActive={isAlarmRegistryMode}
            isAppArtifactsActive={isAppArtifactsMode}
            isChannelsActive={isChannelsMode}
            isInboxActive={isInboxMode}
            onOpenTraces={() =>
              updateCurrentEmployeeRoute({
                panel: "traces",
              })
            }
            onOpenAlarmRegistry={() =>
              updateCurrentEmployeeRoute({
                panel: "alarm-registry",
              })
            }
            onOpenAppArtifacts={() =>
              updateCurrentEmployeeRoute({
                panel: "app-artifacts",
              })
            }
            onOpenChannels={() =>
              updateCurrentEmployeeRoute({
                panel: "channels",
              })
            }
            onOpenInbox={() =>
              updateCurrentEmployeeRoute({
                panel: "inbox",
              })
            }
            onOpenAppMarket={() =>
              updateCurrentEmployeeRoute({
                panel: "app-market",
              })
            }
            onOpenNlCustomization={() =>
              updateCurrentEmployeeRoute({
                panel: "nl-customization",
              })
            }
            onOpenConfig={openModelConfig}
            onOpenSettings={() =>
              updateCurrentEmployeeRoute({
                panel: "settings",
              })
            }
            onOpenCronJobs={() =>
              updateCurrentEmployeeRoute({
                view: "tasks",
                panel: null,
              })
            }
            onOpenTokenUsage={() =>
              updateCurrentEmployeeRoute({
                panel: "token-usage",
              })
            }
            onOpenOpsExpert={() =>
              updateCurrentEmployeeRoute({
                panel: "ops-expert",
              })
            }
            onOpenMcp={() =>
              updateCurrentEmployeeRoute({
                panel: "mcp",
              })
            }
            onOpenSkillPool={openSkillPool}
            onOpenFdeWorkbench={openFdeWorkbench}
            onOpenKnowledgeBase={openKnowledgeBase}
            onOpenInspiration={openInspiration}
            onOpenCli={openCli}
          />
        </div>

        <div
          className={
            isModelConfigMode || isSettingsMode || isTokenUsageMode || isOpsExpertMode || isMcpMode || isSkillPoolMode || isFdeWorkbenchMode || isKnowledgeBaseMode || isInspirationMode || isCliMode || isResourceImportMode || isNlCustomizationMode || isAppMarketMode || isTracesMode || isAlarmRegistryMode || isAppArtifactsMode || isAppWorkbenchMode || isDashboardAssemblyMode || isChannelsMode || isInboxMode
              ? `main-content advanced-page-mode${isKnowledgeBaseMode ? " knowledge-base-page-mode" : ""}`
              : currentView === "chat"
                ? "main-content"
                : currentView === "tasks"
                  ? "main-content card-mode task-page-mode"
                  : "main-content card-mode"
          }
        >
          {!showPortalHomeHero && currentView !== "dashboard" ? (
            <div className="portal-global-quick-actions">
              {renderAlertBell()}
              <button
                type="button"
                className="ops-board-theme-toggle"
                onClick={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
                aria-label="切换整页主题"
                title="切换整页主题"
              >
                {themeToggleIcon}
              </button>
              <PortalTraditionalViewButton />
            </div>
          ) : null}
          {isModelConfigMode ? (
              <ModelConfigModal
                open
                activeProviderId={activeProviderId}
                activeProviderName={activeProviderName}
                activeModelLabel={activeModelLabel}
                globalActiveProviderId={globalActiveProviderId}
                globalActiveProviderName={globalActiveProviderName}
                globalActiveModelId={globalActiveModelId}
                globalActiveModelLabel={globalActiveModelLabel}
                usesGlobalDefault={usesGlobalDefault}
                eligibleProviders={eligibleProviders}
                displayProviders={displayProviders}
                loading={modelsLoading}
                switching={modelsSwitching}
                submitting={modelsSubmitting}
                disabled={isInteractionLocked}
                notice={modelNotice}
                onRefresh={() => void fetchModelState()}
                onSelectDefaultModel={handleSelectDefaultModel}
                onSubmitProvider={handleSaveProvider}
                onSubmitModel={handleAddModel}
                onDeleteProvider={handleDeleteProvider}
                onRevokeProviderAuth={handleRevokeProviderAuth}
                onApplyBuiltinApiKey={handleApplyBuiltinApiKey}
                onRemoveModel={handleRemoveModel}
                onConfigureModel={handleConfigureModel}
                onTestProvider={handleTestProvider}
                onTestModel={handleTestModel}
                onProbeMultimodal={handleProbeMultimodal}
                onDiscoverModels={handleDiscoverModels}
              />
          ) : isSettingsMode ? (
            renderDeferredPanel(<SettingsPanel />)
          ) : isTokenUsageMode ? (
            renderDeferredPanel(
              <TokenUsagePanel
                pageTheme={pageTheme}
                currentEmployeeName={selectedEmployee ? currentEmployee.name : "全局"}
              />,
            )
          ) : isOpsExpertMode ? (
            renderDeferredPanel(<OpsExpertPanel />)
          ) : isMcpMode ? (
            renderDeferredPanel(<McpPanel />)
          ) : isSkillPoolMode ? (
            renderDeferredPanel(<SkillPoolPanel />)
          ) : isFdeWorkbenchMode ? (
            renderDeferredPanel(<FdeWorkbenchPanel />)
          ) : isKnowledgeBaseMode ? (
            renderDeferredPanel(
              <KnowledgeBasePanel />,
            )
          ) : isInspirationMode ? (
            renderDeferredPanel(
              <InspirationPanel
                onOpenEmployeeChat={openEmployeeChat}
                onOpenKnowledgeBase={searchKnowledgeBaseConversation}
                onOpenView={(view) =>
                  updateCurrentEmployeeRoute({
                    view,
                    panel: null,
                  })
                }
                onOpenPanel={(panel) =>
                  updateCurrentEmployeeRoute({
                    panel,
                  })
                }
              />,
            )
          ) : isCliMode ? (
            renderDeferredPanel(
              <CliTerminalPanel
                employees={sidebarEmployees}
                activeEmployeeId={selectedEmployee?.id || currentSidebarEmployee?.id || null}
                onOpenEmployeeChat={openEmployeeChat}
              />,
            )
          ) : isNlCustomizationMode ? (
            renderDeferredPanel(<NaturalLanguageCustomizationPanel />)
          ) : isAppMarketMode ? (
            renderDeferredPanel(<AppMarketPanel />)
          ) : isTracesMode ? (
            renderDeferredPanel(<TracesCenterPanel />)
          ) : isAlarmRegistryMode ? (
            renderDeferredPanel(<AlarmRegistryPanel pageTheme={pageTheme} onOpenChat={(chatId) => {
              const employee = getEmployeeById("fault");
              if (employee) {
                navigateToEmployeePage(employee, {
                  view: "chat",
                  panel: null,
                  state: { openSession: { employeeId: "fault", sessionId: chatId } },
                });
              }
            }} />)
          ) : isAppArtifactsMode ? (
            renderDeferredPanel(<AppArtifactsPanel
              onOpenWorkbench={() => navigate("/app-workbench")}
              onEditApp={(appId) => navigate(`/app-workbench?edit=${appId}`)}
              onOpenDashboardAssembly={() => navigate("/dashboard-assembly")}
              onEditDashboard={(id) => navigate(`/dashboard-assembly?edit=${id}`)}
            />)
          ) : isAppWorkbenchMode ? (
            renderDeferredPanel(<AppWorkbenchPanel
              onBack={() => navigate("/app-artifacts")}
              editAppId={routeSearchParams.get("edit") || undefined}
            />)
          ) : isDashboardAssemblyMode ? (
            renderDeferredPanel(<DashboardAssemblyPanel
              onBack={() => navigate("/app-artifacts")}
              editDashboardId={routeSearchParams.get("edit") || undefined}
            />)
          ) : isChannelsMode ? (
            renderDeferredPanel(<ChannelsPanel />)
          ) : isInboxMode ? (
            renderDeferredPanel(<InboxPanel />)
          ) : isResourceImportMode ? (
            renderDeferredPanel(<ResourceImportPanel />)
          ) : (
            <>
          {!showPortalHomeHero ? (
            <div className="top-bar">
              <div className="active-agent-title">
                <div className="active-agent-avatar">
                  <i
                    className={`fas ${
                      currentView === "overview"
                        ? "fa-chart-line"
                        : currentView === "dashboard"
                        ? "fa-chart-pie"
                        : currentView === "tasks"
                          ? "fa-clock"
                          : visibleEmployee.icon
                    }`}
                  />
                </div>
                <div className="active-agent-info">
                  <h2>
                    {currentView === "overview"
                      ? "数字总览"
                      : currentView === "dashboard"
                      ? "数字员工看板"
                      : currentView === "tasks"
                        ? "定时任务"
                        : visibleEmployee.name}
                  </h2>
                  <span>
                    {currentView === "overview"
                      ? "查看整体态势、告警与业务健康"
                      : currentView === "dashboard"
                        ? "查看实时任务概览和泳道看板"
                        : currentView === "tasks"
                        ? "查看和管理定时任务"
                        : isAlarmWorkbenchMode
                          ? "告警触发后自动生成的待处置工单视图"
                          : visibleEmployee.desc}
                  </span>
                </div>
              </div>
              <div className="top-bar-actions" />
            </div>
          ) : null}

          {currentView === "overview" ? (
            renderDeferredPanel(
              <OverviewPanel
                pageTheme={pageTheme}
                onOpenEmployeeChat={handleOpenTaskEmployeeChat}
                employees={employeesWithRuntimeStatus}
              />,
            )
          ) : null}

          {currentView === "dashboard" ? (
            <DashboardPanel
              kanbanMode={kanbanMode}
              kanbanFilter={kanbanFilter}
              kanbanFilterLabels={kanbanFilterLabels}
              dashboardClock={dashboardClock}
              alertBell={renderAlertBell()}
              themeToggleIcon={themeToggleIcon}
              filteredDashboardEmployeeSnapshots={filteredDashboardEmployeeSnapshots}
              filteredDashboardWorkColumns={filteredDashboardWorkColumns}
              dashboardLatestSessions={dashboardLatestSessions}
              onSetKanbanMode={setKanbanMode}
              onSetKanbanFilter={setKanbanFilter}
              onToggleTheme={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
              onOpenDashboardEmployeeHistory={handleOpenDashboardEmployeeHistory}
              onOpenTaskEmployeeChat={handleOpenTaskEmployeeChat}
            />
          ) : null}

          {currentView === "tasks" ? (
            renderDeferredPanel(<CronJobsPanel />)
          ) : null}

          {currentView === "chat" ? (
            <div
              className={
                showPortalHomeHero
                  ? "chat-container portal-home-chat"
                  : selectedEmployee
                    ? "chat-container show-cards"
                    : "chat-container"
              }
            >
              {showPortalHomeHero ? (
                <PortalHomeHero
                  alertBell={renderAlertBell()}
                  themeToggleIcon={themeToggleIcon}
                  portalLogo={portalLogo}
                  inputMessage={inputMessage}
                  isInteractionLocked={isInteractionLocked}
                  mentionSuggestions={mentionSuggestions}
                  mentionActiveIndex={mentionActiveIndex}
                  safeQuickCommands={safeQuickCommands}
                  resourceImportCommand={RESOURCE_IMPORT_COMMAND}
                  isConversationRunning={isConversationRunning}
                  isCreatingChat={isCreatingChat}
                  homeComposerRef={homeComposerRef}
                  onToggleTheme={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
                  onComposerBlur={handleComposerBlur}
                  onInputSelection={handleInputSelection}
                  onComposerChange={handleHomeComposerChange}
                  onComposerKeyDown={handleHomeComposerKeyDown}
                  onApplyMentionSuggestion={applyMentionSuggestion}
                  onOpenResourceImport={() => openResourceImport()}
                  onOpenHistory={() => void handleOpenHistory()}
                  onSendPreset={handleQuickCommand}
                  onPrimaryAction={() => {
                    if (isKnowledgeBaseRunning) {
                      stopKnowledgeBaseTask();
                      return;
                    }
                    if (isRemoteConversationRunning) {
                      stopActiveStream(true);
                      return;
                    }
                    void handleSendMessage();
                  }}
                />
              ) : (
                <>
                  <EmployeeChatMainPanel
                    visibleEmployee={visibleEmployee}
                    isAlarmWorkbenchMode={isAlarmWorkbenchMode}
                    headerStatusLabel={chatHeaderStatusLabel}
                    chatHeaderActions={chatHeaderActions}
                    chatMessagesRef={chatMessagesRef}
                    messagesEndRef={messagesEndRef}
                    safeMessages={safeMessages}
                    remoteAgentId={remoteAgentId}
                    currentEmployeeBase={currentEmployeeBase}
                    isStreaming={isStreaming}
                    activeAssistantMessageId={activeAssistantMessageIdRef.current}
                    onChatMessagesScroll={handleChatMessagesScroll}
                    onChatMessagesWheelCapture={handleChatMessagesWheelCapture}
                    onDisposalAction={handleAlarmDisposalOperationRequest}
                    onResourceImportBackToConfirm={handleResourceImportBackToConfirm}
                    onResourceImportBuildTopology={handleResourceImportBuildTopology}
                    onResourceImportConfirmStructure={handleResourceImportConfirmStructure}
                    onResourceImportContinue={handleResourceImportContinue}
                    onResourceImportOpenSystemTopology={handleResourceImportOpenSystemTopology}
                    onResourceImportParseFailed={handleResourceImportParseFailed}
                    onResourceImportParseResolved={handleResourceImportParseResolved}
                    onResourceImportReturnToUpload={handleResourceImportReturnToUpload}
                    onResourceImportStartParse={handleResourceImportStartParse}
                    onResourceImportScrollToStage={handleResourceImportScrollToStage}
                    onResourceImportSubmitImport={handleResourceImportSubmitImport}
                    onResourceImportUploadFiles={handleResourceImportUploadFiles}
                    onKnowledgeBaseFlowUpdate={updateKnowledgeBaseFlowMessage}
                    onKnowledgeBaseUploadRequest={() => openKnowledgeBaseConversation("上传知识文档")}
                    onKnowledgeBaseManagementOpen={openKnowledgeBase}
                    releaseResourceImportFiles={releaseResourceImportFiles}
                    resolveResourceImportFiles={resolveResourceImportFiles}
                    pageTheme={pageTheme}
                    onTicketAction={handleAlarmWorkbenchTicketAction}
                    onTicketRefresh={() => void loadAlarmWorkorders()}
                    ticketActionNotice={ticketActionNotice}
                    activeModelLabel={activeModelLabel}
                    safeCapabilities={safeCapabilities}
                    safeQuickCommands={safeQuickCommands}
                    resourceImportCommand={RESOURCE_IMPORT_COMMAND}
                    isInteractionLocked={isInteractionLocked}
                    openResourceImport={() => openResourceImport()}
                    onSendPreset={handleQuickCommand}
                    inputMessage={inputMessage}
                    chatInputRef={chatInputRef}
                    onComposerBlur={handleComposerBlur}
                    onInputSelection={handleInputSelection}
                    onComposerChange={handleChatComposerChange}
                    onComposerKeyDown={handleChatComposerKeyDown}
                    mentionSuggestions={mentionSuggestions}
                    mentionActiveIndex={mentionActiveIndex}
                    onApplyMentionSuggestion={applyMentionSuggestion}
                    isConversationRunning={isConversationRunning}
                    isCreatingChat={isCreatingChat}
                    onPrimaryAction={() => {
                      if (isKnowledgeBaseRunning) {
                        stopKnowledgeBaseTask();
                        return;
                      }
                      if (isRemoteConversationRunning) {
                        stopActiveStream(true);
                        return;
                      }
                      void handleSendMessage();
                    }}
                  />

                  <EmployeeChatSidebar
                    showSidebar={Boolean(!isPortalHomeChat && selectedEmployee)}
                    chatSidebarCollapsed={chatSidebarCollapsed}
                    chatSidebarCollapsedSections={chatSidebarCollapsedSections}
                    visibleEmployee={visibleEmployee}
                    visibleEmployeeMotto={visibleEmployeeMotto}
                    visibleEmployeeStatusLabel={visibleEmployeeStatusLabel}
                    currentEmployeeModelLabel={currentEmployeeModelLabel}
                    visibleEmployeeStatsLabel={visibleEmployeeStatsLabel}
                    visibleEmployeeActivities={visibleEmployeeActivities}
                    visibleEmployeeEfficiency={visibleEmployeeEfficiency}
                    visibleEmployeeWorkload={visibleEmployeeWorkload}
                    visibleEmployeeCollaborators={visibleEmployeeCollaborators}
                    onToggleSection={toggleChatSidebarSection}
                    onOpenEmployeeChat={openEmployeeChat}
                  />
                </>
              )}
            </div>
          ) : null}
            </>
          )}
        </div>
      </div>

      <DashboardHistoryModal
        open={dashboardHistoryVisible}
        employeeName={dashboardHistoryEmployee?.name || ""}
        loading={dashboardHistoryLoading}
        error={dashboardHistoryError}
        sessions={dashboardHistorySessions}
        onClose={() => setDashboardHistoryVisible(false)}
        onSelect={(session) => handleSelectDashboardHistory(dashboardHistoryEmployeeId, session)}
      />

      <SessionHistoryModal
        open={historyVisible}
        actionError={historyActionError}
        loading={isKnowledgeBaseEmployee ? false : historyLoading}
        error={isKnowledgeBaseEmployee ? "" : historyError}
        sessions={sessionList}
        historyDraftTitle={historyDraftTitle}
        historyEditingId={historyEditingId}
        historyActionSessionId={historyActionSessionId}
        activePortalResourceImportSessionId={activePortalResourceImportSessionId}
        activePortalKnowledgeBaseSessionId={activePortalKnowledgeBaseSessionId}
        isRemoteEmployee={isRemoteEmployee}
        currentChatId={currentChatId}
        currentSessionId={currentSessionId}
        isConversationRunning={isConversationRunning}
        isPortalResourceImportSession={isPortalResourceImportSession}
        isPortalKnowledgeBaseSession={isPortalKnowledgeBaseSession}
        onClose={() => setHistoryVisible(false)}
        onSelectHistory={(session) => {
          void handleSelectHistory(session);
        }}
        onDraftTitleChange={setHistoryDraftTitle}
        onSubmitHistoryRename={(session) => {
          void handleSubmitHistoryRename(session);
        }}
        onCancelHistoryRename={handleCancelHistoryRename}
        onStartHistoryRename={handleStartHistoryRename}
        onDeleteHistorySession={(session) => {
          void handleDeleteHistorySession(session);
        }}
      />

      <ExecutionHistoryModal
        open={executionVisible}
        title={executionTitle}
        items={safeExecutionList}
        onClose={() => setExecutionVisible(false)}
      />

      <DisposalConfirmModal
        action={pendingDisposalAction}
        submitting={isSubmittingDisposalAction}
        onCancel={handleCancelDisposalAction}
        onConfirm={() => {
          void handleConfirmDisposalAction();
        }}
      />
      </div>
    </DigitalEmployeePageErrorBoundary>
  );
}
