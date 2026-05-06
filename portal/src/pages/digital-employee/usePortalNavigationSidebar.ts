import { useCallback, useEffect, useMemo, useState } from "react";
import type { NavigateFunction } from "react-router-dom";
import {
  buildEmployeePagePath,
  buildPortalHomePath,
  buildPortalSectionPath,
  type PortalAdvancedPanel,
  type PortalView,
} from "./helpers";
import { sidebarEmployeePriority } from "./pageHelpers";
import type { PortalLocationState } from "./pageHelpers";

export function usePortalNavigationSidebar({
  navigate,
  selectedEmployee,
  currentEntry,
  currentView,
  activeAdvancedPanel,
  employeesWithRuntimeStatus,
  portalHomeEmployee,
  isMcpMode,
}: {
  navigate: NavigateFunction;
  selectedEmployee: any;
  currentEntry: string | null;
  currentView: PortalView;
  activeAdvancedPanel: PortalAdvancedPanel | null;
  employeesWithRuntimeStatus: any[];
  portalHomeEmployee: any;
  isMcpMode: boolean;
}) {
  const navigateToEmployeePage = useCallback((
    employee: any,
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
      state?: PortalLocationState;
    } = {},
  ) => {
    navigate(
      buildEmployeePagePath(employee, {
        entry: options.entry,
        view: options.view,
        panel: options.panel,
      }),
      options.replace || options.state
        ? {
            ...(options.replace ? { replace: true } : {}),
            ...(options.state ? { state: options.state } : {}),
          }
        : undefined,
    );
  }, [navigate]);

  const navigateToPortalHome = useCallback((
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
      state?: PortalLocationState;
    } = {},
  ) => {
    navigate(
      buildPortalHomePath({
        entry: options.entry,
        view: options.view,
        panel: options.panel,
      }),
      options.replace || options.state ? { replace: Boolean(options.replace), state: options.state } : undefined,
    );
  }, [navigate]);

  const updateCurrentEmployeeRoute = useCallback((
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
    } = {},
  ) => {
    const nextEntry = options.entry ?? currentEntry;
    const nextView = options.view ?? currentView;
    const nextPanel =
      options.panel === undefined ? activeAdvancedPanel : options.panel;

    if (selectedEmployee) {
      navigateToEmployeePage(selectedEmployee, {
        entry: nextEntry,
        view: nextView,
        panel: nextPanel,
        replace: options.replace,
      });
      return;
    }

    navigateToPortalHome({
      entry: nextEntry,
      view: nextView,
      panel: nextPanel,
      replace: options.replace,
    });
  }, [
    activeAdvancedPanel,
    currentEntry,
    currentView,
    navigateToEmployeePage,
    navigateToPortalHome,
    selectedEmployee,
  ]);

  const openSkillPool = useCallback(() => {
    navigate(buildPortalSectionPath("skill-pool"));
  }, [navigate]);

  const openKnowledgeBase = useCallback(() => {
    navigate(buildPortalSectionPath("knowledge-base", {
      employeeId: "knowledge",
    }));
  }, [navigate]);

  const openInspiration = useCallback(() => {
    navigate(buildPortalSectionPath("inspiration"));
  }, [navigate]);

  const openCli = useCallback(() => {
    navigate(
      buildPortalSectionPath("cli", {
        employeeId: selectedEmployee?.id || null,
      }),
    );
  }, [navigate, selectedEmployee?.id]);

  const [lastSidebarEmployeeId, setLastSidebarEmployeeId] = useState<string | null>(null);

  const sidebarEmployees = useMemo(() => {
    const priorityIds = new Set<string>(sidebarEmployeePriority);
    const prioritizedEmployees = sidebarEmployeePriority.flatMap((employeeId) => {
      const employee = employeesWithRuntimeStatus.find((item) => item.id === employeeId);
      return employee ? [employee] : [];
    });

    return [
      ...prioritizedEmployees,
      ...employeesWithRuntimeStatus.filter((employee) => !priorityIds.has(employee.id)),
    ];
  }, [employeesWithRuntimeStatus]);

  const currentSidebarEmployee = useMemo(() => {
    const employeeId = selectedEmployee?.id || lastSidebarEmployeeId || sidebarEmployees[0]?.id || null;
    return sidebarEmployees.find((employee) => employee.id === employeeId) || sidebarEmployees[0] || null;
  }, [lastSidebarEmployeeId, selectedEmployee?.id, sidebarEmployees]);

  useEffect(() => {
    if (!selectedEmployee?.id) {
      return;
    }
    setLastSidebarEmployeeId(selectedEmployee.id);
  }, [selectedEmployee?.id]);

  useEffect(() => {
    if (!isMcpMode || selectedEmployee || !currentSidebarEmployee?.id) {
      return;
    }

    navigate(
      buildPortalSectionPath("mcp", {
        entry: currentEntry,
        employeeId: currentSidebarEmployee.id,
      }),
      { replace: true },
    );
  }, [
    currentEntry,
    currentSidebarEmployee?.id,
    isMcpMode,
    navigate,
    selectedEmployee,
  ]);

  const switchMcpEmployee = useCallback((employeeId: string | null) => {
    navigate(buildPortalSectionPath("mcp", { employeeId }));
  }, [navigate]);

  const openEmployeeChat = useCallback((targetEmployeeId: string) => {
    const employee = employeesWithRuntimeStatus.find((item) => item.id === targetEmployeeId);
    if (!employee) {
      return;
    }
    navigateToEmployeePage(employee, {
      entry: null,
      view: "chat",
      panel: null,
    });
  }, [employeesWithRuntimeStatus, navigateToEmployeePage]);

  const getEmployeeStatusBadgeClassName = useCallback((employee: any) => {
    if (employee.urgent) {
      return "status-badge urgent";
    }
    if (employee.status === "running") {
      return "status-badge running";
    }
    return "status-badge stopped";
  }, []);

  const getEmployeeStatusLabel = useCallback((employee: any) => {
    if (employee.urgent) {
      return "紧急任务";
    }
    if (employee.status === "running") {
      return "运行中";
    }
    return "待机";
  }, []);

  return {
    navigateToEmployeePage,
    navigateToPortalHome,
    updateCurrentEmployeeRoute,
    openSkillPool,
    openKnowledgeBase,
    openInspiration,
    openCli,
    switchMcpEmployee,
    openEmployeeChat,
    sidebarEmployees,
    currentSidebarEmployee,
    sidebarCardEmployee: portalHomeEmployee,
    getEmployeeStatusBadgeClassName,
    getEmployeeStatusLabel,
  };
}
