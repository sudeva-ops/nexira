import type { Map as MapLibreMap } from "maplibre-gl";

// The 3D map (UI 2): a globe at world zoom that flattens as you zoom in, an atmosphere, a slow
// turn of the world view while nobody touches it, and a tilted camera on a selected incident.

const GLOBE_KEY = "nexira.map.globe";
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
