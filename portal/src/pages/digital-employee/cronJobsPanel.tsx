import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cronJobsApi,
  type CronDispatchTargetItem,
  type CronJobExecutionRecord,
  type CronJobRequest,
  type CronJobSpec,
  type CronJobState,
} from "../../api/cronJobs";
import { portalGatewayAgentId } from "../../config/portalBranding";
import "./cronJobsPanel.css";

type JobFilter = "all" | "running" | "stopped";
type CronType = "hourly" | "daily" | "weekly" | "custom";
type TaskType = "agent" | "text";
type DispatchMode = "final" | "stream";
type ScheduleType = "cron" | "once";
type RepeatEndType = "never" | "until" | "count";
type DisplayStatusKey = "running" | "stopped";
type DisplayTone = "green" | "amber" | "red" | "slate";

type CronParts = {
  type: CronType;
  hour?: number;
  minute?: number;
  daysOfWeek?: string[];
  rawCron?: string;
};

type CronJobFormState = {
  id: string;
  name: string;
  enabled: boolean;
  saveResultToInbox: boolean;
  scheduleType: ScheduleType;
  taskType: TaskType;
  content: string;
  requestInputJson: string;
  channel: string;
  targetUser: string;
  targetSession: string;
  mode: DispatchMode;
  shareSession: boolean;
  timezone: string;
  cronType: CronType;
  hour: number;
  minute: number;
  daysOfWeek: string[];
  customCron: string;
  onceRunAt: string;
  onceRepeatEnabled: boolean;
  onceRepeatEveryDays: number;
  onceRepeatEndType: RepeatEndType;
  onceRepeatUntil: string;
  onceRepeatCount: number;
  maxConcurrency: number;
  timeoutSeconds: number;
  misfireGraceSeconds: number;
};

type DisplayStatus = {
  key: DisplayStatusKey;
  tone: DisplayTone;
  label: string;
  helper: string;
  isError: boolean;
};

type JobRecord = {
  job: CronJobSpec;
  state: CronJobState;
  status: DisplayStatus;
};

type CronJobsTableSectionProps = {
  loading: boolean;
  filteredJobs: JobRecord[];
  filter: JobFilter;
  actionJobId: string;
  onRunNow: (job: CronJobSpec) => void;
  onToggleSchedule: (record: JobRecord) => void;
  onEdit: (job: CronJobSpec) => void;
  onDelete: (job: CronJobSpec) => void;
  onViewHistory: (record: JobRecord) => void;
};

type CronJobModalProps = {
  editingJob: CronJobSpec | null;
  submitting: boolean;
  dispatchTargets: CronDispatchTargetItem[];
  dispatchChannels: string[];
  onClose: () => void;
  onSubmit: (payload: CronJobSpec, editingJob: CronJobSpec | null) => Promise<void>;
};

const FILTER_OPTIONS: Array<{ id: JobFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "running", label: "已启用" },
  { id: "stopped", label: "已禁用" },
];

const ORDERED_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DAY_LABELS: Record<string, string> = {
  mon: "周一",
  tue: "周二",
  wed: "周三",
  thu: "周四",
  fri: "周五",
  sat: "周六",
  sun: "周日",
};
const REPEAT_END_OPTIONS: Array<{ id: RepeatEndType; label: string }> = [
  { id: "never", label: "永不结束" },
  { id: "until", label: "截止日期" },
  { id: "count", label: "执行次数" },
];
const INTEGER_RE = /^\d+$/;
const CRON_RE = /^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$/;
const DAY_NAME_SET = new Set(ORDERED_DAYS);

const TIMEZONE_LIST = [
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Toronto",
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Moscow",
  "Asia/Dubai",
  "Asia/Jakarta",
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Asia/Seoul",
  "Australia/Sydney",
  "Australia/Melbourne",
  "Pacific/Auckland",
];

function getTimezoneLabel(tz: string): string {
  try {
    const parts = new Intl.DateTimeFormat("zh-CN", { timeZone: tz, timeZoneName: "long" }).formatToParts(new Date());
    const name = parts.find((p) => p.type === "timeZoneName")?.value || tz;
    const offset = new Intl.DateTimeFormat("en", { timeZone: tz, timeZoneName: "shortOffset" }).formatToParts(new Date());
    const gmt = offset.find((p) => p.type === "timeZoneName")?.value || "";
    return `${name} (${gmt}, ${tz})`;
  } catch {
    return tz;
  }
}

const TIMEZONE_OPTIONS: string[] = TIMEZONE_LIST.map((tz) => getTimezoneLabel(tz));
const TIMEZONE_VALUE_MAP: Record<string, string> = {};
TIMEZONE_LIST.forEach((tz, i) => { TIMEZONE_VALUE_MAP[TIMEZONE_OPTIONS[i]] = tz; });
const TIMEZONE_LABEL_MAP: Record<string, string> = {};
TIMEZONE_LIST.forEach((tz, i) => { TIMEZONE_LABEL_MAP[tz] = TIMEZONE_OPTIONS[i]; });

const NUM_TO_NAME: Record<string, (typeof ORDERED_DAYS)[number]> = {
  "0": "sun",
  "1": "mon",
  "2": "tue",
  "3": "wed",
  "4": "thu",
  "5": "fri",
  "6": "sat",
  "7": "sun",
};

function getBrowserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function getDefaultRunAt() {
  const d = new Date(Date.now() + 3600_000);
  d.setMinutes(0, 0, 0);
  return d.toISOString().slice(0, 16);
}

function createDefaultFormState(): CronJobFormState {
  return {
    id: "",
    name: "",
    enabled: false,
    saveResultToInbox: true,
    scheduleType: "cron",
    taskType: "agent",
    content: "",
    requestInputJson: "",
    channel: "console",
    targetUser: "",
    targetSession: "",
    mode: "final",
    shareSession: true,
    timezone: getBrowserTimezone(),
    cronType: "daily",
    hour: 9,
    minute: 0,
    daysOfWeek: ["mon"],
    customCron: "0 9 * * *",
    onceRunAt: getDefaultRunAt(),
    onceRepeatEnabled: false,
    onceRepeatEveryDays: 1,
    onceRepeatEndType: "never",
    onceRepeatUntil: "",
    onceRepeatCount: 2,
    maxConcurrency: 1,
    timeoutSeconds: 120,
    misfireGraceSeconds: 60,
  };
}

function parsePlainCronNumber(value: string, min: number, max: number): number | null {
  if (!INTEGER_RE.test(value)) {
    return null;
  }

  const parsed = Number(value);
  if (parsed < min || parsed > max) {
    return null;
  }

  return parsed;
}

function isDayName(value: string): value is (typeof ORDERED_DAYS)[number] {
  return DAY_NAME_SET.has(value as (typeof ORDERED_DAYS)[number]);
}

function parseDaysOfWeek(dayOfWeek: string): string[] {
  const days: Array<(typeof ORDERED_DAYS)[number]> = [];
  const parts = dayOfWeek.split(",");

  for (const part of parts) {
    const trimmed = part.trim().toLowerCase();

    if (!trimmed) {
      return [];
    }

    if (isDayName(trimmed)) {
      if (!days.includes(trimmed)) {
        days.push(trimmed);
      }
      continue;
    }

    if (trimmed.includes("-")) {
      const rangeParts = trimmed.split("-");
      if (rangeParts.length !== 2) {
        return [];
      }

      const startName = NUM_TO_NAME[rangeParts[0]] || rangeParts[0];
      const endName = NUM_TO_NAME[rangeParts[1]] || rangeParts[1];
      if (!isDayName(startName) || !isDayName(endName)) {
        return [];
      }

      const startIndex = ORDERED_DAYS.indexOf(startName);
      const endIndex = ORDERED_DAYS.indexOf(endName);
      if (startIndex === -1 || endIndex === -1 || startIndex > endIndex) {
        return [];
      }

      for (let index = startIndex; index <= endIndex; index += 1) {
        if (!days.includes(ORDERED_DAYS[index])) {
          days.push(ORDERED_DAYS[index]);
        }
      }
      continue;
    }

    const normalized = NUM_TO_NAME[trimmed];
    if (!normalized) {
      return [];
    }
    if (!days.includes(normalized)) {
      days.push(normalized);
    }
  }

  return days;
}

function serializeDaysOfWeek(daysOfWeek?: string[]) {
  const selectedDays = ORDERED_DAYS.filter((day) => daysOfWeek?.includes(day));
  if (!selectedDays.length) {
    return "mon";
  }

  const segments: string[] = [];
  let rangeStart = selectedDays[0];
  let previousDay = selectedDays[0];

  for (let index = 1; index <= selectedDays.length; index += 1) {
    const currentDay = selectedDays[index];
    const isContiguous =
      currentDay !== undefined
      && ORDERED_DAYS.indexOf(currentDay) === ORDERED_DAYS.indexOf(previousDay) + 1;

    if (isContiguous) {
      previousDay = currentDay;
      continue;
    }

    if (rangeStart === previousDay) {
      segments.push(rangeStart);
    } else {
      segments.push(`${rangeStart}-${previousDay}`);
    }

    rangeStart = currentDay;
    previousDay = currentDay ?? previousDay;
  }

  return segments.join(",");
}

function parseCron(cron: string): CronParts {
  const trimmed = String(cron || "").trim();
  if (!trimmed) {
    return { type: "daily", hour: 9, minute: 0 };
  }

  const match = trimmed.match(CRON_RE);
  if (!match) {
    return { type: "custom", rawCron: trimmed };
  }

  const [, minute, hour, dayOfMonth, month, dayOfWeek] = match;

  if (
    hour === "*"
    && dayOfMonth === "*"
    && month === "*"
    && dayOfWeek === "*"
    && minute === "0"
  ) {
    return { type: "hourly", minute: 0 };
  }

  if (dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
    const parsedHour = parsePlainCronNumber(hour, 0, 23);
    const parsedMinute = parsePlainCronNumber(minute, 0, 59);
    if (parsedHour !== null && parsedMinute !== null) {
      return { type: "daily", hour: parsedHour, minute: parsedMinute };
    }
  }

  if (dayOfMonth === "*" && month === "*" && dayOfWeek !== "*") {
    const parsedHour = parsePlainCronNumber(hour, 0, 23);
    const parsedMinute = parsePlainCronNumber(minute, 0, 59);
    const daysOfWeek = parseDaysOfWeek(dayOfWeek);
    if (parsedHour !== null && parsedMinute !== null && daysOfWeek.length) {
      return {
        type: "weekly",
        hour: parsedHour,
        minute: parsedMinute,
        daysOfWeek,
      };
    }
  }

  return { type: "custom", rawCron: trimmed };
}

function serializeCron(parts: CronParts): string {
  switch (parts.type) {
    case "hourly":
      return "0 * * * *";
    case "daily":
      return `${parts.minute ?? 0} ${parts.hour ?? 9} * * *`;
    case "weekly":
      return `${parts.minute ?? 0} ${parts.hour ?? 9} * * ${serializeDaysOfWeek(parts.daysOfWeek)}`;
    case "custom":
      return String(parts.rawCron || "0 9 * * *").trim();
    default:
      return "0 9 * * *";
  }
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "-";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function extractTextFromUnknown(value: unknown): string[] {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }

  if (Array.isArray(value)) {
    return value.flatMap((item) => extractTextFromUnknown(item));
  }

  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.text === "string") {
      const trimmed = record.text.trim();
      return trimmed ? [trimmed] : [];
    }
    if ("content" in record) {
      return extractTextFromUnknown(record.content);
    }
  }

  return [];
}

function extractPromptFromRequest(request?: CronJobRequest) {
  return extractTextFromUnknown(request?.input).join("\n").trim();
}

function buildAgentRequest(
  prompt: string,
  targetUser: string,
  targetSession: string,
  sourceRequest?: CronJobRequest,
): CronJobRequest {
  return {
    ...(sourceRequest || {}),
    input: [
      {
        role: "user",
        type: "message",
        content: [
          {
            type: "text",
            text: prompt,
          },
        ],
      },
    ],
    user_id: targetUser,
    session_id: targetSession,
  };
}

function createFormStateFromJob(job: CronJobSpec): CronJobFormState {
  const isOnce = job.schedule?.type === "once";
  const schedule = isOnce ? { type: "daily" as CronType, hour: 9, minute: 0 } : parseCron(job.schedule?.cron || "0 9 * * *");
  const requestInput = job.request?.input;
  let requestInputJson = "";
  if (requestInput !== undefined && requestInput !== null) {
    requestInputJson = typeof requestInput === "string" ? requestInput : JSON.stringify(requestInput, null, 2);
  }
  return {
    id: job.id,
    name: job.name || "",
    enabled: job.enabled !== false,
    saveResultToInbox: job.save_result_to_inbox !== false,
    scheduleType: isOnce ? "once" : "cron",
    taskType: job.task_type === "text" ? "text" : "agent",
    content: job.task_type === "text" ? String(job.text || "") : extractPromptFromRequest(job.request),
    requestInputJson,
    channel: job.dispatch?.channel || "console",
    targetUser: job.dispatch?.target?.user_id || "",
    targetSession: job.dispatch?.target?.session_id || "",
    mode: job.dispatch?.mode === "stream" ? "stream" : "final",
    shareSession: job.runtime?.share_session !== false,
    timezone: job.schedule?.timezone || getBrowserTimezone(),
    cronType: schedule.type,
    hour: schedule.hour ?? 9,
    minute: schedule.minute ?? 0,
    daysOfWeek: schedule.daysOfWeek || ["mon"],
    customCron: schedule.rawCron || job.schedule?.cron || "0 9 * * *",
    onceRunAt: (job.schedule as any)?.run_at || getDefaultRunAt(),
    onceRepeatEnabled: Boolean((job.schedule as any)?.repeat_every_days),
    onceRepeatEveryDays: Number((job.schedule as any)?.repeat_every_days || 1),
    onceRepeatEndType: (job.schedule as any)?.repeat_end_type || "never",
    onceRepeatUntil: (job.schedule as any)?.repeat_until || "",
    onceRepeatCount: Number((job.schedule as any)?.repeat_count || 2),
    maxConcurrency: Math.max(1, Number(job.runtime?.max_concurrency || 1)),
    timeoutSeconds: Math.max(1, Number(job.runtime?.timeout_seconds || 120)),
    misfireGraceSeconds: Math.max(0, Number(job.runtime?.misfire_grace_seconds || 60)),
  };
}

function buildPayloadFromForm(form: CronJobFormState, sourceJob: CronJobSpec | null): CronJobSpec {
  const content = form.content.trim();
  const targetUser = form.targetUser.trim();
  const targetSession = form.targetSession.trim();

  let schedule: CronJobSpec["schedule"];
  if (form.scheduleType === "once") {
    schedule = {
      type: "once",
      run_at: form.onceRunAt,
      timezone: form.timezone.trim() || "UTC",
      ...(form.onceRepeatEnabled ? {
        repeat_every_days: form.onceRepeatEveryDays,
        repeat_end_type: form.onceRepeatEndType,
        ...(form.onceRepeatEndType === "until" ? { repeat_until: form.onceRepeatUntil } : {}),
        ...(form.onceRepeatEndType === "count" ? { repeat_count: form.onceRepeatCount } : {}),
      } : {}),
    };
  } else {
    const cron = serializeCron({
      type: form.cronType,
      hour: form.hour,
      minute: form.minute,
      daysOfWeek: form.daysOfWeek,
      rawCron: form.customCron,
    });
    schedule = {
      type: "cron",
      cron,
      timezone: form.timezone.trim() || "UTC",
    };
  }

  let request: CronJobRequest | undefined;
  if (form.taskType === "agent") {
    if (form.requestInputJson.trim()) {
      try {
        const parsed = JSON.parse(form.requestInputJson.trim());
        request = {
          ...(sourceJob?.request || {}),
          input: parsed,
          user_id: targetUser,
          session_id: targetSession,
        };
      } catch {
        request = buildAgentRequest(content, targetUser, targetSession, sourceJob?.request);
      }
    } else {
      request = buildAgentRequest(content, targetUser, targetSession, sourceJob?.request);
    }
  }

  return {
    id: sourceJob?.id || form.id || "",
    name: form.name.trim(),
    enabled: form.enabled,
    save_result_to_inbox: form.saveResultToInbox,
    schedule,
    task_type: form.taskType,
    text: form.taskType === "text" ? content : undefined,
    request,
    dispatch: {
      type: "channel",
      channel: form.channel.trim(),
      target: {
        user_id: targetUser,
        session_id: targetSession,
      },
      mode: form.mode,
      meta: sourceJob?.dispatch?.meta || {},
    },
    runtime: {
      share_session: form.shareSession,
      max_concurrency: Math.max(1, Number(form.maxConcurrency || 1)),
      timeout_seconds: Math.max(1, Number(form.timeoutSeconds || 120)),
      misfire_grace_seconds: Math.max(0, Number(form.misfireGraceSeconds || 60)),
    },
    meta: sourceJob?.meta || {},
  };
}

function resolveDisplayStatus(job: CronJobSpec, state: CronJobState): DisplayStatus {
  const enabled = job.enabled !== false;

  if (!enabled) {
    return {
      key: "stopped",
      tone: "slate",
      label: "已禁用",
      helper: "不会按照计划自动执行",
      isError: false,
    };
  }

  return {
    key: "running",
    tone: "green",
    label: "已启用",
    helper: "按计划继续调度",
    isError: false,
  };
}

function matchesFilter(record: JobRecord, filter: JobFilter) {
  if (filter === "all") {
    return true;
  }
  return record.status.key === filter;
}

function formatTaskType(job: CronJobSpec) {
  return job.task_type === "text" ? "固定消息" : "Agent 提问";
}

function formatTarget(job: CronJobSpec) {
  const channel = job.dispatch?.channel || "-";
  const targetUser = job.dispatch?.target?.user_id || "-";
  const targetSession = job.dispatch?.target?.session_id || "-";
  return `${channel} / ${targetUser} / ${targetSession}`;
}

function getCronSummary(cron: string) {
  const parsed = parseCron(cron);
  if (parsed.type === "hourly") {
    return "每小时整点";
  }
  if (parsed.type === "daily") {
    return `每天 ${String(parsed.hour ?? 0).padStart(2, "0")}:${String(parsed.minute ?? 0).padStart(2, "0")}`;
  }
  if (parsed.type === "weekly") {
    const days = (parsed.daysOfWeek || []).map((day) => DAY_LABELS[day] || day).join("、");
    return `每周 ${days} ${String(parsed.hour ?? 0).padStart(2, "0")}:${String(parsed.minute ?? 0).padStart(2, "0")}`;
  }
  return cron;
}

const CronJobsTableSection = memo(function CronJobsTableSection({
  loading,
  filteredJobs,
  filter,
  actionJobId,
  onRunNow,
  onToggleSchedule,
  onEdit,
  onDelete,
  onViewHistory,
}: CronJobsTableSectionProps) {
  const [moreMenuId, setMoreMenuId] = useState<string | null>(null);
  const [moreMenuPos, setMoreMenuPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const moreMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!moreMenuId) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) {
        setMoreMenuId(null);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [moreMenuId]);

  const handleMoreClick = (jobId: string, e: React.MouseEvent<HTMLButtonElement>) => {
    if (moreMenuId === jobId) {
      setMoreMenuId(null);
      return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    setMoreMenuPos({ top: rect.bottom + 4, left: rect.right });
    setMoreMenuId(jobId);
  };

  return (
    <section className="cron-jobs-table-shell">
      {loading ? (
        <div className="cron-jobs-empty-state">
          <i className="fas fa-spinner fa-spin" />
          <p>正在加载定时任务...</p>
        </div>
      ) : filteredJobs.length ? (
        <div className="cron-jobs-table-wrap">
          <table className="cron-jobs-table">
            <thead>
              <tr>
                <th className="col-fixed-left">任务名称</th>
                <th>状态</th>
                <th>调度类型</th>
                <th>调度计划</th>
                <th>时区</th>
                <th>任务类型</th>
                <th>消息内容</th>
                <th>投递通道</th>
                <th>目标用户</th>
                <th>目标会话</th>
                <th>发送模式</th>
                <th>下次执行</th>
                <th>上次执行</th>
                <th className="col-fixed-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map((record) => {
                const { job, state, status } = record;
                const isBusy = actionJobId === job.id;
                const scheduleLabel = job.schedule?.type === "once" ? "日程任务" : "循环任务";
                const cronDisplay = job.schedule?.type === "once"
                  ? (job.schedule as any)?.run_at ? new Date((job.schedule as any).run_at).toLocaleString("zh-CN") : "-"
                  : getCronSummary(job.schedule?.cron || "") || job.schedule?.cron || "-";

                return (
                  <tr key={job.id}>
                    <td className="col-fixed-left">
                      <div className="cron-jobs-name-cell">
                        <strong>{job.name}</strong>
                        <span>{job.id}</span>
                      </div>
                    </td>
                    <td>
                      <span className={`cron-jobs-status-badge tone-${status.tone}`}>
                        {status.label}
                      </span>
                    </td>
                    <td>{scheduleLabel}</td>
                    <td>
                      <span className="cron-jobs-cron-text" title={job.schedule?.cron || ""}>{cronDisplay}</span>
                    </td>
                    <td>{job.schedule?.timezone || "UTC"}</td>
                    <td>
                      <span className="cron-jobs-pill">{formatTaskType(job)}</span>
                    </td>
                    <td>
                      <span className="cron-jobs-text-ellipsis" title={job.text || ""}>{job.text || "-"}</span>
                    </td>
                    <td>{job.dispatch?.channel || "-"}</td>
                    <td>{job.dispatch?.target?.user_id || "-"}</td>
                    <td>{job.dispatch?.target?.session_id || "-"}</td>
                    <td>{job.dispatch?.mode === "stream" ? "流式结果" : job.dispatch?.mode === "final" ? "仅最终结果" : "-"}</td>
                    <td>{formatDateTime(state.next_run_at)}</td>
                    <td>{formatDateTime(state.last_run_at)}</td>
                    <td className="col-fixed-right">
                      <div className="cron-jobs-actions">
                        <button
                          type="button"
                          className="cron-jobs-action-btn"
                          onClick={() => onToggleSchedule(record)}
                          disabled={isBusy}
                        >
                          {job.enabled === false ? "启用" : "停用"}
                        </button>
                        <button
                          type="button"
                          className="cron-jobs-action-btn primary"
                          onClick={() => onRunNow(job)}
                          disabled={isBusy}
                        >
                          执行
                        </button>
                        <button
                          type="button"
                          className="cron-jobs-action-btn"
                          onClick={() => onViewHistory(record)}
                          disabled={isBusy}
                        >
                          历史
                        </button>
                        <button
                          type="button"
                          className="cron-jobs-action-btn more-trigger"
                          disabled={isBusy}
                          onClick={(e) => handleMoreClick(job.id, e)}
                        >
                          <i className="fas fa-ellipsis" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {moreMenuId && (
            <div
              ref={moreMenuRef}
              className="cron-jobs-more-dropdown visible"
              style={{ top: moreMenuPos.top, left: moreMenuPos.left }}
            >
              <button type="button" onClick={() => { onEdit(filteredJobs.find(j => j.id === moreMenuId)!); setMoreMenuId(null); }} disabled={filteredJobs.find(j => j.id === moreMenuId)?.enabled}>编辑</button>
              <button type="button" className="danger" onClick={() => { onDelete(filteredJobs.find(j => j.id === moreMenuId)!); setMoreMenuId(null); }} disabled={filteredJobs.find(j => j.id === moreMenuId)?.enabled}>删除</button>
            </div>
          )}
        </div>
      ) : (
        <div className="cron-jobs-empty-state">
          <i className="fas fa-clock" />
          <p>{filter === "all" ? "当前还没有定时任务，先创建一个任务。" : "当前筛选条件下没有匹配的任务。"}</p>
        </div>
      )}
    </section>
  );
});

/* ---------- Custom Select (no search) ---------- */
interface CronSelectOption {
  value: string;
  label: string;
}

interface CronSelectProps {
  value: string;
  options: CronSelectOption[];
  onChange: (value: string) => void;
}

function CronSelect({ value, options, onChange }: CronSelectProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const activeLabel = options.find((o) => o.value === value)?.label || value;

  return (
    <div className="cron-searchable-select" ref={containerRef}>
      <button
        type="button"
        className={`cron-searchable-trigger ${open ? "active" : ""}`}
        onClick={() => setOpen(!open)}
      >
        <span>{activeLabel}</span>
        <i className={`fas fa-chevron-${open ? "up" : "down"}`} />
      </button>
      {open ? (
        <div className="cron-searchable-panel">
          <div className="cron-searchable-list">
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`cron-searchable-item ${opt.value === value ? "active" : ""}`}
                onClick={() => { onChange(opt.value); setOpen(false); }}
              >
                <span>{opt.label}</span>
                {opt.value === value ? <i className="fas fa-check" /> : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ---------- Searchable Select Component ---------- */
interface CronSearchableSelectProps {
  value: string;
  options: string[];
  placeholder?: string;
  allowCustom?: boolean;
  onChange: (value: string) => void;
}

function CronSearchableSelect({ value, options, placeholder, allowCustom = true, onChange }: CronSearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const filtered = useMemo(() => {
    if (!search) return options;
    const q = search.toLowerCase();
    return options.filter((o) => o.toLowerCase().includes(q));
  }, [options, search]);

  const handleSelect = (v: string) => {
    onChange(v);
    setOpen(false);
    setSearch("");
  };

  return (
    <div className="cron-searchable-select" ref={containerRef}>
      <button
        type="button"
        className={`cron-searchable-trigger ${open ? "active" : ""}`}
        onClick={() => setOpen(!open)}
      >
        <span className={value ? "" : "placeholder"}>{value || placeholder || "请选择"}</span>
        <i className={`fas fa-chevron-${open ? "up" : "down"}`} />
      </button>
      {open ? (
        <div className="cron-searchable-panel">
          <div className="cron-searchable-search">
            <i className="fas fa-magnifying-glass" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索..."
              onKeyDown={(e) => {
                if (e.key === "Enter" && allowCustom && search && !filtered.includes(search)) {
                  handleSelect(search);
                }
              }}
            />
          </div>
          <div className="cron-searchable-list">
            {filtered.length === 0 ? (
              <div className="cron-searchable-empty">
                {allowCustom && search ? (
                  <button type="button" className="cron-searchable-custom" onClick={() => handleSelect(search)}>
                    使用 &quot;{search}&quot;
                  </button>
                ) : (
                  <span>无匹配项</span>
                )}
              </div>
            ) : (
              filtered.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  className={`cron-searchable-item ${opt === value ? "active" : ""}`}
                  onClick={() => handleSelect(opt)}
                >
                  <span>{opt}</span>
                  {opt === value ? <i className="fas fa-check" /> : null}
                </button>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

const CronJobModal = memo(function CronJobModal({ editingJob, submitting, dispatchTargets, dispatchChannels, onClose, onSubmit }: CronJobModalProps) {
  const [formState, setFormState] = useState<CronJobFormState>(() =>
    editingJob ? createFormStateFromJob(editingJob) : createDefaultFormState(),
  );
  const [formError, setFormError] = useState("");
  const [visibleTooltip, setVisibleTooltip] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });

  const renderLabel = (text: string, options?: { required?: boolean; tooltip?: string; tooltipId?: string }) => (
    <span className="cron-jobs-field-label">
      {text}
      {options?.required ? <em className="cron-jobs-required">*</em> : null}
      {options?.tooltip ? (
        <span
          className="cron-jobs-tooltip-trigger"
          onMouseEnter={(e) => {
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
            setTooltipPos({ top: rect.top - 8, left: rect.left + rect.width / 2 });
            setVisibleTooltip(options.tooltipId || text);
          }}
          onMouseLeave={() => setVisibleTooltip(null)}
        >
          <i className="fas fa-circle-info" />
          {visibleTooltip === (options.tooltipId || text) ? (
            <span
              className="cron-jobs-tooltip-bubble"
              style={{ top: tooltipPos.top, left: tooltipPos.left }}
            >
              {options.tooltip}
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );

  const updateForm = useCallback(<K extends keyof CronJobFormState>(key: K, value: CronJobFormState[K]) => {
    setFormState((prev) => ({ ...prev, [key]: value }));
  }, []);

  const channelOptions = useMemo(() => {
    const set = new Set(dispatchChannels);
    if (formState.channel.trim()) set.add(formState.channel.trim());
    return [...set].sort();
  }, [dispatchChannels, formState.channel]);

  const userOptions = useMemo(() => {
    const set = new Set<string>();
    dispatchTargets.forEach((item) => {
      if (!formState.channel || item.channel === formState.channel) set.add(item.user_id);
    });
    if (formState.targetUser.trim()) set.add(formState.targetUser.trim());
    return [...set].sort();
  }, [dispatchTargets, formState.channel, formState.targetUser]);

  const sessionOptions = useMemo(() => {
    const set = new Set<string>();
    dispatchTargets.forEach((item) => {
      if ((!formState.channel || item.channel === formState.channel) && (!formState.targetUser || item.user_id === formState.targetUser)) {
        set.add(item.session_id);
      }
    });
    if (formState.targetSession.trim()) set.add(formState.targetSession.trim());
    return [...set].sort();
  }, [dispatchTargets, formState.channel, formState.targetUser, formState.targetSession]);

  const validateForm = () => {
    if (editingJob && !formState.id.trim()) return "任务 ID 异常。";
    if (!formState.name.trim()) return "请输入任务名称。";
    if (!formState.channel.trim()) return "请输入投递通道。";
    if (!formState.targetUser.trim()) return "请输入目标 user_id。";
    if (!formState.targetSession.trim()) return "请输入目标 session_id。";
    if (formState.taskType === "text" && !formState.content.trim()) return "请输入固定消息内容。";
    if (formState.taskType === "agent" && !formState.content.trim() && !formState.requestInputJson.trim()) return "请输入发送给 Agent 的问题或 Request Input。";
    if (formState.scheduleType === "cron") {
      if (!formState.timezone.trim()) return "请输入时区。";
      if (formState.cronType === "weekly" && !formState.daysOfWeek.length) return "请选择至少一个执行星期。";
      const cron = serializeCron({ type: formState.cronType, hour: formState.hour, minute: formState.minute, daysOfWeek: formState.daysOfWeek, rawCron: formState.customCron });
      if (!CRON_RE.test(cron)) return "Cron 表达式必须是 5 段格式，例如 0 9 * * *。";
    }
    if (formState.scheduleType === "once" && !formState.onceRunAt) return "请选择执行时间。";
    if (formState.requestInputJson.trim()) {
      try { JSON.parse(formState.requestInputJson.trim()); } catch { return "Request Input 不是合法的 JSON 格式。"; }
    }
    return "";
  };

  const handleSubmit = async () => {
    const nextFormError = validateForm();
    if (nextFormError) { setFormError(nextFormError); return; }
    setFormError("");
    try {
      await onSubmit(buildPayloadFromForm(formState, editingJob), editingJob);
    } catch (submitError: any) {
      setFormError(submitError?.message || "保存失败，请稍后重试。");
    }
  };

  const [closing, setClosing] = useState(false);

  const handleClose = useCallback(() => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 250);
  }, [onClose]);

  return (
    <div className={`cron-jobs-modal-backdrop ${closing ? "closing" : ""}`} onClick={handleClose}>
      <div className={`cron-jobs-modal ${closing ? "closing" : ""}`} onClick={(event) => event.stopPropagation()}>
        <div className="cron-jobs-modal-header">
          <div className="cron-jobs-modal-heading">
            <h4>{editingJob ? "编辑定时任务" : "新增定时任务"}</h4>
          </div>
          <button type="button" className="cron-jobs-modal-close" onClick={handleClose}>
            <i className="fas fa-xmark" />
          </button>
        </div>

        <div className="cron-jobs-modal-body">
          {editingJob ? (
            <label className="cron-jobs-field">
              {renderLabel("任务 ID", { tooltip: "任务的唯一标识符（UUID）由系统在创建时自动分配，不可修改。" })}
              <input value={formState.id} disabled />
            </label>
          ) : null}

          <label className="cron-jobs-field">
            {renderLabel("任务名称", { required: true, tooltip: "任务的友好名称，便于识别。" })}
            <input
              value={formState.name}
              onChange={(event) => updateForm("name", event.target.value)}
              placeholder="例如：每日巡检总结"
            />
          </label>

          <div className="cron-jobs-form-grid two-columns">
            <label className="cron-jobs-field">
              {renderLabel("启用")}
              <div className="cron-jobs-switch-row">
                <button
                  type="button"
                  className={`cron-jobs-switch ${formState.enabled ? "active" : ""}`}
                  onClick={() => updateForm("enabled", !formState.enabled)}
                  aria-pressed={formState.enabled}
                >
                  <span className="cron-jobs-switch-thumb" />
                </button>
                <span className="cron-jobs-switch-label">{formState.enabled ? "保存后立即生效" : "保存后暂不启用"}</span>
              </div>
            </label>
            <label className="cron-jobs-field">
              {renderLabel("结果存入收件箱", { tooltip: "开启后，任务执行成功且投递成功时，会将结果写入收件箱；若投递失败，系统会自动兜底写入收件箱。" })}
              <div className="cron-jobs-switch-row">
                <button
                  type="button"
                  className={`cron-jobs-switch ${formState.saveResultToInbox ? "active" : ""}`}
                  onClick={() => updateForm("saveResultToInbox", !formState.saveResultToInbox)}
                  aria-pressed={formState.saveResultToInbox}
                >
                  <span className="cron-jobs-switch-thumb" />
                </button>
                <span className="cron-jobs-switch-label">{formState.saveResultToInbox ? "已开启" : "未开启"}</span>
              </div>
            </label>
          </div>

          <label className="cron-jobs-field">
            {renderLabel("调度类型", { required: true })}
            <CronSelect
              value={formState.scheduleType}
              options={[
                { value: "cron", label: "循环任务（周期调度）" },
                { value: "once", label: "日程任务（单次执行）" },
              ]}
              onChange={(v) => updateForm("scheduleType", v as ScheduleType)}
            />
          </label>

          {formState.scheduleType === "once" ? (
            <>
              <label className="cron-jobs-field">
                {renderLabel("执行时间", { required: true })}
                <input
                  type="datetime-local"
                  value={formState.onceRunAt}
                  onChange={(event) => updateForm("onceRunAt", event.target.value)}
                />
              </label>
              <label className="cron-jobs-field">
                {renderLabel("重复执行", { tooltip: "从该开始时间按固定天数重复执行" })}
                <div className="cron-jobs-switch-row">
                  <button
                    type="button"
                    className={`cron-jobs-switch ${formState.onceRepeatEnabled ? "active" : ""}`}
                    onClick={() => updateForm("onceRepeatEnabled", !formState.onceRepeatEnabled)}
                    aria-pressed={formState.onceRepeatEnabled}
                  >
                    <span className="cron-jobs-switch-thumb" />
                  </button>
                  <span className="cron-jobs-switch-label">{formState.onceRepeatEnabled ? "已开启" : "未开启"}</span>
                </div>
              </label>
              {formState.onceRepeatEnabled ? (
                <>
                  <label className="cron-jobs-field">
                    {renderLabel("重复频率", { required: true })}
                    <div className="cron-jobs-inline-row">
                      <span>每</span>
                      <input
                        type="number"
                        min={1}
                        value={formState.onceRepeatEveryDays}
                        onChange={(event) => updateForm("onceRepeatEveryDays", Math.max(1, Number(event.target.value)))}
                        style={{ width: 80 }}
                      />
                      <span>天执行一次</span>
                    </div>
                  </label>
                  <label className="cron-jobs-field">
                    {renderLabel("结束条件", { required: true })}
                    <CronSelect
                      value={formState.onceRepeatEndType}
                      options={REPEAT_END_OPTIONS.map((opt) => ({ value: opt.id, label: opt.label }))}
                      onChange={(v) => updateForm("onceRepeatEndType", v as RepeatEndType)}
                    />
                  </label>
                  {formState.onceRepeatEndType === "until" ? (
                    <label className="cron-jobs-field">
                      {renderLabel("截止日期", { required: true })}
                      <input
                        type="datetime-local"
                        value={formState.onceRepeatUntil}
                        onChange={(event) => updateForm("onceRepeatUntil", event.target.value)}
                      />
                    </label>
                  ) : null}
                  {formState.onceRepeatEndType === "count" ? (
                    <label className="cron-jobs-field">
                      {renderLabel("执行次数", { required: true })}
                      <input
                        type="number"
                        min={1}
                        value={formState.onceRepeatCount}
                        onChange={(event) => updateForm("onceRepeatCount", Math.max(1, Number(event.target.value)))}
                      />
                    </label>
                  ) : null}
                </>
              ) : null}
            </>
          ) : (
            <>
              <label className="cron-jobs-field">
                {renderLabel("Cron 周期", { required: true, tooltip: "定义任务执行时间" })}
                <CronSelect
                  value={formState.cronType}
                  options={[
                    { value: "hourly", label: "每小时" },
                    { value: "daily", label: "每天" },
                    { value: "weekly", label: "每周" },
                    { value: "custom", label: "自定义表达式" },
                  ]}
                  onChange={(v) => updateForm("cronType", v as CronType)}
                />
              </label>
              {(formState.cronType === "daily" || formState.cronType === "weekly") ? (
                <div className="cron-jobs-form-grid two-columns">
                  <label className="cron-jobs-field">
                    {renderLabel("小时", { required: true })}
                    <input type="number" min={0} max={23} value={formState.hour} onChange={(event) => updateForm("hour", Number(event.target.value))} />
                  </label>
                  <label className="cron-jobs-field">
                    {renderLabel("分钟", { required: true })}
                    <input type="number" min={0} max={59} value={formState.minute} onChange={(event) => updateForm("minute", Number(event.target.value))} />
                  </label>
                </div>
              ) : null}
              {formState.cronType === "weekly" ? (
                <div className="cron-jobs-field">
                  {renderLabel("执行星期", { required: true })}
                  <div className="cron-jobs-week-grid">
                    {ORDERED_DAYS.map((day) => {
                      const active = formState.daysOfWeek.includes(day);
                      return (
                        <button
                          key={day}
                          type="button"
                          className={active ? "cron-jobs-week-btn active" : "cron-jobs-week-btn"}
                          onClick={() =>
                            updateForm("daysOfWeek", active ? formState.daysOfWeek.filter((item) => item !== day) : [...formState.daysOfWeek, day])
                          }
                        >
                          {DAY_LABELS[day]}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : null}
              {formState.cronType === "custom" ? (
                <label className="cron-jobs-field">
                  {renderLabel("Cron 表达式", { required: true })}
                  <input
                    value={formState.customCron}
                    onChange={(event) => updateForm("customCron", event.target.value)}
                    placeholder="0 9 * * *"
                  />
                  <small>标准 5 段格式：分钟 小时 日 月 星期。<a href="https://crontab.guru/" target="_blank" rel="noopener noreferrer">在线助手 →</a></small>
                </label>
              ) : null}
            </>
          )}

          <label className="cron-jobs-field">
            {renderLabel("时区", { tooltip: "Cron 计划使用的时区。默认：UTC" })}
            <CronSearchableSelect
              value={TIMEZONE_LABEL_MAP[formState.timezone] || formState.timezone}
              options={TIMEZONE_OPTIONS}
              placeholder="Asia/Shanghai"
              allowCustom={true}
              onChange={(v) => updateForm("timezone", TIMEZONE_VALUE_MAP[v] || v)}
            />
          </label>

          <label className="cron-jobs-field">
            {renderLabel("任务类型", { required: true, tooltip: "选择 'text' 用于简单消息任务，选择 'agent' 用于复杂的智能体工作流。" })}
            <CronSelect
              value={formState.taskType}
              options={[
                { value: "agent", label: "Agent 提问" },
                { value: "text", label: "固定消息" },
              ]}
              onChange={(v) => updateForm("taskType", v as TaskType)}
            />
          </label>

          <label className="cron-jobs-field">
            {renderLabel(formState.taskType === "text" ? "消息内容" : "发送给 Agent 的问题", { required: true, tooltip: formState.taskType === "text" ? "简单消息任务：此处为实际的消息正文，任务类型为 text 时必填。" : "发送给 Agent 的问题，任务类型为 agent 时必填（或填写下方 Request Input）。" })}
            <textarea
              rows={3}
              value={formState.content}
              onChange={(event) => updateForm("content", event.target.value)}
              placeholder={formState.taskType === "text" ? "请输入任务执行时要发送的文本" : "请输入要定时发送给 Agent 的问题"}
            />
            <small>{formState.taskType === "text" ? "适合提醒、播报和固定通知内容。" : "建议写清楚任务背景、目标和输出格式。"}</small>
          </label>

          {formState.taskType === "agent" ? (
            <label className="cron-jobs-field">
              {renderLabel("Request Input（JSON）", { tooltip: "JSON 格式的消息内容。这是智能体将接收和处理的内容。若填写将覆盖上方文本问题。" })}
              <textarea
                rows={4}
                value={formState.requestInputJson}
                onChange={(event) => updateForm("requestInputJson", event.target.value)}
                placeholder={'[{"role":"user","content":[{"text":"Hello","type":"text"}]}]'}
                style={{ fontFamily: "monospace", fontSize: 12 }}
              />
              <small>可选。若填写，将覆盖上方的文本问题作为请求体，必须为合法 JSON。</small>
            </label>
          ) : null}

          <label className="cron-jobs-field">
            {renderLabel("投递通道", { required: true, tooltip: "响应将发送到的目标频道（例如：console、discord、dingtalk）。" })}
            <CronSearchableSelect
              value={formState.channel}
              options={channelOptions}
              placeholder="console"
              onChange={(v) => updateForm("channel", v)}
            />
          </label>

          <div className="cron-jobs-form-grid two-columns">
            <label className="cron-jobs-field">
              {renderLabel("目标 user_id", { required: true, tooltip: "在目标频道中接收响应的用户 ID。" })}
              <CronSearchableSelect
                value={formState.targetUser}
                options={userOptions}
                placeholder="admin"
                onChange={(v) => updateForm("targetUser", v)}
              />
            </label>
            <label className="cron-jobs-field">
              {renderLabel("目标 session_id", { required: true, tooltip: "在目标频道中传递响应的会话 ID。" })}
              <CronSearchableSelect
                value={formState.targetSession}
                options={sessionOptions}
                placeholder="default"
                onChange={(v) => updateForm("targetSession", v)}
              />
            </label>
          </div>

          <label className="cron-jobs-field">
            {renderLabel("发送模式", { tooltip: "选择 stream 获取实时响应，或选择 final 仅获取完整响应。" })}
            <CronSelect
              value={formState.mode}
              options={[
                { value: "final", label: "仅最终结果" },
                { value: "stream", label: "流式结果" },
              ]}
              onChange={(v) => updateForm("mode", v as DispatchMode)}
            />
          </label>

          <label className="cron-jobs-field">
            {renderLabel("共享会话", { tooltip: "开启时，与目标用户共用会话。关闭时，每次运行创建独立的会话上下文，互不影响。适用于不需要记忆历史的独立任务。" })}
            <div className="cron-jobs-switch-row">
              <button
                type="button"
                className={`cron-jobs-switch ${formState.shareSession ? "active" : ""}`}
                onClick={() => updateForm("shareSession", !formState.shareSession)}
                aria-pressed={formState.shareSession}
              >
                <span className="cron-jobs-switch-thumb" />
              </button>
              <span className="cron-jobs-switch-label">{formState.shareSession ? "复用同一会话上下文" : "每次执行使用独立会话"}</span>
            </div>
          </label>

          <div className="cron-jobs-form-grid three-columns">
            <label className="cron-jobs-field">
              {renderLabel("最大并发", { tooltip: "此任务可以同时运行的最大数量。默认：1" })}
              <input type="number" min={1} value={formState.maxConcurrency} onChange={(event) => updateForm("maxConcurrency", Math.max(1, Number(event.target.value)))} />
            </label>
            <label className="cron-jobs-field">
              {renderLabel("超时（秒）", { tooltip: "最大执行时间（秒）。超时将终止任务。" })}
              <input type="number" min={1} value={formState.timeoutSeconds} onChange={(event) => updateForm("timeoutSeconds", Math.max(1, Number(event.target.value)))} />
            </label>
            <label className="cron-jobs-field">
              {renderLabel("补偿窗口（秒）", { tooltip: "错过执行的宽限期。如果任务错过计划时间超过此时长，将不会执行。" })}
              <input type="number" min={0} value={formState.misfireGraceSeconds} onChange={(event) => updateForm("misfireGraceSeconds", Math.max(0, Number(event.target.value)))} />
            </label>
          </div>

          {formError ? <div className="cron-jobs-form-error">{formError}</div> : null}
        </div>

        <div className="cron-jobs-modal-footer">
          <button type="button" className="cron-jobs-footer-btn" onClick={onClose} disabled={submitting}>
            取消
          </button>
          <button
            type="button"
            className="cron-jobs-footer-btn primary"
            onClick={() => void handleSubmit()}
            disabled={submitting}
          >
            <i className={`fas ${submitting ? "fa-spinner fa-spin" : "fa-floppy-disk"}`} />
            {editingJob ? "保存修改" : "创建任务"}
          </button>
        </div>
      </div>
    </div>
  );
});

export function CronJobsPanel() {
  const [jobs, setJobs] = useState<CronJobSpec[]>([]);
  const [states, setStates] = useState<Record<string, CronJobState>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [actionJobId, setActionJobId] = useState("");
  const [filter, setFilter] = useState<JobFilter>("all");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<CronJobSpec | null>(null);
  const [dispatchTargets, setDispatchTargets] = useState<CronDispatchTargetItem[]>([]);
  const [dispatchChannels, setDispatchChannels] = useState<string[]>([]);
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [historyJobName, setHistoryJobName] = useState("");
  const [historyRecords, setHistoryRecords] = useState<CronJobExecutionRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timer = window.setTimeout(() => setNotice(""), 2800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const refreshJobs = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const nextJobs = await cronJobsApi.listCronJobs(portalGatewayAgentId);
      const stateEntries = await Promise.all(
        nextJobs.map(async (job) => {
          try {
            const state = await cronJobsApi.getCronJobState(job.id, portalGatewayAgentId);
            return [job.id, state] as const;
          } catch {
            return [job.id, {}] as const;
          }
        }),
      );
      setJobs(nextJobs);
      setStates(Object.fromEntries(stateEntries));
    } catch (loadError: any) {
      setError(loadError?.message || "定时任务加载失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDispatchTargets = useCallback(async () => {
    try {
      const resp = await cronJobsApi.listDispatchTargets(portalGatewayAgentId);
      setDispatchTargets(resp.items || []);
      setDispatchChannels(resp.channels || []);
    } catch {
      // silently ignore – targets are optional for form assistance
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
    void loadDispatchTargets();
  }, [refreshJobs, loadDispatchTargets]);

  const jobRecords = useMemo<JobRecord[]>(() => {
    return [...jobs]
      .map((job) => {
        const state = states[job.id] || {};
        return {
          job,
          state,
          status: resolveDisplayStatus(job, state),
        };
      })
      .sort((left, right) => {
        const leftTime = left.state.next_run_at
          ? new Date(left.state.next_run_at).getTime()
          : Number.MAX_SAFE_INTEGER;
        const rightTime = right.state.next_run_at
          ? new Date(right.state.next_run_at).getTime()
          : Number.MAX_SAFE_INTEGER;
        if (leftTime !== rightTime) {
          return leftTime - rightTime;
        }
        return left.job.name.localeCompare(right.job.name, "zh-CN");
      });
  }, [jobs, states]);

  const filteredJobs = useMemo(
    () => jobRecords.filter((record) => matchesFilter(record, filter)),
    [filter, jobRecords],
  );

  const stats = useMemo(() => {
    return {
      total: jobRecords.length,
      running: jobRecords.filter((record) => record.status.key === "running").length,
      pending: jobRecords.filter((record) => record.status.key === "pending").length,
      errors: jobRecords.filter((record) => record.status.isError).length,
    };
  }, [jobRecords]);

  const openCreateModal = useCallback(() => {
    setEditingJob(null);
    setIsModalOpen(true);
  }, []);

  const openEditModal = useCallback((job: CronJobSpec) => {
    setEditingJob(job);
    setIsModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setIsModalOpen(false);
    setEditingJob(null);
  }, []);

  const handleSubmit = useCallback(
    async (payload: CronJobSpec, currentEditingJob: CronJobSpec | null) => {
      setSubmitting(true);
      try {
        if (currentEditingJob) {
          await cronJobsApi.replaceCronJob(currentEditingJob.id, payload, portalGatewayAgentId);
          setNotice(`已更新任务“${payload.name}”。`);
        } else {
          await cronJobsApi.createCronJob(payload, portalGatewayAgentId);
          setNotice(`已创建任务“${payload.name}”。`);
        }
        closeModal();
        await refreshJobs();
      } finally {
        setSubmitting(false);
      }
    },
    [closeModal, refreshJobs],
  );

  const runJobAction = useCallback(
    async (
      jobId: string,
      action: () => Promise<unknown>,
      successMessage: string,
    ) => {
      setActionJobId(jobId);
      setError("");
      try {
        await action();
        setNotice(successMessage);
        await refreshJobs();
      } catch (actionError: any) {
        setError(actionError?.message || "操作失败，请稍后重试。");
      } finally {
        setActionJobId("");
      }
    },
    [refreshJobs],
  );

  const handleDelete = useCallback(async (job: CronJobSpec) => {
    if (!window.confirm(`确认删除定时任务“${job.name}”吗？`)) {
      return;
    }
    await runJobAction(job.id, () => cronJobsApi.deleteCronJob(job.id, portalGatewayAgentId), `已删除任务"${job.name}"。`);
  }, [runJobAction]);

  const handleToggleSchedule = useCallback(async (record: JobRecord) => {
    const { job } = record;

    if (job.enabled === false) {
      const payload = { ...job, enabled: true };
      await runJobAction(job.id, () => cronJobsApi.replaceCronJob(job.id, payload, portalGatewayAgentId), `已启用任务"${job.name}"。`);
    } else {
      const payload = { ...job, enabled: false };
      await runJobAction(job.id, () => cronJobsApi.replaceCronJob(job.id, payload, portalGatewayAgentId), `已停用任务"${job.name}"。`);
    }
  }, [runJobAction]);

  const handleRunNow = useCallback((job: CronJobSpec) => {
    void runJobAction(
      job.id,
      () => cronJobsApi.runCronJob(job.id, portalGatewayAgentId),
      `已触发任务“${job.name}”立即执行。`,
    );
  }, [runJobAction]);

  const handleViewHistory = useCallback(async (record: JobRecord) => {
    const { job } = record;
    setHistoryJobName(job.name);
    setHistoryModalOpen(true);
    setHistoryLoading(true);
    try {
      const records = await cronJobsApi.getCronJobHistory(job.id, portalGatewayAgentId);
      setHistoryRecords(records || []);
    } catch {
      setHistoryRecords([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  return (
    <div className="cron-jobs-page">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          定时任务 <small>任务调度中心</small>
        </div>
        <div className="portal-model-page-actions">
          <button type="button" className="portal-model-btn" onClick={openCreateModal}>
            <i className="fas fa-plus" />
            新增任务
          </button>
          <button
            type="button"
            className="portal-model-btn"
            onClick={() => void refreshJobs()}
            disabled={loading}
          >
            <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-rotate-right"}`} />
            刷新
          </button>
        </div>
      </div>

      <div className="cron-jobs-content">
        <div className="cron-jobs-stats">
          <article className="cron-jobs-stat-card">
            <span>任务总数</span>
            <strong>{stats.total}</strong>
          </article>
          <article className="cron-jobs-stat-card accent-green">
            <span>运行中</span>
            <strong>{stats.running}</strong>
          </article>
          <article className="cron-jobs-stat-card accent-amber">
            <span>待首次执行</span>
            <strong>{stats.pending}</strong>
          </article>
          <article className="cron-jobs-stat-card accent-red">
            <span>最近失败</span>
            <strong>{stats.errors}</strong>
          </article>
        </div>

        <div className="cron-jobs-filter-bar">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={filter === option.id ? "cron-jobs-filter-chip active" : "cron-jobs-filter-chip"}
              onClick={() => setFilter(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {notice ? <div className="cron-jobs-notice success">{notice}</div> : null}
        {error ? <div className="cron-jobs-notice error">{error}</div> : null}

        <CronJobsTableSection
          loading={loading}
          filteredJobs={filteredJobs}
          filter={filter}
          actionJobId={actionJobId}
          onRunNow={handleRunNow}
          onToggleSchedule={handleToggleSchedule}
          onEdit={openEditModal}
          onDelete={handleDelete}
          onViewHistory={handleViewHistory}
        />
      </div>

      {isModalOpen ? (
        <CronJobModal
          editingJob={editingJob}
          submitting={submitting}
          dispatchTargets={dispatchTargets}
          dispatchChannels={dispatchChannels}
          onClose={closeModal}
          onSubmit={handleSubmit}
        />
      ) : null}

      {historyModalOpen ? (
        <div className="cron-jobs-modal-backdrop" onClick={() => setHistoryModalOpen(false)}>
          <div className="cron-jobs-history-modal" onClick={(e) => e.stopPropagation()}>
            <div className="cron-jobs-modal-header">
              <div className="cron-jobs-modal-heading">
                <h4>执行记录 — {historyJobName}</h4>
              </div>
              <button type="button" className="cron-jobs-modal-close" onClick={() => setHistoryModalOpen(false)}>
                <i className="fas fa-xmark" />
              </button>
            </div>
            <div className="cron-jobs-history-body">
              {historyLoading ? (
                <div className="cron-jobs-empty-state"><i className="fas fa-spinner fa-spin" /><p>加载中...</p></div>
              ) : historyRecords.length === 0 ? (
                <div className="cron-jobs-empty-state"><i className="fas fa-clock-rotate-left" /><p>暂无执行记录</p></div>
              ) : (
                <div className="cron-jobs-history-list">
                  {historyRecords.map((rec, idx) => (
                    <div key={`${rec.run_at}-${idx}`} className="cron-jobs-history-item">
                      <div className="cron-jobs-history-item-main">
                        <span className="cron-jobs-history-time">{new Date(rec.run_at).toLocaleString("zh-CN")}</span>
                        <span className={`cron-jobs-history-status status-${rec.status}`}>
                          {rec.status === "success" ? "成功" : rec.status === "running" ? "执行中" : rec.status === "cancelled" ? "已取消" : rec.status === "skipped" ? "已跳过" : "失败"}
                        </span>
                      </div>
                      <div className="cron-jobs-history-item-meta">
                        {rec.trigger === "manual" ? "手动触发" : "定时触发"}
                      </div>
                      {rec.error ? (
                        <div className="cron-jobs-history-item-error">{rec.error}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
