/**
 * Band selection for auto-laid-out components around reserved regions
 * (user-pinned components + the screen-title band).
 *
 * The old heuristic only compared the space above the topmost reserved
 * rect with the space below the bottommost one. With a title band at the
 * very top plus a component pinned near the bottom, both ended up ~0 and
 * every auto component was shoved below the canvas (y ≥ designHeight) —
 * present in the data, invisible on screen. This picks the largest FREE
 * vertical gap instead (including gaps between reserved bands) and, when
 * no usable gap exists, clamps onto the canvas — visible overlap beats
 * invisible components.
 *
 * JSX-free and pure so node:test can import it directly — same pattern
 * as gridGeometry.ts / registry.ts.
 */

import { LAYOUT_MARGIN, type DesignSize, type Rect } from "./gridGeometry.ts";

export interface Band {
  y: number;
  height: number;
}

/** Auto-layout content reads badly below this height (matches the old
 *  Math.max(140, …) floor). */
export const MIN_BAND_HEIGHT = 140;

export function pickAutoBand(reserved: Rect[], design: DesignSize): Band {
  const top = LAYOUT_MARGIN;
  const bottom = design.designHeight - LAYOUT_MARGIN;
  if (reserved.length === 0) {
    return { y: top, height: bottom - top };
  }

  // Merge reserved rects into sorted, disjoint vertical intervals.
  const intervals = reserved
    .map((r): [number, number] => [r.y, r.y + r.h])
    .sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const [start, end] of intervals) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }

  // Free gaps within [top, bottom], including between reserved bands.
  const gaps: Band[] = [];
  let cursor = top;
  for (const [start, end] of merged) {
    if (start > cursor) {
      gaps.push({ y: cursor, height: start - cursor });
    }
    cursor = Math.max(cursor, end);
  }
  if (bottom > cursor) {
    gaps.push({ y: cursor, height: bottom - cursor });
  }

  let best: Band | null = null;
  for (const gap of gaps) {
    if (!best || gap.height > best.height) {
      best = gap;
    }
  }
  if (best && best.height >= MIN_BAND_HEIGHT) {
    return best;
  }

  // No usable gap — stay on-canvas below the first reserved band (usually
  // the title), overlapping whatever is there rather than vanishing.
  const firstReservedBottom = merged[0]?.[1] ?? top;
  const y = Math.max(
    top,
    Math.min(firstReservedBottom, bottom - MIN_BAND_HEIGHT),
  );
  return { y, height: Math.max(MIN_BAND_HEIGHT, bottom - y) };
}
