import type { Map as MapLibreMap } from "maplibre-gl";

// The 3D map (UI 2): a globe at world zoom that flattens as you zoom in, an atmosphere, a slow
// turn of the world view while nobody touches it, and a tilted camera on a selected incident.

const GLOBE_KEY = "nexira.map.globe";
const RAD = Math.PI / 180;
export const SPIN_DEG_PER_S = 3; // the world view turns slowly
export const SPIN_MAX_ZOOM = 3; // only at world zoom
export const IDLE_MS = 20_000; // and only after 20 s without a touch
export const SELECT_PITCH = 55;
export const SELECT_BEARING = -20;

/** The viewer's choice, globe (default) or flat; kept in this browser only. */
export function globePreferred(): boolean {
  try {
    return window.localStorage.getItem(GLOBE_KEY) !== "flat";
  } catch {
    return true;
  }
}

export function setGlobePreferred(globe: boolean): void {
  try {
    window.localStorage.setItem(GLOBE_KEY, globe ? "globe" : "flat");
  } catch {
    // private window or blocked storage: the choice lasts for this page only
  }
}

/** The globe or flat projection, with an atmosphere that fades as you zoom in. */
export function applyProjection(map: MapLibreMap, globe: boolean): void {
  map.setProjection({ type: globe ? "globe" : "mercator" });
  map.setSky({
    "sky-color": "#0b1424",
    "horizon-color": "#1d3557",
    "fog-color": "#0e1013",
    "sky-horizon-blend": 0.6,
    "horizon-fog-blend": 0.5,
    "fog-ground-blend": 0.3,
    "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 4, 0.8, 7, 0],
  });
}

/** Whether the world view should turn now: the globe, world zoom, and nobody touched it lately. */
export function shouldSpin(globe: boolean, zoom: number, lastTouch: number, now: number): boolean {
  return globe && zoom <= SPIN_MAX_ZOOM && now - lastTouch >= IDLE_MS;
}

/** Turns the world view slowly until the map is touched (then waits IDLE_MS). Returns a stop. */
export function startSpin(map: MapLibreMap, globe: () => boolean): () => void {
  let lastTouch = performance.now() - IDLE_MS; // turn from the start
  let frame = 0;
  let last = 0;
  const touched = () => {
    lastTouch = performance.now();
  };
  const events = ["mousedown", "touchstart", "wheel", "dragstart", "movestart"] as const;
  const user = (e: { originalEvent?: unknown }) => {
    if (e.originalEvent) touched(); // a person, not our own easing
  };
  for (const name of events) map.on(name, user);
  const step = (now: number) => {
    if (last && shouldSpin(globe(), map.getZoom(), lastTouch, now) && !map.isMoving()) {
      const center = map.getCenter();
      map.setCenter([center.lng + (SPIN_DEG_PER_S * (now - last)) / 1000, center.lat]);
    }
    last = now;
    frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
  return () => {
    cancelAnimationFrame(frame);
    for (const name of events) map.off(name, user);
  };
}

/** The globe's centre and radius on screen, in CSS pixels. */
export interface GlobeFrame {
  x: number;
  y: number;
  r: number;
}

/** Measured, not computed from the zoom: the centre and a point 60° up its meridian. */
export function globeFrame(m: MapLibreMap): GlobeFrame {
  const c = m.getCenter();
  const centre = m.project(c);
  const up = m.project([c.lng, c.lat + 60]);
  return { x: centre.x, y: centre.y, r: Math.hypot(up.x - centre.x, up.y - centre.y) / Math.sin(Math.PI / 3) };
}

/** The point `angle` degrees due east of `[lon, lat]` along a great circle. */
export function eastOf([lon, lat]: [number, number], angle: number): [number, number] {
  const [phi, d] = [lat * RAD, angle * RAD];
  const lat2 = Math.asin(Math.sin(phi) * Math.cos(d));
  const lon2 = lon * RAD + Math.atan2(Math.sin(d) * Math.cos(phi), Math.cos(d) - Math.sin(phi) * Math.sin(lat2));
  return [lon2 / RAD, lat2 / RAD];
}

/** The globe's visible rim on screen. The camera is a perspective one, so the rim is short of 90°
 *  from the centre: the furthest of the points walked out east is taken. */
export function globeLimb(m: MapLibreMap): GlobeFrame {
  const c = m.getCenter();
  const centre = m.project(c);
  let r = 0;
  for (let angle = 45; angle <= 90; angle += 0.5) {
    const p = m.project(eastOf([c.lng, c.lat], angle));
    r = Math.max(r, Math.hypot(p.x - centre.x, p.y - centre.y));
  }
  return { x: centre.x, y: centre.y, r };
}

/** The CSS clip that keeps the map's sweep on the globe (GFX-04): a circle on the globe at world
 *  zoom, offset from the map to its frame; none when flat or closer in, where the map fills the box. */
export function sweepClip(frame: GlobeFrame | null, offset: { x: number; y: number }): string {
  if (!frame || !(frame.r > 0) || !Number.isFinite(frame.r)) return "none";
  const px = (n: number) => `${Math.round(n * 10) / 10}px`;
  return `circle(${px(frame.r)} at ${px(frame.x + offset.x)} ${px(frame.y + offset.y)})`;
}

/** Keeps the sweep of the map's frame (`.nx-mapwrap`) inside the globe as the map moves. Returns a stop. */
export function clipSweep(map: MapLibreMap, globe: () => boolean): () => void {
  const container = map.getContainer();
  const frame = container.closest<HTMLElement>(".nx-mapwrap");
  if (!frame) return () => {};
  const update = () => {
    const box = frame.getBoundingClientRect();
    const own = container.getBoundingClientRect();
    const onGlobe = globe() && map.getZoom() <= SPIN_MAX_ZOOM;
    frame.style.setProperty(
      "--nx-sweep-clip",
      sweepClip(onGlobe ? globeLimb(map) : null, { x: own.left - box.left, y: own.top - box.top }),
    );
  };
  const events = ["move", "resize", "projectiontransition"] as const;
  for (const name of events) map.on(name, update);
  update();
  return () => {
    for (const name of events) map.off(name, update);
    frame.style.removeProperty("--nx-sweep-clip");
  };
}
