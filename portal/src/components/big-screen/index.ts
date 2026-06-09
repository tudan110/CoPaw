/** Public entry point for the big-screen module. */
export { BigScreenRenderer } from "./BigScreenRenderer.tsx";
export { DMAX_OPS_FIXTURE } from "./fixtures.ts";
export { normalizeSpec } from "./types.ts";
export type {
  DashboardSpec,
  ScreenComponent,
  CapabilityResult,
  VisualSpec,
  SourceStatus,
} from "./types.ts";
export {
  KNOWN_COMPONENT_TYPES,
  isKnownComponentType,
  resolveComponentType,
} from "./registry.ts";
