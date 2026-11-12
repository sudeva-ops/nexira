import type { FlashTone } from "./useMotion";

// Pure helpers for the small charts and rings in ui/.

/** Counts of `times` in `n` equal buckets over the `spanMs` before `now`, oldest first. */
export function buckets(times: string[], now: number, spanMs: number, n: number): number[] {
  const out = new Array<number>(n).fill(0);
  const width = spanMs / n;
  for (const t of times) {
    const age = now - new Date(t).getTime();
    if (age < 0 || age >= spanMs) continue;
    const i = n - 1 - Math.floor(age / width);
    out[i] = (out[i] ?? 0) + 1;
  }
  return out;
}

/** Whether a series has anything to draw (GFX-07): an all-zero or empty series has no line. */
export function hasHistory(values: number[]): boolean {
  return values.some((v) => v > 0);
}

/** How much of a window is left at `now` (1 at `from`, 0 at `to` and after). */
export function remaining(from: string, to: string, now: number): number {
  const start = new Date(from).getTime();
  const end = new Date(to).getTime();
  if (end <= start) return 0;
  return Math.min(1, Math.max(0, (end - now) / (end - start)));
}

/** How a deadline ring is coloured: amber in its last quarter, red in its last tenth. */
export function ringTone(left: number): FlashTone {
  return left <= 0.1 ? "danger" : left <= 0.25 ? "warning" : "info";
}
