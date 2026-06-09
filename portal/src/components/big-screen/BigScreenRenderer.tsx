// Side-effect import: registerWidgets mutates COMPONENT_REGISTRY at module
// load, so it MUST run before any registry lookup below.
import "./widgets/registerWidgets.tsx";

import {
  normalizeSpec,
  type DashboardSpec,
  type ScreenComponent,
  type VisualSpec,
} from "./types.ts";
import { ScreenStage } from "./panels/ScreenStage.tsx";
import { AuroraBackground } from "./panels/AuroraBackground.tsx";
import { ParticleLayer } from "./panels/ParticleLayer.tsx";
import { GlassPanel } from "./panels/GlassPanel.tsx";
import { COMPONENT_REGISTRY, resolveComponentType } from "./registry.ts";
import { visualSpecClassTokens } from "./visualSpec.ts";
import { computeAutoLayout } from "./autoLayout.ts";

/** Honest L2 status: failed/empty render an explicit note instead of an
 *  empty/broken-looking widget body. gap/live fall through to the widget. */
function StatusNote({ kind, text }: { kind: "failed" | "empty"; text: string }) {
  const color = kind === "failed" ? "#f87171" : "#9fb2cc";
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        color,
        fontSize: 12,
        textAlign: "center",
        padding: "0 10px",
      }}
    >
      <span style={{ fontSize: 18, opacity: 0.85 }}>
        {kind === "failed" ? "⚠" : "∅"}
      </span>
      <span>{text}</span>
    </div>
  );
}

function ComponentBody({ component }: { component: ScreenComponent }) {
  const status = component.data?.sourceStatus;
  if (status === "failed") {
    return (
      <StatusNote kind="failed" text={component.data?.message ?? "数据获取失败"} />
    );
  }
  if (status === "empty") {
    return (
      <StatusNote kind="empty" text={component.data?.message ?? "暂无数据"} />
    );
  }
  const Widget = COMPONENT_REGISTRY[resolveComponentType(component.type)];
  if (!Widget) {
    return <StatusNote kind="empty" text={`未知组件: ${component.type}`} />;
  }
  return <Widget component={component} />;
}

const DEFAULT_POS = { x: 0, y: 0, w: 480, h: 280 };

/** Derive a relative size weight from the component's visual role, used by the
 *  auto-layout engine when a spec ships without explicit coordinates. */
function weightOf(vs: VisualSpec | undefined): number {
  switch (vs?.composition) {
    case "primary":
      return 3;
    case "secondary":
      return 1.6;
    case "supporting":
      return 0.9;
    default:
      return 1.2;
  }
}

/**
 * BigScreenRenderer — turns a DashboardSpec into the full D-max screen.
 *
 * Layout: a full-viewport `.bs-root` holds the ScreenStage, which letterboxes
 * a fixed design canvas (default 1920×1080) scaled to fit ("contain", so
 * nothing is cropped — buttons never pushed off-screen). Aurora + particles
 * are passed as the stage `background` so they fill the entire viewport
 * behind the scaled content — no empty bands at any aspect ratio.
 */
interface BigScreenRendererProps {
  spec: DashboardSpec;
  /** Optional authoring interaction — same contract as the legacy renderer. */
  interactive?: boolean;
  selectedComponentId?: string;
  selectedComponentIds?: string[];
  onSelectComponent?: (
    componentId: string,
    options?: { additive?: boolean },
  ) => void;
}

export function BigScreenRenderer({
  spec,
  interactive = false,
  selectedComponentId = "",
  selectedComponentIds = [],
  onSelectComponent,
}: BigScreenRendererProps) {
  const s = normalizeSpec(spec);
  const selectedSet = new Set(
    [selectedComponentId, ...selectedComponentIds].filter(Boolean),
  );

  // Coordinate-free specs (AI-generated) carry no layoutPosition → run the
  // auto-layout engine over per-component weights so panels fill the canvas
  // with no overlap, for any component count. Fully hand-positioned specs
  // (e.g. the D-max fixture) are used as authored.
  const autoPos =
    s.components.length > 0 && s.components.some((c) => !c.layoutPosition)
      ? new Map(
          computeAutoLayout(
            s.components.map((c) => ({
              id: c.id,
              weight: weightOf(c.visualSpec),
            })),
            { width: s.layout.designWidth, height: s.layout.designHeight },
          ).map((r) => [r.id, r]),
        )
      : null;

  return (
    <div
      className="bs-root"
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
      }}
    >
      <ScreenStage
        design={s.layout}
        mode="contain"
        background={
          <>
            <AuroraBackground />
            <ParticleLayer />
          </>
        }
      >
        {s.components.map((c) => {
          const pos = c.layoutPosition ?? autoPos?.get(c.id) ?? DEFAULT_POS;
          const vsClasses = visualSpecClassTokens(c.visualSpec).join(" ");
          const selected = selectedSet.has(c.id);
          return (
            <div
              key={c.id}
              style={{
                position: "absolute",
                left: pos.x,
                top: pos.y,
                width: pos.w,
                height: pos.h,
                borderRadius: 14,
                cursor: interactive ? "pointer" : undefined,
                outline: selected ? "2px solid #22d3ee" : undefined,
                outlineOffset: -2,
              }}
              onClick={
                interactive
                  ? (e) =>
                      onSelectComponent?.(c.id, {
                        additive: e.shiftKey || e.metaKey || e.ctrlKey,
                      })
                  : undefined
              }
            >
              <GlassPanel
                title={c.title}
                sourceStatus={c.data?.sourceStatus}
                className={vsClasses}
                style={{ width: "100%", height: "100%" }}
              >
                <ComponentBody component={c} />
              </GlassPanel>
            </div>
          );
        })}
      </ScreenStage>
    </div>
  );
}
