import { createPortal } from "react-dom";
import type {
  ChangeEvent,
  KeyboardEvent,
  MouseEvent,
  MutableRefObject,
  ReactNode,
  WheelEvent,
} from "react";
import { Component } from "react";
import type { DigitalEmployee } from "../../types/portal";
import { getEmployeeById } from "../../data/portalData";
import DigitalEmployeeAvatar from "../../components/DigitalEmployeeAvatar";
import PortalTraditionalViewButton from "../../components/PortalTraditionalViewButton";
import { portalAppTitle } from "../../config/portalBranding";
import { ChatMessageItem } from "./components";
import type {
  ChatSidebarActivityItem,
  ChatSidebarSectionKey,
  DashboardEmployeeSnapshot,
  DashboardKanbanFilter,
  DashboardWorkColumn,
  ExecutionRecord,
  PortalAlertToastState,
  PortalOpsAlert,
  SessionRecord,
} from "./pageHelpers";

export class DigitalEmployeePageErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("DigitalEmployeePage render failed:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="portal-digital-employee">
          <div className="app-container">
            <div className="main-content">
              <div className="history-empty" style={{ minHeight: 360 }}>
                <i className="fas fa-triangle-exclamation" />
                <p>数字员工页面渲染失败，请刷新后重试。</p>
              </div>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function SidebarEmployeeCard({
  employee,
  active = false,
  expandable = false,
  expanded = false,
  onClick,
  onToggleExpand,
  getEmployeeStatusBadgeClassName,
  getEmployeeStatusLabel,
}: {
  employee: DigitalEmployee;
  active?: boolean;
  expandable?: boolean;
  expanded?: boolean;
  onClick: () => void;
  onToggleExpand?: () => void;
  getEmployeeStatusBadgeClassName: (employee: DigitalEmployee) => string;
  getEmployeeStatusLabel: (employee: DigitalEmployee) => string;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={
        active
          ? "agent-card active agent-card-selector"
          : "agent-card agent-card-selector"
      }
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick();
        }
      }}
    >
      <span className={getEmployeeStatusBadgeClassName(employee)}>
        {getEmployeeStatusLabel(employee)}
      </span>

      <div className="agent-header">
        <DigitalEmployeeAvatar employee={employee} />
        <div className="agent-info">
          <h3>{employee.name}</h3>
          <p>{employee.desc}</p>
        </div>
        {expandable ? (
          <button
            type="button"
            className={expanded ? "agent-card-chevron open" : "agent-card-chevron"}
            aria-label={expanded ? "收起员工切换" : "展开员工切换"}
            aria-expanded={expanded}
            onClick={(event) => {
              event.stopPropagation();
              onToggleExpand?.();
            }}
          >
            <i className={`fas ${expanded ? "fa-chevron-up" : "fa-chevron-down"}`} />
          </button>
        ) : null}
      </div>
      <div className="agent-stats">
        <div className="stat-item">
          <i className="fas fa-chart-line" />
          <span className="stat-value">{employee.tasks}</span> 执行
        </div>
        <div className="stat-item">
          <i className="fas fa-check-circle" />
          <span className="stat-value" style={{ color: "var(--success)" }}>
            {employee.success}
          </span>
        </div>
      </div>
    </div>
  );
}

export function PortalAlertBell({
  pageTheme,
  alertBellIcon,
  sortedOpsAlerts,
  alertToast,
  alertPopupOpen,
  alertPopupPosition,
  alertPopupRef,
  activeAlertTriggerRef,
  employeesWithRuntimeStatus,
  alertLevelColors,
  alertLevelLabels,
  onClearOpsAlerts,
  onPortalAlertAction,
  onToggleAlertPopup,
}: {
  pageTheme: "light" | "dark";
  alertBellIcon: ReactNode;
  sortedOpsAlerts: PortalOpsAlert[];
  alertToast: PortalAlertToastState | null;
  alertPopupOpen: boolean;
  alertPopupPosition: { top: number; left: number } | null;
  alertPopupRef: MutableRefObject<HTMLDivElement | null>;
  activeAlertTriggerRef: MutableRefObject<HTMLButtonElement | null>;
  employeesWithRuntimeStatus: DigitalEmployee[];
  alertLevelColors: Record<string, string>;
  alertLevelLabels: Record<string, string>;
  onClearOpsAlerts: () => void;
  onPortalAlertAction: (alert: PortalOpsAlert) => void;
  onToggleAlertPopup: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const alertCount = sortedOpsAlerts.length;
  const toastAlert = alertToast?.visible ? alertToast.alert : null;
  const popup =
    alertPopupOpen && alertPopupPosition && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={alertPopupRef}
            className={pageTheme === "dark" ? "portal-alert-popup theme-dark" : "portal-alert-popup"}
            style={{
              top: `${alertPopupPosition.top}px`,
              left: `${alertPopupPosition.left}px`,
            }}
          >
            <div className="alert-popup-header">
              <div className="alert-popup-title">
                {alertBellIcon}
                <span>消息提醒</span>
                {alertCount ? (
                  <span className="alert-count">
                    {alertCount > 99 ? "99+" : alertCount}
                  </span>
                ) : null}
              </div>
              {alertCount ? (
                <button
                  type="button"
                  className="alert-popup-clear"
                  onClick={onClearOpsAlerts}
                >
                  清空
                </button>
              ) : null}
            </div>
            <div className="alert-popup-body">
              {alertCount ? (
                sortedOpsAlerts.map((alert) => {
                  const employee =
                    employeesWithRuntimeStatus.find((item) => item.id === alert.employeeId) ||
                    getEmployeeById(alert.employeeId);
                  const levelColor = alertLevelColors[alert.level];

                  return (
                    <button
                      key={alert.id}
                      type="button"
                      className="alert-popup-item"
                      onClick={() => onPortalAlertAction(alert)}
                    >
                      <div
                        className="alert-popup-item-icon"
                        style={{ background: `${levelColor}14` }}
                      >
                        {employee ? (
                          <DigitalEmployeeAvatar
                            employee={employee}
                            className="portal-alert-popup-avatar"
                          />
                        ) : (
                          <span style={{ color: levelColor, fontWeight: 700 }}>!</span>
                        )}
                      </div>
                      <div className="alert-popup-item-body">
                        <div className="alert-popup-item-msg">{alert.message}</div>
                        <div className="alert-popup-item-meta">
                          {employee ? (
                            <span
                              className="alert-popup-item-emp"
                              style={{ color: levelColor }}
                            >
                              {employee.name}
                            </span>
                          ) : null}
                          <span
                            className="alert-popup-item-level"
                            style={{ color: levelColor }}
                          >
                            {alertLevelLabels[alert.level]}
                          </span>
                          <span className="alert-popup-item-time">{alert.timeLabel}</span>
                        </div>
                      </div>
                      <span className="alert-popup-item-go" aria-hidden="true">
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="m9 18 6-6-6-6" />
                        </svg>
                      </span>
                    </button>
                  );
                })
              ) : (
                <div className="alert-popup-empty">当前没有新的提醒</div>
              )}
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <div className="alert-bell-wrap">
      {toastAlert ? (
        <button
          type="button"
          className="danmaku-toast"
          onClick={() => onPortalAlertAction(toastAlert)}
        >
          <span className="danmaku-dot" />
          <span className="danmaku-toast-message">{toastAlert.message}</span>
          {(() => {
            const employee =
              employeesWithRuntimeStatus.find((item) => item.id === toastAlert.employeeId) ||
              getEmployeeById(toastAlert.employeeId);
            return employee ? (
              <span className="danmaku-emp">{employee.name}</span>
            ) : null;
          })()}
        </button>
      ) : null}
      <button
        ref={activeAlertTriggerRef}
        type="button"
        className={alertCount ? "alert-bell has-alerts" : "alert-bell"}
        aria-label={alertCount ? `消息提醒，当前 ${alertCount} 条未处理` : "消息提醒"}
        aria-expanded={alertPopupOpen}
        onClick={onToggleAlertPopup}
      >
        {alertBellIcon}
        <span className="bell-badge">
          {alertCount > 99 ? "99+" : alertCount}
        </span>
      </button>
      {popup}
    </div>
  );
}

export function PortalHomeHero({
  alertBell,
  themeToggleIcon,
  portalLogo,
  inputMessage,
  isInteractionLocked,
  mentionSuggestions,
  mentionActiveIndex,
  safeQuickCommands,
  resourceImportCommand,
  isConversationRunning,
  isCreatingChat,
  homeComposerRef,
  onToggleTheme,
  onComposerBlur,
  onInputSelection,
  onComposerChange,
  onComposerKeyDown,
  onApplyMentionSuggestion,
  onOpenResourceImport,
  onOpenHistory,
  onSendPreset,
  onPrimaryAction,
  modelSelector,
}: {
  alertBell: ReactNode;
  themeToggleIcon: ReactNode;
  portalLogo: string;
  inputMessage: string;
  isInteractionLocked: boolean;
  mentionSuggestions: Array<{ employee: DigitalEmployee; score: number }>;
  mentionActiveIndex: number;
  safeQuickCommands: string[];
  resourceImportCommand: string;
  isConversationRunning: boolean;
  isCreatingChat: boolean;
  homeComposerRef: MutableRefObject<HTMLTextAreaElement | null>;
  onToggleTheme: () => void;
  onComposerBlur: () => void;
  onInputSelection: (
    event:
      | ChangeEvent<HTMLTextAreaElement>
      | KeyboardEvent<HTMLTextAreaElement>
      | MouseEvent<HTMLTextAreaElement>,
  ) => void;
  onComposerChange: (event: ChangeEvent<HTMLTextAreaElement>) => void;
  onComposerKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onApplyMentionSuggestion: (employeeName: string) => void;
  onOpenResourceImport: () => void;
  onOpenHistory: () => void;
  onSendPreset: (command: string) => void;
  onPrimaryAction: () => void;
  modelSelector: ReactNode;
}) {
  return (
    <div className="portal-home-stage">
      <div className="portal-home-toolbar">
        {alertBell}
        <button
          type="button"
          className="ops-board-theme-toggle portal-home-theme-toggle"
          onClick={onToggleTheme}
          aria-label="切换整页主题"
          title="切换整页主题"
        >
          {themeToggleIcon}
        </button>
        <PortalTraditionalViewButton className="portal-home-traditional-toggle" />
      </div>
      <div className="portal-home-hero">
        <div className="portal-home-orbit">
          <span className="portal-home-orbit-ring outer" />
          <span className="portal-home-orbit-ring inner" />
          <span className="portal-home-orbit-core">
            <img src={portalLogo} alt={portalAppTitle} className="portal-home-orbit-image" />
          </span>
        </div>
        <h2>{portalAppTitle}</h2>
        <p>以对话方式发起运维协同</p>
      </div>

      <div className="portal-home-composer-card">
        <textarea
          ref={homeComposerRef}
          value={inputMessage}
          disabled={isInteractionLocked}
          onBlur={onComposerBlur}
          onClick={onInputSelection}
          onChange={onComposerChange}
          onKeyDown={onComposerKeyDown}
          onKeyUp={onInputSelection}
          placeholder="输入您的问题..."
        />
        {mentionSuggestions.length ? (
          <div className="mention-suggestions home">
            {mentionSuggestions.map((item, index) => (
              <button
                key={`home-mention-${item.employee.id}`}
                type="button"
                className={
                  index === mentionActiveIndex
                    ? "mention-suggestion active"
                    : "mention-suggestion"
                }
                onMouseDown={(event) => {
                  event.preventDefault();
                  onApplyMentionSuggestion(item.employee.name);
                }}
              >
                <DigitalEmployeeAvatar
                  employee={item.employee}
                  className="mention-suggestion-avatar"
                />
                <span className="mention-suggestion-copy">
                  <strong>{item.employee.name}</strong>
                  <small>{item.employee.desc}</small>
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <div className="portal-home-composer-footer">
          <div className="portal-home-quick-actions">
            {safeQuickCommands.map((command) => (
              <button
                key={`home-${command}`}
                className="portal-home-quick-action"
                onClick={() => {
                  if (command === resourceImportCommand) {
                    onOpenResourceImport();
                    return;
                  }
                  onSendPreset(command);
                }}
                disabled={isInteractionLocked}
              >
                {command}
              </button>
            ))}
          </div>
          <div className="portal-home-composer-actions">
            {modelSelector}
            <button
              type="button"
              className="history-btn portal-home-history-btn"
              onClick={onOpenHistory}
              aria-label="已处理任务"
              title="已处理任务"
            >
              <i className="fas fa-history" />
            </button>
            <button
              className={
                isConversationRunning
                  ? "send-btn stop-mode"
                  : isCreatingChat
                    ? "send-btn disabled"
                    : "send-btn"
              }
              onClick={onPrimaryAction}
              disabled={isCreatingChat && !isConversationRunning}
              aria-label={isConversationRunning ? "停止聊天" : "发送消息"}
            >
              {isConversationRunning ? (
                <span className="send-btn-stop-icon" aria-hidden="true" />
              ) : (
                <i className="fas fa-paper-plane" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

type AnyFn = (...args: any[]) => unknown;
type ChatMessageRecord = { id: string; streaming?: boolean } & Record<string, any>;
type MentionSuggestionItem = { employee: DigitalEmployee };
type SidebarEfficiencySummary = {
  completed: number;
  total: number;
  response: string;
  collaboration: number;
};
type SidebarCollaborator = DigitalEmployee & { collaborationCount: number };

export function DashboardPanel({
  kanbanMode,
  kanbanFilter,
  kanbanFilterLabels,
  dashboardClock,
  alertBell,
  themeToggleIcon,
  filteredDashboardEmployeeSnapshots,
  filteredDashboardWorkColumns,
  dashboardLatestSessions,
  onSetKanbanMode,
  onSetKanbanFilter,
  onToggleTheme,
  onOpenDashboardEmployeeHistory,
  onOpenTaskEmployeeChat,
}: {
  kanbanMode: "work" | "employee";
  kanbanFilter: DashboardKanbanFilter;
  kanbanFilterLabels: Partial<Record<DashboardKanbanFilter, string>>;
  dashboardClock: string;
  alertBell: ReactNode;
  themeToggleIcon: ReactNode;
  filteredDashboardEmployeeSnapshots: DashboardEmployeeSnapshot[];
  filteredDashboardWorkColumns: DashboardWorkColumn[];
  dashboardLatestSessions: Record<string, SessionRecord | null>;
  onSetKanbanMode: (mode: "work" | "employee") => void;
  onSetKanbanFilter: (filter: DashboardKanbanFilter) => void;
  onToggleTheme: () => void;
  onOpenDashboardEmployeeHistory: (employeeId: string) => void;
  onOpenTaskEmployeeChat: (employeeId: string, session?: SessionRecord | null) => void;
}) {
  return (
    <div className="kanban-shell">
      <div className="kanban-toolbar main-header">
        <div className="kanban-main-title main-title">
          运维看板
          <small>
            {kanbanMode === "employee"
              ? "数字员工维度 · 当前工作状态"
              : "工作维度 · 实时任务概览"}
          </small>
        </div>
        <div className="ops-filter-bar">
          <div className="ops-filter-left">
            <div className="ops-filter-tabs ops-dimension-tabs">
              <button
                type="button"
                className={kanbanMode === "work" ? "ops-filter-tab active" : "ops-filter-tab"}
                onClick={() => onSetKanbanMode("work")}
              >
                工作维度
              </button>
              <button
                type="button"
                className={kanbanMode === "employee" ? "ops-filter-tab active" : "ops-filter-tab"}
                onClick={() => onSetKanbanMode("employee")}
              >
                数字员工维度
              </button>
            </div>
            <div className="ops-filter-tabs">
              {(Object.entries(kanbanFilterLabels) as [DashboardKanbanFilter, string][])
                .map(([filterId, label]) => (
                  <button
                    key={`kanban-filter-${filterId}`}
                    type="button"
                    className={kanbanFilter === filterId ? "ops-filter-tab active" : "ops-filter-tab"}
                    onClick={() => onSetKanbanFilter(filterId)}
                  >
                    {label}
                  </button>
                ))}
            </div>
          </div>
        </div>
        <div className="kanban-header-actions main-header-actions">
          <div className="ops-clock">
            <span className="ops-clock-dot" />
            <span>{dashboardClock}</span>
          </div>
          {alertBell}
          <button
            type="button"
            className="kanban-theme-toggle theme-toggle"
            onClick={onToggleTheme}
            aria-label="切换整页主题"
            title="切换整页主题"
          >
            {themeToggleIcon}
          </button>
          <PortalTraditionalViewButton />
        </div>
      </div>

      {kanbanMode === "employee" ? (
        <div className="kanban-board employee-dimension">
          {filteredDashboardEmployeeSnapshots.length ? (
            filteredDashboardEmployeeSnapshots.map((worker) => {
              const latestSession = dashboardLatestSessions[worker.id];
              const runtimeLabel = worker.statusLabel;
              const runtimeColor = worker.urgent
                ? "#f97316"
                : worker.runtimeState === "running"
                  ? "#22c55e"
                  : "#94a3b8";
              const runtimeBg = worker.urgent
                ? "rgba(249, 115, 22, 0.14)"
                : worker.runtimeState === "running"
                  ? "rgba(34, 197, 94, 0.14)"
                  : "rgba(100, 116, 139, 0.14)";
              const runtimeTextColor = worker.urgent
                ? "#fb923c"
                : worker.runtimeState === "running"
                  ? "#86efac"
                  : "#cbd5e1";

              return (
                <div
                  key={`kanban-worker-${worker.id}`}
                  className="kanban-card employee-worker-card"
                >
                  <span
                    className="kanban-card-stripe"
                    style={{ background: worker.color }}
                    aria-hidden="true"
                  />
                  <div className="kanban-emp">
                    <DigitalEmployeeAvatar
                      employee={getEmployeeById(worker.id)}
                      className="kanban-emp-avatar"
                    />
                    <div className="kanban-emp-copy">
                      <div className="kanban-card-title compact">{worker.name}</div>
                      <div className="kanban-emp-name">{worker.desc}</div>
                    </div>
                  </div>
                  <div className="kanban-worker-status">
                    <span
                      className="kanban-worker-status-dot"
                      style={{ background: runtimeColor, color: runtimeColor }}
                    />
                    <span className="kanban-worker-status-text">{runtimeLabel}</span>
                    <span className="kanban-card-time">{worker.updatedAt}</span>
                  </div>
                  <div className="kanban-card-title">{worker.currentJob}</div>
                  <div className="kanban-progress">
                    <div className="kanban-progress-bar">
                      <div
                        className="kanban-progress-fill"
                        style={{
                          width: `${worker.progress}%`,
                          background: `linear-gradient(90deg, ${worker.color}, ${worker.color}cc)`,
                        }}
                      />
                    </div>
                    <div className="kanban-progress-label">
                      <span>当前工作进度</span>
                      <span style={{ color: worker.color, fontWeight: 600 }}>
                        {worker.progress}%
                      </span>
                    </div>
                  </div>
                  <div className="kanban-worker-summary">
                    <button
                      type="button"
                      className="kanban-worker-stat kanban-worker-stat-action"
                      onClick={() => onOpenDashboardEmployeeHistory(worker.id)}
                      title={`查看 ${worker.name} 已处理任务`}
                    >
                      <div className="kanban-worker-stat-label">已处理任务</div>
                      <div className="kanban-worker-stat-value">{worker.historyCount} 条</div>
                    </button>
                    <div className="kanban-worker-stat">
                      <div className="kanban-worker-stat-label">工作状态</div>
                      <div className="kanban-worker-stat-value">{worker.workStatus}</div>
                    </div>
                  </div>
                  <div className="kanban-card-footer">
                    <span
                      className="kanban-card-tag"
                      style={{ background: runtimeBg, color: runtimeTextColor }}
                    >
                      {runtimeLabel}
                    </span>
                    <button
                      type="button"
                      className="kanban-card-time kanban-card-link-btn"
                      onClick={() => onOpenTaskEmployeeChat(worker.id, latestSession)}
                      title={`进入 ${worker.name} 对话`}
                    >
                      点击进入对话
                    </button>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="kanban-empty-card">
              <div className="kanban-card-title">暂无匹配的数字员工</div>
              <div className="kanban-card-desc">请切换筛选条件，查看其他数字员工状态。</div>
            </div>
          )}
        </div>
      ) : (
        <div className="kanban-board">
          {filteredDashboardWorkColumns.length ? (
            filteredDashboardWorkColumns.map((column) => (
              <section key={`kanban-column-${column.id}`} className="kanban-col">
                <div className="kanban-col-header">
                  <div className="kanban-col-dot" style={{ background: column.dot, color: column.dot }} />
                  <div className="kanban-col-title">{column.title}</div>
                  <div className="kanban-col-count">{column.cards.length}</div>
                </div>
                <div className="kanban-col-body">
                  {column.cards.map((card) => (
                    <button
                      key={card.id}
                      type="button"
                      className="kanban-card work-card"
                      onClick={() => onOpenTaskEmployeeChat(card.ownerEmployeeIds[0])}
                    >
                      <span
                        className="kanban-card-stripe"
                        style={{ background: card.ownerColor }}
                        aria-hidden="true"
                      />
                      <div className="kanban-card-title">{card.title}</div>
                      <div className="kanban-card-desc">{card.description}</div>
                      <div className="kanban-emp divided">
                        <DigitalEmployeeAvatar
                          employee={getEmployeeById(card.ownerEmployeeIds[0])}
                          className="kanban-emp-avatar small"
                        />
                        <div className="kanban-emp-name">{card.ownerLabel}</div>
                      </div>
                      {typeof card.progress === "number" ? (
                        <div className="kanban-progress">
                          <div className="kanban-progress-bar">
                            <div
                              className="kanban-progress-fill"
                              style={{
                                width: `${card.progress}%`,
                                background: `linear-gradient(90deg, ${card.ownerColor}, ${card.ownerColor}cc)`,
                              }}
                            />
                          </div>
                          <div className="kanban-progress-label">
                            <span>进度</span>
                            <span style={{ color: card.ownerColor, fontWeight: 600 }}>
                              {card.progress}%
                            </span>
                          </div>
                        </div>
                      ) : null}
                      {typeof card.score === "number" ? (
                        <div className="kanban-score" aria-label={`评分 ${card.score}`}>
                          {Array.from({ length: 5 }, (_, index) => (
                            <span
                              key={`${card.id}-score-${index}`}
                              className={card.score >= index + 1 ? "star filled" : "star"}
                            >
                              ★
                            </span>
                          ))}
                          <span className="kanban-score-val">{card.score}</span>
                        </div>
                      ) : null}
                      <div className="kanban-card-footer">
                        <span
                          className="kanban-card-tag"
                          style={{ background: card.tagBg, color: card.tagColor }}
                        >
                          {card.label}
                        </span>
                        <span className={card.isUrgent ? "kanban-card-time urgent" : "kanban-card-time"}>
                          {card.timeText}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </section>
            ))
          ) : (
            <div className="kanban-empty-column">
              <div className="kanban-col-header">
                <div className="kanban-col-dot" style={{ background: "#94a3b8", color: "#94a3b8" }} />
                <div className="kanban-col-title">当前筛选结果</div>
                <div className="kanban-col-count">0</div>
              </div>
              <div className="kanban-col-body">
                <div className="kanban-empty-card">
                  <div className="kanban-card-title">暂无匹配内容</div>
                  <div className="kanban-card-desc">请切换筛选条件，查看其他工作任务状态。</div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function EmployeeChatMainPanel({
  visibleEmployee,
  isAlarmWorkbenchMode,
  headerStatusLabel,
  chatHeaderActions,
  chatMessagesRef,
  messagesEndRef,
  safeMessages,
  remoteAgentId,
  currentEmployeeBase,
  isStreaming,
  activeAssistantMessageId,
  onChatMessagesScroll,
  onChatMessagesWheelCapture,
  onDisposalAction,
  onResourceImportBackToConfirm,
  onResourceImportBuildTopology,
  onResourceImportConfirmStructure,
  onResourceImportContinue,
  onResourceImportOpenSystemTopology,
  onResourceImportParseFailed,
  onResourceImportParseResolved,
  onResourceImportReturnToUpload,
  onResourceImportStartParse,
  onResourceImportScrollToStage,
  onResourceImportSubmitImport,
  onResourceImportUploadFiles,
  onKnowledgeBaseFlowUpdate,
  onKnowledgeBaseUploadRequest,
  onKnowledgeBaseManagementOpen,
  releaseResourceImportFiles,
  resolveResourceImportFiles,
  pageTheme,
  onTicketAction,
  onTicketRefresh,
  ticketActionNotice,
  activeModelLabel,
  safeCapabilities,
  safeQuickCommands,
  resourceImportCommand,
  isInteractionLocked,
  openResourceImport,
  onSendPreset,
  inputMessage,
  chatInputRef,
  onComposerBlur,
  onInputSelection,
  onComposerChange,
  onComposerKeyDown,
  mentionSuggestions,
  mentionActiveIndex,
  onApplyMentionSuggestion,
  isConversationRunning,
  isCreatingChat,
  onPrimaryAction,
}: {
  visibleEmployee: DigitalEmployee;
  isAlarmWorkbenchMode: boolean;
  headerStatusLabel?: string | null;
  chatHeaderActions: ReactNode;
  chatMessagesRef: MutableRefObject<HTMLDivElement | null>;
  messagesEndRef: MutableRefObject<HTMLDivElement | null>;
  safeMessages: ChatMessageRecord[];
  remoteAgentId: string;
  currentEmployeeBase: DigitalEmployee | null;
  isStreaming: boolean;
  activeAssistantMessageId?: string | null;
  onChatMessagesScroll: () => void;
  onChatMessagesWheelCapture: (event: WheelEvent<HTMLDivElement>) => void;
  onDisposalAction: AnyFn;
  onResourceImportBackToConfirm: AnyFn;
  onResourceImportBuildTopology: AnyFn;
  onResourceImportConfirmStructure: AnyFn;
  onResourceImportContinue: AnyFn;
  onResourceImportOpenSystemTopology: AnyFn;
  onResourceImportParseFailed: AnyFn;
  onResourceImportParseResolved: AnyFn;
  onResourceImportReturnToUpload: AnyFn;
  onResourceImportStartParse: AnyFn;
  onResourceImportScrollToStage: AnyFn;
  onResourceImportSubmitImport: AnyFn;
  onResourceImportUploadFiles: AnyFn;
  onKnowledgeBaseFlowUpdate: AnyFn;
  onKnowledgeBaseUploadRequest: AnyFn;
  onKnowledgeBaseManagementOpen: AnyFn;
  releaseResourceImportFiles: (flowId: string) => void;
  resolveResourceImportFiles: (flowId: string) => File[];
  pageTheme: "light" | "dark";
  onTicketAction: AnyFn;
  onTicketRefresh: () => void;
  ticketActionNotice: string;
  activeModelLabel?: string;
  safeCapabilities: string[];
  safeQuickCommands: string[];
  resourceImportCommand: string;
  isInteractionLocked: boolean;
  openResourceImport: () => void;
  onSendPreset: (command?: string) => void;
  inputMessage: string;
  chatInputRef: MutableRefObject<HTMLTextAreaElement | null>;
  onComposerBlur: () => void;
  onInputSelection: (
    event:
      | ChangeEvent<HTMLTextAreaElement>
      | KeyboardEvent<HTMLTextAreaElement>
      | MouseEvent<HTMLTextAreaElement>,
  ) => void;
  onComposerChange: (event: ChangeEvent<HTMLTextAreaElement>) => void;
  onComposerKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  mentionSuggestions: MentionSuggestionItem[];
  mentionActiveIndex: number;
  onApplyMentionSuggestion: (name: string) => void;
  isConversationRunning: boolean;
  isCreatingChat: boolean;
  onPrimaryAction: () => void;
}) {
  return (
    <div className="chat-main">
      <div className="chat-header">
        <div className="chat-header-main">
          <div className="chat-header-copy">
            <strong>
              {isAlarmWorkbenchMode
                ? `${visibleEmployee.name} - 告警工单处置`
                : `${visibleEmployee.name} - 智能服务`}
            </strong>
            <span>支持历史追溯、模型切换与专属能力调用</span>
          </div>
          {headerStatusLabel ? (
            <span className="chat-status-pill alert">{headerStatusLabel}</span>
          ) : null}
        </div>
        <div className={isAlarmWorkbenchMode ? "chat-capabilities alarm-mode" : "chat-capabilities"}>
          {chatHeaderActions}
        </div>
      </div>

      <div
        className="chat-messages"
        ref={chatMessagesRef}
        onScroll={onChatMessagesScroll}
        onWheelCapture={onChatMessagesWheelCapture}
      >
        {safeMessages.map((message) => (
          <ChatMessageItem
            agentId={remoteAgentId}
            key={message.id}
            currentEmployee={currentEmployeeBase}
            isStreamingMessage={
              Boolean(message.streaming) || (isStreaming && message.id === activeAssistantMessageId)
            }
            message={message}
            onDisposalAction={onDisposalAction}
            onResourceImportBackToConfirm={onResourceImportBackToConfirm}
            onResourceImportBuildTopology={onResourceImportBuildTopology}
            onResourceImportConfirmStructure={onResourceImportConfirmStructure}
            onResourceImportContinue={onResourceImportContinue}
            onResourceImportOpenSystemTopology={onResourceImportOpenSystemTopology}
            onResourceImportParseFailed={onResourceImportParseFailed}
            onResourceImportParseResolved={onResourceImportParseResolved}
            onResourceImportReturnToUpload={onResourceImportReturnToUpload}
            onResourceImportStartParse={onResourceImportStartParse}
            onResourceImportScrollToStage={onResourceImportScrollToStage}
            onResourceImportSubmitImport={onResourceImportSubmitImport}
            onResourceImportUploadFiles={onResourceImportUploadFiles}
            onResourceImportGuideOpen={openResourceImport}
            onKnowledgeBaseFlowUpdate={onKnowledgeBaseFlowUpdate}
            onKnowledgeBaseUploadRequest={onKnowledgeBaseUploadRequest}
            onKnowledgeBaseManagementOpen={onKnowledgeBaseManagementOpen}
            releaseResourceImportFiles={releaseResourceImportFiles}
            resolveResourceImportFiles={resolveResourceImportFiles}
            pageTheme={pageTheme}
            onTicketAction={onTicketAction}
            onTicketRefresh={onTicketRefresh}
            ticketActionNotice={ticketActionNotice}
            activeModelLabel={activeModelLabel}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {!isAlarmWorkbenchMode ? (
        <div className="quick-commands">
          <div className="capabilities-row">
            {safeCapabilities.map((item) => (
              <span key={item} className="capability-label">
                {item}
              </span>
            ))}
          </div>
          <div className="quick-cmd-row">
            {safeQuickCommands.map((command) => (
              <button
                key={command}
                className="quick-cmd"
                onClick={() => {
                  if (command === resourceImportCommand) {
                    openResourceImport();
                    return;
                  }
                  onSendPreset(command);
                }}
                disabled={isInteractionLocked}
              >
                <i className="fas fa-bolt" />
                {command}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="input-area">
        <div className="input-hint-row">
          <span>输入自然语言即可开始协同办公。</span>
        </div>
        <div className="input-wrapper">
          <div className={isCreatingChat ? "input-box disabled" : "input-box"}>
            <i className="fas fa-comment-dots" />
            <textarea
              ref={chatInputRef}
              rows={1}
              value={inputMessage}
              disabled={isInteractionLocked}
              onBlur={onComposerBlur}
              onClick={onInputSelection}
              onChange={onComposerChange}
              onKeyDown={onComposerKeyDown}
              onKeyUp={onInputSelection}
              placeholder={`向 ${visibleEmployee.name} 描述您的需求...（Enter 发送，Shift+Enter 换行）`}
            />
          </div>
          {mentionSuggestions.length ? (
            <div className="mention-suggestions">
              {mentionSuggestions.map((item, index) => (
                <button
                  key={`mention-${item.employee.id}`}
                  type="button"
                  className={index === mentionActiveIndex ? "mention-suggestion active" : "mention-suggestion"}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onApplyMentionSuggestion(item.employee.name);
                  }}
                >
                  <DigitalEmployeeAvatar
                    employee={item.employee}
                    className="mention-suggestion-avatar"
                  />
                  <span className="mention-suggestion-copy">
                    <strong>{item.employee.name}</strong>
                    <small>{item.employee.desc}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          <button
            className={
              isConversationRunning
                ? "send-btn stop-mode"
                : isCreatingChat
                  ? "send-btn disabled"
                  : "send-btn"
            }
            onClick={onPrimaryAction}
            disabled={isCreatingChat && !isConversationRunning}
            aria-label={isConversationRunning ? "停止聊天" : "发送消息"}
          >
            {isConversationRunning ? (
              <span className="send-btn-stop-icon" aria-hidden="true" />
            ) : (
              <i className="fas fa-paper-plane" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export function EmployeeChatSidebar({
  showSidebar,
  chatSidebarCollapsed,
  chatSidebarCollapsedSections,
  visibleEmployee,
  visibleEmployeeMotto,
  visibleEmployeeStatusLabel,
  currentEmployeeModelLabel,
  visibleEmployeeStatsLabel,
  visibleEmployeeActivities,
  visibleEmployeeEfficiency,
  visibleEmployeeWorkload,
  visibleEmployeeCollaborators,
  onToggleSection,
  onOpenEmployeeChat,
}: {
  showSidebar: boolean;
  chatSidebarCollapsed: boolean;
  chatSidebarCollapsedSections: Record<ChatSidebarSectionKey, boolean>;
  visibleEmployee: DigitalEmployee;
  visibleEmployeeMotto: string;
  visibleEmployeeStatusLabel: string;
  currentEmployeeModelLabel: string;
  visibleEmployeeStatsLabel: string;
  visibleEmployeeActivities: ChatSidebarActivityItem[];
  visibleEmployeeEfficiency: SidebarEfficiencySummary;
  visibleEmployeeWorkload: number[];
  visibleEmployeeCollaborators: SidebarCollaborator[];
  onToggleSection: (section: ChatSidebarSectionKey) => void;
  onOpenEmployeeChat: (employeeId: string) => void;
}) {
  if (!showSidebar) {
    return null;
  }

  return (
    <div
      className={
        chatSidebarCollapsed
          ? "chat-sidebar-shell chat-sidebar-shell-collapsed"
          : "chat-sidebar-shell"
      }
    >
      <aside className={chatSidebarCollapsed ? "chat-sidebar chat-sidebar-collapsed" : "chat-sidebar"}>
        {!chatSidebarCollapsed ? (
          <>
            <section className="chat-side-card">
              <button
                type="button"
                className="chat-side-card-header"
                onClick={() => onToggleSection("profile")}
              >
                <h4>员工档案</h4>
                <span
                  className={
                    chatSidebarCollapsedSections.profile
                      ? "chat-side-card-toggle collapsed"
                      : "chat-side-card-toggle"
                  }
                  aria-hidden="true"
                >
                  <i className="fas fa-chevron-down" />
                </span>
              </button>
              {!chatSidebarCollapsedSections.profile ? (
                <div className="chat-side-card-body">
                  <div className="chat-side-profile-hero">
                    <div className="chat-side-profile-avatar-wrap">
                      <DigitalEmployeeAvatar
                        employee={visibleEmployee}
                        className="chat-side-profile-avatar"
                      />
                    </div>
                    <div className="chat-side-profile-meta">
                      <strong>{visibleEmployee.name}</strong>
                      <p>"{visibleEmployeeMotto}"</p>
                    </div>
                  </div>
                  <div className="chat-side-info-list">
                    <div className="chat-side-info-row">
                      <span className="chat-side-info-label">状态</span>
                      <span className="chat-side-info-value">
                        <span
                          className={
                            visibleEmployee.urgent
                              ? "chat-side-status-badge urgent"
                              : visibleEmployee.status === "running"
                                ? "chat-side-status-badge running"
                                : "chat-side-status-badge stopped"
                          }
                        >
                          {visibleEmployeeStatusLabel}
                        </span>
                      </span>
                    </div>
                    <div className="chat-side-info-row">
                      <span className="chat-side-info-label">当前模型</span>
                      <span className="chat-side-info-value">{currentEmployeeModelLabel}</span>
                    </div>
                    <div className="chat-side-info-row">
                      <span className="chat-side-info-label">统计</span>
                      <span className="chat-side-info-value">{visibleEmployeeStatsLabel}</span>
                    </div>
                  </div>
                  <div className="chat-side-capability-block">
                    <div className="chat-side-capability-row">
                      <div className="chat-side-capability-title">核心能力</div>
                      <div className="chat-side-tag-group">
                        {visibleEmployee.capabilities.slice(0, 3).map((capability, index) => (
                          <span
                            key={capability}
                            className={
                              index % 3 === 1
                                ? "chat-side-capability-tag green"
                                : index % 3 === 2
                                  ? "chat-side-capability-tag purple"
                                  : "chat-side-capability-tag"
                            }
                          >
                            {capability}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}
            </section>

            <section className="chat-side-card">
              <button
                type="button"
                className="chat-side-card-header"
                onClick={() => onToggleSection("activity")}
              >
                <h4>最近活动</h4>
                <span
                  className={
                    chatSidebarCollapsedSections.activity
                      ? "chat-side-card-toggle collapsed"
                      : "chat-side-card-toggle"
                  }
                  aria-hidden="true"
                >
                  <i className="fas fa-chevron-down" />
                </span>
              </button>
              {!chatSidebarCollapsedSections.activity ? (
                <div className="chat-side-card-body">
                  <div className="chat-side-activity-list">
                    {visibleEmployeeActivities.map((activity) => (
                      <div key={activity.id} className="chat-side-activity-item">
                        <span className={`chat-side-activity-dot ${activity.tone}`} />
                        <span className="chat-side-activity-time">{activity.time}</span>
                        <span className="chat-side-activity-text">{activity.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>

            <section className="chat-side-card">
              <button
                type="button"
                className="chat-side-card-header"
                onClick={() => onToggleSection("efficiency")}
              >
                <h4>工作效能</h4>
                <span
                  className={
                    chatSidebarCollapsedSections.efficiency
                      ? "chat-side-card-toggle collapsed"
                      : "chat-side-card-toggle"
                  }
                  aria-hidden="true"
                >
                  <i className="fas fa-chevron-down" />
                </span>
              </button>
              {!chatSidebarCollapsedSections.efficiency ? (
                <div className="chat-side-card-body">
                  <div className="chat-side-stats-list">
                    <div className="chat-side-stat-row">
                      <span>今日任务</span>
                      <strong>{visibleEmployeeEfficiency.completed}/{visibleEmployeeEfficiency.total}</strong>
                    </div>
                    <div className="chat-side-stat-row">
                      <span>响应速度</span>
                      <strong>{visibleEmployeeEfficiency.response}</strong>
                    </div>
                    <div className="chat-side-stat-row">
                      <span>协作次数</span>
                      <strong>{visibleEmployeeEfficiency.collaboration} 次</strong>
                    </div>
                  </div>
                  <div className="chat-side-workload">
                    <div className="chat-side-workload-title">本周工作量</div>
                    <div className="chat-side-workload-bars">
                      {visibleEmployeeWorkload.map((value, index) => (
                        <span
                          key={`${visibleEmployee.id}-workload-${index}`}
                          className="chat-side-workload-bar"
                          style={{ height: `${value}%` }}
                        />
                      ))}
                    </div>
                    <div className="chat-side-workload-labels">
                      <span>一</span>
                      <span>二</span>
                      <span>三</span>
                      <span>四</span>
                      <span>五</span>
                      <span>六</span>
                      <span>日</span>
                    </div>
                  </div>
                </div>
              ) : null}
            </section>

            <section className="chat-side-card">
              <button
                type="button"
                className="chat-side-card-header"
                onClick={() => onToggleSection("collaboration")}
              >
                <h4>协作关系</h4>
                <span
                  className={
                    chatSidebarCollapsedSections.collaboration
                      ? "chat-side-card-toggle collapsed"
                      : "chat-side-card-toggle"
                  }
                  aria-hidden="true"
                >
                  <i className="fas fa-chevron-down" />
                </span>
              </button>
              {!chatSidebarCollapsedSections.collaboration ? (
                <div className="chat-side-card-body">
                  <div className="chat-side-collaboration-list">
                    {visibleEmployeeCollaborators.map((employee) => (
                      <button
                        key={`chat-sidebar-${employee.id}`}
                        type="button"
                        className="chat-side-collaboration-item"
                        onClick={() => onOpenEmployeeChat(employee.id)}
                      >
                        <DigitalEmployeeAvatar
                          employee={employee}
                          className="chat-side-collaboration-avatar"
                        />
                        <span className="chat-side-collaboration-copy">
                          <strong>{employee.name}</strong>
                          <span>{employee.desc}</span>
                        </span>
                        <span className="chat-side-collaboration-count">
                          协作 {employee.collaborationCount} 次
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          </>
        ) : null}
      </aside>
    </div>
  );
}

export function SessionHistoryModal({
  open,
  actionError,
  loading,
  error,
  sessions,
  historyDraftTitle,
  historyEditingId,
  historyActionSessionId,
  activePortalResourceImportSessionId,
  activePortalKnowledgeBaseSessionId,
  isRemoteEmployee,
  currentChatId,
  currentSessionId,
  isConversationRunning,
  isPortalResourceImportSession,
  isPortalKnowledgeBaseSession,
  onClose,
  onSelectHistory,
  onDraftTitleChange,
  onSubmitHistoryRename,
  onCancelHistoryRename,
  onStartHistoryRename,
  onDeleteHistorySession,
}: {
  open: boolean;
  actionError: string;
  loading: boolean;
  error: string;
  sessions: SessionRecord[];
  historyDraftTitle: string;
  historyEditingId: string;
  historyActionSessionId: string;
  activePortalResourceImportSessionId: string;
  activePortalKnowledgeBaseSessionId: string;
  isRemoteEmployee: boolean;
  currentChatId: string;
  currentSessionId: string;
  isConversationRunning: boolean;
  isPortalResourceImportSession: (session: SessionRecord) => boolean;
  isPortalKnowledgeBaseSession: (session: SessionRecord) => boolean;
  onClose: () => void;
  onSelectHistory: (session: SessionRecord) => void;
  onDraftTitleChange: (value: string) => void;
  onSubmitHistoryRename: (session: SessionRecord) => void;
  onCancelHistoryRename: () => void;
  onStartHistoryRename: (session: SessionRecord) => void;
  onDeleteHistorySession: (session: SessionRecord) => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="history-modal show" onClick={onClose}>
      <div className="history-content" onClick={(event) => event.stopPropagation()}>
        <div className="history-header">
          <h3>
            <i className="fas fa-history" /> 已处理任务
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body">
          {actionError ? (
            <div className="history-inline-error">
              <i className="fas fa-circle-exclamation" />
              <span>{actionError}</span>
            </div>
          ) : null}
          {loading ? (
            <div className="history-empty">
              <i className="fas fa-spinner fa-spin" />
              <p>正在加载已处理任务...</p>
            </div>
          ) : error ? (
            <div className="history-empty">
              <i className="fas fa-triangle-exclamation" />
              <p>{error}</p>
            </div>
          ) : sessions.length ? (
            <div className="history-timeline">
              {sessions.map((session) => {
                const isActiveSession =
                  isPortalResourceImportSession(session)
                    ? session.id === activePortalResourceImportSessionId
                    : isPortalKnowledgeBaseSession(session)
                      ? session.id === activePortalKnowledgeBaseSessionId
                      : session.id === (isRemoteEmployee ? currentChatId : currentSessionId);
                const isEditingSession = historyEditingId === session.id;
                const isBusySession = historyActionSessionId === session.id;
                const isLockedRemoteSession =
                  isRemoteEmployee && isActiveSession && isConversationRunning;

                return (
                  <div
                    key={session.id}
                    className={
                      isActiveSession
                        ? `history-item ${session.status || ""} active-session`.trim()
                        : `history-item ${session.status || ""}`.trim()
                    }
                  >
                    <button
                      type="button"
                      className="history-item-main"
                      onClick={() => onSelectHistory(session)}
                    >
                      <div className="history-time">
                        {new Date(
                          session.updatedAt || session.createdAt || new Date().toISOString(),
                        ).toLocaleString("zh-CN")}
                      </div>
                      {isEditingSession ? (
                        <input
                          autoFocus
                          className="history-title-input"
                          value={historyDraftTitle}
                          onChange={(event) => onDraftTitleChange(event.target.value)}
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              onSubmitHistoryRename(session);
                            }
                            if (event.key === "Escape") {
                              event.preventDefault();
                              onCancelHistoryRename();
                            }
                          }}
                          placeholder="请输入会话名称"
                        />
                      ) : (
                        <div className="history-title">{session.title}</div>
                      )}
                    </button>
                    <div className="history-item-actions">
                      {isEditingSession ? (
                        <>
                          <button
                            type="button"
                            className="history-item-action confirm"
                            onClick={() => onSubmitHistoryRename(session)}
                            disabled={isBusySession}
                            title="保存会话名称"
                          >
                            <i className={isBusySession ? "fas fa-spinner fa-spin" : "fas fa-check"} />
                          </button>
                          <button
                            type="button"
                            className="history-item-action"
                            onClick={onCancelHistoryRename}
                            disabled={isBusySession}
                            title="取消编辑"
                          >
                            <i className="fas fa-xmark" />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="history-item-action"
                            onClick={() => onStartHistoryRename(session)}
                            disabled={isBusySession || isLockedRemoteSession}
                            title={isLockedRemoteSession ? "当前会话处理中，暂不可编辑" : "编辑会话名称"}
                          >
                            <i className="fas fa-pen" />
                          </button>
                          <button
                            type="button"
                            className="history-item-action delete"
                            onClick={() => onDeleteHistorySession(session)}
                            disabled={isBusySession || isLockedRemoteSession}
                            title={isLockedRemoteSession ? "当前会话处理中，暂不可删除" : "删除会话"}
                          >
                            <i className={isBusySession ? "fas fa-spinner fa-spin" : "fas fa-trash-can"} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="history-empty">
              <i className="fas fa-clock-rotate-left" />
              <p>当前暂无已处理任务</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function DashboardHistoryModal({
  open,
  employeeName,
  loading,
  error,
  sessions,
  onClose,
  onSelect,
}: {
  open: boolean;
  employeeName: string;
  loading: boolean;
  error: string;
  sessions: SessionRecord[];
  onClose: () => void;
  onSelect: (session: SessionRecord) => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="history-modal show" onClick={onClose}>
      <div className="history-content" onClick={(event) => event.stopPropagation()}>
        <div className="history-header">
          <h3>
            <i className="fas fa-history" /> {employeeName || "数字员工"}已处理任务
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body">
          {loading ? (
            <div className="history-empty">
              <i className="fas fa-spinner fa-spin" />
              <p>正在加载已处理任务...</p>
            </div>
          ) : error ? (
            <div className="history-empty">
              <i className="fas fa-triangle-exclamation" />
              <p>{error}</p>
            </div>
          ) : sessions.length ? (
            <div className="history-timeline">
              {sessions.map((session) => (
                <div key={session.id} className={`history-item ${session.status || ""}`.trim()}>
                  <button
                    type="button"
                    className="history-item-main"
                    onClick={() => onSelect(session)}
                  >
                    <div className="history-time">
                      {new Date(
                        session.updatedAt || session.createdAt || new Date().toISOString(),
                      ).toLocaleString("zh-CN")}
                    </div>
                    <div className="history-title">{session.title}</div>
                    {session.detail ? <div className="history-detail">{session.detail}</div> : null}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="history-empty">
              <i className="fas fa-clock-rotate-left" />
              <p>当前暂无已处理任务</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ExecutionHistoryModal({
  open,
  title,
  items,
  onClose,
}: {
  open: boolean;
  title: string;
  items: ExecutionRecord[];
  onClose: () => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="history-modal show" onClick={onClose}>
      <div className="history-content" onClick={(event) => event.stopPropagation()}>
        <div className="history-header">
          <h3>
            <i className="fas fa-history" /> {title}
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body">
          <div className="history-timeline">
            {items.map((item) => (
              <div key={item.id} className={`history-item ${item.status}`}>
                <div className="history-time">{item.time}</div>
                <div className="history-title">{item.title}</div>
                <div className="history-detail">{item.detail}</div>
                <div className="history-agent-tag">
                  <i className={`fas ${item.agentIcon}`} />
                  {item.agent}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function DisposalConfirmModal({
  action,
  submitting,
  onCancel,
  onConfirm,
}: {
  action: any;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!action) {
    return null;
  }

  const isAlarmWorkorderProposal = Boolean(action?.proposalId);
  const countdownText = action?.expiresInSeconds ? `（${action.expiresInSeconds}s 内未确认将自动取消）` : "";

  return (
    <div className="history-modal show" onClick={onCancel}>
      <div
        className="history-content disposal-confirm-content"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-triangle-exclamation" /> {isAlarmWorkorderProposal ? "确认创建故障工单" : "确认执行慢SQL处置"}
          </h3>
          <button className="history-close" onClick={onCancel}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body disposal-confirm-body">
          <div className="disposal-confirm-alert">
            {isAlarmWorkorderProposal ? (
              <>
                当前告警分析已完成，可基于分析结论创建故障工单。{countdownText}
              </>
            ) : (
              <>
                即将对根因工单
                <strong>{` ${action.operation.rootCauseWorkorderNo} `}</strong>
                执行慢SQL终止动作。该动作会中断当前异常会话，适合用于演示环境串联处置流程。
              </>
            )}
          </div>
          <div className="disposal-confirm-grid">
            {isAlarmWorkorderProposal ? (
              <>
                <div>
                  <span>告警标题</span>
                  <strong>{action.title || "告警分析结果"}</strong>
                </div>
                <div>
                  <span>告警编号</span>
                  <strong>{action.alarmId || "未提供"}</strong>
                </div>
                <div>
                  <span>设备</span>
                  <strong>{action.deviceName || "未提供"}</strong>
                </div>
                <div>
                  <span>IP</span>
                  <strong>{action.manageIp || "未提供"}</strong>
                </div>
                <div>
                  <span>告警时间</span>
                  <strong>{action.eventTime || "未提供"}</strong>
                </div>
                <div>
                  <span>根因摘要</span>
                  <strong>{action.rootCauseSummary || action.summary || "未提供"}</strong>
                </div>
              </>
            ) : (
              <>
                <div>
                  <span>来源工单</span>
                  <strong>{action.operation.sourceWorkorderNo}</strong>
                </div>
                <div>
                  <span>根因工单</span>
                  <strong>{action.operation.rootCauseWorkorderNo}</strong>
                </div>
                <div>
                  <span>SQL_ID</span>
                  <strong>{action.operation.sqlId}</strong>
                </div>
                <div>
                  <span>会话ID</span>
                  <strong>{action.operation.sessionId}</strong>
                </div>
                <div>
                  <span>设备</span>
                  <strong>{action.operation.deviceName}</strong>
                </div>
                <div>
                  <span>实例/IP</span>
                  <strong>{`${action.operation.locateName} / ${action.operation.manageIp}`}</strong>
                </div>
                <div>
                  <span>处置对象</span>
                  <strong>
                    {action.operation.targetSummary || "数据库核心业务慢 SQL 会话"}
                  </strong>
                </div>
              </>
            )}
          </div>
          <div className="disposal-confirm-actions">
            <button
              className="alarm-workorder-action"
              disabled={submitting}
              onClick={onCancel}
            >
              取消
            </button>
            <button
              className="alarm-workorder-action primary"
              disabled={submitting}
              onClick={onConfirm}
            >
              <i
                className={`fas ${
                  submitting ? "fa-spinner fa-spin" : "fa-bolt"
                }`}
              />{" "}
              {submitting ? (isAlarmWorkorderProposal ? "创建中..." : "执行中...") : (isAlarmWorkorderProposal ? "确认创建" : "确认执行")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
