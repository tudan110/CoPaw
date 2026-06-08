import { useEffect, useRef, useState } from "react";
import { computeStageTransform, type FitMode } from "../layout.ts";

interface ScreenStageProps {
  design: { designWidth: number; designHeight: number };
  mode?: FitMode;
  children: React.ReactNode;
}

export function ScreenStage({
  design,
  mode = "contain",
  children,
}: ScreenStageProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) =>
      setVp({
        width: e.contentRect.width,
        height: e.contentRect.height,
      }),
    );
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const t = computeStageTransform(design, vp, mode);

  return (
    <div ref={ref} className="bs-stage-root">
      <div
        className="bs-stage"
        style={{
          width: design.designWidth,
          height: design.designHeight,
          transform: `translate(${t.offsetX}px, ${t.offsetY}px) scale(${t.scale})`,
          transformOrigin: "top left",
        }}
      >
        {children}
      </div>
    </div>
  );
}
