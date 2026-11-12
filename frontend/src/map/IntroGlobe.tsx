import type { FeatureCollection, LineString, Point } from "geojson";
import { type GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { Mission } from "../api/people";
import { arcPairs } from "../app/introRules";
import { registerPmtiles, tilesAvailable } from "./base";
import { addDaylight } from "./daylight";
import { addStars } from "./stars";
import { greatCircle, missionFeatures } from "./geo";
import { baseStyle } from "./style";
import { applyProjection, globeFrame, type GlobeFrame } from "./three";

// The sign-in intro's globe: the same self-hosted map as Global Operations (D-24), turning faster,
// each mission a pulsing dot in its risk colour, arcs drawing between neighbours; then it settles on
// the view Global Operations opens with, so the hand-over reads as one movement.

const SPIN_DEG_PER_S = 9;
const ARC_DELAY_MS = 90; // one arc after another
const ARC_DRAW_MS = 1_100;
const PULSE_MS = 1_800;
const COMET_MS = 2_400; // a light runs the length of each arc this often
const START: [number, number] = [20, 15]; // where Global Operations opens

function arcs(missions: Mission[], elapsed: number): FeatureCollection<LineString> {
  return {
    type: "FeatureCollection",
    features: arcPairs(missions).flatMap(([a, b], i) => {
      const f = Math.min(1, Math.max(0, (elapsed - i * ARC_DELAY_MS) / ARC_DRAW_MS));
      const line = greatCircle([a.lat, a.lon], [b.lat, b.lon], 40);
      const shown = line.slice(0, Math.max(2, Math.ceil(f * line.length)));
      return f > 0 ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: shown } }] : [];
    }),
  };
}

/** A light running along each drawn arc, each starting at its own point. */
function comets(missions: Mission[], elapsed: number): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: arcPairs(missions).flatMap(([a, b], i) => {
      if (elapsed < i * ARC_DELAY_MS + ARC_DRAW_MS) return [];
      const line = greatCircle([a.lat, a.lon], [b.lat, b.lon], 40);
      const f = ((elapsed + i * 613) % COMET_MS) / COMET_MS;
      const at = line[Math.min(line.length - 1, Math.floor(f * line.length))] ?? line[0];
      return at ? [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: at } }] : [];
    }),
  };
}

export function IntroGlobe({
  missions,
  descend,
  onTurn,
  onFrame,
}: {
  missions: Mission[];
  descend: boolean;
  onTurn?: (lon: number, lat: number) => void; // the HUD's readout
  onFrame?: (frame: GlobeFrame) => void; // where the globe is on screen, for the compass ring
}) {
  const turned = useRef(onTurn);
  const framed = useRef(onFrame);
  useEffect(() => {
    turned.current = onTurn;
    framed.current = onFrame;
  });
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const data = useRef(missions);
  const descending = useRef(false);
  useEffect(() => {
    data.current = missions;
  });

  useEffect(() => {
    let disposed = false;
    let frame = 0;
    let stopDaylight = () => {};
    let stopStars = () => {};
    registerPmtiles();
    void tilesAvailable().then((tiles) => {
      if (disposed || !container.current) return;
      const m = new MapLibreMap({
        container: container.current,
        style: baseStyle(window.location.origin, tiles),
        center: START,
        zoom: 2.1,
        interactive: false,
        attributionControl: { compact: true },
      });
      map.current = m;
      // The globe sits right of the name and counters; it centres again as it descends.
      m.setPadding({ left: Math.round(container.current.clientWidth * 0.38), top: 0, right: 0, bottom: 0 });
      m.on("load", () => {
        if (disposed) return;
        applyProjection(m, true);
        stopDaylight = addDaylight(m);
        stopStars = addStars(m, () => true);
        framed.current?.(globeFrame(m));
        m.addSource("arcs", { type: "geojson", data: arcs([], 0), lineMetrics: true });
        m.addSource("missions", { type: "geojson", data: missionFeatures(data.current) });
        m.addSource("comets", { type: "geojson", data: comets([], 0) });
        m.addLayer({
          id: "arcs-glow",
          type: "line",
          source: "arcs",
          paint: { "line-color": "#4C90F0", "line-width": 6, "line-blur": 6, "line-opacity": 0.25 },
        });
        m.addLayer({
          id: "arcs",
          type: "line",
          source: "arcs",
          paint: { "line-color": "#8ABBFF", "line-width": 1.2, "line-opacity": 0.8 },
        });
        m.addLayer({
          id: "comets",
          type: "circle",
          source: "comets",
          paint: {
            "circle-color": "#D6E8FF",
            "circle-radius": 2.4,
            "circle-blur": 0.6,
            "circle-stroke-color": "#4C90F0",
            "circle-stroke-width": 3,
            "circle-stroke-opacity": 0.35,
          },
        });
        m.addLayer({
          id: "glow",
          type: "circle",
          source: "missions",
          paint: { "circle-color": ["get", "colour"], "circle-radius": 10, "circle-blur": 1, "circle-opacity": 0.45 },
        });
        m.addLayer({
          id: "pulse",
          type: "circle",
          source: "missions",
          paint: { "circle-color": ["get", "colour"], "circle-radius": 4, "circle-opacity": 0.5 },
        });
        m.addLayer({
          id: "dots",
          type: "circle",
          source: "missions",
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": 3.5,
            "circle-stroke-color": "#0B1424",
            "circle-stroke-width": 1,
          },
        });
        const start = performance.now();
        let last = start;
        let drawn = -1;
        const step = (now: number) => {
          const elapsed = now - start;
          if (!descending.current) {
            const c = m.getCenter();
            m.setCenter([c.lng + (SPIN_DEG_PER_S * (now - last)) / 1000, c.lat]);
          }
          last = now;
          const centre = m.getCenter();
          turned.current?.(centre.lng, centre.lat);
          (m.getSource("comets") as GeoJSONSource | undefined)?.setData(comets(data.current, elapsed));
          const p = (elapsed % PULSE_MS) / PULSE_MS;
          m.setPaintProperty("pulse", "circle-radius", 4 + 14 * p);
          m.setPaintProperty("pulse", "circle-opacity", 0.7 * (1 - p));
          const count = arcPairs(data.current).length;
          if (drawn < count * ARC_DELAY_MS + ARC_DRAW_MS) {
            (m.getSource("arcs") as GeoJSONSource | undefined)?.setData(arcs(data.current, elapsed));
            (m.getSource("missions") as GeoJSONSource | undefined)?.setData(missionFeatures(data.current));
            drawn = elapsed;
          }
          frame = requestAnimationFrame(step);
        };
        frame = requestAnimationFrame(step);
      });
    });
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      stopDaylight();
      stopStars();
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!descend || !m || descending.current) return;
    descending.current = true;
    m.flyTo({
      center: START,
      zoom: 2, // Global Operations' opening view (OperationsMap)
      padding: { left: 0, top: 0, right: 0, bottom: 0 },
      duration: 1_400,
      essential: true,
    });
  }, [descend]);

  return <div ref={container} className="nx-intro-globe" aria-hidden="true" />;
}
