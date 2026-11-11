import type { Zone } from "../../api/twin";

// People who move on the plan (TWN-12, D-53; plan-pilot-twa §4, G-6, G-7). Each occupant has a
// stable spot in its zone, from a hash of its key on a jittered grid, so dots do not overlap or
// jump when the twin is read again. The drift and the walk to a new zone are CSS (a keyframe and
// a transition on the dot's transform), so reduced motion and Calm mode still them (styles.css).
// Pure.

const CELL = 16; // plan units between neighbouring spots
const MARGIN = 12;
const TOP = 26; // under the zone's name and count
const JITTER = 3;

export interface Spot {
  x: number;
  y: number;
}

/** FNV-1a: a small, stable hash of a key. */
export function hash(key: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Each key's spot in the zone: its own cell, the next free one if taken, jittered a little. */
export function spots(zone: Pick<Zone, "x" | "y" | "w" | "h">, keys: string[]): Map<string, Spot> {
  const cols = Math.max(1, Math.floor((zone.w - 2 * MARGIN) / CELL));
  const rows = Math.max(1, Math.floor((zone.h - TOP - MARGIN) / CELL));
  const cells = cols * rows;
  const taken = new Set<number>();
  const out = new Map<string, Spot>();
  // In hash order, so a key keeps its cell however the others are listed.
  for (const key of [...keys].sort((a, b) => hash(a) - hash(b) || a.localeCompare(b))) {
    const h = hash(key);
    let cell = h % cells;
    for (let probe = 0; probe < cells && taken.has(cell); probe++) cell = (cell + 1) % cells;
    taken.add(cell); // a zone fuller than its cells shares the last one
    const jx = ((h >>> 8) % (2 * JITTER + 1)) - JITTER;
    const jy = ((h >>> 16) % (2 * JITTER + 1)) - JITTER;
    out.set(key, {
      x: zone.x + MARGIN + CELL / 2 + (cell % cols) * CELL + jx,
      y: zone.y + TOP + CELL / 2 + Math.floor(cell / cols) * CELL + jy,
    });
  }
  return out;
}

/** Each dot drifts on its own: a delay and a period from its key (CSS custom properties). */
export function drift(key: string): { delay: string; period: string } {
  const h = hash(key);
  return { delay: `-${(h % 9000) / 1000}s`, period: `${6 + ((h >>> 4) % 50) / 10}s` };
}

/** A zone's fill grows a little stronger with its share of the people on site (§120 Q2). */
export function shareFill(count: number, onSite: number): string {
  const share = onSite > 0 ? count / onSite : 0;
  return `rgba(76, 144, 240, ${(0.03 + 0.2 * Math.min(1, share * 2)).toFixed(3)})`;
}
