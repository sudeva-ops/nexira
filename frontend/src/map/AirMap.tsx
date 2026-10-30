import "maplibre-gl/dist/maplibre-gl.css";

import { type GeoJSONSource, Map as MapLibreMap, NavigationControl } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { Flight } from "../api/flights";
import { useReducedMotion } from "../ui/useMotion";
import { registerPmtiles, tilesAvailable } from "./base";
import { flightFeatures, routeFeatures } from "./geo";
import { DASH_FRAMES, DASH_STEP_MS, GLIDE_MS, glideFlights, type LonLat, positions } from "./motion";
import { ATTRIBUTION, baseStyle } from "./style";

const EMPTY = { type: "FeatureCollection" as const, features: [] };

interface Props {
  flights: Flight[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** AT-02: our travellers' flights only, with their routes; positions are simulated. */
export function AirMap({ flights, selectedId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [baseMissing, setBaseMissing] = useState(false);
  const onSelectRef = useRef(onSelect);
  const reduced = useReducedMotion();
  const drawn = useRef(new Map<string, LonLat>()); // where each aircraft is on screen now
  useEffect(() => {
    onSelectRef.current = onSelect;
  });

  useEffect(() => {
    let disposed = false;
    let created: MapLibreMap | null = null;
    registerPmtiles();
    void tilesAvailable().then((available) => {
      if (disposed || !container.current) return;
      setBaseMissing(!available);
      const m = new MapLibreMap({
        container: container.current,
        style: baseStyle(window.location.origin, available),
        center: [40, 15],
        zoom: 1.6,
        attributionControl: { compact: false, customAttribution: ATTRIBUTION },
      });
      created = m;
      m.addControl(new NavigationControl({ showCompass: false }), "top-right");
      m.on("load", () => {
        if (disposed) return;
        m.addSource("routes", { type: "geojson", data: EMPTY });
        m.addSource("flights", { type: "geojson", data: EMPTY });
        m.addLayer({
          id: "routes",
          type: "line",
          source: "routes",
          paint: {
            "line-color": ["get", "colour"],
            "line-opacity": 0.45,
            "line-width": 1.4,
            "line-dasharray": [3, 3],
          },
        });
        m.addLayer({
          id: "flights",
          type: "circle",
          source: "flights",
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": 6,
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 1.5,
          },
        });
        // Labels need the self-hosted glyphs, installed with the tiles (D-24).
        if (available) m.addLayer({
          id: "flight-labels",
          type: "symbol",
          source: "flights",
          layout: {
            "text-field": ["get", "label"],
            "text-font": ["Noto Sans Regular"],
            "text-size": 11,
            "text-offset": [0, 1.3],
          },
          paint: { "text-color": ["get", "colour"], "text-halo-color": "#111418", "text-halo-width": 1 },
        });
        m.on("click", "flights", (e) => {
          const id = e.features?.[0]?.properties?.id;
          if (typeof id === "string") onSelectRef.current(id);
        });
        m.on("mouseenter", "flights", () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", "flights", () => (m.getCanvas().style.cursor = ""));
        setMap(m);
      });
    });
    return () => {
      disposed = true;
      created?.remove();
    };
  }, []);

  useEffect(() => {
    (map?.getSource("routes") as GeoJSONSource | undefined)?.setData(routeFeatures(flights));
  }, [map, flights]);

  // Aircraft glide from where they are drawn to their new position (positions arrive
  // every 15 s, D-33) instead of jumping.
  useEffect(() => {
    const source = map?.getSource("flights") as GeoJSONSource | undefined;
    if (!source) return;
    const from = new Map(drawn.current);
    const draw = (shown: Flight[]) => {
      source.setData(flightFeatures(shown));
      drawn.current = positions(shown);
    };
    if (reduced || from.size === 0) {
      draw(flights);
      return;
    }
    let frame = 0;
    let start: number | null = null;
    const step = (now: number) => {
      start ??= now;
      const k = (now - start) / GLIDE_MS;
      draw(k >= 1 ? flights : glideFlights(from, flights, k));
      if (k < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [map, flights, reduced]);

  // Flight paths move along, so the picture reads as live.
  useEffect(() => {
    if (!map || reduced) return;
    let frame = 0;
    let last = 0;
    let i = 0;
    const step = (now: number) => {
      if (now - last >= DASH_STEP_MS) {
        last = now;
        i = (i + 1) % DASH_FRAMES.length;
        if (map.getLayer("routes")) map.setPaintProperty("routes", "line-dasharray", DASH_FRAMES[i]);
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [map, reduced]);

  useEffect(() => {
    const flight = flights.find((f) => f.id === selectedId);
    if (map && flight?.lat != null && flight.lon != null) {
      map.easeTo({ center: [flight.lon, flight.lat], zoom: Math.max(map.getZoom(), 3) });
    }
    // Only when the selection changes, not on every position update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selectedId]);

  return (
    <div className="nx-map nx-air-map" ref={container} data-testid="air-map">
      {baseMissing && <div className="nx-map-note">Base map not installed. Run `make tiles` (D-24).</div>}
    </div>
  );
}
