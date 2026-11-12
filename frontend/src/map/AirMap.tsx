import "maplibre-gl/dist/maplibre-gl.css";

import { type GeoJSONSource, Map as MapLibreMap, NavigationControl } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { Flight } from "../api/flights";
import { useReducedMotion } from "../ui/useMotion";
import { registerPmtiles, tilesAvailable } from "./base";
import { addDaylight } from "./daylight";
import { addStars } from "./stars";
import { flightFeatures, routeFeatures } from "./geo";
import { DASH_FRAMES, DASH_STEP_MS, GLIDE_MS, glideFlights, type LonLat, positions } from "./motion";
import { MapToggle } from "./MapToggle";
import { phase, PLANE_ICON, planeImage, sonar } from "./plane";
import { applyProjection, globePreferred, setGlobePreferred } from "./three";
import { ATTRIBUTION, baseStyle } from "./style";

const EMPTY = { type: "FeatureCollection" as const, features: [] };
const HOLD_MS = 2000; // a holding flight's sonar ring
const SPIN_DEG_PER_S = 40; // a holding flight circles

interface Props {
  flights: Flight[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  fly?: { lon: number; lat: number; zoom: number } | null; // a search result (SRC-04)
}

/** AT-02: our travellers' flights only, with their routes; positions are simulated. */
export function AirMap({ flights, selectedId, onSelect, fly = null }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [baseMissing, setBaseMissing] = useState(false);
  const onSelectRef = useRef(onSelect);
  const reduced = useReducedMotion();
  const drawn = useRef(new Map<string, LonLat>()); // where each aircraft is on screen now
  const [globe, setGlobe] = useState(globePreferred);
  const globeRef = useRef(globe);
  useEffect(() => {
    onSelectRef.current = onSelect;
  });

  useEffect(() => {
    let disposed = false;
    let created: MapLibreMap | null = null;
    let stopDaylight = () => {};
    let stopStars = () => {};
    registerPmtiles();
    void tilesAvailable().then((tiles) => {
      if (disposed || !container.current) return;
      setBaseMissing(!tiles.base);
      const m = new MapLibreMap({
        container: container.current,
        style: baseStyle(window.location.origin, tiles),
        center: [40, 15],
        zoom: globeRef.current ? 2 : 1.6, // a globe at 1.6 is small
        attributionControl: { compact: false, customAttribution: ATTRIBUTION },
      });
      created = m;
      m.addControl(new NavigationControl({ showCompass: false }), "top-right");
      m.on("load", () => {
        if (disposed) return;
        applyProjection(m, globeRef.current);
        stopDaylight = addDaylight(m);
        stopStars = addStars(m, () => globeRef.current);
        m.addSource("routes", { type: "geojson", data: EMPTY });
        m.addSource("flights", { type: "geojson", data: EMPTY });
        // The part of each route flown is solid; the part ahead is dashed and moves along.
        m.addLayer({
          id: "routes-flown",
          type: "line",
          source: "routes",
          filter: ["==", ["get", "part"], "flown"],
          paint: { "line-color": ["get", "colour"], "line-opacity": 0.75, "line-width": 2 },
        });
        m.addLayer({
          id: "routes",
          type: "line",
          source: "routes",
          filter: ["==", ["get", "part"], "ahead"],
          paint: {
            "line-color": ["get", "colour"],
            "line-opacity": 0.5,
            "line-width": 1.4,
            "line-dasharray": [3, 3],
          },
        });
        // A holding flight sends out a sonar ring while it circles.
        m.addLayer({
          id: "flight-holding",
          type: "circle",
          source: "flights",
          filter: ["==", ["get", "holding"], true],
          paint: { "circle-color": ["get", "colour"], "circle-radius": 10, "circle-opacity": 0.3 },
        });
        const plane = planeImage();
        if (plane) {
          // A plane pointing where the flight is going; its colour is its status.
          m.addImage(PLANE_ICON, plane, { sdf: true, pixelRatio: 2 });
          m.addLayer({
            id: "flights",
            type: "symbol",
            source: "flights",
            layout: {
              "icon-image": PLANE_ICON,
              "icon-size": 0.7,
              "icon-rotate": ["get", "bearing"],
              "icon-rotation-alignment": "map",
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
            },
            paint: { "icon-color": ["get", "colour"], "icon-halo-color": "#111418", "icon-halo-width": 1.2 },
          });
        } else {
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
        }
        // Labels need the self-hosted glyphs, installed with the tiles (D-24).
        if (tiles.base) m.addLayer({
          id: "flight-labels",
          type: "symbol",
          source: "flights",
          layout: {
            "text-field": ["get", "label"],
            "text-font": ["Noto Sans Regular"],
            "text-size": 11,
            "text-offset": [0, 1.6],
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
      stopDaylight();
      stopStars();
      created?.remove();
    };
  }, []);

  useEffect(() => {
    (map?.getSource("routes") as GeoJSONSource | undefined)?.setData(routeFeatures(flights));
  }, [map, flights]);

  useEffect(() => {
    globeRef.current = globe;
    if (map) applyProjection(map, globe);
  }, [map, globe]);

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

  // Flight paths move along, a holding flight circles with a sonar ring, so the picture reads
  // as live.
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
        if (map.getLayer("flight-holding")) {
          const ring = sonar(phase(now, HOLD_MS), 8, 26, 0.5);
          map.setPaintProperty("flight-holding", "circle-radius", ring.radius);
          map.setPaintProperty("flight-holding", "circle-opacity", ring.opacity);
        }
        if (map.getLayer("flights") && map.getLayer("flights")?.type === "symbol") {
          const spin = ((now / 1000) * SPIN_DEG_PER_S) % 360;
          map.setLayoutProperty("flights", "icon-rotate", [
            "case",
            ["get", "holding"],
            ["%", ["+", ["get", "bearing"], spin], 360],
            ["get", "bearing"],
          ]);
        }
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

  useEffect(() => {
    if (map && fly) map.flyTo({ center: [fly.lon, fly.lat], zoom: fly.zoom });
  }, [map, fly]);

  return (
    <div className="nx-map nx-air-map" ref={container} data-testid="air-map">
      <MapToggle
        globe={globe}
        onChange={(g) => {
          setGlobePreferred(g);
          setGlobe(g);
        }}
      />
      {baseMissing && <div className="nx-map-note">Base map not installed. Run `make tiles` (D-24).</div>}
    </div>
  );
}
