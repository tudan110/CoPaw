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

/**
 * BigScreenRenderer — turns a DashboardSpec into the full D-max screen.
 *
 * Layout: a full-viewport `.bs-root` holds the ScreenStage, which letterboxes
 * a fixed design canvas (default 1920×1080) scaled to fit ("contain", so
 * nothing is cropped — buttons never pushed off-screen). Aurora + particles
 * are passed as the stage `background` so they fill the entire viewport
 * behind the scaled content — no empty bands at any aspect ratio.
 */
export function BigScreenRenderer({ spec }: { spec: DashboardSpec }) {
  const s = normalizeSpec(spec);
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
          const pos = c.layoutPosition ?? DEFAULT_POS;
          const vsClasses = visualSpecClassTokens(c.visualSpec).join(" ");
          return (
            <GlassPanel
              key={c.id}
              title={c.title}
              sourceStatus={c.data?.sourceStatus}
              className={vsClasses}
              style={{
                position: "absolute",
                left: pos.x,
                top: pos.y,
                width: pos.w,
                height: pos.h,
              }}
            >
              <ComponentBody component={c} />
            </GlassPanel>
          );
        })}
      </ScreenStage>
    </div>
  );
}
