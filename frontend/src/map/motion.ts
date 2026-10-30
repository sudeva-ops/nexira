import type { Flight } from "../api/flights";

// Map motion (pure parts): aircraft glide between position updates, flight paths
// move along, and a new incident's zone grows out from its centre.

export const GLIDE_MS = 4000;
export const GROW_MS = 1200;
export const DASH_STEP_MS = 90;

export type LonLat = [number, number];

const easeInOut = (k: number) => (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2);
export const easeOut = (k: number) => 1 - (1 - k) ** 3;

/** The point a fraction k of the way from a to b, the short way across the 180° meridian. */
export function lerpLonLat(a: LonLat, b: LonLat, k: number): LonLat {
  let dLon = b[0] - a[0];
  if (dLon > 180) dLon -= 360;
  if (dLon < -180) dLon += 360;
  let lon = a[0] + dLon * k;
  if (lon > 180) lon -= 360;
  if (lon < -180) lon += 360;
  return [lon, a[1] + (b[1] - a[1]) * k];
}

/** Flights placed k (0..1, eased) of the way from where they were drawn to where they are now. */
export function glideFlights(from: ReadonlyMap<string, LonLat>, to: Flight[], k: number): Flight[] {
  const eased = easeInOut(Math.min(1, Math.max(0, k)));
  return to.map((f) => {
    const start = from.get(f.id);
    if (!start || f.lon == null || f.lat == null) return f;
    const [lon, lat] = lerpLonLat(start, [f.lon, f.lat], eased);
    return { ...f, lon, lat };
  });
}

/** Where each flight is drawn, to glide from on the next update. */
export function positions(flights: Flight[]): Map<string, LonLat> {
  const out = new Map<string, LonLat>();
  for (const f of flights) if (f.lon != null && f.lat != null) out.set(f.id, [f.lon, f.lat]);
  return out;
}

// A dashed line seems to move when its dash pattern is shifted step by step.
export const DASH_FRAMES: number[][] = [
  [0, 4, 3],
  [0.5, 4, 2.5],
  [1, 4, 2],
  [1.5, 4, 1.5],
  [2, 4, 1],
  [2.5, 4, 0.5],
  [3, 4, 0],
  [0, 0.5, 3, 3.5],
  [0, 1, 3, 3],
  [0, 1.5, 3, 2.5],
  [0, 2, 3, 2],
  [0, 2.5, 3, 1.5],
  [0, 3, 3, 1],
  [0, 3.5, 3, 0.5],
];

/** How much of a new incident's zone is drawn, `elapsed` ms after it appeared (1 = all). */
export function growScale(elapsed: number): number {
  return elapsed >= GROW_MS ? 1 : easeOut(Math.max(0, elapsed) / GROW_MS);
}
