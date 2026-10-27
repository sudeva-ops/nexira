import "maplibre-gl/dist/maplibre-gl.css";

import { type GeoJSONSource, Map as MapLibreMap, Marker, NavigationControl, Popup } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { Exposure, Incident } from "../api/intel";
import type { Mission } from "../api/people";
import { exposureFeatures, missionFeatures, SEVERITY_COLOUR, zoneFeatures } from "./geo";
import { registerPmtiles, tilesAvailable } from "./base";
import { ATTRIBUTION, baseStyle, CITY_MINZOOM } from "./style";

const EMPTY = { type: "FeatureCollection" as const, features: [] };

interface Props {
  missions: Mission[];
  incidents: Incident[]; // ACTIVE incidents: marker and impact zone
  exposure: Exposure[]; // the selected incident's exposure (people at city zoom)
  selectedId: string | null;
  onSelect: (incident: Incident) => void;
}

export function OperationsMap({ missions, incidents, exposure, selectedId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [baseMissing, setBaseMissing] = useState(false);
  const markers = useRef(new Map<string, Marker>());
  const onSelectRef = useRef(onSelect);
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
        center: [20, 15],
        zoom: 1.4,
        attributionControl: { compact: false, customAttribution: ATTRIBUTION },
      });
      created = m;
      m.addControl(new NavigationControl({ showCompass: false }), "top-right");
      m.on("load", () => {
        if (disposed) return;
        m.addSource("zones", { type: "geojson", data: EMPTY });
        m.addSource("missions", { type: "geojson", data: EMPTY });
        m.addSource("exposure", { type: "geojson", data: EMPTY });
        m.addLayer({
          id: "zones-fill",
          type: "fill",
          source: "zones",
          paint: { "fill-color": ["get", "colour"], "fill-opacity": 0.14 },
        });
        m.addLayer({
          id: "zones-line",
          type: "line",
          source: "zones",
          paint: { "line-color": ["get", "colour"], "line-width": 1.5, "line-dasharray": [3, 2] },
        });
        m.addLayer({
          id: "missions",
          type: "circle",
          source: "missions",
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 3.5, 8, 7],
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 1,
          },
        });
        m.addLayer({
          id: "exposure",
          type: "circle",
          source: "exposure",
          minzoom: CITY_MINZOOM + 3, // people in the zone at city zoom (OPS-01)
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": ["case", ["==", ["get", "kind"], "SITE"], 6, 3.5],
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 1,
          },
        });
        const popup = new Popup({ closeButton: false, closeOnClick: false });
        for (const layer of ["missions", "exposure"]) {
          m.on("mouseenter", layer, (e) => {
            const f = e.features?.[0];
            if (!f || f.geometry.type !== "Point") return;
            const p = f.properties as Record<string, string | number | null>;
            const text =
              layer === "missions"
                ? `${p.city} (${p.code}) · ${p.label}`
                : `${p.name}${p.confidence != null ? ` · ${p.confidence}%` : ""}`;
            popup
              .setLngLat(f.geometry.coordinates as [number, number])
              .setText(text)
              .addTo(m);
          });
          m.on("mouseleave", layer, () => popup.remove());
        }
        setMap(m);
      });
    });
    const placed = markers.current;
    return () => {
      disposed = true;
      for (const marker of placed.values()) marker.remove();
      placed.clear();
      created?.remove();
    };
  }, []);

  useEffect(() => {
    (map?.getSource("missions") as GeoJSONSource | undefined)?.setData(missionFeatures(missions));
  }, [map, missions]);

  useEffect(() => {
    if (!map) return;
    (map.getSource("zones") as GeoJSONSource | undefined)?.setData(zoneFeatures(incidents));
    const seen = new Set<string>();
    for (const incident of incidents) {
      seen.add(incident.id);
      let marker = markers.current.get(incident.id);
      if (!marker) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "nx-incident-marker";
        el.dataset.testid = `incident-marker-${incident.reference}`;
        el.addEventListener("click", () => {
          const current = incidents.find((i) => i.id === incident.id) ?? incident;
          onSelectRef.current(current);
        });
        marker = new Marker({ element: el }).setLngLat([incident.lon, incident.lat]);
        marker.addTo(map);
        markers.current.set(incident.id, marker);
      }
      const el = marker.getElement();
      el.style.setProperty("--c", SEVERITY_COLOUR[incident.severity]);
      el.setAttribute("aria-label", `${incident.reference} · ${incident.severity} · ${incident.title}`);
      el.title = `${incident.reference} · ${incident.title}`;
    }
    for (const [id, marker] of markers.current) {
      if (!seen.has(id)) {
        marker.remove();
        markers.current.delete(id);
      }
    }
  }, [map, incidents]);

  useEffect(() => {
    (map?.getSource("exposure") as GeoJSONSource | undefined)?.setData(exposureFeatures(exposure));
  }, [map, exposure]);

  useEffect(() => {
    const incident = incidents.find((i) => i.id === selectedId);
    if (map && incident) map.flyTo({ center: [incident.lon, incident.lat], zoom: 11.2 });
    // Only when the selection changes, not on every refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selectedId]);

  return (
    <div className="nx-map" ref={container} data-testid="operations-map">
      {baseMissing && (
        <div className="nx-map-note">Base map not installed. Run `make tiles` (D-24).</div>
      )}
    </div>
  );
}
