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
        active: m.incident_id !== null, // an ACTIVE incident at the mission: the map pulses it
      },
    })),
  };
}

/** Impact zones; `scale` draws a zone partly grown (0..1), as when an incident appears. */
/** How high an impact zone rises in the 3D view, by severity (metres; illustrative). */
export const ZONE_HEIGHT_M: Record<Severity, number> = {
  CRITICAL: 2400,
  HIGH: 1600,
  MODERATE: 1000,
  LOW: 600,
};

export function zoneFeatures(incidents: Incident[], scale: (id: string) => number = () => 1): FeatureCollection<Polygon> {
  return {
    type: "FeatureCollection",
    features: incidents.map(
      (i): Feature<Polygon> => ({
        type: "Feature",
        id: i.reference,
        geometry: circlePolygon(i.lon, i.lat, Math.max(1, i.impact_radius_m * scale(i.id))),
        properties: {
          reference: i.reference,
          colour: SEVERITY_COLOUR[i.severity],
          height: ZONE_HEIGHT_M[i.severity], // the raised zone in the 3D view
        },
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

export type PulseTier = "CRITICAL" | "HIGH" | "MODERATE";
/** How often a dot pulses, by how critical it is: the more critical, the quicker. */
export const EXPOSURE_PULSE_MS: Record<PulseTier, number> = { CRITICAL: 1200, HIGH: 1800, MODERATE: 2600 };
const TIERS: PulseTier[] = ["CRITICAL", "HIGH", "MODERATE"];
const ANSWER_TIER: Record<NonNullable<Exposure["checkin_status"]>, PulseTier | null> = {
  NEED_HELP: "CRITICAL",
  PENDING: "HIGH",
  SAFE: null,
};

/** How critical an exposed person or site is, so how fast its dot pulses (null: still).
 * A person asked in this incident's check-in: NEED HELP is CRITICAL, no answer yet HIGH, SAFE
 * still. Otherwise, and for sites, how close it is: the inner third of the impact zone is
 * CRITICAL, the middle HIGH, the outer MODERATE, a site one tier higher since many people
 * depend on it. Unknown distance: MODERATE. */
export function exposureTier(
  e: Pick<Exposure, "subject_type" | "distance_m" | "checkin_status">,
  radiusM: number,
): PulseTier | null {
  if (e.subject_type === "PERSON" && e.checkin_status) {
    return ANSWER_TIER[e.checkin_status];
  }
  if (e.distance_m === null || radiusM <= 0) return "MODERATE";
  const band = Math.min(2, Math.floor((3 * e.distance_m) / radiusM));
  return TIERS[Math.max(0, band - (e.subject_type === "SITE" ? 1 : 0))] ?? "MODERATE";
}

/** People in the zone (shown at city zoom) and exposed sites, each with its pulse tier. */
export function exposureFeatures(exposure: Exposure[], radiusM = 5000): FeatureCollection<Point> {
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
          tier: exposureTier(e, radiusM) ?? "STILL", // STILL matches no ripple layer
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

/** The initial great-circle bearing from a to b, in degrees clockwise from north (0..360);
 * [lat, lon] in. The heading a plane's icon points along. */
export function bearing(a: [number, number], b: [number, number]): number {
  const [lat1, lat2] = [a[0] * RAD, b[0] * RAD];
  const dLon = (b[1] - a[1]) * RAD;
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return (Math.atan2(y, x) / RAD + 360) % 360;
}

/** Where a flight is heading: the diversion airport once diverted, else its destination. */
function target(f: FlightLike): [number, number] | undefined {
  const [, destination, diversion] = f.route;
  return f.status === "DIVERTED" && diversion ? diversion : destination;
}

/** A flight's heading from where it is to where it is going; along its route before it leaves
 * and after it lands (the icon still points the way it flew). */
export function flightBearing(f: FlightLike): number {
  const [origin] = f.route;
  const to = target(f);
  if (!origin || !to) return 0;
  const here: [number, number] | null = f.lat !== null && f.lon !== null ? [f.lat, f.lon] : null;
  const far = here && Math.abs(here[0] - to[0]) + Math.abs(here[1] - to[1]) > 0.05;
  return here && far ? bearing(here, to) : bearing(origin, to);
}

export function flightFeatures(flights: FlightLike[]): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: flights
      .filter((f) => f.lat !== null && f.lon !== null)
      .map((f) => ({
        type: "Feature",
        geometry: point(f.lon ?? 0, f.lat ?? 0),
        properties: {
          id: f.id,
          label: f.flight_number,
          colour: flightColour(f.status),
          bearing: flightBearing(f),
          holding: f.status === "HOLDING",
        },
      })),
  };
}

const FLOWN: ReadonlySet<string> = new Set(["AIRBORNE", "HOLDING", "DIVERTED"]);

/** Each flight's route, split at the aircraft: the part flown (solid) and the part ahead
 * (dashed, moving). Before departure all of it is ahead; after landing all of it is flown. A
 * diverted flight's part ahead goes to the diversion airport. */
export function routeFeatures(flights: FlightLike[]): FeatureCollection<LineString> {
  const features: Feature<LineString>[] = [];
  const line = (f: FlightLike, from: [number, number], to: [number, number], part: string, steps = 48) => {
    const coordinates = greatCircle(from, to, steps);
    if (coordinates.length < 2) return;
    const colour = flightColour(part === "ahead" ? f.status : f.status === "DIVERTED" ? "AIRBORNE" : f.status);
    features.push({ type: "Feature", geometry: { type: "LineString", coordinates }, properties: { id: f.id, part, colour } });
  };
  for (const f of flights) {
    const [origin, destination] = f.route;
    const to = target(f);
    if (!origin || !destination || !to) continue;
    const here: [number, number] | null = f.lat !== null && f.lon !== null ? [f.lat, f.lon] : null;
    if (here && FLOWN.has(f.status)) {
      line(f, origin, here, "flown");
      line(f, here, to, "ahead", 32);
    } else if (f.status === "LANDED") {
      line(f, origin, to, "flown");
    } else {
      line(f, origin, to, "ahead");
    }
  }
  return { type: "FeatureCollection", features };
}
