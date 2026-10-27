import type { Feature, FeatureCollection, LineString, Point, Polygon } from "geojson";

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

// --- air picture (Prompt 31, D-33) ------------------------------------------------------

const FLIGHT_COLOUR: Record<string, string> = {
  SCHEDULED: "#8ABBFF",
  DELAYED: "#EC9A3C",
  AIRBORNE: "#8ABBFF",
  HOLDING: "#EC9A3C",
  DIVERTED: "#EC9A3C",
  LANDED: "#32A467",
  CANCELLED: "#738091",
};

export function flightColour(status: string): string {
  return FLIGHT_COLOUR[status] ?? "#8ABBFF";
}

type Vec = [number, number, number];
const RAD = Math.PI / 180;

function toVec([lat, lon]: [number, number]): Vec {
  return [Math.cos(lat * RAD) * Math.cos(lon * RAD), Math.cos(lat * RAD) * Math.sin(lon * RAD), Math.sin(lat * RAD)];
}

/** Points along the great circle from a to b ([lat, lon] in, [lon, lat] out). */
export function greatCircle(a: [number, number], b: [number, number], steps = 48): [number, number][] {
  const [px, py, pz] = toVec(a);
  const [qx, qy, qz] = toVec(b);
  const angle = Math.acos(Math.min(1, Math.max(-1, px * qx + py * qy + pz * qz)));
  if (angle < 1e-9) return [[a[1], a[0]]];
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i += 1) {
    const f = i / steps;
    const wa = Math.sin((1 - f) * angle) / Math.sin(angle);
    const wb = Math.sin(f * angle) / Math.sin(angle);
    const [x, y, z] = [wa * px + wb * qx, wa * py + wb * qy, wa * pz + wb * qz];
    out.push([Math.atan2(y, x) / RAD, Math.atan2(z, Math.hypot(x, y)) / RAD]);
  }
  return out;
}

interface FlightLike {
  id: string;
  flight_number: string;
  status: string;
  lat: number | null;
  lon: number | null;
  route: [number, number][];
}

export function flightFeatures(flights: FlightLike[]): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: flights
      .filter((f) => f.lat !== null && f.lon !== null)
      .map((f) => ({
        type: "Feature",
        geometry: point(f.lon ?? 0, f.lat ?? 0),
        properties: { id: f.id, label: f.flight_number, colour: flightColour(f.status) },
      })),
  };
}

/** The planned leg, and the diversion leg from the destination to the diversion airport. */
export function routeFeatures(flights: FlightLike[]): FeatureCollection<LineString> {
  const features: Feature<LineString>[] = [];
  for (const f of flights) {
    const [origin, destination, diversion] = f.route;
    if (!origin || !destination) continue;
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: greatCircle(origin, destination) },
      properties: { id: f.id, colour: flightColour(f.status === "DIVERTED" ? "AIRBORNE" : f.status) },
    });
    if (diversion) {
      features.push({
        type: "Feature",
        geometry: { type: "LineString", coordinates: greatCircle(destination, diversion, 16) },
        properties: { id: f.id, colour: flightColour("DIVERTED") },
      });
    }
  }
  return { type: "FeatureCollection", features };
}
