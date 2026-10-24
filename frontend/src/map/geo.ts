import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

import type { Exposure, Incident, Severity } from "../api/intel";
import type { Mission } from "../api/people";

export const SEVERITY_COLOUR: Record<Severity, string> = {
  LOW: "#4C90F0",
  MODERATE: "#EC9A3C",
  HIGH: "#E76A6E",
  CRITICAL: "#CD4246",
};

// D-08: the mission labels; signals and incidents use the plain severity names.
export const MISSION_RISK_LABEL: Record<Severity, string> = {
  LOW: "Normal",
  MODERATE: "Elevated",
  HIGH: "High",
  CRITICAL: "Critical",
};

const EARTH_RADIUS_M = 6_371_008.8;

/** A geodesic circle as a polygon (the incident's impact zone). */
export function circlePolygon(lon: number, lat: number, radiusM: number, steps = 64): Polygon {
  const φ1 = (lat * Math.PI) / 180;
  const λ1 = (lon * Math.PI) / 180;
  const δ = radiusM / EARTH_RADIUS_M;
  const ring: [number, number][] = [];
  for (let i = 0; i <= steps; i += 1) {
    const θ = (2 * Math.PI * (i % steps)) / steps;
    const φ2 = Math.asin(Math.sin(φ1) * Math.cos(δ) + Math.cos(φ1) * Math.sin(δ) * Math.cos(θ));
    const λ2 =
      λ1 +
      Math.atan2(
        Math.sin(θ) * Math.sin(δ) * Math.cos(φ1),
        Math.cos(δ) - Math.sin(φ1) * Math.sin(φ2),
      );
    ring.push([(λ2 * 180) / Math.PI, (φ2 * 180) / Math.PI]);
  }
  return { type: "Polygon", coordinates: [ring] };
}

function point(lon: number, lat: number): Point {
  return { type: "Point", coordinates: [lon, lat] };
}

export function missionFeatures(missions: Mission[]): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: missions.map((m) => ({
      type: "Feature",
      id: m.code,
      geometry: point(m.lon, m.lat),
      properties: {
        code: m.code,
        city: m.city,
        risk: m.display_risk,
        label: MISSION_RISK_LABEL[m.display_risk],
        colour: SEVERITY_COLOUR[m.display_risk],
      },
    })),
  };
}

export function zoneFeatures(incidents: Incident[]): FeatureCollection<Polygon> {
  return {
    type: "FeatureCollection",
    features: incidents.map(
      (i): Feature<Polygon> => ({
        type: "Feature",
        id: i.reference,
        geometry: circlePolygon(i.lon, i.lat, i.impact_radius_m),
        properties: { reference: i.reference, colour: SEVERITY_COLOUR[i.severity] },
      }),
    ),
  };
}

const PERSON_COLOUR: Record<string, string> = {
  DIPLOMAT: "#8ABBFF",
  LOCAL_STAFF: "#8ABBFF",
  DELEGATE: "#BDADFF",
  CITIZEN: "#FBB360",
};

/** People in the zone (shown at city zoom) and exposed sites. */
export function exposureFeatures(exposure: Exposure[]): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: exposure
      .filter((e) => e.subject_type !== "TRIP" && e.lat !== null && e.lon !== null)
      .map((e) => ({
        type: "Feature",
        id: `${e.subject_type}:${e.subject_id}`,
        geometry: point(e.lon ?? 0, e.lat ?? 0),
        properties: {
          kind: e.subject_type,
          name: e.name,
          confidence: e.confidence,
          colour: e.subject_type === "SITE" ? "#F6F7F9" : (PERSON_COLOUR[e.kind] ?? "#ABB3BF"),
        },
      })),
  };
}
