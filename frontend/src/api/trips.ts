import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";
import type { Requirement } from "./health";
import type { Severity } from "./intel";

// Journey Management (Prompts 25-26; JR-01..09, D-32). The backend decides every
// action; the screen only hides what GET /api/me/permissions says is not allowed.

export type TripStatus = "DRAFT" | "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED";
export type SegmentKind = "FLIGHT" | "STAY" | "MEETING" | "GROUND";
export const CHECK_ITEMS = [
  ["security_briefing", "Security briefing completed"],
  ["insurance_medical", "Travel insurance & medical cover"],
  ["emergency_contacts", "Emergency contacts verified"],
  ["checkin_schedule", "Check-in schedule agreed"],
] as const;
export type CheckItem = (typeof CHECK_ITEMS)[number][0];

export interface Trip {
  id: string;
  reference: string;
  purpose: string | null;
  origin: string;
  destination: string;
  destination_country: string | null;
  starts_on: string;
  ends_on: string;
  approval_status: TripStatus;
  restricted: boolean; // VIP or ministerial: flights never tracked (D-33)
  risk_level: Severity; // submitted; for a trip never submitted, what submitting gives now
  live_risk: Severity;
  risk_changed: boolean; // JR-07
  mission_id: string | null;
  requested_by: string | null;
  requested_by_name: string | null;
  submitted_at: string | null;
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  approved_risk_level: Severity | null;
  rejection_reason: string | null;
  checklist: Record<CheckItem | "security_approval", boolean>;
  travellers_count: number;
  impacted_by: string[]; // JR-06: ACTIVE incident references
  created_at: string;
}

/** A restricted trip's FLIGHT segments come masked for most roles (plan G-7): title
 *  "Flight (restricted)" and no place, times or flight fields. */
export interface Segment {
  seq: number;
  kind: SegmentKind;
  title: string;
  place_label: string | null;
  starts_at: string | null;
  ends_at: string | null;
  flight_number: string | null;
  from_airport: string | null;
  to_airport: string | null;
  flight_id: string | null; // set while tracked (D-33)
  flight_status: string | null;
}

export interface SegmentPlan {
  kind: SegmentKind;
  title: string;
  place_label: string | null;
  starts_at: string;
  ends_at: string;
  flight_number?: string | null;
  from_airport?: string | null;
  to_airport?: string | null;
}

export interface CountryRisk {
  country_code: string;
  level: Severity;
  base_level: Severity;
  rated: boolean;
  security: number | null;
  unrest: number | null;
  health: number | null;
  transport: number | null;
  source: string | null;
  incident_level: Severity | null;
  incidents: string[];
  simulated: boolean;
}

/** DX-06: no passport valid for 180 days after the trip ends. A warning; it never blocks approval. */
export interface DocumentWarning {
  person_id: string;
  full_name: string;
  valid_until: string | null; // the latest passport-type date; null if they hold none
}

export interface TripDetail extends Trip {
  travellers: { id: string; full_name: string; person_type: string }[];
  segments: Segment[];
  country_risk: CountryRisk | null;
  document_warnings: DocumentWarning[]; // DX-06: within the caller's document read scope
  health_requirement: Requirement | null; // HL-03, plan-pilot-hl G-9: the destination's, simulated
}

export interface TripPlan {
  purpose: string | null;
  origin: string;
  destination: string;
  destination_country: string;
  starts_on: string;
  ends_on: string;
  travellers: string[];
  segments: SegmentPlan[];
  restricted?: boolean;
}

export interface TripPermissions {
  edit_trip: boolean;
  submit_trip: boolean;
  approve_trip: boolean;
  reject_trip: boolean;
  check_trip: boolean;
  cancel_trip: boolean;
}

export interface TripFilters {
  status?: string;
  risk?: string;
  mission_id?: string;
  impacted?: string;
}

export const tripKeys = {
  all: ["trips"] as const, // what realtime invalidates on TRIP_UPDATED
  list: (filters: TripFilters) => [...tripKeys.all, "list", filters] as const,
  one: (id: string) => [...tripKeys.all, "one", id] as const,
  permissions: (id: string) => [...tripKeys.all, "permissions", id] as const,
};

export function useTrips(filters: TripFilters) {
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(filters)) if (v) params[k] = v;
  return useQuery({
    queryKey: tripKeys.list(filters),
    queryFn: () => apiGet<Trip[]>("/api/trips", params),
  });
}

export function useTrip(id: string | undefined) {
  return useQuery({
    queryKey: tripKeys.one(id ?? ""),
    queryFn: () => apiGet<TripDetail>(`/api/trips/${id}`),
    enabled: !!id,
  });
}

/** Plan G-07: what this user may do, from the same checks that enforce it. */
export function useTripPermissions(id: string | undefined) {
  return useQuery({
    queryKey: tripKeys.permissions(id ?? ""),
    queryFn: () =>
      apiGet<TripPermissions>("/api/me/permissions", { entity_type: "trip", entity_id: id ?? "" }),
    enabled: !!id,
  });
}

function useTripMutation<T>(send: (arg: T) => Promise<TripDetail>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: (trip) => {
      client.setQueryData(tripKeys.one(trip.id), trip);
      void client.invalidateQueries({ queryKey: tripKeys.all });
    },
  });
}

export function useSaveTrip() {
  return useTripMutation(({ id, plan }: { id: string | null; plan: TripPlan }) =>
    id
      ? apiSend<TripDetail>("PATCH", `/api/trips/${id}`, plan)
      : apiSend<TripDetail>("POST", "/api/trips", plan),
  );
}

export function useTripAction() {
  return useTripMutation(({ id, action }: { id: string; action: "submit" | "approve" | "cancel" }) =>
    apiSend<TripDetail>("POST", `/api/trips/${id}/${action}`, {}),
  );
}

export function useRejectTrip() {
  return useTripMutation(({ id, reason }: { id: string; reason: string }) =>
    apiSend<TripDetail>("POST", `/api/trips/${id}/reject`, { reason }),
  );
}

export function useCheckTrip() {
  return useTripMutation(({ id, item, done }: { id: string; item: CheckItem; done: boolean }) =>
    apiSend<TripDetail>("POST", `/api/trips/${id}/checklist`, { item, done }),
  );
}
