// The aircraft icon (D-24: nothing is downloaded at run time): a plane drawn on a canvas, pointing
// north, added to the map as an SDF image so each flight's colour and heading come from its data.

export const PLANE_ICON = "nx-plane";
const SIZE = 64;

/** The plane's outline in a 64 x 64 box, nose up (north). */
export const PLANE_PATH =
  "M32 4 C35 4 36 8 36 12 L36 24 L58 36 L58 41 L36 35 L36 49 L43 55 L43 59 L32 56 L21 59 L21 55 " +
  "L28 49 L28 35 L6 41 L6 36 L28 24 L28 12 C28 8 29 4 32 4 Z";

/** The icon's pixels, or null where there is no canvas (tests). */
export function planeImage(): ImageData | null {
  const canvas = document.createElement("canvas");
  canvas.width = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx || typeof Path2D === "undefined") return null;
  ctx.fillStyle = "#fff";
  ctx.fill(new Path2D(PLANE_PATH));
  return ctx.getImageData(0, 0, SIZE, SIZE);
}

/** 0..1, repeating every `periodMs`: the phase of a pulse at time `now`. */
export function phase(now: number, periodMs: number): number {
  return (now % periodMs) / periodMs;
}

/** A sonar ring at phase k: it grows from `from` to `to` pixels and fades out. */
export function sonar(k: number, from: number, to: number, peak = 0.6): { radius: number; opacity: number } {
  return { radius: from + (to - from) * k, opacity: peak * (1 - k) };
}

/** A slow breath between `low` and `high` (for the impact zones). */
export function breath(now: number, periodMs: number, low: number, high: number): number {
  return low + ((high - low) * (1 - Math.cos(2 * Math.PI * phase(now, periodMs)))) / 2;
}
