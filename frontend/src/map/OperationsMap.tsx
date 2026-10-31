import "maplibre-gl/dist/maplibre-gl.css";

import { type GeoJSONSource, Map as MapLibreMap, Marker, NavigationControl, Popup } from "maplibre-gl";
import { Icon } from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { HAZARD_ICON, isHazard } from "../api/hazards";
import type { Exposure, Incident } from "../api/intel";
import type { Mission } from "../api/people";
import { type Weather, weatherMarkers, weatherSummary } from "../api/weather";
import { useReducedMotion } from "../ui/useMotion";
import { exposureFeatures, missionFeatures, SEVERITY_COLOUR, zoneFeatures } from "./geo";
import { registerPmtiles, tilesAvailable } from "./base";
import { GROW_MS, growScale } from "./motion";
import { ATTRIBUTION, baseStyle, CITY_MINZOOM } from "./style";

const EMPTY = { type: "FeatureCollection" as const, features: [] };

interface Props {
  missions: Mission[];
  incidents: Incident[]; // ACTIVE incidents: marker and impact zone
  incidentsLoaded: boolean; // incidents present at first load are drawn whole; later ones grow in
  exposure: Exposure[]; // the selected incident's exposure (people at city zoom)
  selectedId: string | null;
  onSelect: (incident: Incident) => void;
  weather: Weather[]; // WX-02: the weather layer and the popup line; empty hides the layer
  weatherAt: number; // when it was fetched: staleness is judged from then (plan G-6)
}

export function OperationsMap({
  missions,
  incidents,
  incidentsLoaded,
  exposure,
  selectedId,
  onSelect,
  weather,
  weatherAt,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [baseMissing, setBaseMissing] = useState(false);
  const markers = useRef(new Map<string, Marker>());
  const onSelectRef = useRef(onSelect);
  const weatherRef = useRef(new Map<string, Weather>());
  const wxMarkers = useRef(new Map<string, Marker>());
  const [wxElements, setWxElements] = useState(new Map<string, HTMLElement>());
  const [hazardElements, setHazardElements] = useState(new Map<string, HTMLElement>()); // HZ-09
  const wxData = useMemo(() => weatherMarkers(weather, weatherAt), [weather, weatherAt]);
  const reduced = useReducedMotion();
  const known = useRef<Set<string> | null>(null); // incidents already on the map
  useEffect(() => {
    onSelectRef.current = onSelect;
    weatherRef.current = new Map(weather.map((w) => [w.mission_code, w]));
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
            const wx = layer === "missions" ? weatherRef.current.get(String(p.code)) : undefined;
            const text =
              layer === "missions"
                ? `${p.city} (${p.code}) · ${p.label}${wx ? ` · ${weatherSummary(wx)}` : ""}`
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
    const wxPlaced = wxMarkers.current;
    return () => {
      disposed = true;
      for (const marker of [...placed.values(), ...wxPlaced.values()]) marker.remove();
      placed.clear();
      wxPlaced.clear();
      created?.remove();
    };
  }, []);

  useEffect(() => {
    (map?.getSource("missions") as GeoJSONSource | undefined)?.setData(missionFeatures(missions));
  }, [map, missions]);

  useEffect(() => {
    if (!map || !incidentsLoaded) return;
    // A new incident's zone grows out from its centre and its marker pings; those
    // already there when the screen opened are drawn as they are.
    const fresh = known.current ? incidents.filter((i) => !known.current?.has(i.id)).map((i) => i.id) : [];
    known.current = new Set(incidents.map((i) => i.id));
    const zones = map.getSource("zones") as GeoJSONSource | undefined;
    let frame = 0;
    if (reduced || fresh.length === 0) {
      zones?.setData(zoneFeatures(incidents));
    } else {
      let start: number | null = null;
      const step = (now: number) => {
        start ??= now;
        const k = growScale(now - start);
        zones?.setData(zoneFeatures(incidents, (id) => (fresh.includes(id) ? k : 1)));
        if (now - start < GROW_MS) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    }
    const seen = new Set<string>();
    let changed = false;
    for (const incident of incidents) {
      seen.add(incident.id);
      let marker = markers.current.get(incident.id);
      if (!marker) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = fresh.includes(incident.id) ? "nx-incident-marker nx-new" : "nx-incident-marker";
        el.dataset.testid = `incident-marker-${incident.reference}`;
        el.addEventListener("click", () => {
          const current = incidents.find((i) => i.id === incident.id) ?? incident;
          onSelectRef.current(current);
        });
        marker = new Marker({ element: el }).setLngLat([incident.lon, incident.lat]);
        marker.addTo(map);
        markers.current.set(incident.id, marker);
        changed = true;
      }
      const el = marker.getElement();
      el.style.setProperty("--c", SEVERITY_COLOUR[incident.severity]);
      el.classList.toggle("nx-hazard", isHazard(incident.category)); // its own icon (HZ-09)
      el.setAttribute("aria-label", `${incident.reference} · ${incident.severity} · ${incident.title}`);
      el.title = `${incident.reference} · ${incident.title}`;
    }
    for (const [id, marker] of markers.current) {
      if (!seen.has(id)) {
        marker.remove();
        markers.current.delete(id);
        changed = true;
      }
    }
    if (changed) setHazardElements(new Map([...markers.current].map(([id, m]) => [id, m.getElement()])));
    return () => cancelAnimationFrame(frame);
  }, [map, incidents, incidentsLoaded, reduced]);

  useEffect(() => {
    (map?.getSource("exposure") as GeoJSONSource | undefined)?.setData(exposureFeatures(exposure));
  }, [map, exposure]);

  // The weather layer (WX-02): a marker per mission, offset from its dot; the icon is
  // rendered into it by a portal below.
  useEffect(() => {
    if (!map) return;
    const seen = new Set<string>();
    let changed = false;
    for (const w of wxData) {
      seen.add(w.code);
      let marker = wxMarkers.current.get(w.code);
      if (!marker) {
        const el = document.createElement("div");
        el.className = "nx-wx-marker";
        el.dataset.testid = `weather-marker-${w.code}`;
        marker = new Marker({ element: el, offset: [14, -14] }).setLngLat([w.lon, w.lat]).addTo(map);
        wxMarkers.current.set(w.code, marker);
        changed = true;
      }
      const el = marker.getElement();
      el.style.setProperty("--c", w.colour);
      el.classList.toggle("severe", w.severe); // a severe-weather icon turns slowly
      el.title = w.title;
      el.setAttribute("aria-label", w.title);
    }
    for (const [code, marker] of wxMarkers.current) {
      if (!seen.has(code)) {
        marker.remove();
        wxMarkers.current.delete(code);
        changed = true;
      }
    }
    if (changed) {
      setWxElements(new Map([...wxMarkers.current].map(([code, m]) => [code, m.getElement()])));
    }
  }, [map, wxData]);

  useEffect(() => {
    const incident = incidents.find((i) => i.id === selectedId);
    if (map && incident) map.flyTo({ center: [incident.lon, incident.lat], zoom: 11.2 });
    // Only when the selection changes, not on every refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selectedId]);

  return (
    <div className="nx-map" ref={container} data-testid="operations-map">
      {incidents.map((i) => {
        const el = hazardElements.get(i.id);
        return el && isHazard(i.category)
          ? createPortal(<Icon icon={HAZARD_ICON[i.category]} size={10} />, el, i.id)
          : null;
      })}
      {wxData.map((w) => {
        const el = wxElements.get(w.code);
        return el ? createPortal(<Icon icon={w.icon} size={11} />, el, w.code) : null;
      })}
      {baseMissing && (
        <div className="nx-map-note">Base map not installed. Run `make tiles` (D-24).</div>
      )}
    </div>
  );
}
