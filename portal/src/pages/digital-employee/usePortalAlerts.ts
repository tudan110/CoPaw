import { useCallback, useEffect, useRef, useState } from "react";
import { getEmployeeById } from "../../data/portalData";
import { listPortalRealAlarms } from "../../api/portalRealAlarms";
import { registerAlarmRecord } from "../../api/alarmRegistry";
import {
  normalizePortalBellAlerts,
  PORTAL_REAL_ALARM_POLL_ENABLED,
  PORTAL_REAL_ALARM_POLL_INTERVAL_MS,
} from "./realAlarms";
import { buildPortalAlertDispatchText } from "./pageHelpers";
import type {
  PortalAlertToastState,
  PortalLocationState,
  PortalOpsAlert,
} from "./pageHelpers";

type NavigateToEmployeePage = (
  employee: any,
  options?: {
    entry?: string | null;
    view?: "overview" | "dashboard" | "tasks" | "chat";
    panel?: string | null;
    replace?: boolean;
    state?: PortalLocationState;
  },
) => void;

export function usePortalAlerts({
  employeesWithRuntimeStatus,
  navigateToEmployeePage,
  locationPathname,
  locationSearch,
  suspended = false,
}: {
  employeesWithRuntimeStatus: any[];
  navigateToEmployeePage: NavigateToEmployeePage;
  locationPathname: string;
  locationSearch: string;
  suspended?: boolean;
}) {
  const [opsAlerts, setOpsAlerts] = useState<PortalOpsAlert[]>([]);
  const [alertToast, setAlertToast] = useState<PortalAlertToastState | null>(null);
  const [alertPopupOpen, setAlertPopupOpen] = useState(false);
  const [alertPopupPosition, setAlertPopupPosition] = useState<{ top: number; left: number } | null>(null);
  const alertPopupRef = useRef<HTMLDivElement | null>(null);
  const activeAlertTriggerRef = useRef<HTMLButtonElement | null>(null);
  const alertToastTimerRef = useRef<number | null>(null);
  const alertPollTimerRef = useRef<number | null>(null);
  const knownAlertIdsRef = useRef<string[]>([]);

  // 后端按 INOE sortType=1（最新告警时间倒序）返回，前端不再排序。
  const sortedOpsAlerts = opsAlerts;

  const loadOpsAlerts = useCallback(async () => {
    try {
      // No explicit limit: the backend applies the configurable list
      // size from 设置-诊断 (alarm_list_limit, default 20).
      const response = await listPortalRealAlarms();
      setOpsAlerts(normalizePortalBellAlerts(response));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (message.includes("请求超时")) {
        console.warn("Portal real alarms polling timed out; will retry later.");
        return;
      }
      console.error("Failed to load portal real alarms", error);
    }
  }, []);

  const handleClearOpsAlerts = useCallback(() => {
    if (alertToastTimerRef.current) {
      window.clearTimeout(alertToastTimerRef.current);
      alertToastTimerRef.current = null;
    }
    knownAlertIdsRef.current = [];
    setOpsAlerts([]);
    setAlertToast(null);
    setAlertPopupOpen(false);
  }, []);

  const handlePortalAlertAction = useCallback((alert: PortalOpsAlert) => {
    if (alertToastTimerRef.current) {
      window.clearTimeout(alertToastTimerRef.current);
      alertToastTimerRef.current = null;
    }
    setAlertPopupOpen(false);
    setAlertToast((current) =>
      current?.alert.id === alert.id ? null : current,
    );
    setOpsAlerts((currentAlerts) => currentAlerts.filter((item) => item.id !== alert.id));

    const employee =
      employeesWithRuntimeStatus.find((item) => item.id === alert.employeeId) ||
      getEmployeeById(alert.employeeId);
    if (!employee) {
      return;
    }

    if (alert.dispatchContent) {
      // Register alarm in the registry (fire-and-forget)
      registerAlarmRecord({
        alarmId: alert.id,
        sessionId: `portal-fault-alarm-${alert.id}`,
        resId: alert.resId,
        title: alert.title || alert.message.split(" · ")[0] || "",
        deviceName: alert.deviceName || alert.message.split(" · ")[1] || "",
        manageIp: alert.manageIp || alert.message.split(" · ")[2] || "",
        visibleContent: alert.visibleContent || alert.dispatchContent,
        additionalText: alert.additionalText || alert.visibleContent || alert.dispatchContent,
        alarmLocation: alert.alarmLocation,
        eventTime: alert.eventTime,
        eventLastTime: alert.eventLastTime,
        actCount: alert.actCount,
        status: "analyzing",
        source: "manual-bell",
      }).catch(() => {});

      const normalizedVisibleContent = buildPortalAlertDispatchText(
        alert.visibleContent || alert.dispatchContent,
        alert.resId,
        alert.timeLabel,
      );
      navigateToEmployeePage(employee, {
        entry: alert.routeEntry ?? null,
        view: "chat",
        panel: null,
        state: {
          pendingPortalDispatch: {
            token: `alert-dispatch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            targetEmployeeId: employee.id,
            content: normalizedVisibleContent,
            visibleContent: normalizedVisibleContent,
            forceNewChat: true,
            alarmId: alert.id,
            sessionId: `portal-fault-alarm-${alert.id}`,
            chatMeta: {
              source: "portal-real-alarm",
              alarmId: alert.id,
              resId: alert.resId,
              title: alert.title || alert.message.split(" · ")[0] || "",
              deviceName: alert.deviceName || alert.message.split(" · ")[1] || "",
              manageIp: alert.manageIp || alert.message.split(" · ")[2] || "",
              eventTime: alert.eventTime,
              eventLastTime: alert.eventLastTime,
              visibleContent: normalizedVisibleContent,
              additionalText: alert.additionalText || alert.visibleContent || alert.dispatchContent,
              alarmLocation: alert.alarmLocation,
            },
            resId: alert.resId,
            title: alert.title || alert.message.split(" · ")[0] || "",
            deviceName: alert.deviceName || alert.message.split(" · ")[1] || "",
            manageIp: alert.manageIp || alert.message.split(" · ")[2] || "",
            eventTime: alert.eventTime,
            eventLastTime: alert.eventLastTime,
            actCount: alert.actCount,
            additionalText: alert.additionalText || alert.visibleContent || alert.dispatchContent,
            alarmLocation: alert.alarmLocation,
          },
        } satisfies PortalLocationState,
      });
      return;
    }

    navigateToEmployeePage(employee, {
      entry: alert.routeEntry ?? null,
      view: "chat",
      panel: null,
    });
  }, [employeesWithRuntimeStatus, navigateToEmployeePage]);

  const handleToggleAlertPopup = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();

    const trigger = event.currentTarget;
    const isSameTrigger = activeAlertTriggerRef.current === trigger;
    const popupWidth = Math.min(400, window.innerWidth - 32);
    const rect = trigger.getBoundingClientRect();
    const left = Math.min(
      Math.max(16, rect.right - popupWidth),
      window.innerWidth - popupWidth - 16,
    );

    activeAlertTriggerRef.current = trigger;
    setAlertPopupPosition({
      top: Math.min(rect.bottom + 8, window.innerHeight - 24),
      left,
    });
    setAlertPopupOpen((current) => (isSameTrigger ? !current : true));
  }, []);

  useEffect(() => {
    if (!alertPopupOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (activeAlertTriggerRef.current?.contains(event.target as Node)) {
        return;
      }
      if (alertPopupRef.current?.contains(event.target as Node)) {
        return;
      }
      setAlertPopupOpen(false);
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [alertPopupOpen]);

  useEffect(() => {
    setAlertPopupOpen(false);
  }, [locationPathname, locationSearch]);

  useEffect(
    () => () => {
      if (alertToastTimerRef.current) {
        window.clearTimeout(alertToastTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (!PORTAL_REAL_ALARM_POLL_ENABLED || suspended) {
      if (alertPollTimerRef.current) {
        window.clearTimeout(alertPollTimerRef.current);
        alertPollTimerRef.current = null;
      }
      setOpsAlerts([]);
      setAlertToast(null);
      setAlertPopupOpen(false);
      return undefined;
    }

    let cancelled = false;

    const poll = async () => {
      await loadOpsAlerts();
      if (cancelled) {
        return;
      }
      alertPollTimerRef.current = window.setTimeout(
        () => {
          void poll();
        },
        PORTAL_REAL_ALARM_POLL_INTERVAL_MS,
      );
    };

    void poll();

    return () => {
      cancelled = true;
      if (alertPollTimerRef.current) {
        window.clearTimeout(alertPollTimerRef.current);
        alertPollTimerRef.current = null;
      }
    };
  }, [loadOpsAlerts, suspended]);

  useEffect(() => {
    const nextAlertIds = opsAlerts.map((alert) => alert.id);
    const previousAlertIds = knownAlertIdsRef.current;
    const incomingAlerts = opsAlerts.filter((alert) => !previousAlertIds.includes(alert.id));

    knownAlertIdsRef.current = nextAlertIds;

    if (!incomingAlerts.length) {
      if (opsAlerts.length === 0) {
        setAlertToast(null);
      }
      return;
    }

    const latestAlert = incomingAlerts[incomingAlerts.length - 1];
    if (alertToastTimerRef.current) {
      window.clearTimeout(alertToastTimerRef.current);
    }
    setAlertToast({
      alert: latestAlert,
      visible: true,
    });
    alertToastTimerRef.current = window.setTimeout(() => {
      setAlertToast((current) =>
        current?.alert.id === latestAlert.id
          ? null
          : current,
      );
      alertToastTimerRef.current = null;
    }, 6000);
  }, [opsAlerts]);

  useEffect(() => {
    if (!alertPopupOpen) {
      return;
    }

    const updateAlertPopupPosition = () => {
      const trigger = activeAlertTriggerRef.current;
      if (!trigger) {
        return;
      }

      const rect = trigger.getBoundingClientRect();
      const popupWidth = Math.min(400, window.innerWidth - 32);
      const left = Math.min(
        Math.max(16, rect.right - popupWidth),
        window.innerWidth - popupWidth - 16,
      );
      const top = Math.min(rect.bottom + 8, window.innerHeight - 24);

      setAlertPopupPosition({ top, left });
    };

    updateAlertPopupPosition();
    window.addEventListener("resize", updateAlertPopupPosition);
    const handleScroll = (event: Event) => {
      if (alertPopupRef.current?.contains(event.target as Node)) {
        return;
      }
      updateAlertPopupPosition();
    };
    window.addEventListener("scroll", handleScroll, true);

    return () => {
      window.removeEventListener("resize", updateAlertPopupPosition);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [alertPopupOpen]);

  return {
    sortedOpsAlerts,
    alertToast,
    alertPopupOpen,
    alertPopupPosition,
    alertPopupRef,
    activeAlertTriggerRef,
    handleClearOpsAlerts,
    handlePortalAlertAction,
    handleToggleAlertPopup,
  };
}
