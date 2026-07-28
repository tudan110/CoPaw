const DEFAULT_REQUEST_TIMEOUT_MS = 30000;

async function requestAlarmAnalystCardApi<T = unknown>(
  path: string,
  {
    agentId,
    init = {},
    timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  }: {
    agentId?: string;
    init?: RequestInit;
    timeoutMs?: number;
  } = {},
): Promise<T> {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`/portal-api${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        ...(init.headers || {}),
        ...(agentId ? { "X-Agent-Id": agentId } : {}),
      },
    });

    if (!response.ok) {
      throw new Error((await response.text()) || "告警分析卡片请求失败");
    }

    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("告警分析卡片请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}

export async function createAlarmAnalystCard(
  payload: Record<string, unknown>,
  { agentId }: { agentId?: string } = {},
) {
  return requestAlarmAnalystCardApi<{ matched?: boolean; card?: Record<string, unknown> | null }>(
    "/alarm-analyst/cards",
    {
      agentId,
      init: {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      },
    },
  );
}

export async function listAlarmAnalystCards(
  chatId: string,
  {
    sessionId,
    agentId,
  }: {
    sessionId: string;
    agentId?: string;
  },
) {
  return requestAlarmAnalystCardApi<{ cards?: Array<Record<string, unknown>> }>(
    `/alarm-analyst/cards/${encodeURIComponent(chatId)}?sessionId=${encodeURIComponent(sessionId)}`,
    { agentId },
  );
}

export async function createAlarmAnalystWorkorder(
  payload: Record<string, unknown>,
  { agentId }: { agentId?: string } = {},
) {
  return requestAlarmAnalystCardApi<{
    status?: string;
    proposalId?: string;
    workorderStatus?: Record<string, unknown> | null;
    workorderId?: string;
    processId?: string;
    message?: string;
  }>(
    "/alarm-analyst/workorders",
    {
      agentId,
      init: {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      },
    },
  );
}
