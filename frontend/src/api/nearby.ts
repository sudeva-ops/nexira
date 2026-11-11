import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

// Nearby (Prompts 130-131; NBY-01..06, D-52): what is within a radius of a point, from the record,
// as the person asking. Names only within their people scope; counts for everyone in range.

export interface Located {
  distance_m: number;
  lon: number;
  lat: number;
}

export interface Nearby {
  lon: number;
  lat: number;
  radius_m: number;
  country_code: string | null;
  mission_code: string | null;
  people: {
    staff: number;
    delegates: number;
    citizens: number;
    others: number;
    confidence: number | null;
    named: (Located & {
      id: string;
      name: string;
      group: "STAFF" | "DELEGATE" | "CITIZEN" | "OTHER";
      confidence: number;
      place_label: string | null;
    })[];
    unnamed: number;
  };
  sites: (Located & { id: string; name: string; site_type: string; mission_code: string })[];
  vehicles: (Located & { id: string; code: string; type_label: string; status: string })[];
  travellers: { people: number; trips: number };
  partners: { id: string; name: string; services: string[]; sla_minutes: number }[];
  incidents: (Located & {
    id: string;
    reference: string;
    title: string;
    severity: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
    category: string;
  })[];
  annotations: (Located & { id: string; kind: string; symbol: string | null; label: string })[];
}

/** NBY-02: the radii, in km; 10 by default. */
export const RADII_KM = [1, 5, 10, 25, 50] as const;
export const DEFAULT_RADIUS_KM = 10;

export interface Near {
  lon: number;
  lat: number;
  km: number;
}

/** NBY-06: "?near=-1.2921,36.8219&r=10" (lat first, as people write it) and back. */
export function parseNear(near: string | null, r: string | null): Near | null {
  const m = near?.match(/^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[2]);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  const km = Number(r);
  return { lon, lat, km: (RADII_KM as readonly number[]).includes(km) ? km : DEFAULT_RADIUS_KM };
}

export function nearParams(n: Near): { near: string; r: string } {
  return { near: `${n.lat.toFixed(5)},${n.lon.toFixed(5)}`, r: String(n.km) };
}

/** "350 m", "2.4 km". */
export function distanceText(m: number): string {
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(m < 10_000 ? 1 : 0)} km`;
}

export const nearbyKeys = {
  all: ["nearby"] as const,
  at: (n: Near) => ["nearby", n.lon, n.lat, n.km] as const,
};

export function useNearby(near: Near | null) {
  return useQuery({
    queryKey: near ? nearbyKeys.at(near) : nearbyKeys.all,
    queryFn: () =>
      apiGet<Nearby>("/api/nearby", {
        lon: near?.lon ?? 0,
        lat: near?.lat ?? 0,
        radius_m: (near?.km ?? DEFAULT_RADIUS_KM) * 1000,
      }),
    enabled: near !== null,
  });
}
