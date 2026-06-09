import { BigScreenRenderer } from "../components/big-screen/BigScreenRenderer.tsx";
import { DMAX_OPS_FIXTURE } from "../components/big-screen/fixtures.ts";
import "../components/big-screen/big-screen.css";

/**
 * Dev/QA preview of the D-max big-screen visual foundation (P1).
 * Renders the inline DMAX_OPS_FIXTURE full-viewport so the layout, glass
 * panels, map flying-lines, and status badges can be eyeballed at any
 * window size. Route: /big-screen-preview.
 */
export default function BigScreenPreviewPage() {
  return (
    <div style={{ position: "fixed", inset: 0, background: "#070c16" }}>
      <BigScreenRenderer spec={DMAX_OPS_FIXTURE} />
    </div>
  );
}
