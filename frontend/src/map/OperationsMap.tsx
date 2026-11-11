import "maplibre-gl/dist/maplibre-gl.css";

import { type GeoJSONSource, Map as MapLibreMap, Marker, NavigationControl, Popup } from "maplibre-gl";
import { Icon } from "@blueprintjs/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { Annotation } from "../api/annotations";
import { HAZARD_ICON, isHazard } from "../api/hazards";
import type { Exposure, Incident } from "../api/intel";
import type { Mission } from "../api/people";
import { type Weather, weatherMarkers, weatherSummary } from "../api/weather";
import { useReducedMotion } from "../ui/useMotion";
import {
  circlePolygon,
  EXPOSURE_PULSE_MS,
  exposureFeatures,
  missionFeatures,
  type PulseTier,
  SEVERITY_COLOUR,
  zoneFeatures,
} from "./geo";
import { MapToggle } from "./MapToggle";
import {
  addAnnotationLayers,
  ANNOTATION_LAYERS,
  annotationFeatures,
  type Draft,
  draftFeatures,
  type LonLat,
} from "./annotations";
import { registerPmtiles, tilesAvailable } from "./base";
import { addDaylight } from "./daylight";
import { addStars } from "./stars";
import { GROW_MS, growScale } from "./motion";
import { breath, phase, sonar } from "./plane";
import {
  applyProjection,
  globePreferred,
  SELECT_BEARING,
  SELECT_PITCH,
  setGlobePreferred,
  startSpin,
} from "./three";
import { ATTRIBUTION, baseStyle, CITY_MINZOOM } from "./style";

const EMPTY = { type: "FeatureCollection" as const, features: [] };
const PULSE_TIERS: PulseTier[] = ["CRITICAL", "HIGH", "MODERATE"];
// Light ripples, so they read on the red impact zone: red, amber, yellow.
const RING_COLOUR: Record<PulseTier, string> = { CRITICAL: "#FF8F8F", HIGH: "#FBB360", MODERATE: "#FBD065" };
const PULSE_MS = 2400; // a mission halo's sonar
const BREATH_MS = 3200; // an impact zone's breath
const FRAME_MS = 40; // about 25 frames a second is enough for a pulse
// How fast an incident's rings go out, by severity (CSS --pulse).
const PULSE_BY_SEVERITY: Record<string, string> = {
  CRITICAL: "1.2s",
  HIGH: "1.8s",
  MODERATE: "2.6s",
  LOW: "3.4s",
};

interface Props {
  missions: Mission[];
  incidents: Incident[]; // ACTIVE incidents: marker and impact zone
  incidentsLoaded: boolean; // incidents present at first load are drawn whole; later ones grow in
  exposure: Exposure[]; // the selected incident's exposure (people at city zoom)
  selectedId: string | null;
  onSelect: (incident: Incident) => void;
  weather: Weather[]; // WX-02: the weather layer and the popup line; empty hides the layer
  weatherAt: number; // when it was fetched: staleness is judged from then (plan G-6)
  // Map annotations (ANN-01..03, D-52): those to show, the drawing in progress, and its events.
  annotations?: Annotation[];
  draft?: Draft | null;
  onDrawPoint?: (p: LonLat) => void;
  onDrawFinish?: () => void;
  onPickAnnotation?: (id: string) => void;
  onZoom?: (zoom: number) => void;
  // Nearby (NBY-01, NBY-05): the point and radius drawn, where a right-click or long press
  // asks for it, and where the map flies to (a new object each time).
  near?: { lon: number; lat: number; km: number } | null;
  onNearby?: (p: LonLat) => void;
  fly?: { lon: number; lat: number; zoom?: number } | null;
  mark?: { lon: number; lat: number } | null; // a search result's point (SRC-04)
}

const LONG_PRESS_MS = 600;
const STILL_PX = 5; // a right-click, not a right-drag (the map's rotate gesture: plan G-10)

const NO_ANNOTATIONS: Annotation[] = [];
const noop = () => {};

export function OperationsMap({
  missions,
  incidents,
  incidentsLoaded,
  exposure,
  selectedId,
  onSelect,
  weather,
  weatherAt,
  annotations = NO_ANNOTATIONS,
  draft = null,
  onDrawPoint = noop,
  onDrawFinish = noop,
  onPickAnnotation = noop,
  onZoom = noop,
  near = null,
  onNearby = noop,
  fly = null,
  mark = null,
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
  // The selected incident's radius sets how critical each exposed dot is (exposureTier).
  const radius = incidents.find((i) => i.id === selectedId)?.impact_radius_m ?? 5000;
  const known = useRef<Set<string> | null>(null); // incidents already on the map
  const [globe, setGlobe] = useState(globePreferred);
  const globeRef = useRef(globe);
  // The map's handlers read these, so they are set once and never stale.
  const drawing = useRef({ draft, onDrawPoint, onDrawFinish, onPickAnnotation, onZoom, onNearby });
  useEffect(() => {
    onSelectRef.current = onSelect;
    weatherRef.current = new Map(weather.map((w) => [w.mission_code, w]));
    drawing.current = { draft, onDrawPoint, onDrawFinish, onPickAnnotation, onZoom, onNearby };
  });

  useEffect(() => {
    let disposed = false;
    let created: MapLibreMap | null = null;
    let stopDaylight = () => {};
    let stopStars = () => {};
    registerPmtiles();
    void tilesAvailable().then((available) => {
      if (disposed || !container.current) return;
      setBaseMissing(!available);
      const m = new MapLibreMap({
        container: container.current,
        style: baseStyle(window.location.origin, available),
        center: [20, 15],
        zoom: globeRef.current ? 2 : 1.4, // a globe at 1.4 is small
        attributionControl: { compact: false, customAttribution: ATTRIBUTION },
      });
      created = m;
      m.addControl(new NavigationControl({ showCompass: false }), "top-right");
      m.on("load", () => {
        if (disposed) return;
        applyProjection(m, globeRef.current);
        stopDaylight = addDaylight(m);
        stopStars = addStars(m, () => globeRef.current);
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
        // In 3D, closer in: each impact zone rises as a translucent column, higher for higher
        // severity.
        m.addLayer({
          id: "zones-extrude",
          type: "fill-extrusion",
          source: "zones",
          minzoom: 5,
          paint: {
            "fill-extrusion-color": ["get", "colour"],
            "fill-extrusion-height": ["get", "height"],
            "fill-extrusion-opacity": 0.26,
          },
        });
        // Annotations (ANN-01): above the zones, under the missions and people.
        addAnnotationLayers(m, true);
        m.on("click", (e) => {
          if (drawing.current.draft) drawing.current.onDrawPoint([e.lngLat.lng, e.lngLat.lat]);
        });
        m.on("dblclick", (e) => {
          if (!drawing.current.draft) return;
          e.preventDefault(); // finishes the drawing instead of zooming in
          drawing.current.onDrawFinish();
        });
        for (const layer of ANNOTATION_LAYERS) {
          m.on("click", layer, (e) => {
            const id: unknown = e.features?.[0]?.properties?.id;
            if (!drawing.current.draft && typeof id === "string") drawing.current.onPickAnnotation(id);
          });
          m.on("mouseenter", layer, () => {
            if (!drawing.current.draft) m.getCanvas().style.cursor = "pointer";
          });
          m.on("mouseleave", layer, () => {
            if (!drawing.current.draft) m.getCanvas().style.cursor = "";
          });
        }
        // Nearby (NBY-01): a right-click that did not drag, or a long press on a touch screen.
        m.addSource("nearby", { type: "geojson", data: EMPTY });
        m.addLayer({
          id: "nearby-fill",
          type: "fill",
          source: "nearby",
          filter: ["==", ["geometry-type"], "Polygon"],
          paint: { "fill-color": "#4C90F0", "fill-opacity": 0.06 },
        });
        m.addLayer({
          id: "nearby-line",
          type: "line",
          source: "nearby",
          filter: ["==", ["geometry-type"], "Polygon"],
          paint: { "line-color": "#8ABBFF", "line-width": 1.5, "line-dasharray": [4, 3] },
        });
        m.addLayer({
          id: "nearby-point",
          type: "circle",
          source: "nearby",
          filter: ["==", ["geometry-type"], "Point"],
          paint: {
            "circle-color": "#8ABBFF",
            "circle-radius": 5,
            "circle-stroke-color": "#111418",
            "circle-stroke-width": 2,
          },
        });
        m.addSource("searched", { type: "geojson", data: EMPTY });
        m.addLayer({
          id: "searched",
          type: "circle",
          source: "searched",
          paint: {
            "circle-color": "transparent",
            "circle-radius": 11,
            "circle-stroke-color": "#FBD065",
            "circle-stroke-width": 3,
          },
        });
        let pressedAt: { x: number; y: number } | null = null;
        m.on("mousedown", (e) => {
          pressedAt = e.originalEvent.button === 2 ? { x: e.point.x, y: e.point.y } : null;
        });
        m.on("contextmenu", (e) => {
          const still =
            pressedAt !== null && Math.hypot(e.point.x - pressedAt.x, e.point.y - pressedAt.y) < STILL_PX;
          pressedAt = null;
          if (still && !drawing.current.draft) drawing.current.onNearby([e.lngLat.lng, e.lngLat.lat]);
        });
        let press = 0;
        m.on("touchstart", (e) => {
          window.clearTimeout(press);
          if (e.originalEvent.touches.length !== 1 || drawing.current.draft) return;
          const at: LonLat = [e.lngLat.lng, e.lngLat.lat];
          press = window.setTimeout(() => drawing.current.onNearby(at), LONG_PRESS_MS);
        });
        for (const name of ["touchend", "touchmove", "touchcancel"] as const) {
          m.on(name, () => window.clearTimeout(press));
        }
        const zoomed = () => drawing.current.onZoom(m.getZoom());
        m.on("zoomend", zoomed);
        zoomed();
        // A soft glow under each mission above LOW risk, stronger the higher, so what matters
        // stands out on the dark globe.
        m.addLayer({
          id: "missions-glow",
          type: "circle",
          source: "missions",
          filter: ["!=", ["get", "risk"], "LOW"],
          paint: {
            "circle-color": ["get", "colour"],
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 11, 8, 20],
            "circle-blur": 1,
            "circle-opacity": ["match", ["get", "risk"], "CRITICAL", 0.6, "HIGH", 0.5, 0.35],
          },
        });
        // Missions with an ACTIVE incident send out a sonar ring (two, half a beat apart).
        for (const id of ["mission-halo-a", "mission-halo-b"]) {
          m.addLayer({
            id,
            type: "circle",
            source: "missions",
            filter: ["==", ["get", "active"], true],
            paint: { "circle-color": ["get", "colour"], "circle-radius": 9, "circle-opacity": 0.3 },
          });
        }
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
        // Exposed people and sites at city zoom pulse by how critical they are: the more
        // critical, the quicker (one ring layer per tier, under the dots).
        for (const tier of PULSE_TIERS) {
          m.addLayer({
            id: `exposure-pulse-${tier}`,
            type: "circle",
            source: "exposure",
            minzoom: CITY_MINZOOM + 3,
            filter: ["==", ["get", "tier"], tier],
            paint: {
              "circle-color": RING_COLOUR[tier],
              "circle-radius": ["case", ["==", ["get", "kind"], "SITE"], 6, 3.5],
              "circle-opacity": 0,
              "circle-stroke-color": RING_COLOUR[tier],
              "circle-stroke-width": 1.5,
              "circle-stroke-opacity": 0,
            },
          });
        }
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
      stopDaylight();
      stopStars();
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
        // The diamond is drawn on an inner element: MapLibre sets the marker's own transform.
        const core = document.createElement("span");
        core.className = "nx-incident-core";
        el.append(core);
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
      el.style.setProperty("--pulse", PULSE_BY_SEVERITY[incident.severity] ?? "2.4s");
      el.classList.toggle("nx-hazard", isHazard(incident.category)); // its own icon (HZ-09)
      const drill = incident.exercise ? " · EXERCISE" : ""; // EXR-03
      el.setAttribute("aria-label", `${incident.reference} · ${incident.severity} · ${incident.title}${drill}`);
      el.title = `${incident.reference} · ${incident.title}${drill}`;
    }
    for (const [id, marker] of markers.current) {
      if (!seen.has(id)) {
        marker.remove();
        markers.current.delete(id);
        changed = true;
      }
    }
    if (changed) {
      setHazardElements(
        new Map(
          [...markers.current].map(([id, m]) => [
            id,
            m.getElement().querySelector<HTMLElement>(".nx-incident-core") ?? m.getElement(),
          ]),
        ),
      );
    }
    return () => cancelAnimationFrame(frame);
  }, [map, incidents, incidentsLoaded, reduced]);

  useEffect(() => {
    (map?.getSource("exposure") as GeoJSONSource | undefined)?.setData(exposureFeatures(exposure, radius));
  }, [map, exposure, radius]);

  useEffect(() => {
    (map?.getSource("annotations") as GeoJSONSource | undefined)?.setData(annotationFeatures(annotations));
  }, [map, annotations]);
  useEffect(() => {
    (map?.getSource("nearby") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: near
        ? [
            { type: "Feature", geometry: circlePolygon(near.lon, near.lat, near.km * 1000), properties: {} },
            { type: "Feature", geometry: { type: "Point", coordinates: [near.lon, near.lat] }, properties: {} },
          ]
        : [],
    });
  }, [map, near]);
  // The whole circle in view when Nearby opens or its radius changes (NBY-01).
  const nearKey = near ? `${near.lon},${near.lat},${near.km}` : null;
  useEffect(() => {
    if (!map || !near) return;
    const ring = circlePolygon(near.lon, near.lat, near.km * 1000).coordinates[0] ?? [];
    const lons = ring.map((p) => p[0] ?? near.lon);
    const lats = ring.map((p) => p[1] ?? near.lat);
    map.fitBounds(
      [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      { padding: 40, maxZoom: 14, pitch: 0, bearing: 0, duration: reduced ? 0 : 1200 },
    );
    // Only when the point or radius changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, nearKey]);
  useEffect(() => {
    if (map && fly) map.flyTo({ center: [fly.lon, fly.lat], zoom: fly.zoom ?? Math.max(map.getZoom(), 13) });
  }, [map, fly]);
  useEffect(() => {
    (map?.getSource("searched") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: mark ? [{ type: "Feature", geometry: { type: "Point", coordinates: [mark.lon, mark.lat] }, properties: {} }] : [],
    });
  }, [map, mark]);
  useEffect(() => {
    (map?.getSource("draft") as GeoJSONSource | undefined)?.setData(draftFeatures(draft));
    if (map) map.getCanvas().style.cursor = draft ? "crosshair" : "";
  }, [map, draft]);

  // Globe or flat (UI 2), and the slow turn of the world view while nobody touches it.
  useEffect(() => {
    globeRef.current = globe;
    if (map) applyProjection(map, globe);
  }, [map, globe]);
  useEffect(() => {
    if (!map || reduced) return;
    return startSpin(map, () => globeRef.current);
  }, [map, reduced]);

  // The live picture: impact zones breathe and missions with an ACTIVE incident pulse. None of
  // it with reduced motion; browsers pause animation frames in a hidden tab.
  useEffect(() => {
    if (!map || reduced) return;
    let frame = 0;
    let last = 0;
    const step = (now: number) => {
      if (now - last >= FRAME_MS) {
        last = now;
        if (map.getLayer("zones-fill")) {
          map.setPaintProperty("zones-fill", "fill-opacity", breath(now, BREATH_MS, 0.08, 0.26));
          map.setPaintProperty("zones-line", "line-opacity", breath(now, BREATH_MS, 0.5, 1));
          map.setPaintProperty("zones-extrude", "fill-extrusion-opacity", breath(now, BREATH_MS, 0.18, 0.34));
        }
        const k = phase(now, PULSE_MS);
        for (const [id, offset] of [["mission-halo-a", 0], ["mission-halo-b", 0.5]] as const) {
          if (!map.getLayer(id)) continue;
          const ring = sonar((k + offset) % 1, 5, 24);
          map.setPaintProperty(id, "circle-radius", ring.radius);
          map.setPaintProperty(id, "circle-opacity", ring.opacity);
        }
        for (const tier of PULSE_TIERS) {
          const id = `exposure-pulse-${tier}`;
          if (!map.getLayer(id)) continue;
          const ring = sonar(phase(now, EXPOSURE_PULSE_MS[tier]), 4, 16, 0.95);
          map.setPaintProperty(id, "circle-radius", ring.radius);
          map.setPaintProperty(id, "circle-stroke-opacity", ring.opacity);
          map.setPaintProperty(id, "circle-opacity", ring.opacity * 0.25);
        }
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [map, reduced]);

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
    // A tilted camera on the incident, its whole zone in view, so the zone and the people in
    // it stand up (UI 2); at most city zoom for a small zone.
    if (map && incident) {
      const ring = circlePolygon(incident.lon, incident.lat, incident.impact_radius_m).coordinates[0] ?? [];
      const lons = ring.map((p) => p[0] ?? incident.lon);
      const lats = ring.map((p) => p[1] ?? incident.lat);
      map.fitBounds(
        [
          [Math.min(...lons), Math.min(...lats)],
          [Math.max(...lons), Math.max(...lats)],
        ],
        { padding: 40, maxZoom: 12, pitch: reduced ? 0 : SELECT_PITCH, bearing: reduced ? 0 : SELECT_BEARING },
      );
    }
    // Only when the selection changes, not on every refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selectedId]);

  return (
    <div className="nx-map" ref={container} data-testid="operations-map">
      <MapToggle
        globe={globe}
        onChange={(g) => {
          setGlobePreferred(g);
          setGlobe(g);
        }}
      />
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
