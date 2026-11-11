import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Site Twin (TWN-01..06, D-43; docs/plan-pilot-twn.md §8). Every role reads it; a staff name
// only within the caller's people scope; guards and visitors are labels. Refreshed by realtime
// SITE_UPDATED (ids and counts only) and by what the overlays follow.

export type ZoneKind =
  | "OFFICE"
  | "SUITE"
  | "CONFERENCE"
  | "COMMS"
  | "SAFE_ROOM"
  | "LOBBY"
  | "CONSULAR"
  | "MUSTER"
  | "GATE";
export type OccupantKind = "STAFF" | "GUARD" | "VISITOR";
export type SensorStatus = "OK" | "DEGRADED" | "FAULT" | "OFFLINE";

export interface SiteSummary {
  id: string;
  name: string;
  site_type: string;
  mission_id: string;
  mission_code: string;
  city: string;
}

export interface Zone {
  id: string;
  code: string;
  name: string;
  kind: ZoneKind;
  x: number;
  y: number;
  w: number;
  h: number;
  capacity: number | null;
  count: number;
}

export interface Occupant {
  id: string;
  kind: OccupantKind;
  zone_code: string;
  name: string | null;
  label: string | null;
  since: string;
}

/** Where a camera is mounted and points, in plan units (TWN-08, PC-53); heading 0 is up the
 * plan, clockwise, and the field of view is centred on it. */
export interface Mount {
  x: number;
  y: number;
  heading_deg: number;
  fov_deg: number;
  range_u: number;
}

export interface Sensor {
  code: string;
  kind: string;
  label: string;
  zone_code: string | null;
  status: SensorStatus;
  detail: string | null;
  status_at: string;
  online: boolean;
  mount: Mount | null; // CCTV only
}

export interface SiteSystem {
  code: string;
  label: string;
  state: string;
  fuel_pct: number | null;
}

export interface ReadinessItem {
  id: string | null;
  label: string;
  done: boolean;
  done_by_name: string | null;
  done_at: string | null;
  derived: boolean;
  detail: string | null;
}

export interface Twin {
  site: SiteSummary;
  zones: Zone[];
  occupants: Occupant[];
  sensors: Sensor[];
  systems: SiteSystem[];
  counts: {
    on_site: number;
    staff: number;
    guards: number;
    visitors: number;
    safe_room: number;
    safe_room_capacity: number | null;
    sensors_online: number;
    sensors: number;
    faults: number;
  };
  shelter: { incident_id: string; incident_reference: string } | null;
  route: { code: string; label: string; path: number[][]; exit_zone_code: string; evacuation_reference: string } | null;
  readiness: { score: number | null; last_drill_on: string | null; items: ReadinessItem[] };
  source: string;
  simulated: boolean;
}

export const twinKeys = {
  all: ["twin"] as const, // what realtime invalidates
  sites: ["twin", "sites"] as const,
  twin: (siteId: string) => ["twin", "site", siteId] as const,
  permissions: (siteId: string) => ["twin", "permissions", siteId] as const,
  movements: (siteId: string) => ["twin", "movements", siteId] as const, // under "twin": live
};

export const OCCUPANT_COLOUR: Record<OccupantKind, string> = {
  STAFF: "#4C90F0",
  GUARD: "#9D7FDB",
  VISITOR: "#EC9A3C",
};
export const OCCUPANT_LABEL: Record<OccupantKind, string> = { STAFF: "Staff", GUARD: "Guard force", VISITOR: "Visitor" };
export const SENSOR_SEV: Record<SensorStatus, string> = { OK: "ok", DEGRADED: "med", FAULT: "high", OFFLINE: "crit" };

/** "3 weeks ago" from the last drill date (TWN-05). */
export function drillAgo(lastDrillOn: string | null, today: Date = new Date()): string | null {
  if (!lastDrillOn) return null;
  const day = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  const days = Math.max(0, Math.round((day - Date.parse(lastDrillOn)) / 86_400_000));
  if (days < 7) return days === 1 ? "1 day ago" : `${days} days ago`;
  const weeks = Math.round(days / 7);
  return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
}

/** Dot positions inside a zone: a grid of 16-unit cells, as the design. */
export function dotsIn(zone: Pick<Zone, "x" | "y" | "w">, count: number): { x: number; y: number }[] {
  const cols = Math.max(1, Math.floor((zone.w - 24) / 16));
  return Array.from({ length: count }, (_, k) => ({
    x: zone.x + 14 + (k % cols) * 16,
    y: zone.y + 36 + Math.floor(k / cols) * 16,
  }));
}

export function useTwinSites() {
  return useQuery({ queryKey: twinKeys.sites, queryFn: () => apiGet<SiteSummary[]>("/api/sites/twin") });
}

export function useTwin(siteId: string | undefined) {
  return useQuery({
    queryKey: twinKeys.twin(siteId ?? ""),
    queryFn: () => apiGet<Twin>(`/api/sites/${siteId}/twin`),
    enabled: !!siteId,
  });
}

export function useTwinPermissions(siteId: string | undefined) {
  return useQuery({
    queryKey: twinKeys.permissions(siteId ?? ""),
    queryFn: () => apiGet<{ tick_readiness: boolean }>("/api/me/permissions", { entity_type: "site", entity_id: siteId ?? "" }),
    enabled: !!siteId,
  });
}

export function useTickReadiness() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiSend<Twin>("POST", `/api/sites/readiness/${id}/done`, {}),
    onSuccess: (twin) => {
      client.setQueryData(twinKeys.twin(twin.site.id), twin);
      void client.invalidateQueries({ queryKey: twinKeys.all });
    },
  });
}

/** TWN-14 (D-53): one presence move, by kind and zone names only; never who. */
export interface Movement {
  at: string;
  kind: OccupantKind;
  from_zone: string | null; // null for an arrival
  to_zone: string | null; // null for a departure
}

export interface Movements {
  movements: Movement[];
  arrivals_today: number;
  departures_today: number;
  visitors_waiting: number;
}

export function useMovements(siteId: string | undefined) {
  return useQuery({
    queryKey: twinKeys.movements(siteId ?? ""),
    queryFn: () => apiGet<Movements>(`/api/sites/${siteId}/twin/movements`),
    enabled: !!siteId,
  });
}
