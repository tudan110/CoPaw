/**
 * Component registry — whitelist + dispatch contract.
 * JSX-free and pure so node:test can parse it without transformation.
 *
 * Widget components are registered here as they are implemented in Tasks 10-12.
 * Until then COMPONENT_REGISTRY is empty; KNOWN_COMPONENT_TYPES is the
 * AI-facing whitelist that never changes without explicit review.
 */

import type { FC } from "react";
import type { ScreenComponent } from "./types.ts";

/** Shared prop contract for every big-screen widget. */
export interface WidgetProps {
  component: ScreenComponent;
}

/**
 * The exhaustive whitelist of component types the AI is allowed to use.
 * Backed by a constant array so isKnownComponentType is independent of
 * COMPONENT_REGISTRY contents (registry can be empty during development).
 */
export const KNOWN_COMPONENT_TYPES = [
  "metric-kpi",
  "flip-number",
  "liquid-ball",
  "line-chart",
  "bar-chart",
  "area-chart",
  "donut",
  "gauge",
  "radar",
  "heatmap",
  "graph",
  "map-fly",
  "alarm-stream",
  "top-n",
  "risk-pulse",
  "funnel",
  "timeline",
  "bar3d",
  "text",
] as const;

export type KnownComponentType = (typeof KNOWN_COMPONENT_TYPES)[number];

/** Returns true iff `t` is in the whitelist array (not in registry contents). */
export function isKnownComponentType(t: string): boolean {
  return (KNOWN_COMPONENT_TYPES as readonly string[]).includes(t);
}

/**
 * Maps a raw component type to a renderer key: known types pass through,
 * anything else collapses to "unknown" so the renderer shows an explicit
 * placeholder instead of crashing. Pure + JSX-free so node:test can import it.
 */
export function resolveComponentType(t: string): string {
  return isKnownComponentType(t) ? t : "unknown";
}

/**
 * Live registry: populated by widget modules as they land (Tasks 10-12).
 * Empty until then — BigScreenRenderer falls back to an "unknown" placeholder.
 */
export const COMPONENT_REGISTRY: Record<string, FC<WidgetProps>> = {};
