import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Evacuation Management (Prompts 66-69; EV-01..09, D-40). Plans, the scanner, the charter and
// the convoy are simulated (D-19). Every role reads counts; names only within the caller's
// scope (plan-pilot-ev G-8). Every button comes from GET /api/me/permissions, and the
// backend decides through app/core/approvals.py.

export type EvacuationStatus = "PENDING_ACTIVATION" | "ACTIVE" | "COMPLETED" | "STOOD_DOWN";
export type Category = "STAFF" | "DELEGATE" | "DEPENDANT" | "CITIZEN";
export const CATEGORIES: Category[] = ["STAFF", "DELEGATE", "DEPENDANT", "CITIZEN"];
export const CATEGORY_LABEL: Record<Category, string> = {
  STAFF: "Staff",
  DELEGATE: "Delegate",
  DEPENDANT: "Dependant",
  CITIZEN: "Citizen",
};
export const ROLE_LABEL: Record<string, string> = {
  HEAD_OF_MISSION: "Head of Mission",
  HQ_CRISIS_DIRECTOR: "HQ Crisis Director",
};
const OTHER_ROLE: Record<string, string> = {
  HEAD_OF_MISSION: "HQ_CRISIS_DIRECTOR",
  HQ_CRISIS_DIRECTOR: "HEAD_OF_MISSION",
};

export interface PlanOption {
  role: "PRIMARY" | "BACKUP" | "CONTINGENCY";
  kind: "CHARTER" | "COMMERCIAL" | "ROAD";
  label: string;
  seats: number | null;
  partner_id: string | null;
  partner_name: string | null;
  covered: boolean;
}

export interface Plan {
  id: string;
  reference: string;
  mission_id: string;
  mission_code: string;
  city: string;
  muster_name: string;
  route_label: string;
  destination: string;
  options: PlanOption[];
  source: string;
  simulated: boolean;
}

export interface Step {
  step: number;
  name: string;
  at: string | null;
}

export interface Evacuation {
  id: string;
  reference: string;
  plan_reference: string;
  mission_id: string;
  incident_id: string | null;
  proposal_id: string | null;
  status: EvacuationStatus;
  requested_role: string;
  requested_by_name: string | null;
  requested_at: string;
  activated_by_name: string | null;
  activated_at: string | null;
  step: number | null;
  steps: Step[];
  stood_down_reason: string | null;
  counts: Record<Category, number>;
  checked_in: number;
  seats: number | null;
  documents_flagged: number;
  partner_requests: { reference: string; partner_name: string; service: string; status: string }[];
  message_reference: string | null;
  message_status: string | null;
  simulated: boolean;
}

/** Category, seat, name and document flag are null outside the caller's scope (G-8). */
export interface ManifestEntry {
  id: string;
  category: Category | null;
  seat: string | null;
  status: "EXPECTED" | "CHECKED_IN";
  checked_in_at: string | null;
  name: string | null;
  document_flag: boolean | null;
}

export interface EvacuationDetail extends Evacuation {
  manifest: ManifestEntry[];
  names_shown: boolean;
}

export interface EvacuationPermissions {
  activate_evacuation: boolean;
  confirm_evacuation: boolean;
  check_in_evacuee: boolean;
  advance_evacuation: boolean;
  stand_down_evacuation: boolean;
}

export const evacuationKeys = {
  all: ["evacuations"] as const, // what realtime invalidates (EVACUATION_UPDATED and more)
  plans: ["evacuations", "plans"] as const,
  list: (missionId: string) => ["evacuations", "list", missionId] as const,
  one: (id: string) => ["evacuations", "one", id] as const,
  permissions: (missionId: string) => ["evacuations", "permissions", missionId] as const,
};

export const LIVE: EvacuationStatus[] = ["PENDING_ACTIVATION", "ACTIVE"];

export function total(e: Pick<Evacuation, "counts">): number {
  return CATEGORIES.reduce((n, c) => n + (e.counts[c] ?? 0), 0);
}

/** "16 mission · 44 registered citizens" (EV-08). */
export function manifestText(e: Pick<Evacuation, "counts">): string {
  const mission = total(e) - (e.counts.CITIZEN ?? 0);
  const citizens = e.counts.CITIZEN ?? 0;
  return `${mission} mission · ${citizens} registered citizen${citizens === 1 ? "" : "s"}`;
}

/** Who must confirm a pending request: the role the requester did not use (G-1). */
export function waitingFor(e: Pick<Evacuation, "requested_role">): string {
  return ROLE_LABEL[OTHER_ROLE[e.requested_role] ?? ""] ?? "the second person";
}

/** The mission to open: a live evacuation's, else one with an ACTIVE incident (EV-08). */
export function defaultMission(
  latest: Evacuation[],
  missions: { id: string; incident_id: string | null }[],
): string | undefined {
  const live = latest.find((e) => LIVE.includes(e.status));
  if (live) return live.mission_id;
  return missions.find((m) => m.incident_id !== null)?.id ?? missions[0]?.id;
}

export function usePlans() {
  return useQuery({
    queryKey: evacuationKeys.plans,
    queryFn: () => apiGet<Plan[]>("/api/evacuations/plans"),
    staleTime: 10 * 60_000, // seeded reference data (EV-01)
  });
}

/** All evacuations, newest first; mission "" for every mission. */
export function useEvacuations(missionId = "") {
  return useQuery({
    queryKey: evacuationKeys.list(missionId),
    queryFn: () =>
      apiGet<Evacuation[]>("/api/evacuations", missionId ? { mission_id: missionId } : undefined),
  });
}

export function useEvacuation(id: string | undefined) {
  return useQuery({
    queryKey: evacuationKeys.one(id ?? ""),
    queryFn: () => apiGet<EvacuationDetail>(`/api/evacuations/${id}`),
    enabled: !!id,
  });
}

export function useEvacuationPermissions(missionId: string | undefined) {
  return useQuery({
    queryKey: evacuationKeys.permissions(missionId ?? ""),
    queryFn: () =>
      apiGet<EvacuationPermissions>("/api/me/permissions", {
        entity_type: "evacuation",
        entity_id: missionId ?? "",
      }),
    enabled: !!missionId,
  });
}

function useEvacuationMutation<T>(send: (arg: T) => Promise<Evacuation>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => void client.invalidateQueries({ queryKey: evacuationKeys.all }),
  });
}

export function useRequestEvacuation() {
  return useEvacuationMutation((missionId: string) =>
    apiSend<Evacuation>("POST", "/api/evacuations", { mission_id: missionId }),
  );
}

export function useConfirmEvacuation() {
  return useEvacuationMutation((id: string) =>
    apiSend<Evacuation>("POST", `/api/evacuations/${id}/confirm`, {}),
  );
}

export function useCheckIn() {
  return useEvacuationMutation(({ id, entry }: { id: string; entry: string }) =>
    apiSend<Evacuation>("POST", `/api/evacuations/${id}/manifest/${entry}/check-in`, {}),
  );
}

export function useAdvance() {
  return useEvacuationMutation(({ id, step }: { id: string; step: number }) =>
    apiSend<Evacuation>("POST", `/api/evacuations/${id}/advance`, { step }),
  );
}

export function useStandDown() {
  return useEvacuationMutation(({ id, reason }: { id: string; reason: string }) =>
    apiSend<Evacuation>("POST", `/api/evacuations/${id}/stand-down`, { reason }),
  );
}
