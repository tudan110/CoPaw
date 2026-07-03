// Side-effect import: registerWidgets mutates COMPONENT_REGISTRY at module
// load, so it MUST run before any registry lookup below.
import "./widgets/registerWidgets.tsx";

import { useEffect } from "react";
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
import { pickAutoBand } from "./autoLayoutBands.ts";
import { computePatternLayout } from "./compositionLayout.ts";
import { intrinsicSize } from "./intrinsicSize.ts";
import { LAYOUT_MARGIN, gridToPx, pxToGrid, type Rect } from "./gridGeometry.ts";

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

/** Vertical band (design px, margin included) reserved for the screen title
 *  banner when the spec carries a name — auto components flow below it. */
const TITLE_BAND_HEIGHT = 96;

/**
 * Auto-layout for un-pinned components, reserving the vertical bands the
 * pinned components (and the title banner) occupy. The band is the largest
 * FREE gap — including the gap between the title band and a low-pinned
 * component — clamped on-canvas (see pickAutoBand; the old above/below
 * split could exile auto components below the visible canvas). With no
 * pinned components this is identical to plain auto-layout.
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
  const band = pickAutoBand(pinnedRects, design);
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
  /**
   * Reports every component's actual on-screen rect (grid-unit equivalent,
   * see pxToGrid) after each geometry recompute. Lets callers hand real
   * layout ground truth to the AI patch flow instead of the stored
   * (possibly stale/fictional, for un-pinned components) layoutPosition.
   */
  onLayoutComputed?: (
    rects: Record<string, { x: number; y: number; w: number; h: number }>,
  ) => void;
}

export function BigScreenRenderer({
  spec,
  interactive = false,
  selectedComponentId = "",
  selectedComponentIds = [],
  onSelectComponent,
  onLayoutComputed,
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
  const screenTitle = s.name.trim();
  // The title banner occupies a full-width band at the top; feeding it to
  // the band calculation as a synthetic pinned rect keeps auto components
  // from rendering underneath it.
  const reservedRects: Rect[] = [...pinnedRects.values()];
  if (screenTitle) {
    reservedRects.push({
      x: LAYOUT_MARGIN,
      y: 0,
      w: s.layout.designWidth - 2 * LAYOUT_MARGIN,
      h: TITLE_BAND_HEIGHT,
    });
  }
  const autoComponents = s.components.filter((c) => !c.layoutPosition);
  // Screen-level composition (T-018): when the planner picked a pattern and
  // the user hasn't taken manual control (no pinned components), lay auto
  // components out by role in the free band. Pattern preconditions unmet →
  // null → the content-packing auto layout, so plans degrade gracefully.
  const patternName = String(s.layoutPlan?.pattern ?? "");
  const patternPos =
    autoComponents.length && patternName && pinnedRects.size === 0
      ? computePatternLayout(
          patternName,
          autoComponents.map((c) => ({
            id: c.id,
            role: String(c.compositionRole ?? ""),
            ...intrinsicSize(c),
          })),
          s.layout,
          pickAutoBand(reservedRects, s.layout),
        )
      : null;
  const autoPos =
    patternPos ??
    (autoComponents.length
      ? layoutAutoAroundPinned(autoComponents, reservedRects, s.layout)
      : null);
  const resolvedRects = new Map<string, Rect>();
  for (const c of s.components) {
    resolvedRects.set(
      c.id,
      pinnedRects.get(c.id) ??
        c.layoutPosition ??
        autoPos?.get(c.id) ??
        DEFAULT_POS,
    );
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps -- `spec` fully
  // determines resolvedRects; re-deriving it here (vs. depending on the
  // Map, which is a fresh object every render) avoids firing on renders
  // that don't change geometry.
  useEffect(() => {
    if (!onLayoutComputed) return;
    const grid: Record<
      string,
      { x: number; y: number; w: number; h: number }
    > = {};
    for (const [id, rect] of resolvedRects) {
      grid[id] = pxToGrid(rect, s.layout);
    }
    onLayoutComputed(grid);
  }, [spec, onLayoutComputed]);

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
        {screenTitle ? (
          <div
            className="bs-screen-title"
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              height: TITLE_BAND_HEIGHT,
            }}
          >
            {screenTitle}
          </div>
        ) : null}
        {s.components.map((c) => {
          const pos = resolvedRects.get(c.id) ?? DEFAULT_POS;
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
