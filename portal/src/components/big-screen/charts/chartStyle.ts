/**
 * Resolve a controlled visualSpec.style into concrete echarts values.
 *
 * This is the single place that turns the declarative style vocabulary
 * (palette name, accentColor, lineOpacity, labelBrightness) into colours
 * the option builders consume — so the builders stay clean and there is
 * one home for palette mapping + brightness math. Everything here is data
 * (plain strings/numbers); nothing is executed.
 */
import type { VisualStyle } from "../types.ts";
import { AXIS_LABEL_COLOR, BS_PALETTE, PALETTES } from "./palettes.ts";

/**
 * Bare hex or plain colour name only — defence in depth over the backend
 * gate. Strict enough to be the sole frontend validator: it admits nothing
 * but `#rgb`/`#rrggbb` and plain alpha names, so no script/url/css can pass.
 */
const ACCENT_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$|^[a-zA-Z]{3,20}$/;

export interface ResolvedChartStyle {
  palette: string[];
  primary: string;
  secondary: string;
  labelColor: string;
  /** 0..1 user override for line/area/link alpha; null → builder default. */
  lineOpacity: number | null;
  /** multiplier for graph node size; 1 = unchanged. */
  nodeSizeScale: number;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

/** Lighten (amount>0) or darken (amount<0) a hex colour. amount ∈ -100..100. */
export function adjustBrightness(hex: string, amount: number): string {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return hex;
  const num = parseInt(m[1], 16);
  let r = (num >> 16) & 255;
  let g = (num >> 8) & 255;
  let b = num & 255;
  const t = clamp(amount, -100, 100) / 100;
  if (t >= 0) {
    r = Math.round(r + (255 - r) * t);
    g = Math.round(g + (255 - g) * t);
    b = Math.round(b + (255 - b) * t);
  } else {
    const k = 1 + t; // t<0 → k<1 darkens
    r = Math.round(r * k);
    g = Math.round(g * k);
    b = Math.round(b * k);
  }
  const hexOut = ((1 << 24) + (r << 16) + (g << 8) + b)
    .toString(16)
    .slice(1);
  return `#${hexOut}`;
}

/** hex (#rgb / #rrggbb) → rgba(); named colours are returned unchanged. */
export function withAlpha(color: string, alpha: number): string {
  const a = clamp(alpha, 0, 1);
  const m6 = /^#?([0-9a-fA-F]{6})$/.exec(color);
  if (m6) {
    const num = parseInt(m6[1], 16);
    return `rgba(${(num >> 16) & 255},${(num >> 8) & 255},${num & 255},${a})`;
  }
  const m3 = /^#?([0-9a-fA-F]{3})$/.exec(color);
  if (m3) {
    const [r, g, b] = m3[1].split("").map((c) => parseInt(c + c, 16));
    return `rgba(${r},${g},${b},${a})`;
  }
  return color;
}

export function resolveChartStyle(style?: VisualStyle): ResolvedChartStyle {
  const basePalette =
    (style?.palette && PALETTES[style.palette]) || BS_PALETTE;

  const rawAccent =
    typeof style?.accentColor === "string"
      ? style.accentColor.trim().slice(0, 20)
      : "";
  const accent = ACCENT_RE.test(rawAccent) ? rawAccent : "";
  const primary = accent || basePalette[0];
  // When an accent is given, lead the palette with it so series pick it up.
  const palette = accent ? [accent, ...basePalette] : basePalette;

  const brightness =
    typeof style?.labelBrightness === "number" ? style.labelBrightness : 0;
  const labelColor = brightness
    ? adjustBrightness(AXIS_LABEL_COLOR, brightness)
    : AXIS_LABEL_COLOR;

  const lineOpacity =
    typeof style?.lineOpacity === "number"
      ? clamp(style.lineOpacity, 0, 100) / 100
      : null;

  const nodeSizeScale =
    typeof style?.sizeScale === "number" ? clamp(style.sizeScale, 0.5, 2) : 1;

  return {
    palette,
    primary,
    secondary: basePalette[1] ?? primary,
    labelColor,
    lineOpacity,
    nodeSizeScale,
  };
}

/** Builder default when a component has no style. */
export const DEFAULT_CHART_STYLE: ResolvedChartStyle = resolveChartStyle();
