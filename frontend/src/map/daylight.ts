import type { Feature, LineString, Polygon } from "geojson";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

// Day and night on the world maps: the night side shaded, with a soft edge along the terminator.
// The sun's place is worked out here from the clock (a low-precision solar position, well under
// a degree); nothing is fetched (D-24). Shown at world zoom, gone by city zoom.

const RAD = Math.PI / 180;
const STEPS = 180;
const POLE = 85.0511; // points along the terminator, one each two degrees of longitude
export const DAYLIGHT_EVERY_MS = 60_000; // the line moves a quarter of a degree a minute

/** The point where the sun is overhead at this moment, in degrees. */
export function subsolar(at: Date): { lon: number; lat: number } {
  const n = at.getTime() / 86_400_000 - 10_957.5; // days since J2000.0 (2000-01-01 12:00 UTC)
  const mean = (280.46 + 0.9856474 * n) % 360;
  const anomaly = ((357.528 + 0.9856003 * n) % 360) * RAD;
  const ecliptic = (mean + 1.915 * Math.sin(anomaly) + 0.02 * Math.sin(2 * anomaly)) * RAD;
  const tilt = (23.439 - 0.0000004 * n) * RAD;
  const declination = Math.asin(Math.sin(tilt) * Math.sin(ecliptic));
  const ascension = Math.atan2(Math.cos(tilt) * Math.sin(ecliptic), Math.cos(ecliptic)) / RAD;
  const sidereal = 280.46061837 + 360.98564736629 * n; // Greenwich, in degrees
  return { lon: wrap(ascension - sidereal), lat: declination / RAD };
}

function wrap(lon: number): number {
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

/** Whether the sun is below the horizon at a place. */
export function isNight(lon: number, lat: number, at: Date): boolean {
  const sun = subsolar(at);
  const altitude =
    Math.sin(lat * RAD) * Math.sin(sun.lat * RAD) +
    Math.cos(lat * RAD) * Math.cos(sun.lat * RAD) * Math.cos((lon - sun.lon) * RAD);
  return altitude < 0;
}

/** The terminator's latitude on each meridian, west to east. */
function terminator(at: Date): [number, number][] {
  const sun = subsolar(at);
  // At an equinox the line runs pole to pole; a hair off zero keeps the formula finite.
  const tan = Math.tan((Math.abs(sun.lat) < 0.01 ? 0.01 : sun.lat) * RAD);
  return Array.from({ length: STEPS + 1 }, (_, i): [number, number] => {
    const lon = -180 + (360 * i) / STEPS;
    return [lon, Math.atan(-Math.cos((lon - sun.lon) * RAD) / tan) / RAD];
  });
}

/** The night side as one polygon, closed over the pole the sun does not reach. */
export function nightSide(at: Date): Feature<Polygon> {
  const line = terminator(at);
  // The tiles stop at ±85.05° (Web Mercator); a vertex at the pole itself breaks the globe's mesh.
  const pole = subsolar(at).lat >= 0 ? -POLE : POLE;
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [[...line, [180, pole], [-180, pole], line[0] ?? [-180, 0]]] },
  };
}

function edge(at: Date): Feature<LineString> {
  return { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: terminator(at) } };
}

/** Adds the night layers under the base map's labels and keeps them current. Returns a stop. */
export function addDaylight(map: MapLibreMap, now: () => Date = () => new Date()): () => void {
  // Over every land, water and road layer; under the labels drawn after them (the base style
  // has a world and a city set, each with its own labels).
  const layers = map.getStyle().layers;
  const lastShape = layers.map((l) => l.type !== "symbol").lastIndexOf(true);
  const labels = layers.slice(lastShape + 1).find((l) => l.type === "symbol")?.id;
  map.addSource("night", { type: "geojson", data: nightSide(now()) });
  map.addSource("night-edge", { type: "geojson", data: edge(now()) });
  map.addLayer(
    {
      id: "night",
      type: "fill",
      source: "night",
      maxzoom: 7,
      paint: {
        "fill-color": "#000614",
        "fill-opacity": ["interpolate", ["linear"], ["zoom"], 0, 0.72, 4, 0.5, 6.5, 0],
        "fill-antialias": false,
      },
    },
    labels,
  );
  // Twilight: a wide, blurred line along the terminator softens the edge.
  map.addLayer(
    {
      id: "night-edge",
      type: "line",
      source: "night-edge",
      maxzoom: 7,
      paint: {
        "line-color": "#000614",
        "line-width": ["interpolate", ["linear"], ["zoom"], 0, 14, 4, 40],
        "line-blur": ["interpolate", ["linear"], ["zoom"], 0, 14, 4, 40],
        "line-opacity": ["interpolate", ["linear"], ["zoom"], 0, 0.4, 4, 0.25, 6.5, 0],
      },
    },
    labels,
  );
  const timer = window.setInterval(() => {
    const at = now();
    (map.getSource("night") as GeoJSONSource | undefined)?.setData(nightSide(at));
    (map.getSource("night-edge") as GeoJSONSource | undefined)?.setData(edge(at));
  }, DAYLIGHT_EVERY_MS);
  return () => window.clearInterval(timer);
}
