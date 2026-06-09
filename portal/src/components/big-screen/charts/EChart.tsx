import ReactECharts from "echarts-for-react";
import { registerDarkChartTheme } from "./darkTheme.ts";

// Register theme once at module load time
registerDarkChartTheme();

interface EChartProps {
  /** Plain echarts option object — no function literals. */
  option: Record<string, unknown>;
  style?: React.CSSProperties;
  className?: string;
}

/**
 * Thin echarts-for-react wrapper for big-screen widgets.
 * - Always uses bs-dark theme and canvas renderer.
 * - Accepts plain option objects only (no fn-literal configs).
 * - Fills its container by default.
 */
export function EChart({ option, style, className }: EChartProps) {
  return (
    <ReactECharts
      option={option}
      theme="bs-dark"
      opts={{ renderer: "canvas" }}
      style={{
        height: "100%",
        width: "100%",
        ...style,
      }}
      className={className}
      notMerge
      lazyUpdate
    />
  );
}
