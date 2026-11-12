import "maplibre-gl/dist/maplibre-gl.css";

import type { Feature } from "geojson";
import { type GeoJSONSource, LngLatBounds, Map as MapLibreMap, NavigationControl } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { Replay } from "../api/replay";
import { type Moment, STATE_COLOUR } from "../screens/replay/state";
import { addAnnotationLayers, annotationColour } from "./annotations";
import { registerPmtiles, tilesAvailable } from "./base";
import { circlePolygon, SEVERITY_COLOUR } from "./geo";
import { ATTRIBUTION, baseStyle } from "./style";

const EMPTY = { type: "FeatureCollection" as const, features: [] };

function point(lon: number, lat: number, properties: Record<string, string>): Feature {
  return { type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties };
}

/** RPL-02: the incident at one moment, on the self-hosted base map (D-24). Positions as now. */
export function ReplayMap({ replay, moment }: { replay: Replay; moment: Moment }) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [baseMissing, setBaseMissing] = useState(false);
  const { lon, lat, impact_radius_m: radius } = replay.incident;

  useEffect(() => {
    let disposed = false;
    let created: MapLibreMap | null = null;
    registerPmtiles();
    void tilesAvailable().then((tiles) => {
      if (disposed || !container.current) return;
      setBaseMissing(!tiles.base);
      const zone = circlePolygon(lon, lat, radius);
      const fit = new LngLatBounds();
      for (const c of zone.coordinates[0] ?? []) fit.extend(c as [number, number]);
      const m = new MapLibreMap({
        container: container.current,
        style: baseStyle(window.location.origin, tiles),
        bounds: fit,
        fitBoundsOptions: { padding: 60 },
        attributionControl: { compact: false, customAttribution: ATTRIBUTION },
      });
      created = m;
      m.addControl(new NavigationControl({ showCompass: false }), "top-right");
      m.on("load", () => {
        if (disposed) return;
        for (const id of ["zone", "signals", "sites", "people"]) m.addSource(id, { type: "geojson", data: EMPTY });
        m.addLayer({
          id: "zone-fill",
          type: "fill",
          source: "zone",
          paint: { "fill-color": "#CD4246", "fill-opacity": 0.14 },
        });
        m.addLayer({
          id: "zone-line",
          type: "line",
          source: "zone",
          paint: { "line-color": "#E76A6E", "line-width": 1.5, "line-dasharray": [3, 2] },
        });
        addAnnotationLayers(m, false); // no labels: free text stays off the replay (G-4)
        m.addLayer({
          id: "sites",
          type: "circle",
          source: "sites",
          paint: {
            "circle-color": "#4C90F0",
            "circle-radius": 7,
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 2,
          },
        });
        m.addLayer({
          id: "people",
          type: "circle",
          source: "people",
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": 4,
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 1,
          },
        });
        m.addLayer({
          id: "signals",
          type: "circle",
          source: "signals",
          paint: {
            "circle-color": "transparent",
            "circle-radius": 11,
            "circle-stroke-color": ["get", "colour"],
            "circle-stroke-width": 2.5,
          },
        });
        setMap(m);
      });
    });
    return () => {
      disposed = true;
      created?.remove();
    };
  }, [lon, lat, radius]);

  useEffect(() => {
    if (!map) return;
    const set = (id: string, features: Feature[]) =>
      (map.getSource(id) as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features });
    set(
      "zone",
      moment.zone ? [{ type: "Feature", geometry: circlePolygon(lon, lat, radius), properties: {} }] : [],
    );
    set(
      "signals",
      moment.signals.flatMap((s) =>
        s.lon === null || s.lat === null
          ? []
          : [point(s.lon, s.lat, { colour: SEVERITY_COLOUR[s.severity ?? "MODERATE"] })],
      ),
    );
    set(
      "sites",
      moment.sites.flatMap((s) => (s.lon === null || s.lat === null ? [] : [point(s.lon, s.lat, {})])),
    );
    set(
      "people",
      moment.people.map((p) => point(p.lon, p.lat, { colour: STATE_COLOUR[p.state] })),
    );
    set(
      "annotations",
      moment.annotations.map((a) => ({
        type: "Feature",
        geometry: a.shape,
        properties: { kind: a.kind, colour: annotationColour(a) },
      })),
    );
  }, [map, moment, lon, lat, radius]);

  return (
    <div className="nx-map" ref={container} data-testid="replay-map">
      {baseMissing && <div className="nx-map-note">Base map not installed. Run `make tiles` (D-24).</div>}
    </div>
  );
}
