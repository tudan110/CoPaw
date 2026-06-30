// Side-effect import: registerWidgets mutates COMPONENT_REGISTRY at module
// load, so it MUST run before any registry lookup below.
import "./widgets/registerWidgets.tsx";

import {
  normalizeSpec,
  type DashboardSpec,
  type ScreenComponent,
} from "./types.ts";
import { ScreenStage } from "./panels/ScreenStage.tsx";
import { AuroraBackground } from "./panels/AuroraBackground.tsx";
import { ParticleLayer } from "./panels/ParticleLayer.tsx";
import { GlassPanel } from "./panels/GlassPanel.tsx";
import { COMPONENT_REGISTRY, resolveComponentType } from "./registry.ts";
import { visualSpecClassTokens } from "./visualSpec.ts";
import { computeAutoLayout } from "./autoLayout.ts";
import { intrinsicSize } from "./intrinsicSize.ts";

/** Honest L2 status: failed/empty render an explicit note instead of an
 *  empty/broken-looking widget body. gap/live fall through to the widget. */
function StatusNote({
  kind,
  text,
}: {
  kind: "failed" | "empty";
  text: string;
}) {
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
      <StatusNote
        kind="failed"
        text={component.data?.message ?? "数据获取失败"}
      />
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

const LAYOUT_MARGIN = 24;
const GRID_COLS = 12;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Convert a pinned 12-col grid position (backend units) to design pixels. */
function gridToPx(
  lp: { x: number; y: number; w: number; h: number },
  design: { designWidth: number; designHeight: number },
): Rect {
  const colW = (design.designWidth - 2 * LAYOUT_MARGIN) / GRID_COLS;
  const rowH = (design.designHeight - 2 * LAYOUT_MARGIN) / GRID_COLS;
  return {
    x: LAYOUT_MARGIN + Math.max(0, lp.x) * colW,
    y: LAYOUT_MARGIN + Math.max(0, lp.y) * rowH,
    w: Math.max(1, lp.w) * colW,
    h: Math.max(1, lp.h) * rowH,
  };
}

/**
 * Auto-layout for un-pinned components, reserving the vertical band the
 * pinned components occupy so the two never overlap. v1: auto items flow into
 * the larger free band above or below the pinned span — overlap-safe and
 * predictable. With no pinned components this is identical to plain
 * auto-layout (zero change to generated screens).
 */
function layoutAutoAroundPinned(
  autoComponents: ScreenComponent[],
  pinnedRects: Rect[],
  design: { designWidth: number; designHeight: number },
): Map<string, Rect> {
  const items = autoComponents.map((c) => ({ id: c.id, ...intrinsicSize(c) }));
  if (items.length === 0) return new Map();
  if (pinnedRects.length === 0) {
    return new Map(
      computeAutoLayout(items, {
        width: design.designWidth,
        height: design.designHeight,
      }).map((r) => [r.id, r]),
    );
  }
  const top = LAYOUT_MARGIN;
  const bottom = design.designHeight - LAYOUT_MARGIN;
  const pinnedTop = Math.min(...pinnedRects.map((r) => r.y));
  const pinnedBottom = Math.max(...pinnedRects.map((r) => r.y + r.h));
  const above = pinnedTop - top;
  const below = bottom - pinnedBottom;
  const band =
    above >= below
      ? { y: top, height: Math.max(140, above) }
      : { y: pinnedBottom, height: Math.max(140, below) };
  const rects = computeAutoLayout(items, {
    width: design.designWidth,
    height: band.height,
  });
  return new Map(rects.map((r) => [r.id, { ...r, y: r.y + band.y }]));
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

  // Geometry resolution, three cases:
  //  • pinned (explicit user "move"): honour its 12-col grid coords (→ px).
  //  • un-positioned (AI-generated): auto-layout, reserving pinned bands so
  //    nothing overlaps — packed to content (sparse → compact + whitespace).
  //  • pixel-positioned (hand-authored fixture): used as authored.
  const pinnedRects = new Map<string, Rect>();
  for (const c of s.components) {
    if (c.layoutPosition?.pinned) {
      pinnedRects.set(c.id, gridToPx(c.layoutPosition, s.layout));
    }
  }
  const autoComponents = s.components.filter((c) => !c.layoutPosition);
  const autoPos = autoComponents.length
    ? layoutAutoAroundPinned(
        autoComponents,
        [...pinnedRects.values()],
        s.layout,
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
          const pos =
            pinnedRects.get(c.id) ??
            c.layoutPosition ??
            autoPos?.get(c.id) ??
            DEFAULT_POS;
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
