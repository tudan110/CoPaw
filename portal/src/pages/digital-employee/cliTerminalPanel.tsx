import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createChat, stopChat, streamChat } from "../../api/copawChat";
import { toFriendlyChatError } from "../../lib/chatErrorMessage";
import {
  digitalEmployees,
  employeeResults,
  employeeWorkflows,
} from "../../data/portalData";
import {
  buildThinkingBlock,
  buildToolBlock,
  createRemoteSessionId,
  extractCopawMessageText,
  isCopawReasoningMessage,
  mergeStreamingText,
} from "./helpers";
import { MessageMarkdown } from "./components";
import "../cli-terminal.css";

type EmployeeRecord = (typeof digitalEmployees)[number];
type CliTone = "cmd" | "info" | "success" | "error" | "warn" | "accent" | "banner";
type CliLine = {
  id: string;
  content: string;
  tone: CliTone;
  format?: "plain" | "markdown";
  streaming?: boolean;
};
type CliOutputEntry = {
  content: string;
  tone?: CliTone;
  delay?: number;
};
type EmployeeSession = {
  chatId: string;
  sessionId: string;
};
type CliCommandDefinition = {
  name: string;
  usage: string;
  description: string;
  requiresArgs?: boolean;
};

const CLI_COMMANDS: CliCommandDefinition[] = [
  { name: "help", usage: "help", description: "显示命令参考" },
  { name: "list", usage: "list", description: "列出全部数字员工" },
  { name: "status", usage: "status", description: "查看系统状态总览" },
  { name: "agents", usage: "agents", description: "查看员工运行负载" },
  { name: "history", usage: "history", description: "查看命令历史" },
  { name: "clear", usage: "clear", description: "清空当前终端输出" },
  { name: "use", usage: "use <employee_id>", description: "切换当前数字员工", requiresArgs: true },
  { name: "open", usage: "open [employee_id]", description: "打开完整聊天页" },
  { name: "ask", usage: "ask <question>", description: "向当前数字员工发问", requiresArgs: true },
  { name: "run", usage: "run <employee_id> <command>", description: "调度指定数字员工执行", requiresArgs: true },
  { name: "deploy", usage: "deploy <service>", description: "发起部署任务", requiresArgs: true },
  { name: "scan", usage: "scan <target>", description: "发起扫描任务", requiresArgs: true },
];
const CLI_COMMAND_NAME_SET = new Set(CLI_COMMANDS.map((command) => command.name));
const REMOTE_AGENT_IDS: Record<string, string> = {
  fault: "fault",
  resource: "resource",
  inspection: "inspection",
  query: "query",
  order: "order",
  knowledge: "knowledge",
};
const COPAW_USER_ID = "default";
const COPAW_CHANNEL = "console";

function createCliLine(
  content: string,
  tone: CliTone = "info",
  options: { format?: "plain" | "markdown"; streaming?: boolean } = {},
): CliLine {
  return {
    id: `cli-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    content,
    tone,
    format: options.format || "plain",
    streaming: options.streaming || false,
  };
}

function resolveEmployee(employees: EmployeeRecord[], rawValue: string | null | undefined) {
  const normalized = String(rawValue || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  return (
    employees.find((employee) => employee.id.toLowerCase() === normalized)
    || employees.find((employee) => employee.name.toLowerCase() === normalized)
    || null
  );
}

function getEmployeeState(employee: EmployeeRecord) {
  if (employee.urgent) {
    return { label: "URGENT", tone: "error" as const };
  }
  if (employee.status === "running") {
    return { label: "ACTIVE", tone: "success" as const };
  }
  return { label: "STANDBY", tone: "warn" as const };
}

function buildLoadBar(percent: number) {
  const bounded = Math.max(0, Math.min(100, percent));
  const filled = Math.round(bounded / 10);
  return `${"█".repeat(filled)}${"░".repeat(10 - filled)}`;
}

function computeEmployeeLoad(employee: EmployeeRecord, index: number) {
  const successSeed = Number.parseFloat(employee.success) || 0;
  return Math.max(34, Math.min(96, Math.round(employee.tasks / 90 + successSeed / 2 + index * 3)));
}

function isBareCommand(action: string, args: string[]) {
  return (
    (action === "help" && args.length === 0)
    || (action === "list" && args.length === 0)
    || (action === "status" && args.length === 0)
    || (action === "agents" && args.length === 0)
    || (action === "history" && args.length === 0)
    || (action === "clear" && args.length === 0)
    || (action === "use" && args.length === 1)
    || (action === "open" && args.length <= 1)
    || (action === "ask" && args.length >= 1)
    || (action === "run" && args.length >= 2)
    || (action === "deploy" && args.length >= 1)
    || (action === "scan" && args.length >= 1)
  );
}

function buildHelpEntries(): CliOutputEntry[] {
  return [
    { content: "" },
    { content: "  ╔══════════════════════════════════════════════════════╗", tone: "accent" },
    { content: "  ║             智观 Paw Command Reference              ║", tone: "banner" },
    { content: "  ╠══════════════════════════════════════════════════════╣", tone: "accent" },
    { content: "  ║  直接输入自然语言       与当前数字员工对话          ║", tone: "info" },
    { content: "  ║  输入 /                打开命令面板                ║", tone: "info" },
    ...CLI_COMMANDS.map((command) => ({
      content: `  ║  ${command.usage.padEnd(22)} ${command.description.padEnd(26)}║`,
      tone: "info" as const,
    })),
    { content: "  ╚══════════════════════════════════════════════════════╝", tone: "accent" },
    { content: "" },
  ];
}

function buildWelcomeEntries(employee: EmployeeRecord | null): CliLine[] {
  const targetLabel = employee ? `${employee.name} (${employee.id})` : "未指定";
  return [
    createCliLine("欢迎使用智观 Paw CLI", "banner"),
    createCliLine('直接输入自然语言即可开始对话；输入 "/" 可打开命令面板。', "info"),
    createCliLine(`当前数字员工：${targetLabel}`, "accent"),
    createCliLine("", "info"),
  ];
}

function buildLocalResponse(employee: EmployeeRecord, prompt: string) {
  const workflow = employeeWorkflows[employee.id as keyof typeof employeeWorkflows] || [];
  const result = employeeResults[employee.id as keyof typeof employeeResults];
  const metrics = (result?.metrics || []).slice(0, 2);
  const capabilitySummary = employee.capabilities.slice(0, 3).join("、");
  const quickCommand = employee.quickCommands?.[0];

  return [
    `${employee.name}：已收到你的请求「${prompt}」。`,
    workflow.length ? `我会按 ${workflow.join(" -> ")} 的流程继续处理。` : `我会围绕 ${employee.desc} 能力继续处理。`,
    result
      ? `本轮预期输出：${result.title}（${result.badge}）${metrics.length ? `，关键指标 ${metrics.map((metric) => `${metric.label}${metric.value}`).join(" / ")}` : ""}。`
      : `我当前可用的核心能力包括：${capabilitySummary}。`,
    capabilitySummary ? `你也可以继续让我处理：${capabilitySummary}。` : "",
    quickCommand ? `例如继续输入：${quickCommand}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

export function CliTerminalPanel({
  employees,
  activeEmployeeId,
  onOpenEmployeeChat,
}: {
  employees: EmployeeRecord[];
  activeEmployeeId?: string | null;
  onOpenEmployeeChat: (employeeId: string) => void;
}) {
  const terminalOutputRef = useRef<HTMLDivElement | null>(null);
  const commandInputRef = useRef<HTMLInputElement | null>(null);
  const scheduledTimersRef = useRef<number[]>([]);
  const streamAbortRef = useRef<AbortController | null>(null);
  const employeeSessionsRef = useRef(new Map<string, EmployeeSession>());
  const assistantLineMapRef = useRef(new Map<string, string>());
  const reasoningLineMapRef = useRef(new Map<string, string>());
  const lineContentMapRef = useRef(new Map<string, string>());
  const streamMessageMetaRef = useRef(new Map<string, { role?: string; type?: string }>());
  const streamPendingTextRef = useRef(new Map<string, string>());
  const activeStreamAgentIdRef = useRef("");
  const activeStreamChatIdRef = useRef("");

  const [commandInput, setCommandInput] = useState("");
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [activeSlashIndex, setActiveSlashIndex] = useState(0);
  const [activeTargetId, setActiveTargetId] = useState(activeEmployeeId || employees[0]?.id || "");
  const [isStreaming, setIsStreaming] = useState(false);
  const [lines, setLines] = useState<CliLine[]>(() =>
    buildWelcomeEntries(resolveEmployee(employees, activeEmployeeId || employees[0]?.id)),
  );

  const activeTarget = useMemo(
    () => resolveEmployee(employees, activeTargetId) || employees[0] || null,
    [activeTargetId, employees],
  );
  const slashDraft = commandInput.startsWith("/") ? commandInput.slice(1) : "";
  const slashDraftTrimmedStart = slashDraft.trimStart();
  const slashQuery = slashDraftTrimmedStart.toLowerCase();
  const slashMenuOpen = commandInput.startsWith("/") && !/\s/.test(slashDraftTrimmedStart);
  const slashSuggestions = useMemo(() => {
    if (!slashMenuOpen) {
      return [];
    }
    if (!slashQuery) {
      return CLI_COMMANDS;
    }
    return CLI_COMMANDS
      .filter((command) =>
        command.name.includes(slashQuery)
        || command.usage.includes(slashQuery)
        || command.description.toLowerCase().includes(slashQuery),
      )
      .sort((left, right) => {
        const leftExact = left.name.startsWith(slashQuery) ? 0 : 1;
        const rightExact = right.name.startsWith(slashQuery) ? 0 : 1;
        return leftExact - rightExact || left.name.localeCompare(right.name);
      });
  }, [slashMenuOpen, slashQuery]);

  useEffect(() => {
    setActiveSlashIndex(0);
  }, [slashQuery]);

  useEffect(() => {
    if (!slashSuggestions.length) {
      setActiveSlashIndex(0);
      return;
    }
    setActiveSlashIndex((current) => Math.min(current, slashSuggestions.length - 1));
  }, [slashSuggestions]);

  const clearScheduledTimers = useCallback(() => {
    scheduledTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
    scheduledTimersRef.current = [];
  }, []);

  const appendLine = useCallback((
    content: string,
    tone: CliTone = "info",
    options: { format?: "plain" | "markdown"; streaming?: boolean } = {},
  ) => {
    const line = createCliLine(content, tone, options);
    setLines((current) => [...current, line]);
    return line.id;
  }, []);

  const updateLine = useCallback((
    lineId: string,
    content: string,
    options: { tone?: CliTone; streaming?: boolean } = {},
  ) => {
    lineContentMapRef.current.set(lineId, content);
    setLines((current) =>
      current.map((line) =>
        line.id === lineId
          ? {
            ...line,
            content,
            tone: options.tone || line.tone,
            streaming: options.streaming ?? line.streaming,
          }
          : line,
      ),
    );
  }, []);

  const removeLine = useCallback((lineId: string) => {
    lineContentMapRef.current.delete(lineId);
    setLines((current) => current.filter((line) => line.id !== lineId));
  }, []);

  const appendEntries = useCallback((entries: CliOutputEntry[]) => {
    let elapsed = 0;
    entries.forEach((entry) => {
      elapsed += entry.delay || 0;
      const timerId = window.setTimeout(() => {
        appendLine(entry.content, entry.tone || "info");
      }, elapsed);
      scheduledTimersRef.current.push(timerId);
    });
  }, [appendLine]);

  const appendAssistantText = useCallback((messageId: string, incomingText: string) => {
    if (!incomingText) {
      return;
    }

    let lineId = assistantLineMapRef.current.get(messageId);
    if (!lineId) {
      lineId = appendLine("", "info", { format: "markdown", streaming: true });
      assistantLineMapRef.current.set(messageId, lineId);
      lineContentMapRef.current.set(lineId, "");
    }

    const currentText = lineContentMapRef.current.get(lineId) || "";
    const nextText = mergeStreamingText(currentText, incomingText);
    updateLine(lineId, nextText, { tone: "info", streaming: true });
  }, [appendLine, updateLine]);

  const appendReasoningText = useCallback((messageId: string, incomingText: string) => {
    if (!incomingText) {
      return;
    }

    let lineId = reasoningLineMapRef.current.get(messageId);
    if (!lineId) {
      lineId = appendLine("> Thinking\n\n", "warn", { format: "markdown", streaming: true });
      reasoningLineMapRef.current.set(messageId, lineId);
      lineContentMapRef.current.set(lineId, "");
    }

    const currentText = lineContentMapRef.current.get(lineId) || "";
    const nextText = mergeStreamingText(currentText, incomingText);
    updateLine(lineId, `> Thinking\n\n${nextText}`, { tone: "warn", streaming: true });
    lineContentMapRef.current.set(lineId, nextText);
  }, [appendLine, updateLine]);

  const reclassifyAssistantLineAsReasoning = useCallback((messageId: string) => {
    const assistantLineId = assistantLineMapRef.current.get(messageId);
    if (!assistantLineId) {
      return;
    }
    assistantLineMapRef.current.delete(messageId);
    removeLine(assistantLineId);
  }, [removeLine]);

  const flushPendingRemoteText = useCallback((messageId: string) => {
    const pendingText = String(streamPendingTextRef.current.get(messageId) || "");
    if (!pendingText) {
      return;
    }

    const streamMeta = streamMessageMetaRef.current.get(messageId);
    if (streamMeta?.role === "assistant" && streamMeta?.type === "reasoning") {
      appendReasoningText(messageId, pendingText);
      streamPendingTextRef.current.delete(messageId);
      return;
    }

    if (streamMeta?.role === "assistant" && streamMeta?.type === "message") {
      appendAssistantText(messageId, pendingText);
      streamPendingTextRef.current.delete(messageId);
    }
  }, [appendAssistantText, appendReasoningText]);

  const stopStreaming = useCallback(async (withNotice = true) => {
    const controller = streamAbortRef.current;
    if (!controller) {
      return;
    }

    controller.abort();
    streamAbortRef.current = null;
    setIsStreaming(false);

    if (activeStreamAgentIdRef.current && activeStreamChatIdRef.current) {
      try {
        await stopChat(activeStreamAgentIdRef.current, activeStreamChatIdRef.current);
      } catch {
        // Ignore stop errors so the terminal stays responsive.
      }
    }

    if (withNotice) {
      appendLine("Generation stopped.", "warn");
    }
  }, [appendLine]);

  const handleRemoteEvent = useCallback((event: any) => {
    if (event.object === "message" && event.id) {
      streamMessageMetaRef.current.set(event.id, {
        role: event.role,
        type: event.type,
      });
      flushPendingRemoteText(event.id);
      if (event.role === "assistant" && event.type === "reasoning") {
        reclassifyAssistantLineAsReasoning(event.id);
      }
    }

    if (event.object === "message" && event.status === "completed") {
      if (isCopawReasoningMessage(event)) {
        streamPendingTextRef.current.delete(event.id);
        reclassifyAssistantLineAsReasoning(event.id);
        const block = buildThinkingBlock(event);
        if (block.content) {
          const existingLineId = reasoningLineMapRef.current.get(event.id);
          if (existingLineId) {
            updateLine(existingLineId, `> Thinking\n\n${block.content}`, {
              tone: "warn",
              streaming: false,
            });
            lineContentMapRef.current.set(existingLineId, block.content);
          } else {
            const lineId = appendLine(`> Thinking\n\n${block.content}`, "warn", {
              format: "markdown",
            });
            reasoningLineMapRef.current.set(event.id, lineId);
            lineContentMapRef.current.set(lineId, block.content);
          }
        }
        return;
      }

      if (event.type === "plugin_call" || event.type === "plugin_call_output") {
        const block = buildToolBlock(event);
        if (block.content) {
          appendLine(`**[tool]**\n\n${block.content}`, "accent", { format: "markdown" });
        }
        return;
      }
    }

    if (
      event.object === "message"
      && event.role === "assistant"
      && event.type === "message"
    ) {
      const finalText = extractCopawMessageText(event);
      if (event.status === "completed" && finalText) {
        streamPendingTextRef.current.delete(event.id);
        appendAssistantText(event.id, finalText);
        const lineId = assistantLineMapRef.current.get(event.id);
        if (lineId) {
          updateLine(lineId, lineContentMapRef.current.get(lineId) || finalText, {
            tone: "info",
            streaming: false,
          });
        }
      }
      return;
    }

    if (event.object === "content" && event.type === "text" && event.msg_id && event.text) {
      const streamMeta = streamMessageMetaRef.current.get(event.msg_id);
      if (streamMeta?.role === "assistant" && streamMeta?.type === "reasoning") {
        appendReasoningText(event.msg_id, event.text);
        return;
      }
      if (streamMeta?.role === "assistant" && streamMeta?.type === "message") {
        appendAssistantText(event.msg_id, event.text);
        return;
      }
      const currentPendingText = String(streamPendingTextRef.current.get(event.msg_id) || "");
      streamPendingTextRef.current.set(
        event.msg_id,
        mergeStreamingText(currentPendingText, event.text),
      );
    }
  }, [
    appendAssistantText,
    appendLine,
    appendReasoningText,
    flushPendingRemoteText,
    reclassifyAssistantLineAsReasoning,
    updateLine,
  ]);

  const runLocalConversation = useCallback((employee: EmployeeRecord, prompt: string) => {
    setIsStreaming(true);
    const assistantLineId = appendLine("", "info", { format: "markdown", streaming: true });
    const chunks = buildLocalResponse(employee, prompt).split("\n");

    chunks.forEach((chunk, index) => {
      const timerId = window.setTimeout(() => {
        const previous = lineContentMapRef.current.get(assistantLineId) || "";
        const nextContent = previous ? `${previous}\n${chunk}` : chunk;
        updateLine(assistantLineId, nextContent, {
          tone: "info",
          streaming: index !== chunks.length - 1,
        });
        if (index === chunks.length - 1) {
          setIsStreaming(false);
        }
      }, (index + 1) * 240);
      scheduledTimersRef.current.push(timerId);
    });
  }, [appendLine, updateLine]);

  const runRemoteConversation = useCallback(async (employee: EmployeeRecord, prompt: string) => {
    const remoteAgentId = REMOTE_AGENT_IDS[employee.id];
    if (!remoteAgentId) {
      runLocalConversation(employee, prompt);
      return;
    }

    clearScheduledTimers();
    assistantLineMapRef.current = new Map();
    reasoningLineMapRef.current = new Map();
    lineContentMapRef.current = new Map();
    streamMessageMetaRef.current = new Map();
    streamPendingTextRef.current = new Map();
    setIsStreaming(true);

    const controller = new AbortController();
    streamAbortRef.current = controller;
    activeStreamAgentIdRef.current = remoteAgentId;

    try {
      let session = employeeSessionsRef.current.get(employee.id);
      if (!session) {
        const createdChat = await createChat(remoteAgentId, {
          name: prompt,
          session_id: createRemoteSessionId(employee.id),
          user_id: COPAW_USER_ID,
          channel: COPAW_CHANNEL,
        });
        session = {
          chatId: createdChat.id,
          sessionId: createdChat.session_id,
        };
        employeeSessionsRef.current.set(employee.id, session);
      }

      activeStreamChatIdRef.current = session.chatId;

      await streamChat(
        remoteAgentId,
        {
          input: [
            {
              role: "user",
              type: "message",
              content: [
                {
                  type: "text",
                  text: prompt,
                  status: "created",
                },
              ],
            },
          ],
          session_id: session.sessionId,
          user_id: COPAW_USER_ID,
          channel: COPAW_CHANNEL,
          stream: true,
        },
        {
          signal: controller.signal,
          onEvent: handleRemoteEvent,
        },
      );

      if (!assistantLineMapRef.current.size) {
        appendLine("本轮对话未返回可展示内容。", "warn");
      }
    } catch (error: any) {
      if (!controller.signal.aborted) {
        appendLine(`对话失败：${toFriendlyChatError(error)}`, "error");
      }
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      streamMessageMetaRef.current = new Map();
      streamPendingTextRef.current = new Map();
      activeStreamAgentIdRef.current = "";
      activeStreamChatIdRef.current = "";
      setIsStreaming(false);
    }
  }, [appendLine, clearScheduledTimers, handleRemoteEvent, runLocalConversation]);

  const submitPrompt = useCallback(async (
    prompt: string,
    targetEmployee: EmployeeRecord | null,
  ) => {
    if (!targetEmployee) {
      appendLine("Error: no active employee.", "error");
      return;
    }
    if (isStreaming) {
      appendLine("当前仍在生成响应，请先停止当前输出。", "warn");
      return;
    }

    if (REMOTE_AGENT_IDS[targetEmployee.id]) {
      await runRemoteConversation(targetEmployee, prompt);
      return;
    }

    runLocalConversation(targetEmployee, prompt);
  }, [appendLine, isStreaming, runLocalConversation, runRemoteConversation]);

  useEffect(() => () => {
    clearScheduledTimers();
    streamAbortRef.current?.abort();
  }, [clearScheduledTimers]);

  useEffect(() => {
    if (activeEmployeeId && resolveEmployee(employees, activeEmployeeId)) {
      setActiveTargetId(activeEmployeeId);
    }
  }, [activeEmployeeId, employees]);

  useEffect(() => {
    terminalOutputRef.current?.scrollTo({
      top: terminalOutputRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [lines]);

  const usageFor = useCallback((action: string) => {
    return CLI_COMMANDS.find((command) => command.name === action)?.usage || action;
  }, []);

  const applySlashCommand = useCallback((command: CliCommandDefinition) => {
    setCommandInput(command.requiresArgs ? `/${command.name} ` : `/${command.name}`);
    setHistoryIndex(-1);
    window.requestAnimationFrame(() => {
      commandInputRef.current?.focus();
    });
  }, []);

  const runCommand = useCallback(async (rawCommand: string) => {
    const displayCommand = rawCommand.trim();
    if (!displayCommand) {
      return;
    }

    setCommandHistory((current) => [...current, displayCommand]);
    setHistoryIndex(-1);
    appendLine(`智观 Paw> ${displayCommand}`, "cmd");

    const usesSlash = displayCommand.startsWith("/");
    const command = usesSlash ? displayCommand.slice(1).trim() : displayCommand;
    if (!command) {
      appendEntries([{ content: '输入 "/" 查看可用命令。', tone: "info" }]);
      return;
    }
    const parts = command.split(/\s+/);
    const action = parts[0]?.toLowerCase() || "";
    const args = parts.slice(1);

    if (usesSlash && !CLI_COMMAND_NAME_SET.has(action)) {
      appendEntries([
        { content: `Unknown slash command: /${action}`, tone: "error" },
        { content: '输入 "/" 查看可用命令。', tone: "info" },
      ]);
      return;
    }

    if (!usesSlash && !isBareCommand(action, args)) {
      await submitPrompt(command, activeTarget);
      return;
    }

    if (action === "clear") {
      if (args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("clear")}`, tone: "error" }]);
        return;
      }
      clearScheduledTimers();
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
      setIsStreaming(false);
      setLines([]);
      lineContentMapRef.current = new Map();
      assistantLineMapRef.current = new Map();
      return;
    }

    if (action === "help") {
      if (args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("help")}`, tone: "error" }]);
        return;
      }
      appendEntries(buildHelpEntries());
      return;
    }

    if (action === "list") {
      if (args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("list")}`, tone: "error" }]);
        return;
      }
      appendEntries([
        { content: "" },
        { content: "  Digital Employee Matrix:", tone: "accent" },
        { content: `  ${"-".repeat(54)}`, tone: "info" },
        ...employees.map((employee) => {
          const state = getEmployeeState(employee);
          const marker = activeTarget?.id === employee.id ? "›" : " ";
          return {
            content: ` ${marker} ${employee.id.padEnd(12)} ${employee.name.padEnd(8)} [${state.label}]`,
            tone: state.tone,
          };
        }),
        { content: "" },
      ]);
      return;
    }

    if (action === "status") {
      if (args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("status")}`, tone: "error" }]);
        return;
      }
      const running = employees.filter((employee) => employee.status === "running").length;
      const urgent = employees.filter((employee) => employee.urgent).length;
      const stopped = employees.length - running;
      const totalTasks = employees.reduce((sum, employee) => sum + employee.tasks, 0);
      appendEntries([
        { content: "" },
        { content: "  System Status Overview", tone: "accent" },
        { content: `  ${"-".repeat(40)}`, tone: "info" },
        { content: `  Employees Online:  ${running}/${employees.length}`, tone: "success" },
        { content: `  Urgent Alerts:     ${urgent}`, tone: urgent > 0 ? "error" : "success" },
        { content: `  Standby Agents:    ${stopped}`, tone: stopped > 0 ? "warn" : "info" },
        { content: `  Managed Tasks:     ${totalTasks.toLocaleString("zh-CN")}`, tone: "info" },
        { content: `  当前数字员工：      ${activeTarget?.name || "未指定"}`, tone: "accent" },
        { content: "" },
      ]);
      return;
    }

    if (action === "agents") {
      if (args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("agents")}`, tone: "error" }]);
        return;
      }
      appendEntries([
        { content: "" },
        { content: "  ┌─ Active Agent Status ─────────────────────┐", tone: "accent" },
        ...employees.map((employee, index) => {
          const load = computeEmployeeLoad(employee, index);
          const state = getEmployeeState(employee);
          return {
            content: `  │ ${employee.name.padEnd(10)} [${state.label}]  Load: ${buildLoadBar(load)}  ${String(load).padStart(2)}%`,
            tone: state.tone,
            delay: index === 0 ? 120 : 90,
          };
        }),
        { content: "  └──────────────────────────────────────────┘", tone: "accent", delay: 120 },
        { content: "" },
      ]);
      return;
    }

    if (action === "use") {
      if (args.length !== 1) {
        appendEntries([{ content: `Error: usage: ${usageFor("use")}`, tone: "error" }]);
        return;
      }
      const employee = resolveEmployee(employees, args[0]);
      if (!employee) {
        appendEntries([{ content: `Error: usage: ${usageFor("use")}`, tone: "error" }]);
        return;
      }

      setActiveTargetId(employee.id);
      appendEntries([
        { content: `当前数字员工已切换为 ${employee.name} (${employee.id})`, tone: "success" },
        { content: '直接输入问题即可开始对话，或输入 "open" 进入完整聊天页。', tone: "info" },
        { content: "" },
      ]);
      return;
    }

    if (action === "open") {
      if (args.length > 1) {
        appendEntries([{ content: `Error: usage: ${usageFor("open")}`, tone: "error" }]);
        return;
      }
      const employee = resolveEmployee(employees, args[0]) || activeTarget;
      if (!employee) {
        appendEntries([{ content: `Error: usage: ${usageFor("open")}`, tone: "error" }]);
        return;
      }

      appendEntries([{ content: `Opening ${employee.name} chat...`, tone: "warn" }]);
      const timerId = window.setTimeout(() => {
        onOpenEmployeeChat(employee.id);
      }, 320);
      scheduledTimersRef.current.push(timerId);
      return;
    }

    if (action === "ask") {
      if (!args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("ask")}`, tone: "error" }]);
        return;
      }
      await submitPrompt(args.join(" "), activeTarget);
      return;
    }

    if (action === "run") {
      if (args.length < 2) {
        appendEntries([{ content: `Error: usage: ${usageFor("run")}`, tone: "error" }]);
        return;
      }
      const employee = resolveEmployee(employees, args[0]);
      const subCommand = args.slice(1).join(" ");
      if (!employee || !subCommand) {
        appendEntries([{ content: `Error: usage: ${usageFor("run")}`, tone: "error" }]);
        return;
      }
      appendEntries([{ content: `Dispatching to ${employee.name}...`, tone: "warn" }]);
      await submitPrompt(subCommand, employee);
      return;
    }

    if (action === "deploy") {
      if (!args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("deploy")}`, tone: "error" }]);
        return;
      }
      appendEntries([{ content: `Dispatching deployment plan: ${args.join(" ")}`, tone: "warn" }]);
      await submitPrompt(`请为我执行部署：${args.join(" ")}`, activeTarget);
      return;
    }

    if (action === "scan") {
      if (!args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("scan")}`, tone: "error" }]);
        return;
      }
      appendEntries([{ content: `Dispatching scan task: ${args.join(" ")}`, tone: "warn" }]);
      await submitPrompt(`请扫描目标：${args.join(" ")}`, activeTarget);
      return;
    }

    if (action === "history") {
      if (args.length) {
        appendEntries([{ content: `Error: usage: ${usageFor("history")}`, tone: "error" }]);
        return;
      }
      appendEntries([
        { content: "" },
        { content: "  Command History:", tone: "accent" },
        ...(commandHistory.length
          ? commandHistory.map((item, index) => ({
            content: `  ${index + 1}. ${item}`,
            tone: "info" as const,
          }))
          : [{ content: "  暂无历史命令。", tone: "info" as const }]),
        { content: "" },
      ]);
    }
  }, [
    activeTarget,
    appendEntries,
    appendLine,
    clearScheduledTimers,
    commandHistory,
    employees,
    onOpenEmployeeChat,
    submitPrompt,
    usageFor,
  ]);

  const handleSubmitCommand = useCallback(async () => {
    const nextCommand = commandInput;
    setCommandInput("");
    await runCommand(nextCommand);
  }, [commandInput, runCommand]);

  const handleInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (slashMenuOpen) {
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (!slashSuggestions.length) {
          return;
        }
        setActiveSlashIndex((current) =>
          current <= 0 ? slashSuggestions.length - 1 : current - 1,
        );
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (!slashSuggestions.length) {
          return;
        }
        setActiveSlashIndex((current) =>
          current >= slashSuggestions.length - 1 ? 0 : current + 1,
        );
        return;
      }

      if (event.key === "Enter" || event.key === "Tab") {
        if (!slashSuggestions.length) {
          if (event.key === "Tab") {
            event.preventDefault();
          }
          return;
        }
        const exactCommand = CLI_COMMANDS.find(
          (command) => `/${command.name}` === commandInput.trim(),
        );
        if (event.key === "Enter" && exactCommand && !exactCommand.requiresArgs) {
          event.preventDefault();
          void handleSubmitCommand();
          return;
        }
        event.preventDefault();
        const selected = slashSuggestions[activeSlashIndex] || slashSuggestions[0];
        if (selected) {
          applySlashCommand(selected);
        }
        return;
      }
    }

    if (slashMenuOpen && event.key === "Escape") {
      event.preventDefault();
      setCommandInput("");
      setHistoryIndex(-1);
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      void handleSubmitCommand();
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!commandHistory.length) {
        return;
      }
      const nextIndex =
        historyIndex < 0 ? commandHistory.length - 1 : Math.max(0, historyIndex - 1);
      setHistoryIndex(nextIndex);
      setCommandInput(commandHistory[nextIndex] || "");
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!commandHistory.length || historyIndex < 0) {
        return;
      }
      const nextIndex = historyIndex + 1;
      if (nextIndex >= commandHistory.length) {
        setHistoryIndex(-1);
        setCommandInput("");
        return;
      }
      setHistoryIndex(nextIndex);
      setCommandInput(commandHistory[nextIndex] || "");
    }
  };

  return (
    <div className="cli-terminal-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          CLI终端 <small>输入 / 打开命令面板，也能像 copilot-cli 一样直接对话</small>
        </div>
        <div className="portal-model-page-actions">
          <span className="cli-terminal-target-badge">
            当前数字员工：{activeTarget?.name || "未指定"}
          </span>
          {isStreaming ? (
            <button
              type="button"
              className="portal-model-btn cli-terminal-stop-btn"
              onClick={() => void stopStreaming()}
            >
              停止输出
            </button>
          ) : null}
          {activeTarget ? (
            <button
              type="button"
              className="portal-model-btn"
              onClick={() => onOpenEmployeeChat(activeTarget.id)}
            >
              打开对话
            </button>
          ) : null}
        </div>
      </div>

      <div className="cli-terminal-content">
        <div className="cli-terminal-shell">
          <div className="cli-terminal-topbar">
            <div className="cli-terminal-dots" aria-hidden="true">
              <span className="red" />
              <span className="yellow" />
              <span className="green" />
            </div>
            <div className="cli-terminal-topbar-title">智观 Paw CLI</div>
            <div className="cli-terminal-topbar-target">
              {isStreaming ? "streaming" : activeTarget?.id || "default"}
            </div>
          </div>

          <div ref={terminalOutputRef} className="cli-output" role="log" aria-live="polite">
            {lines.map((line) => (
              <div key={line.id} className={`cli-line cli-line-${line.tone}`}>
                {line.format === "markdown" ? (
                  <div className="markdown-bubble cli-markdown-line">
                    <MessageMarkdown content={line.content} isStreaming={Boolean(line.streaming)} />
                  </div>
                ) : (
                  line.content
                )}
              </div>
            ))}
          </div>

          <div className="cli-input-row">
            <span className="cli-prompt">智观 Paw&gt;</span>
            <div className="cli-input-field">
              {slashMenuOpen ? (
                <div className="cli-command-menu" role="listbox" aria-label="Slash commands">
                  <div className="cli-command-menu-header">
                    <span>Command palette</span>
                    <span>Enter 选择 · Esc 关闭</span>
                  </div>
                  {slashSuggestions.length ? (
                    slashSuggestions.map((command, index) => (
                      <button
                        key={command.name}
                        type="button"
                        role="option"
                        aria-selected={index === activeSlashIndex}
                        className={`cli-command-option${index === activeSlashIndex ? " is-active" : ""}`}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => applySlashCommand(command)}
                      >
                        <div className="cli-command-option-main">
                          <span className="cli-command-option-name">/{command.name}</span>
                          <span className="cli-command-option-desc">{command.description}</span>
                        </div>
                      </button>
                    ))
                  ) : (
                    <div className="cli-command-empty">没有匹配的命令</div>
                  )}
                </div>
              ) : null}
              <input
                ref={commandInputRef}
                className="cli-input"
                value={commandInput}
                placeholder='输入 / 打开命令面板，或直接输入自然语言'
                onChange={(event) => {
                  setCommandInput(event.target.value);
                  setHistoryIndex(-1);
                }}
                onKeyDown={handleInputKeyDown}
              />
            </div>
            <span className="cli-input-hint">/ commands</span>
          </div>
        </div>
      </div>
    </div>
  );
}
