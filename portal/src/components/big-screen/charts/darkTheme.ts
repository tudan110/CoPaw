import * as echarts from "echarts";

let registered = false;

export const BS_PALETTE = ["#22d3ee", "#34d399", "#a78bfa", "#fb923c", "#f87171"];

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
