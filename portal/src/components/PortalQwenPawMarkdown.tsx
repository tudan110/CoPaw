import { memo, type ComponentProps } from "react";
import { Markdown } from "@agentscope-ai/chat";

type MarkdownComponents = ComponentProps<typeof Markdown>["components"];

type PortalQwenPawMarkdownProps = {
  className?: string;
  content: string;
  isStreaming?: boolean;
  components?: MarkdownComponents;
};

export const PortalQwenPawMarkdown = memo(function PortalQwenPawMarkdown({
  className,
  content,
  isStreaming = false,
  components,
}: PortalQwenPawMarkdownProps) {
  return (
    <div className={["portal-qwenpaw-markdown-host", className].filter(Boolean).join(" ")}>
      <Markdown
        content={content}
        cursor={isStreaming}
        baseFontSize={15}
        baseLineHeight={1.7}
        disableImage={false}
        allowHtml={false}
        animation={false}
        components={components}
      />
    </div>
  );
});
