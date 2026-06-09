import { useLayoutEffect, useRef, useState } from "react";
import { computeStageTransform, type FitMode } from "../layout.ts";

interface ScreenStageProps {
  design: { designWidth: number; designHeight: number };
  mode?: FitMode;
  /** Full-bleed layers (aurora/particles) rendered inside the letterbox
   *  container but behind the scaled stage — fills the viewport so there
   *  are never empty bands, even when "contain" leaves letterbox margins. */
  background?: React.ReactNode;
  children: React.ReactNode;
}

export function ScreenStage({
  design,
  mode = "contain",
  background,
  children,
}: ScreenStageProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState({ width: 0, height: 0 });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Measure synchronously before paint so the stage (and any echarts
    // inside it) never initialise at scale(0) / 0×0.
    const rect = el.getBoundingClientRect();
    setVp({ width: rect.width, height: rect.height });
    const ro = new ResizeObserver(([e]) =>
      setVp({
        width: e.contentRect.width,
        height: e.contentRect.height,
      }),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const ready = vp.width > 0 && vp.height > 0;
  const t = computeStageTransform(design, vp, mode);

  return (
    <div ref={ref} className="bs-stage-root">
      {background}
      <div
        className="bs-stage"
        style={{
          width: design.designWidth,
          height: design.designHeight,
          transform: `translate(${t.offsetX}px, ${t.offsetY}px) scale(${t.scale})`,
          transformOrigin: "top left",
          visibility: ready ? "visible" : "hidden",
        }}
      >
        {children}
      </div>
    </div>
  );
}
