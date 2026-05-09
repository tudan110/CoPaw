import { useCallback, useEffect, useMemo, useState } from "react";
import { getEmployeeById } from "../../data/portalData";
import { listChats } from "../../api/copawChat";
import { normalizeRemoteSessions } from "./helpers";
import {
  buildDashboardEmployeeSnapshots,
  buildDashboardWorkColumns,
  DASHBOARD_CHAT_CHANNEL,
  ensureSessionRecords,
  formatDashboardClock,
  getDashboardFilterLabels,
  REMOTE_AGENT_IDS,
} from "./pageHelpers";
import type {
  ConversationStoreState,
  DashboardEmployeeSnapshot,
  DashboardKanbanFilter,
  DashboardKanbanMode,
  DashboardWorkColumn,
  SessionRecord,
} from "./pageHelpers";

const DASHBOARD_USER_ID = "default";

export function usePortalDashboard({
  employeesWithRuntimeStatus,
  employeeRuntimeStatusMap,
  conversationStore,
  currentView,
  currentChatId,
  remoteSessionsLength,
  onOpenTaskEmployeeChat,
}: {
  employeesWithRuntimeStatus: any[];
  employeeRuntimeStatusMap: Record<string, any>;
  conversationStore: ConversationStoreState;
  currentView: string;
  currentChatId: string;
  remoteSessionsLength: number;
  onOpenTaskEmployeeChat: (employeeId: string, session?: SessionRecord | null) => void;
}) {
  const [kanbanMode, setKanbanMode] = useState<DashboardKanbanMode>("employee");
  const [kanbanFilter, setKanbanFilter] = useState<DashboardKanbanFilter>("all");
  const [dashboardRemoteHistoryCounts, setDashboardRemoteHistoryCounts] = useState<Record<string, number>>({});
  const [dashboardRemoteSessionsMap, setDashboardRemoteSessionsMap] = useState<Record<string, SessionRecord[]>>({});
  const [dashboardClock, setDashboardClock] = useState(() => formatDashboardClock(new Date()));
  const [dashboardHistoryVisible, setDashboardHistoryVisible] = useState(false);
  const [dashboardHistoryEmployeeId, setDashboardHistoryEmployeeId] = useState("");
  const [dashboardHistorySessions, setDashboardHistorySessions] = useState<SessionRecord[]>([]);
  const [dashboardHistoryLoading, setDashboardHistoryLoading] = useState(false);
  const [dashboardHistoryError, setDashboardHistoryError] = useState("");

  useEffect(() => {
    const timerId = window.setInterval(() => {
      setDashboardClock(formatDashboardClock(new Date()));
    }, 1000);

    return () => {
      window.clearInterval(timerId);
    };
  }, []);

  useEffect(() => {
    setKanbanFilter("all");
  }, [kanbanMode]);

  const localHistoryCounts = useMemo(
    () =>
      Object.fromEntries(
        employeesWithRuntimeStatus.map((employee) => [
          employee.id,
          ensureSessionRecords(conversationStore[employee.id]).length,
        ]),
      ) as Record<string, number>,
    [conversationStore, employeesWithRuntimeStatus],
  );

  useEffect(() => {
    if (currentView !== "dashboard") {
      return;
    }

    const remoteEntries = Object.entries(REMOTE_AGENT_IDS);
    if (!remoteEntries.length) {
      setDashboardRemoteHistoryCounts({});
      setDashboardRemoteSessionsMap({});
      return;
    }

    let cancelled = false;

    void Promise.all(
      remoteEntries.map(async ([employeeId, agentId]) => {
        try {
          const chats = await listChats(agentId, {
            user_id: DASHBOARD_USER_ID,
            channel: DASHBOARD_CHAT_CHANNEL,
          });
          const chatList = Array.isArray(chats) ? chats : [];
          const normalizedSessions = normalizeRemoteSessions(chatList, employeeId);
          return [
            employeeId,
            {
              count: normalizedSessions.length,
              sessions: normalizedSessions,
            },
          ] as const;
        } catch {
          return [
            employeeId,
            {
              count: localHistoryCounts[employeeId] || 0,
              sessions: null,
            },
          ] as const;
        }
      }),
    ).then((entries) => {
      if (cancelled) {
        return;
      }
      setDashboardRemoteHistoryCounts((prev) => ({
        ...prev,
        ...Object.fromEntries(entries.map(([employeeId, data]) => [employeeId, data.count])),
      }));
      const resolvedEntries = entries
        .filter((entry) => Array.isArray(entry[1].sessions))
        .map(([employeeId, data]) => [employeeId, data.sessions as SessionRecord[]]);
      setDashboardRemoteSessionsMap((prev) => ({
        ...prev,
        ...Object.fromEntries(resolvedEntries),
      }));
    });

    return () => {
      cancelled = true;
    };
  }, [currentChatId, currentView, localHistoryCounts, remoteSessionsLength]);

  const dashboardHistoryCounts = useMemo(
    () =>
      Object.fromEntries(
        employeesWithRuntimeStatus.map((employee) => [
          employee.id,
          REMOTE_AGENT_IDS[employee.id]
            ? (dashboardRemoteHistoryCounts[employee.id] ?? localHistoryCounts[employee.id] ?? 0)
            : (localHistoryCounts[employee.id] ?? 0),
        ]),
      ) as Record<string, number>,
    [dashboardRemoteHistoryCounts, employeesWithRuntimeStatus, localHistoryCounts],
  );

  const dashboardLatestSessions = useMemo(
    () =>
      Object.fromEntries(
        employeesWithRuntimeStatus.map((employee) => [
          employee.id,
          REMOTE_AGENT_IDS[employee.id]
            ? (dashboardRemoteSessionsMap[employee.id]?.[0] ?? null)
            : (ensureSessionRecords(conversationStore[employee.id])[0] ?? null),
        ]),
      ) as Record<string, SessionRecord | null>,
    [conversationStore, dashboardRemoteSessionsMap, employeesWithRuntimeStatus],
  );

  const dashboardHistoryEmployee = useMemo(
    () => (dashboardHistoryEmployeeId ? getEmployeeById(dashboardHistoryEmployeeId) : null),
    [dashboardHistoryEmployeeId],
  );

  const dashboardWorkColumns = useMemo(() => buildDashboardWorkColumns(), []);
  const dashboardEmployeeSnapshots = useMemo(
    () =>
      buildDashboardEmployeeSnapshots(
        dashboardHistoryCounts,
        employeesWithRuntimeStatus,
        employeeRuntimeStatusMap,
      ),
    [dashboardHistoryCounts, employeeRuntimeStatusMap, employeesWithRuntimeStatus],
  );

  const kanbanFilterLabels = useMemo(
    () => getDashboardFilterLabels(kanbanMode),
    [kanbanMode],
  );

  const filteredDashboardWorkColumns = useMemo(() => {
    if (kanbanFilter === "all") {
      return dashboardWorkColumns;
    }
    if (kanbanFilter === "idle") {
      return dashboardWorkColumns;
    }

    return dashboardWorkColumns
      .map((column) => ({
        ...column,
        cards: column.cards.filter((card) =>
          kanbanFilter === "urgent" ? card.isUrgent : card.isRunning,
        ),
      }))
      .filter((column) => column.cards.length);
  }, [dashboardWorkColumns, kanbanFilter]);

  const filteredDashboardEmployeeSnapshots = useMemo(() => {
    if (kanbanFilter === "urgent") {
      return dashboardEmployeeSnapshots.filter((worker) => worker.urgent);
    }
    if (kanbanFilter === "running") {
      return dashboardEmployeeSnapshots.filter(
        (worker) => !worker.urgent && worker.runtimeState === "running",
      );
    }
    if (kanbanFilter === "idle") {
      return dashboardEmployeeSnapshots.filter(
        (worker) => !worker.urgent && worker.runtimeState === "idle",
      );
    }
    return dashboardEmployeeSnapshots;
  }, [dashboardEmployeeSnapshots, kanbanFilter]);

  useEffect(() => {
    if (!dashboardHistoryVisible || !dashboardHistoryEmployeeId) {
      return;
    }

    if (REMOTE_AGENT_IDS[dashboardHistoryEmployeeId]) {
      setDashboardHistorySessions(dashboardRemoteSessionsMap[dashboardHistoryEmployeeId] || []);
      return;
    }

    setDashboardHistorySessions(
      ensureSessionRecords(conversationStore[dashboardHistoryEmployeeId]),
    );
  }, [
    conversationStore,
    dashboardHistoryEmployeeId,
    dashboardHistoryVisible,
    dashboardRemoteSessionsMap,
  ]);

  const handleOpenDashboardEmployeeHistory = useCallback(async (employeeId: string) => {
    const employee = getEmployeeById(employeeId);
    if (!employee) {
      return;
    }

    setDashboardHistoryEmployeeId(employee.id);
    setDashboardHistoryVisible(true);
    setDashboardHistoryError("");

    if (!REMOTE_AGENT_IDS[employee.id]) {
      setDashboardHistoryLoading(false);
      setDashboardHistorySessions(ensureSessionRecords(conversationStore[employee.id]));
      return;
    }

    const cachedSessions = dashboardRemoteSessionsMap[employee.id];
    if (cachedSessions) {
      setDashboardHistoryLoading(false);
      setDashboardHistorySessions(cachedSessions);
      return;
    }

    setDashboardHistoryLoading(true);
    try {
      const chats = await listChats(REMOTE_AGENT_IDS[employee.id], {
        user_id: DASHBOARD_USER_ID,
        channel: DASHBOARD_CHAT_CHANNEL,
      });
      const normalizedSessions = normalizeRemoteSessions(
        Array.isArray(chats) ? chats : [],
        employee.id,
      );
      setDashboardRemoteSessionsMap((prev) => ({
        ...prev,
        [employee.id]: normalizedSessions,
      }));
      setDashboardHistorySessions(normalizedSessions);
    } catch (error: any) {
      setDashboardHistoryError(error?.message || "获取已处理任务失败，请稍后重试");
      setDashboardHistorySessions([]);
    } finally {
      setDashboardHistoryLoading(false);
    }
  }, [conversationStore, dashboardRemoteSessionsMap]);

  const handleSelectDashboardHistory = useCallback((employeeId: string, session: SessionRecord) => {
    setDashboardHistoryVisible(false);
    setDashboardHistoryEmployeeId("");
    setDashboardHistorySessions([]);
    setDashboardHistoryError("");
    onOpenTaskEmployeeChat(employeeId, session);
  }, [onOpenTaskEmployeeChat]);

  return {
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
    filteredDashboardWorkColumns: filteredDashboardWorkColumns as DashboardWorkColumn[],
    filteredDashboardEmployeeSnapshots: filteredDashboardEmployeeSnapshots as DashboardEmployeeSnapshot[],
    handleOpenDashboardEmployeeHistory,
    handleSelectDashboardHistory,
  };
}
