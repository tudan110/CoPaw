import * as echarts from "echarts";

import { BS_PALETTE } from "./palettes.ts";

let registered = false;

// Re-exported for back-compat with callers that imported it from here.
export { BS_PALETTE };

export function registerDarkChartTheme(): string {
  if (!registered) {
    echarts.registerTheme("bs-dark", {
      color: BS_PALETTE,
      backgroundColor: "transparent",
      textStyle: { color: "#cbd6e8" },
      categoryAxis: {
        axisLine: { lineStyle: { color: "rgba(255,255,255,.18)" } },
        axisLabel: { color: "#9fb2cc" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } },
      },
      valueAxis: {
        axisLabel: { color: "#9fb2cc" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.06)" } },
      },
    });
    registered = true;
  }
  return "bs-dark";
}
