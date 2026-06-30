/**
 * Pure colour constants — NO echarts import, so the option builders, the
 * style resolver and their node:test suites never transitively load echarts.
 * darkTheme.ts (which does import echarts) reads BS_PALETTE from here.
 */

export const BS_PALETTE = ["#22d3ee", "#34d399", "#a78bfa", "#fb923c", "#f87171"];

/**
 * Named palettes the LLM/edit loop can select per component (style.palette)
 * or per screen (theme.palette). Keys mirror the backend ALLOWED_PALETTES;
 * each is a 5-colour series. Without this map "换暖色/冷色/高管风" had nothing
 * to switch to — the renderer only knew BS_PALETTE.
 */
export const PALETTES: Record<string, string[]> = {
  industrial: BS_PALETTE,
  professional: ["#38bdf8", "#818cf8", "#34d399", "#a3b8d8", "#f59e0b"],
  warm: ["#fb923c", "#f87171", "#fbbf24", "#fb7185", "#f472b6"],
  cool: ["#22d3ee", "#38bdf8", "#818cf8", "#5eead4", "#34d399"],
  executive: ["#e0b450", "#6ea8fe", "#c9a24b", "#9bb0cf", "#dd8452"],
  aurora: ["#34d399", "#22d3ee", "#a78bfa", "#5eead4", "#c084fc"],
  mono: ["#67e8f9", "#22d3ee", "#0ea5e9", "#7dd3fc", "#a5f3fc"],
};

export const DEFAULT_PALETTE = BS_PALETTE;
export const AXIS_LABEL_COLOR = "#9fb2cc";
