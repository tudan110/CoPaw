import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
  type CSSProperties,
  type ReactNode,
} from "react";
import { Bubble, Markdown } from "@agentscope-ai/chat";
import { Avatar, Flex } from "antd";
import DefaultResponseCard from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Card";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import Actions from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Actions";
// Tool is kept ONLY for MCP approval requests (informed-consent detail is
// wanted there); normal tool steps render as friendly one-liners instead.
import Tool from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Tool";
import { useChatAnywhereOptions } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereOptionsContext";
import Images from "@agentscope-ai/chat/lib/DefaultCards/Images";
import Videos from "@agentscope-ai/chat/lib/DefaultCards/Videos";
import Files from "@agentscope-ai/chat/lib/DefaultCards/Files";
import Audios from "@agentscope-ai/chat/lib/DefaultCards/Audios";
import {
  AgentScopeRuntimeContentType,
  AgentScopeRuntimeMessageType,
  AgentScopeRuntimeRunStatus,
  type IAgentScopeRuntimeMessage,
  type IAgentScopeRuntimeResponse,
} from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import {
  getPortalOrderDetailMarkdownContentFromRuntimeOutput,
  hasPortalOrderDetailPayloadContent,
  parsePortalOrderDetailPayloadFromRuntimeOutput,
  PortalOrderDetailReport,
} from "./PortalOrderDetailReport";
import { runtimeErrorToFriendly } from "../lib/chatErrorMessage";
import { extractToolName, toolActivityLabel } from "../lib/agentActivityLabels";

type ResponseCardProps = ComponentProps<typeof DefaultResponseCard>;

const RAW_TEXT_STYLE: CSSProperties = {
  margin: "8px 0",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  overflowWrap: "anywhere",
};

// Friendly one-line activity indicator for a tool / reasoning step.
const ACTIVITY_LINE_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  margin: "6px 0",
  padding: "6px 10px",
  borderRadius: 8,
  color: "#475569",
  background: "rgba(15, 23, 42, 0.03)",
  fontSize: 13,
  lineHeight: 1.6,
};

// Friendly error line — a single reassuring sentence, never a raw stack.
const ERROR_LINE_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: 8,
  margin: "8px 0",
  padding: "10px 12px",
  borderRadius: 10,
  color: "#b45309",
  background: "rgba(251, 191, 36, 0.12)",
  border: "1px solid rgba(245, 158, 11, 0.24)",
  fontSize: 13,
  lineHeight: 1.6,
};

const STREAM_NOTICE_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  margin: "8px 0",
  padding: "8px 10px",
  borderRadius: 8,
  color: "#92400e",
  background: "rgba(251, 191, 36, 0.14)",
  border: "1px solid rgba(245, 158, 11, 0.24)",
  fontSize: 13,
  lineHeight: 1.6,
};

function isGeneratingStatus(status?: string): boolean {
  return (
    status === AgentScopeRuntimeRunStatus.Created ||
    status === AgentScopeRuntimeRunStatus.InProgress
  );
}

function hasGeneratingContent(content?: Array<{ status?: string }> | null): boolean {
  return Array.isArray(content)
    ? content.some((item) => isGeneratingStatus(item?.status))
    : false;
}

function hasGeneratingMessages(messages?: IAgentScopeRuntimeMessage[] | null): boolean {
  return Array.isArray(messages)
    ? messages.some(
        (item) =>
          isGeneratingStatus(item?.status) || hasGeneratingContent(item?.content),
      )
    : false;
}

function isGeneratingResponse(data: IAgentScopeRuntimeResponse): boolean {
  return isGeneratingStatus(data.status) || hasGeneratingMessages(data.output);
}

function getStreamingActivityKey(data: IAgentScopeRuntimeResponse): string {
  const messages = data.output || [];
  return messages
    .map((message) => {
      const contentKey = (message.content || [])
        .map((item) => {
          if (item.type === AgentScopeRuntimeContentType.TEXT) {
            return `${item.type}:${String(item.text || "").length}:${item.status || ""}`;
          }
          if (item.type === AgentScopeRuntimeContentType.REFUSAL) {
            return `${item.type}:${String(item.refusal || "").length}:${item.status || ""}`;
          }
          return `${item.type}:${item.status || ""}`;
        })
        .join(",");
      return `${message.id || ""}:${message.type || ""}:${message.status || ""}:${contentKey}`;
    })
    .join("|");
}

function useStreamingWaitNotice(
  isGenerating: boolean,
  activityKey: string,
): string {
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!isGenerating) {
      setNotice("");
      return undefined;
    }

    setNotice("");
    const timers = [
      window.setTimeout(() => {
        setNotice("正在等待模型返回内容，请稍候。");
      }, 12000),
      window.setTimeout(() => {
        setNotice("LLM 响应时间较长，后端可能正在等待上游模型或自动重试，请继续等待。");
      }, 45000),
      window.setTimeout(() => {
        setNotice("仍未收到新的模型内容，请检查 LLM 服务、DNS 或网络状态；当前请求可能仍在后端重试。");
      }, 90000),
    ];

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [activityKey, isGenerating]);

  return notice;
}

function StreamingWaitNotice({ notice }: { notice: string }) {
  if (!notice) {
    return null;
  }

  return (
    <div style={STREAM_NOTICE_STYLE} role="status" aria-live="polite">
      <span aria-hidden="true">...</span>
      <span>{notice}</span>
    </div>
  );
}

const StreamingMessage = memo(function StreamingMessage({
  data,
}: {
  data: IAgentScopeRuntimeMessage;
}) {
  const replaceMediaURL = useChatAnywhereOptions((value) => value.api?.replaceMediaURL);
  const formatMediaURL = useCallback(
    (url?: string) => {
      if (!url) return url;
      return replaceMediaURL?.(url) || url;
    },
    [replaceMediaURL],
  );

  if (!data.content?.length) return null;

  return (
    <>
      {data.content.map((item, index) => {
        switch (item.type) {
          case AgentScopeRuntimeContentType.TEXT:
            return (
              <div key={index} style={RAW_TEXT_STYLE}>
                <Markdown raw content={item.text || ""} />
              </div>
            );
          case AgentScopeRuntimeContentType.REFUSAL:
            return (
              <div key={index} style={RAW_TEXT_STYLE}>
                <Markdown raw content={item.refusal || ""} />
              </div>
            );
          case AgentScopeRuntimeContentType.IMAGE:
            return <Images key={index} data={[{ url: formatMediaURL(item.image_url) }]} />;
          case AgentScopeRuntimeContentType.VIDEO:
            return (
              <Videos
                key={index}
                data={[
                  {
                    src: formatMediaURL(item.video_url),
                    poster: formatMediaURL(item.video_poster),
                  },
                ]}
              />
            );
          case AgentScopeRuntimeContentType.FILE:
            return (
              <Files
                key={index}
                data={[
                  {
                    url: formatMediaURL(item.file_url),
                    name: item.file_name || item.fileName || item.file_id,
                    size: item.file_size,
                  },
                ]}
              />
            );
          case AgentScopeRuntimeContentType.AUDIO:
            return (
              <Audios
                key={index}
                data={[{ src: formatMediaURL(item.audio_url || item.data) }]}
              />
            );
          case AgentScopeRuntimeContentType.DATA:
            // Structured payloads are internal detail — never dump raw JSON at
            // the user. Visualizations render via dedicated blocks elsewhere.
            return null;
          default:
            return null;
        }
      })}
    </>
  );
});

// One friendly line per tool step — the raw arguments and output stay in the
// Traces Center, not in the conversation.
function PortalAgentActivityLine({
  data,
}: {
  data: IAgentScopeRuntimeMessage;
}) {
  const running =
    data.status === AgentScopeRuntimeRunStatus.InProgress ||
    data.status === AgentScopeRuntimeRunStatus.Created;
  const label = toolActivityLabel(extractToolName(data), { done: !running });
  return (
    <div style={ACTIVITY_LINE_STYLE} role="status" aria-live="polite">
      <span>{label}</span>
    </div>
  );
}

// Surface a subtle "thinking" line only while reasoning is in progress; once
// done it is internal noise, so drop it and let the answer speak.
function PortalReasoningLine({
  data,
}: {
  data: IAgentScopeRuntimeMessage;
}) {
  if (data.status !== AgentScopeRuntimeRunStatus.InProgress) {
    return null;
  }
  return (
    <div style={ACTIVITY_LINE_STYLE} role="status" aria-live="polite">
      <span>🧠 正在思考…</span>
    </div>
  );
}

// A single reassuring sentence in place of any raw error / traceback.
function PortalFriendlyError({ errorLike }: { errorLike: unknown }) {
  const message = runtimeErrorToFriendly(errorLike);
  if (!message) {
    return null;
  }
  return (
    <div style={ERROR_LINE_STYLE} role="alert">
      <span aria-hidden="true">⚠️</span>
      <span>{message}</span>
    </div>
  );
}

export default function PortalStreamingResponseCard(
  props: ResponseCardProps,
): ReactNode {
  const isGenerating = isGeneratingResponse(props.data);
  const avatar = useChatAnywhereOptions((value) => value.welcome.avatar);
  const nick = useChatAnywhereOptions((value) => value.welcome.nick);
  const activityKey = useMemo(
    () => getStreamingActivityKey(props.data),
    [props.data],
  );
  const waitNotice = useStreamingWaitNotice(isGenerating, activityKey);
  const messages = useMemo(
    () => AgentScopeRuntimeResponseBuilder.mergeToolMessages(props.data.output),
    [props.data.output],
  );
  const orderDetailPayload = useMemo(
    () => parsePortalOrderDetailPayloadFromRuntimeOutput(props.data.output),
    [props.data.output],
  );
  const orderDetailMarkdown = useMemo(
    () => getPortalOrderDetailMarkdownContentFromRuntimeOutput(props.data.output),
    [props.data.output],
  );
  const shouldRenderOrderDetailCard = orderDetailPayload
    ? hasPortalOrderDetailPayloadContent(orderDetailPayload)
    : false;

  if (orderDetailPayload) {
    return (
      <>
        <div className="order-detail-composite">
          {orderDetailMarkdown ? (
            <div className="order-detail-markdown">
              <Markdown raw content={orderDetailMarkdown} />
            </div>
          ) : null}
          {shouldRenderOrderDetailCard ? (
            <PortalOrderDetailReport payload={orderDetailPayload} />
          ) : null}
        </div>
        {props.data.error ? <PortalFriendlyError errorLike={props.data.error} /> : null}
        <Actions {...props} />
      </>
    );
  }

  if (!messages?.length && AgentScopeRuntimeResponseBuilder.maybeGenerating(props.data)) {
    return (
      <>
        <Bubble.Spin />
        <StreamingWaitNotice notice={waitNotice} />
      </>
    );
  }

  return (
    <>
      {avatar ? (
        <Flex align="center" gap={8} style={{ marginBottom: 8 }}>
          <Avatar src={avatar} />
          {nick ? <span>{String(nick)}</span> : null}
        </Flex>
      ) : null}
      {messages.map((item) => {
        switch (item.type) {
          case AgentScopeRuntimeMessageType.MESSAGE:
            return <StreamingMessage key={item.id} data={item} />;
          case AgentScopeRuntimeMessageType.PLUGIN_CALL:
          case AgentScopeRuntimeMessageType.PLUGIN_CALL_OUTPUT:
          case AgentScopeRuntimeMessageType.MCP_CALL:
          case AgentScopeRuntimeMessageType.MCP_CALL_OUTPUT:
            return <PortalAgentActivityLine key={item.id} data={item} />;
          case AgentScopeRuntimeMessageType.MCP_APPROVAL_REQUEST:
            return <Tool key={item.id} data={item} isApproval />;
          case AgentScopeRuntimeMessageType.REASONING:
            return <PortalReasoningLine key={item.id} data={item} />;
          case AgentScopeRuntimeMessageType.ERROR:
            return <PortalFriendlyError key={item.id} errorLike={item} />;
          case AgentScopeRuntimeMessageType.HEARTBEAT:
            return null;
          default:
            console.warn(`[WIP] Unknown message type: ${item.type}`);
            return null;
        }
      })}
      <StreamingWaitNotice notice={waitNotice} />
      {props.data.error ? <PortalFriendlyError errorLike={props.data.error} /> : null}
      <Actions {...props} />
    </>
  );
}
