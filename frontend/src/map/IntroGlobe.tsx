import type { FeatureCollection, LineString } from "geojson";
import { type GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { Mission } from "../api/people";
import { arcPairs } from "../app/introRules";
import { registerPmtiles, tilesAvailable } from "./base";
import { greatCircle, missionFeatures } from "./geo";
import { baseStyle } from "./style";
import { applyProjection } from "./three";

// The sign-in intro's globe: the same self-hosted map as Global Operations (D-24), turning faster,
// each mission a pulsing dot in its risk colour, arcs drawing between neighbours; then it settles on
// the view Global Operations opens with, so the hand-over reads as one movement.

const SPIN_DEG_PER_S = 9;
const ARC_DELAY_MS = 90; // one arc after another
const ARC_DRAW_MS = 1_100;
const PULSE_MS = 1_800;
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

export function IntroGlobe({ missions, descend }: { missions: Mission[]; descend: boolean }) {
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
    registerPmtiles();
    void tilesAvailable().then((available) => {
      if (disposed || !container.current) return;
      const m = new MapLibreMap({
        container: container.current,
        style: baseStyle(window.location.origin, available),
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
        m.addSource("arcs", { type: "geojson", data: arcs([], 0), lineMetrics: true });
        m.addSource("missions", { type: "geojson", data: missionFeatures(data.current) });
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
