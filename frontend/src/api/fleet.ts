import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Fleet & Assets (Prompts 72-75; FLT-01..07, D-41). The register and its telematics are
// simulated (D-19). Blocked, in an impact zone and assigned are worked out by the backend on
// every read (plan-pilot-flt §3). A driver's name only within the caller's scope (G-8). Every
// button comes from GET /api/me/permissions; the backend decides through app/core/approvals.py.

export type StateCode = "MAINTENANCE" | "BLOCKED" | "IN_ZONE" | "ASSIGNED" | "AVAILABLE" | "IN_USE";
export type StoredStatus = "AVAILABLE" | "IN_USE" | "MAINTENANCE";
export const STORED_STATUSES: StoredStatus[] = ["AVAILABLE", "IN_USE", "MAINTENANCE"];

export interface State {
  code: StateCode;
  reference: string | null;
}

export interface Asset {
  id: string;
  code: string;
  kind: "VEHICLE" | "EQUIPMENT";
  type_label: string;
  armoured: boolean;
  seats: number | null;
  mission_id: string;
  mission_code: string;
  city: string;
  location_label: string;
  lat: number;
  lon: number;
  at_site: boolean;
  fuel_pct: number;
  position_at: string;
  status: StoredStatus;
  status_reason: string | null;
  state: State;
  tags: State[];
  available: boolean;
  driver_assigned: boolean;
  driver_name: string | null;
  source: string;
  simulated: boolean;
}

export interface Capacity {
  seats_available: number;
  seats_needed: number;
  needed_from: "EVACUATION" | "PEOPLE";
  evacuation_reference: string | null;
  shortfall: number;
  suggestion: { partner_id: string; partner_name: string; sla_minutes: number } | null;
}

export interface MissionFleet {
  mission_id: string;
  mission_code: string;
  city: string;
  country_code: string;
  vehicles: number;
  available: number;
  generator_fuel_pct: number | null;
  capacity: Capacity;
  simulated: boolean;
}

export interface FleetSummary {
  vehicles: number;
  armoured: number;
  average_fuel_pct: number | null;
  maintenance_due: number;
}

export interface MaintenanceItem {
  id: string;
  asset_id: string;
  asset_code: string;
  mission_id: string;
  mission_code: string;
  task: string;
  due_on: string;
  done_at: string | null;
  done_by_type: "USER" | "WORKSHOP" | null;
  alert: boolean;
  overdue: boolean;
}

export interface FleetPermissions {
  set_asset_status: boolean;
  complete_maintenance: boolean;
}

export const fleetKeys = {
  all: ["fleet"] as const, // what realtime invalidates (FLEET_UPDATED and the states' sources)
  assets: (missionId: string) => ["fleet", "assets", missionId] as const,
  summary: ["fleet", "summary"] as const,
  mission: (missionId: string) => ["fleet", "mission", missionId] as const,
  maintenance: (missionId: string) => ["fleet", "maintenance", missionId] as const,
  permissions: (missionId: string) => ["fleet", "permissions", missionId] as const,
};

/** The design's status tags (FLT-02). */
export const STATE_LABEL: Record<StateCode, string> = {
  MAINTENANCE: "MAINTENANCE",
  BLOCKED: "BLOCKED · DRIVER SOS",
  IN_ZONE: "IN IMPACT ZONE",
  ASSIGNED: "ASSIGNED · EVAC",
  AVAILABLE: "AVAILABLE",
  IN_USE: "IN USE",
};
export const STATE_SEV: Record<StateCode, string> = {
  MAINTENANCE: "low",
  BLOCKED: "crit",
  IN_ZONE: "high",
  ASSIGNED: "high",
  AVAILABLE: "ok",
  IN_USE: "med",
};

/** The tags to show: the derived ones, or the stored status when none applies. */
export function shownStates(asset: Pick<Asset, "tags" | "state">): State[] {
  return asset.tags.length ? asset.tags : [asset.state];
}

/** "Overdue 3 d", "Due today", "Due in 5 d". */
export function dueText(dueOn: string, today: Date = new Date()): string {
  const day = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  const days = Math.round((Date.parse(dueOn) - day) / 86_400_000);
  if (days < 0) return `Overdue ${-days} d`;
  return days === 0 ? "Due today" : `Due in ${days} d`;
}

/** The mission to open: one with an ACTIVE incident, else every mission (FLT-06). */
export function defaultFleetMission(missions: { id: string; incident_id: string | null }[]): string {
  return missions.find((m) => m.incident_id !== null)?.id ?? "";
}

export function useFleetAssets(missionId: string) {
  return useQuery({
    queryKey: fleetKeys.assets(missionId),
    queryFn: () => apiGet<Asset[]>("/api/fleet/assets", missionId ? { mission_id: missionId } : undefined),
  });
}

export function useFleetSummary() {
  return useQuery({ queryKey: fleetKeys.summary, queryFn: () => apiGet<FleetSummary>("/api/fleet/summary") });
}

export function useMissionFleet(missionId: string) {
  return useQuery({
    queryKey: fleetKeys.mission(missionId),
    queryFn: () => apiGet<MissionFleet>(`/api/fleet/missions/${missionId}`),
    enabled: !!missionId,
  });
}

export function useMaintenance(missionId: string) {
  return useQuery({
    queryKey: fleetKeys.maintenance(missionId),
    queryFn: () =>
      apiGet<MaintenanceItem[]>("/api/fleet/maintenance", missionId ? { mission_id: missionId } : undefined),
  });
}

export function useFleetPermissions(missionId: string | undefined) {
  return useQuery({
    queryKey: fleetKeys.permissions(missionId ?? ""),
    queryFn: () =>
      apiGet<FleetPermissions>("/api/me/permissions", { entity_type: "fleet", entity_id: missionId ?? "" }),
    enabled: !!missionId,
  });
}

export function useSetStatus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, reason }: { id: string; status: StoredStatus; reason: string | null }) =>
      apiSend<Asset>("PATCH", `/api/fleet/assets/${id}/status`, reason ? { status, reason } : { status }),
    onSuccess: () => void client.invalidateQueries({ queryKey: fleetKeys.all }),
  });
}

export function useCompleteMaintenance() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiSend<MaintenanceItem[]>("POST", `/api/fleet/maintenance/${id}/done`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: fleetKeys.all }),
  });
}
