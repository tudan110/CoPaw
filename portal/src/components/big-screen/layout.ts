export interface DesignSize { designWidth: number; designHeight: number; }
export interface Viewport { width: number; height: number; }
export interface StageTransform { scale: number; offsetX: number; offsetY: number; }
export type FitMode = "contain" | "cover";

export function computeStageTransform(design: DesignSize, viewport: Viewport, mode: FitMode = "contain"): StageTransform {
  const sx = viewport.width / design.designWidth;
  const sy = viewport.height / design.designHeight;
  const scale = mode === "cover" ? Math.max(sx, sy) : Math.min(sx, sy);
  const offsetX = (viewport.width - design.designWidth * scale) / 2;
  const offsetY = (viewport.height - design.designHeight * scale) / 2;
  return { scale, offsetX, offsetY };
}
