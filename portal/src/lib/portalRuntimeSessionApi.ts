import type {
  IAgentScopeRuntimeWebUIMessage,
  IAgentScopeRuntimeWebUISession,
  IAgentScopeRuntimeWebUISessionAPI,
} from "@agentscope-ai/chat";
import {
  createChat,
  deleteChat,
  getChatTraceRecovery,
  getChatHistory,
  listChats,
  updateChat,
} from "../api/copawChat";

const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";
const DEFAULT_SESSION_NAME = "New Chat";
const ROLE_TOOL = "tool";
const ROLE_USER = "user";
const ROLE_ASSISTANT = "assistant";
const TYPE_PLUGIN_CALL_OUTPUT = "plugin_call_output";
const CARD_RESPONSE = "AgentScopeRuntimeResponseCard";
const STORAGE_PREFIX = "portal_runtime_pending_user_msg_";
const LOCAL_SESSION_REAL_ID_POLL_INTERVAL_MS = 100;
const LOCAL_SESSION_REAL_ID_WAIT_TIMEOUT_MS = 10000;

interface ContentItem {
  type: string;
  text?: string;
  [key: string]: unknown;
}

interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  sessionId: string;
  userId: string;
  channel: string;
  meta: Record<string, unknown>;
  realId?: string;
  status?: string;
  createdAt?: string | null;
  generating?: boolean;
  pinned?: boolean;
}

export interface PortalRuntimeSessionContext {
  sessionId: string;
  userId: string;
  channel: string;
  realId: string | null;
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function extractTextFromContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return String(content || "");
  return (content as ContentItem[])
    .filter((c) => c.type === "text")
    .map((c) => c.text || "")
    .filter(Boolean)
    .join("\n");
}

function contentToRequestParts(content: unknown): Array<Record<string, unknown>> {
  if (typeof content === "string") {
    return [{ type: "text", text: content, status: "created" }];
  }
  if (!Array.isArray(content)) {
    return [{ type: "text", text: String(content || ""), status: "created" }];
  }
  const parts = (content as ContentItem[]).map((item) => ({
    ...item,
    status: "created",
  }));
  return parts.length ? parts : [{ type: "text", text: "", status: "created" }];
}

function normalizeOutputMessageContent(content: unknown): unknown {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content;
  return content;
}

function toOutputMessage(msg: any) {
  return {
    ...msg,
    role:
      msg.type === TYPE_PLUGIN_CALL_OUTPUT && msg.role === "system"
        ? ROLE_TOOL
        : msg.role,
    metadata: null,
  };
}

function buildUserCard(msg: any): IAgentScopeRuntimeWebUIMessage {
  const contentParts = contentToRequestParts(msg.content);
  return {
    id: msg.id || generateId(),
    role: "user",
    cards: [
      {
        code: "AgentScopeRuntimeRequestCard",
        data: {
          input: [
            {
              role: "user",
              type: "message",
              content: contentParts,
            },
          ],
        },
      },
    ],
  };
}

function buildResponseCard(outputMessages: any[]): IAgentScopeRuntimeWebUIMessage {
  const now = Math.floor(Date.now() / 1000);
  const maxSeq = outputMessages.reduce(
    (max, item) => Math.max(max, item.sequence_number || 0),
    0,
  );

  const normalizedMessages = outputMessages.map((item) => ({
    ...item,
    content: normalizeOutputMessageContent(item.content),
  }));

  return {
    id: generateId(),
    role: ROLE_ASSISTANT,
    cards: [
      {
        code: CARD_RESPONSE,
        data: {
          id: `response_${generateId()}`,
          output: normalizedMessages,
          object: "response",
          status: "completed",
          created_at: now,
          sequence_number: maxSeq + 1,
          error: null,
          completed_at: now,
          usage: null,
        },
      },
    ],
    msgStatus: "finished",
  };
}

function convertMessages(messages: any[]): IAgentScopeRuntimeWebUIMessage[] {
  const result: IAgentScopeRuntimeWebUIMessage[] = [];
  let index = 0;

  while (index < messages.length) {
    if (messages[index].role === ROLE_USER) {
      result.push(buildUserCard(messages[index]));
      index += 1;
      continue;
    }

    const outputMessages: any[] = [];
    while (index < messages.length && messages[index].role !== ROLE_USER) {
      outputMessages.push(toOutputMessage(messages[index]));
      index += 1;
    }
    if (outputMessages.length) {
      result.push(buildResponseCard(outputMessages));
    }
  }

  return result;
}

function chatSpecToSession(chat: any): ExtendedSession {
  return {
    id: chat.id,
    name: chat.name || DEFAULT_SESSION_NAME,
    sessionId: chat.session_id,
    userId: chat.user_id,
    channel: chat.channel,
    messages: [],
    meta: chat.meta || {},
    status: chat.status ?? "idle",
    createdAt: chat.created_at ?? null,
    pinned: chat.pinned ?? false,
  } as ExtendedSession;
}

function isLocalTimestamp(id: string): boolean {
  return /^\d+$/.test(id);
}

function isGenerating(chatHistory: any): boolean {
  if (chatHistory.status === "running") return true;
  if (chatHistory.status === "idle") return false;
  const messages = chatHistory.messages || [];
  if (!messages.length) return false;
  const lastMessage = messages[messages.length - 1];
  return lastMessage.role === ROLE_USER;
}

function savePendingUserMessage(sessionId: string, text: string): void {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${sessionId}`, text);
  } catch {
    // ignore
  }
}

function loadPendingUserMessage(sessionId: string): string {
  try {
    return sessionStorage.getItem(`${STORAGE_PREFIX}${sessionId}`) || "";
  } catch {
    return "";
  }
}

function clearPendingUserMessage(sessionId: string): void {
  try {
    sessionStorage.removeItem(`${STORAGE_PREFIX}${sessionId}`);
  } catch {
    // ignore
  }
}

function resolveRealId(
  sessionList: IAgentScopeRuntimeWebUISession[],
  tempSessionId: string,
): { list: IAgentScopeRuntimeWebUISession[]; realId: string | null } {
  const realSession = sessionList.find(
    (session) => (session as ExtendedSession).sessionId === tempSessionId,
  );
  if (!realSession) return { list: sessionList, realId: null };

  const realUUID = realSession.id;
  const nextSession: ExtendedSession = {
    ...(realSession as ExtendedSession),
    id: tempSessionId,
    realId: realUUID,
  };
  return {
    list: [nextSession, ...sessionList.filter((session) => session !== realSession)],
    realId: realUUID,
  };
}

export class PortalRuntimeSessionApi implements IAgentScopeRuntimeWebUISessionAPI {
  private sessionList: IAgentScopeRuntimeWebUISession[] = [];
  private preferredChatId: string | null = null;
  private sessionListRequest: Promise<IAgentScopeRuntimeWebUISession[]> | null = null;
  private sessionRequests = new Map<string, Promise<IAgentScopeRuntimeWebUISession>>();
  private lastSelectedSessionId: string | null = null;

  constructor(private readonly agentId?: string) {}

  setPreferredChatId(chatId: string | null) {
    this.preferredChatId = chatId;
  }

  setLastUserMessage(sessionId: string, text: string): void {
    if (!sessionId || !text) return;
    savePendingUserMessage(sessionId, text);
  }

  private findSession(sessionId: string): ExtendedSession | undefined {
    return this.sessionList.find(
      (item) =>
        item.id === sessionId || (item as ExtendedSession).sessionId === sessionId,
    ) as ExtendedSession | undefined;
  }

  getRealIdForSession(sessionId: string): string | null {
    return this.findSession(sessionId)?.realId ?? null;
  }

  getSessionContext(sessionId?: string | null): PortalRuntimeSessionContext {
    const normalizedSessionId = String(sessionId || "");
    const session = normalizedSessionId ? this.findSession(normalizedSessionId) : undefined;
    return {
      sessionId: session?.sessionId || normalizedSessionId,
      userId: session?.userId || DEFAULT_USER_ID,
      channel: session?.channel || DEFAULT_CHANNEL,
      realId: session?.realId ?? null,
    };
  }

  private patchLastUserMessage(
    messages: IAgentScopeRuntimeWebUIMessage[],
    generating: boolean,
    backendSessionId: string,
  ): void {
    if (!generating) {
      clearPendingUserMessage(backendSessionId);
      return;
    }

    const cachedText = loadPendingUserMessage(backendSessionId);
    if (!cachedText) return;

    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.role === ROLE_USER) {
      const text = extractTextFromContent(
        lastMessage?.cards?.[0]?.data?.input?.[0]?.content,
      );
      if (!text) {
        lastMessage.cards = buildUserCard({
          content: [{ type: "text", text: cachedText }],
          role: ROLE_USER,
        }).cards;
      }
      return;
    }

    messages.push(
      buildUserCard({
        content: [{ type: "text", text: cachedText }],
        role: ROLE_USER,
      }),
    );
  }

  private createEmptySession(sessionId: string): ExtendedSession {
    return {
      id: sessionId,
      name: DEFAULT_SESSION_NAME,
      sessionId,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
      messages: [],
      meta: {},
    } as ExtendedSession;
  }

  private getLocalSession(sessionId: string): IAgentScopeRuntimeWebUISession {
    const local = this.findSession(sessionId);
    if (local) {
      return local;
    }
    return this.createEmptySession(sessionId);
  }

  private async waitForRealId(sessionId: string): Promise<ExtendedSession | undefined> {
    const startedAt = Date.now();
    while (Date.now() - startedAt < LOCAL_SESSION_REAL_ID_WAIT_TIMEOUT_MS) {
      const target = this.findSession(sessionId);
      if (target?.realId) {
        return target;
      }
      await new Promise((resolve) =>
        window.setTimeout(resolve, LOCAL_SESSION_REAL_ID_POLL_INTERVAL_MS),
      );
    }
    return this.findSession(sessionId);
  }

  private applyChatsToSessionList(chats: any[]): IAgentScopeRuntimeWebUISession[] {
    const newList = chats
      .filter((chat) => chat.id && chat.id !== "undefined" && chat.id !== "null")
      .map(chatSpecToSession)
      .reverse();

    this.sessionList = newList.map((session) => {
      const existing = this.sessionList.find(
        (item) =>
          (item as ExtendedSession).sessionId === (session as ExtendedSession).sessionId,
      ) as ExtendedSession | undefined;
      if (!existing) return session;

      const next = { ...session } as ExtendedSession;
      if (existing.realId) {
        next.id = existing.id;
        next.realId = existing.realId;
      }
      if (existing.generating !== undefined) {
        next.generating = existing.generating;
      }
      return next as IAgentScopeRuntimeWebUISession;
    });

    if (this.preferredChatId) {
      const preferredId = this.preferredChatId;
      this.preferredChatId = null;
      const targetIndex = this.sessionList.findIndex((session) => session.id === preferredId);
      if (targetIndex > 0) {
        const [preferred] = this.sessionList.splice(targetIndex, 1);
        this.sessionList.unshift(preferred);
      }
    }

    return [...this.sessionList];
  }

  async getSessionList() {
    if (this.sessionListRequest) return this.sessionListRequest;

    this.sessionListRequest = (async () => {
      try {
        const chats = await listChats(this.agentId, {
          user_id: DEFAULT_USER_ID,
          channel: DEFAULT_CHANNEL,
        });
        return this.applyChatsToSessionList(chats as any[]);
      } finally {
        this.sessionListRequest = null;
      }
    })();

    return this.sessionListRequest;
  }

  async getSession(sessionId: string) {
    const existingRequest = this.sessionRequests.get(sessionId);
    if (existingRequest) return existingRequest;

    const requestPromise = this.doGetSession(sessionId);
    this.sessionRequests.set(sessionId, requestPromise);

    try {
      const session = await requestPromise;
      if (sessionId !== this.lastSelectedSessionId) {
        this.lastSelectedSessionId = sessionId;
      }
      return session;
    } finally {
      this.sessionRequests.delete(sessionId);
    }
  }

  private async buildHistoryMessages(chatId: string, chatHistory: any) {
    const messages = convertMessages(chatHistory.messages || []);
    if (!isGenerating(chatHistory) && messages.at(-1)?.role !== ROLE_ASSISTANT) {
      try {
        const recovery = await getChatTraceRecovery(this.agentId, chatId);
        if (recovery.available && recovery.message) {
          messages.push(buildResponseCard([recovery.message]));
        }
      } catch {
        // The canonical QwenPaw history remains usable when trace recovery is unavailable.
      }
    }
    return messages;
  }

  private async doGetSession(sessionId: string): Promise<IAgentScopeRuntimeWebUISession> {
    if (isLocalTimestamp(sessionId)) {
      const fromList = this.sessionList.find((session) => session.id === sessionId) as
        | ExtendedSession
        | undefined;

      if (fromList?.realId) {
        const chatHistory = await getChatHistory(this.agentId, fromList.realId);
        const generating = isGenerating(chatHistory);
        const messages = await this.buildHistoryMessages(fromList.realId, chatHistory);
        this.patchLastUserMessage(messages, generating, fromList.realId);
        const session: ExtendedSession = {
          id: sessionId,
          name: fromList.name || DEFAULT_SESSION_NAME,
          sessionId: fromList.sessionId || sessionId,
          userId: fromList.userId || DEFAULT_USER_ID,
          channel: fromList.channel || DEFAULT_CHANNEL,
          messages,
          meta: fromList.meta || {},
          realId: fromList.realId,
          generating,
        };
        return session;
      }

      const refreshed = await this.waitForRealId(sessionId);
      if (refreshed?.realId) {
        const chatHistory = await getChatHistory(this.agentId, refreshed.realId);
        const generating = isGenerating(chatHistory);
        const messages = await this.buildHistoryMessages(refreshed.realId, chatHistory);
        this.patchLastUserMessage(messages, generating, refreshed.realId);
        const session: ExtendedSession = {
          id: sessionId,
          name: refreshed.name || DEFAULT_SESSION_NAME,
          sessionId: refreshed.sessionId || sessionId,
          userId: refreshed.userId || DEFAULT_USER_ID,
          channel: refreshed.channel || DEFAULT_CHANNEL,
          messages,
          meta: refreshed.meta || {},
          realId: refreshed.realId,
          generating,
        };
        return session;
      }

      return this.getLocalSession(sessionId);
    }

    if (!sessionId || sessionId === "undefined" || sessionId === "null") {
      return this.createEmptySession(Date.now().toString());
    }

    const fromList = this.sessionList.find((session) => session.id === sessionId) as
      | ExtendedSession
      | undefined;
    const chatHistory = await getChatHistory(this.agentId, sessionId);
    const generating = isGenerating(chatHistory);
    const messages = await this.buildHistoryMessages(sessionId, chatHistory);
    this.patchLastUserMessage(messages, generating, sessionId);

    const session: ExtendedSession = {
      id: sessionId,
      name: fromList?.name || sessionId,
      sessionId: fromList?.sessionId || sessionId,
      userId: fromList?.userId || DEFAULT_USER_ID,
      channel: fromList?.channel || DEFAULT_CHANNEL,
      messages,
      meta: fromList?.meta || {},
      generating,
    };
    return session;
  }

  async updateSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    const { messages: _messages, ...metadata } = session;
    const targetIndex = this.sessionList.findIndex((item) => item.id === metadata.id);

    if (targetIndex > -1) {
      this.sessionList[targetIndex] = { ...this.sessionList[targetIndex], ...metadata };

      const existing = this.sessionList[targetIndex] as ExtendedSession;
      if (isLocalTimestamp(existing.id) && !existing.realId) {
        const tempId = existing.id;
        this.getSessionList().then(() => {
          const { list } = resolveRealId(this.sessionList, tempId);
          this.sessionList = list;
        });
      }
    } else {
      const tempId = session.id!;
      await this.getSessionList().then(() => {
        const { list } = resolveRealId(this.sessionList, tempId);
        this.sessionList = list;
      });
    }

    const realId = this.getRealIdForSession(metadata.id || "");
    if (realId && metadata.name) {
      await updateChat(this.agentId, realId, { name: metadata.name });
    }

    return [...this.sessionList];
  }

  async createSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    session.id = Date.now().toString();
    const extended: ExtendedSession = {
      ...session,
      sessionId: session.id,
      userId: DEFAULT_USER_ID,
      channel: DEFAULT_CHANNEL,
    } as ExtendedSession;

    this.sessionList = [extended, ...this.sessionList];
    return [...this.sessionList];
  }

  async removeSession(session: Partial<IAgentScopeRuntimeWebUISession>) {
    if (!session.id) return [...this.sessionList];

    const existing = this.sessionList.find((item) => item.id === session.id) as
      | ExtendedSession
      | undefined;
    const deleteId =
      existing?.realId ?? (isLocalTimestamp(session.id) ? null : session.id);

    if (deleteId) {
      await deleteChat(this.agentId, deleteId);
    }

    this.sessionList = this.sessionList.filter((item) => item.id !== session.id);
    return [...this.sessionList];
  }
}

export function createPortalRuntimeSessionApi(agentId?: string) {
  return new PortalRuntimeSessionApi(agentId);
}
