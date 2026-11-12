import "maplibre-gl/dist/maplibre-gl.css";

import { type GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { IncidentDetail } from "../api/intel";
import type { Mission } from "../api/people";
import { registerPmtiles, tilesAvailable } from "./base";
import { miniLayers, miniZoom } from "./mini";
import { ATTRIBUTION, baseStyle } from "./style";

/** GFX-08 (D-55; plan G-9): a still, flat map of the incident's place, with its zone and marker,
 *  its mission and the people and sites exposed. One WebGL context, only while the incident is
 *  open. A click opens Global Operations on the incident, as "Open in map" does. */
export function MiniMap({ incident, missions }: { incident: IncidentDetail; missions: Mission[] }) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const navigate = useNavigate();
  const { lon, lat } = incident;

  useEffect(() => {
    let disposed = false;
    let created: MapLibreMap | null = null;
    registerPmtiles();
    void tilesAvailable().then((tiles) => {
      if (disposed || !container.current) return;
      let m: MapLibreMap;
      try {
        m = new MapLibreMap({
          container: container.current,
          style: baseStyle(window.location.origin, tiles),
          center: [lon, lat],
          zoom: miniZoom(lon, lat),
          interactive: false,
          attributionControl: { compact: false, customAttribution: ATTRIBUTION },
        });
      } catch {
        setUnavailable(true); // no WebGL here: say so, and the link still works
        return;
      }
      created = m;
      m.on("load", () => {
        if (disposed) return;
        for (const id of ["zone", "mission", "exposure", "marker"]) {
          m.addSource(id, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        }
        m.addLayer({
          id: "zone-fill",
          type: "fill",
          source: "zone",
          paint: { "fill-color": ["get", "colour"], "fill-opacity": 0.14 },
        });
        m.addLayer({
          id: "zone-line",
          type: "line",
          source: "zone",
          paint: { "line-color": ["get", "colour"], "line-width": 1.5, "line-dasharray": [3, 2] },
        });
        m.addLayer({
          id: "mission",
          type: "circle",
          source: "mission",
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": 7,
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 2,
          },
        });
        m.addLayer({
          id: "exposure",
          type: "circle",
          source: "exposure",
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": ["case", ["==", ["get", "kind"], "SITE"], 6, 3.5],
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 1,
          },
        });
        m.addLayer({
          id: "marker",
          type: "circle",
          source: "marker",
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": 7,
            "circle-stroke-color": "#F6F7F9",
            "circle-stroke-width": 2,
          },
        });
        setMap(m);
      });
    });
    return () => {
      disposed = true;
      created?.remove();
    };
  }, [lon, lat]);

  useEffect(() => {
    if (!map) return;
    const layers = miniLayers(incident, missions);
    for (const [id, data] of Object.entries(layers)) {
      (map.getSource(id) as GeoJSONSource | undefined)?.setData(data);
    }
  }, [map, incident, missions]);

  return (
    <button
      type="button"
      className="nx-minimap"
      aria-label={`Open ${incident.reference} in Global Operations`}
      title="Open in Global Operations"
      onClick={() => void navigate(`/operations?incident=${incident.id}`)}
    >
      <div className="nx-minimap-map" ref={container} data-testid="mini-map">
        {unavailable && <div className="nx-map-note">This browser cannot draw the map (WebGL).</div>}
      </div>
    </button>
  );
}
