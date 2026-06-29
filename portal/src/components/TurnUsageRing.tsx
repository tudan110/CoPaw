import React from "react";
import { Popover, Progress } from "antd";
import type { ContextUsage, TurnUsage } from "./turnUsage";

/**
 * Per-turn token + context usage indicator for the portal chat — a colored
 * ring (context-window usage) that opens a popover with this turn's token
 * counts. Takes the usage/context_usage captured from the ``turn_usage`` SSE
 * event directly (the portal digital-employee chat is a bespoke UI, not the
 * @agentscope-ai/chat SDK). Labels are hardcoded Chinese (portal has no i18n).
 */

const RING_SIZE = 18;
const RING_STROKE = 3;
const RING_R = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRC = 2 * Math.PI * RING_R;

/** Compact number: 1234 -> "1.2k", 1_200_000 -> "1.2m". */
function formatCompact(n: number): string {
  const v = Number(n) || 0;
  if (v < 1000) return String(Math.round(v));
  if (v < 1_000_000) return `${(v / 1000).toFixed(v < 10_000 ? 1 : 0)}k`;
  return `${(v / 1_000_000).toFixed(1)}m`;
}

function ringColor(ratio: number): string {
  if (ratio >= 95) return "#cf1322";
  if (ratio >= 85) return "#f5222d";
  if (ratio >= 75) return "#fa8c16";
  if (ratio >= 50) return "#faad14";
  return "#52c41a";
}

function clampRatio(value: unknown): number {
  return Math.max(0, Math.min(Number(value) || 0, 100));
}

function UsageRing({ ratio }: { ratio: number }) {
  const pct = clampRatio(ratio);
  const cx = RING_SIZE / 2;
  return (
    <svg width={RING_SIZE} height={RING_SIZE} aria-hidden>
      <circle
        cx={cx}
        cy={cx}
        r={RING_R}
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.2}
        strokeWidth={RING_STROKE}
      />
      <circle
        cx={cx}
        cy={cx}
        r={RING_R}
        fill="none"
        stroke={ringColor(pct)}
        strokeWidth={RING_STROKE}
        strokeDasharray={`${RING_CIRC} ${RING_CIRC}`}
        strokeDashoffset={RING_CIRC * (1 - pct / 100)}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cx})`}
      />
    </svg>
  );
}

function PopoverBody({
  usage,
  context,
}: {
  usage: TurnUsage | null;
  context: ContextUsage | null;
}) {
  const ratio = context ? clampRatio(context.context_usage_ratio) : 0;
  const pctLabel =
    ratio > 0 && ratio < 1 ? `${ratio.toFixed(1)}%` : `${Math.round(ratio)}%`;

  return (
    <div style={{ width: 280, fontSize: 13, lineHeight: 1.5 }}>
      {usage && (
        <div style={{ marginBottom: context ? 12 : 0 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {usage.estimated ? "本轮约" : "本轮"}{" "}
            {formatCompact(usage.total_tokens || 0)} token
          </div>
          <div style={{ opacity: 0.75 }}>
            输入 {formatCompact(usage.prompt_tokens || 0)} · 输出{" "}
            {formatCompact(usage.completion_tokens || 0)}
          </div>
        </div>
      )}
      {context && (
        <>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              marginBottom: 6,
            }}
          >
            <span style={{ fontWeight: 600 }}>上下文窗口：{pctLabel}</span>
            <span style={{ opacity: 0.75, fontSize: 12 }}>
              {formatCompact(context.estimated_tokens)}/
              {formatCompact(context.max_input_length)}
            </span>
          </div>
          <Progress
            percent={ratio}
            showInfo={false}
            strokeColor={ringColor(ratio)}
            size="small"
          />
        </>
      )}
    </div>
  );
}

const TurnUsageRing: React.FC<{
  usage?: TurnUsage | null;
  context_usage?: ContextUsage | null;
}> = ({ usage = null, context_usage = null }) => {
  const hasUsage =
    !!usage &&
    ((Number(usage.total_tokens) || 0) > 0 ||
      (Number(usage.prompt_tokens) || 0) +
        (Number(usage.completion_tokens) || 0) >
        0);
  const hasCtx =
    !!context_usage && (Number(context_usage.estimated_tokens) || 0) > 0;
  if (!hasUsage && !hasCtx) {
    return null;
  }

  const ratio = hasCtx ? clampRatio(context_usage!.context_usage_ratio) : 0;

  return (
    <Popover
      trigger={["hover", "click"]}
      mouseEnterDelay={0.15}
      content={
        <PopoverBody
          usage={hasUsage ? usage : null}
          context={hasCtx ? context_usage : null}
        />
      }
    >
      <span
        role="button"
        tabIndex={0}
        aria-label="查看本轮 Token 与上下文用量"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "default",
          color: "inherit",
          opacity: 0.65,
          padding: "0 2px",
        }}
      >
        {hasCtx ? (
          <UsageRing ratio={ratio} />
        ) : (
          <span style={{ fontSize: 12, fontWeight: 600 }}>tok</span>
        )}
      </span>
    </Popover>
  );
};

export default TurnUsageRing;
