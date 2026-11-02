import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// VIP & Delegation Protection (VIP-01..07, D-42; docs/plan-pilot-vip.md §8). Restricted: for
// anyone outside the protection roles the API answers 404, [] and {visible: false} (VIP-06).
// No realtime (G-3): the screen refetches every 10 s while open and after its own actions.

export type Risk = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
export type VisitStatus = "PLANNED" | "LIVE" | "COMPLETED" | "CANCELLED";
export type SegmentStatus = "PLANNED" | "IN_PROGRESS" | "COMPLETED";
export type ChangeStatus = "PENDING" | "APPROVED" | "REJECTED" | "CLOSED";

export interface Reason {
  level: Risk;
  text: string;
  incident_id: string | null;
  incident_reference: string | null;
}

export interface Change {
  id: string;
  segment_id: string;
  new_starts_at: string | null;
  new_ends_at: string | null;
  make_virtual: boolean;
  reason: string;
  proposed_by_name: string;
  proposed_at: string;
  status: ChangeStatus;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

export interface Segment {
  id: string;
  seq: number;
  kind: string;
  title: string;
  venue_name: string;
  starts_at: string;
  ends_at: string | null;
  attendees: number | null;
  virtual: boolean;
  status: SegmentStatus;
  risk: Risk;
  reasons: Reason[];
  recommendation: string | null;
  pending_change: Change | null;
}

export interface Vehicle {
  code: string;
  type_label: string | null;
  armoured: boolean;
  state: string;
  available: boolean;
}

export interface Detail {
  team_lead: string | null;
  advance_team: string | null;
  team_size: number | null;
  medic: boolean;
  vehicles: Vehicle[];
  medical: {
    facility_name: string | null;
    facility_distance_m: number | null;
    partner_name: string | null;
  };
  safe_havens: string[];
}

export interface ChecklistItem {
  id: string;
  label: string;
  due_on: string;
  done: boolean;
  done_at: string | null;
  done_by_name: string | null;
  overdue: boolean;
}

export interface VisitSummary {
  id: string;
  reference: string;
  title: string;
  mission_id: string;
  mission_code: string;
  starts_on: string;
  ends_on: string;
  status: VisitStatus;
  risk: Risk;
  simulated: boolean;
}

export interface Visit extends VisitSummary {
  principal_role: string;
  trip_id: string | null;
  trip_reference: string | null;
  country_risk: Risk | null;
  started_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  segments: Segment[];
  changes: Change[];
  detail: Detail;
  checklist: ChecklistItem[];
  kpis: {
    segments: number;
    high: number;
    team_size: number | null;
    vehicles: number;
    medics: number;
    venues: number;
    venues_surveyed: number;
  };
  source: string;
}

export interface VipPermissions {
  start_visit: boolean;
  progress_visit: boolean;
  cancel_visit: boolean;
  tick_vip_checklist: boolean;
  propose_vip_change: string[]; // segment ids
  decide_vip_change: string[]; // change ids
}

export const POLL_MS = 10_000; // G-3
export const vipKeys = {
  all: ["vip"] as const,
  access: ["vip", "access"] as const,
  visits: ["vip", "visits"] as const,
  visit: (id: string) => ["vip", "visit", id] as const,
  permissions: (id: string) => ["vip", "permissions", id] as const,
};

export const RISK_SEV: Record<Risk, string> = {
  LOW: "low",
  MODERATE: "med",
  HIGH: "high",
  CRITICAL: "crit",
};
export const STATUS_SEV: Record<SegmentStatus, string> = {
  PLANNED: "nt",
  IN_PROGRESS: "ok",
  COMPLETED: "ok",
};

const EAT = "Africa/Addis_Ababa";

/** "24 Oct 09:30" in the host city's time; the first segment of a day carries the date. */
export function segmentTime(
  segment: Segment,
  previous: Segment | undefined,
  timeZone: string = EAT,
): string {
  const day = (iso: string) =>
    new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      timeZone,
    }).format(new Date(iso));
  const clock = (iso: string) =>
    new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone,
    }).format(new Date(iso));
  const parts: string[] = [];
  const start = clock(segment.starts_at);
  parts.push(
    !previous || day(previous.starts_at) !== day(segment.starts_at)
      ? `${day(segment.starts_at)} ${start}`
      : start,
  );
  if (segment.kind === "MOTORCADE" && segment.ends_at) {
    parts.push(
      `${Math.round((Date.parse(segment.ends_at) - Date.parse(segment.starts_at)) / 60_000)} min`,
    );
  }
  if (segment.attendees !== null) parts.push(`${segment.attendees} attendees`);
  return parts.join(" · ");
}

/** "24–26 Oct" (VIP-07 banner). */
export function visitDates(
  visit: Pick<VisitSummary, "starts_on" | "ends_on">,
): string {
  const fmt = (iso: string, opts: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: "UTC" }).format(
      new Date(`${iso}T00:00:00Z`),
    );
  const sameMonth = visit.starts_on.slice(0, 7) === visit.ends_on.slice(0, 7);
  return sameMonth
    ? `${fmt(visit.starts_on, { day: "numeric" })}–${fmt(visit.ends_on, { day: "numeric", month: "short" })}`
    : `${fmt(visit.starts_on, { day: "numeric", month: "short" })} – ${fmt(visit.ends_on, { day: "numeric", month: "short" })}`;
}

/** The local wall time as an ISO string with the host city's offset (UTC+3, no daylight saving). */
export function localToIso(date: string, time: string): string {
  return `${date}T${time}:00+03:00`;
}

export function useVipAccess() {
  return useQuery({
    queryKey: vipKeys.access,
    queryFn: () => apiGet<{ visible: boolean }>("/api/vip/access"),
    staleTime: 60_000,
  });
}

export function useVisits(enabled: boolean) {
  return useQuery({
    queryKey: vipKeys.visits,
    queryFn: () => apiGet<VisitSummary[]>("/api/vip/visits"),
    enabled,
    refetchInterval: POLL_MS,
  });
}

export function useVisit(id: string | undefined) {
  return useQuery({
    queryKey: vipKeys.visit(id ?? ""),
    queryFn: () => apiGet<Visit>(`/api/vip/visits/${id}`),
    enabled: !!id,
    refetchInterval: POLL_MS,
  });
}

export function useVipPermissions(id: string | undefined) {
  return useQuery({
    queryKey: vipKeys.permissions(id ?? ""),
    queryFn: () =>
      apiGet<VipPermissions>("/api/me/permissions", {
        entity_type: "vip_visit",
        entity_id: id ?? "",
      }),
    enabled: !!id,
    refetchInterval: POLL_MS,
  });
}

function useVipAction<T>(send: (input: T) => Promise<Visit>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: (visit) => {
      client.setQueryData(vipKeys.visit(visit.id), visit);
      void client.invalidateQueries({ queryKey: vipKeys.all });
    },
  });
}

export const useStartVisit = () =>
  useVipAction((id: string) =>
    apiSend<Visit>("POST", `/api/vip/visits/${id}/start`, {}),
  );
export const useProgressSegment = () =>
  useVipAction((id: string) =>
    apiSend<Visit>("POST", `/api/vip/segments/${id}/progress`, {}),
  );
export const useTickItem = () =>
  useVipAction((id: string) =>
    apiSend<Visit>("POST", `/api/vip/checklist/${id}/done`, {}),
  );
export const useProposeChange = () =>
  useVipAction(
    ({
      segmentId,
      ...body
    }: {
      segmentId: string;
      reason: string;
      new_starts_at?: string;
      make_virtual?: boolean;
    }) =>
      apiSend<Visit>("POST", `/api/vip/segments/${segmentId}/changes`, body),
  );
export const useDecideChange = () =>
  useVipAction(
    ({ id, approve, note }: { id: string; approve: boolean; note?: string }) =>
      apiSend<Visit>(
        "POST",
        `/api/vip/changes/${id}/${approve ? "approve" : "reject"}`,
        note ? { note } : {},
      ),
  );
