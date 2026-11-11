import type { Map as MapLibreMap } from "maplibre-gl";

import STARS from "./stars.json";

// The star field behind the world globe: the real sky, from the Yale Bright Star Catalogue
// (public domain; built once by infra/scripts/build-stars.py and bundled, so nothing is fetched,
// D-24). The globe is seen from space above the map's centre, so the stars behind it are those
// around the opposite direction in the sky; they turn as the globe turns. Shown on the globe at
// world zoom only.

export type Star = [ra: number, dec: number, magnitude: number];
const CATALOGUE = STARS as Star[];

const RAD = Math.PI / 180;
const FIELD_DEG = 70; // the sky across the canvas height
export const STARS_MAX_ZOOM = 4.5; // gone by then; they fade out over the last 1.5 zoom levels

/** Greenwich sidereal time in degrees: how far the sky has turned over Greenwich. */
export function sidereal(at: Date): number {
  const days = at.getTime() / 86_400_000 - 10_957.5; // since J2000.0
  return (((280.46061837 + 360.98564736629 * days) % 360) + 360) % 360;
}

export interface View {
  lon: number; // the map's centre
  lat: number;
  bearing: number;
  width: number; // CSS pixels
  height: number;
  at: Date;
}

/** Each star in view as [x, y, radius, alpha] in CSS pixels; east is to the left, as in the sky. */
export function project(stars: Star[], v: View): [number, number, number, number][] {
  // Behind the globe: the direction from the viewer through the Earth's centre.
  const ra0 = (v.lon + sidereal(v.at) + 180) * RAD;
  const dec0 = -v.lat * RAD;
  const scale = v.height / (2 * Math.tan((FIELD_DEG / 2) * RAD));
  const turn = -v.bearing * RAD;
  const [cx, cy] = [v.width / 2, v.height / 2];
  const out: [number, number, number, number][] = [];
  for (const [ra, dec, mag] of stars) {
    const d = dec * RAD;
    const h = ra * RAD - ra0;
    const cosc = Math.sin(dec0) * Math.sin(d) + Math.cos(dec0) * Math.cos(d) * Math.cos(h);
    if (cosc <= 0) continue; // the other half of the sky
    const x = (Math.cos(d) * Math.sin(h)) / cosc;
    const y = (Math.cos(dec0) * Math.sin(d) - Math.sin(dec0) * Math.cos(d) * Math.cos(h)) / cosc;
    const sx = cx - scale * (x * Math.cos(turn) - y * Math.sin(turn));
    const sy = cy - scale * (x * Math.sin(turn) + y * Math.cos(turn));
    if (sx < -2 || sy < -2 || sx > v.width + 2 || sy > v.height + 2) continue;
    out.push([sx, sy, Math.max(0.6, 2 - 0.28 * mag), Math.min(1, Math.max(0.3, 1.15 - mag / 6))]);
  }
  return out;
}

/** How visible the stars are at this zoom: 1 at world zoom, 0 from STARS_MAX_ZOOM. */
export function starOpacity(globe: boolean, zoom: number): number {
  if (!globe) return 0;
  return Math.min(1, Math.max(0, (STARS_MAX_ZOOM - zoom) / 1.5));
}

/** Draws the stars on a canvas behind the map, redrawn as the map moves. Returns a stop. */
export function addStars(map: MapLibreMap, globe: () => boolean): () => void {
  const container = map.getContainer();
  const canvas = document.createElement("canvas");
  canvas.className = "nx-stars";
  canvas.setAttribute("aria-hidden", "true");
  container.prepend(canvas); // before MapLibre's canvas: behind the globe
  const draw = () => {
    const { clientWidth: width, clientHeight: height } = container;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const shown = starOpacity(globe(), map.getZoom());
    if (!shown) return;
    const { lng, lat } = map.getCenter();
    ctx.fillStyle = "#dce8ff";
    for (const [x, y, r, a] of project(CATALOGUE, { lon: lng, lat, bearing: map.getBearing(), width, height, at: new Date() })) {
      ctx.globalAlpha = a * shown;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  };
  const events = ["move", "resize", "projectiontransition"] as const;
  for (const name of events) map.on(name, draw);
  draw();
  const timer = window.setInterval(draw, 60_000); // the sky turns too, slowly
  return () => {
    window.clearInterval(timer);
    for (const name of events) map.off(name, draw);
    canvas.remove();
  };
}
