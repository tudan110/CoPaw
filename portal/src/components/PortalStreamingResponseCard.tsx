import { memo, useCallback, useMemo, type ComponentProps, type CSSProperties, type ReactNode } from "react";
import { Bubble, Markdown } from "@agentscope-ai/chat";
import { Avatar, Flex } from "antd";
import DefaultResponseCard from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Card";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import Actions from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Actions";
import ErrorCard from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Error";
import Reasoning from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Reasoning";
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
  type IAgentScopeRuntimeContent,
  type IAgentScopeRuntimeMessage,
  type IAgentScopeRuntimeResponse,
} from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";

type ResponseCardProps = ComponentProps<typeof DefaultResponseCard>;

const RAW_TEXT_STYLE: CSSProperties = {
  margin: "8px 0",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  overflowWrap: "anywhere",
};

const RAW_BLOCK_STYLE: CSSProperties = {
  margin: "8px 0",
  padding: "12px 14px",
  borderRadius: 12,
  background: "rgba(15, 23, 42, 0.04)",
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  overflowWrap: "anywhere",
};

function isGeneratingStatus(status?: string): boolean {
  return (
    status === AgentScopeRuntimeRunStatus.Created ||
    status === AgentScopeRuntimeRunStatus.InProgress
  );
}

function hasGeneratingContent(content?: IAgentScopeRuntimeContent[] | null): boolean {
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
            return (
              <pre key={index} style={RAW_BLOCK_STYLE}>
                {JSON.stringify(item.data, null, 2)}
              </pre>
            );
          default:
            return (
              <pre key={index} style={RAW_BLOCK_STYLE}>
                {JSON.stringify(item, null, 2)}
              </pre>
            );
        }
      })}
    </>
  );
});

export default function PortalStreamingResponseCard(
  props: ResponseCardProps,
): ReactNode {
  const isGenerating = isGeneratingResponse(props.data);
  const avatar = useChatAnywhereOptions((value) => value.welcome.avatar);
  const nick = useChatAnywhereOptions((value) => value.welcome.nick);
  const messages = useMemo(
    () => AgentScopeRuntimeResponseBuilder.mergeToolMessages(props.data.output),
    [props.data.output],
  );

  if (!isGenerating) {
    return <DefaultResponseCard {...props} />;
  }

  if (!messages?.length && AgentScopeRuntimeResponseBuilder.maybeGenerating(props.data)) {
    return <Bubble.Spin />;
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
            return <Tool key={item.id} data={item} />;
          case AgentScopeRuntimeMessageType.MCP_APPROVAL_REQUEST:
            return <Tool key={item.id} data={item} isApproval />;
          case AgentScopeRuntimeMessageType.REASONING:
            return <Reasoning key={item.id} data={item} />;
          case AgentScopeRuntimeMessageType.ERROR:
            return <ErrorCard key={item.id} data={item} />;
          case AgentScopeRuntimeMessageType.HEARTBEAT:
            return null;
          default:
            console.warn(`[WIP] Unknown message type: ${item.type}`);
            return null;
        }
      })}
      {props.data.error ? <ErrorCard data={props.data.error} /> : null}
      <Actions {...props} />
    </>
  );
}
