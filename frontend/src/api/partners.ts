import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Assistance Partners (Prompts 45-46; AS-01..08, D-36). Partners are fictional and answer
// through a simulated adapter (D-19): the screen labels everything simulated. The backend
// decides every action; the screen only hides what the user cannot do.

export type Service = "MEDICAL" | "EVACUATION" | "SECURE_TRANSPORT" | "WELFARE" | "RELOCATION";
export const SERVICES: Service[] = ["MEDICAL", "EVACUATION", "SECURE_TRANSPORT", "WELFARE", "RELOCATION"];
export const SERVICE_LABEL: Record<Service, string> = {
  MEDICAL: "Medical",
  EVACUATION: "Evacuation",
  SECURE_TRANSPORT: "Secure transport",
  WELFARE: "Welfare",
  RELOCATION: "Relocation",
};

export type RequestStatus = "REQUESTED" | "ACCEPTED" | "EN_ROUTE" | "COMPLETED" | "DECLINED" | "CANCELLED";
export const OPEN: RequestStatus[] = ["REQUESTED", "ACCEPTED", "EN_ROUTE"];
export const STATUS_LABEL: Record<RequestStatus, string> = {
  REQUESTED: "Requested",
  ACCEPTED: "Accepted",
  EN_ROUTE: "En route",
  COMPLETED: "Completed",
  DECLINED: "Declined",
  CANCELLED: "Cancelled",
};

export interface Partner {
  id: string;
  code: string;
  name: string;
  services: Service[];
  coverage: string[];
  sla_minutes: number;
  hours: string;
  is_active: boolean;
  simulated: boolean;
}

export interface Coverage {
  mission_id: string;
  code: string;
  city: string;
  country_code: string;
  missing: Service[];
}

export interface Suggestion {
  person_id: string;
  service: Service;
  mission_id: string;
  mission_code: string;
  country_code: string;
  partners: Partner[];
}

export interface PartnerRequest {
  id: string;
  reference: string;
  partner_id: string;
  partner_name: string;
  service: Service;
  mission_id: string;
  mission_code: string;
  incident_id: string | null;
  incident_reference: string | null;
  person_id: string | null;
  person_name: string | null;
  person_role: string | null;
  place_label: string | null;
  note: string | null;
  status: RequestStatus;
  eta: string | null;
  created_by_type: "USER" | "PLAYBOOK";
  requested_at: string;
  accepted_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export interface RequestBody {
  partner_id: string;
  service: Service;
  mission_id?: string;
  incident_id?: string;
  person_id?: string;
  note?: string;
}

export const partnerKeys = {
  all: ["partners"] as const, // what realtime invalidates on PARTNER_REQUEST_UPDATED
  directory: ["partners", "directory"] as const,
  coverage: ["partners", "coverage"] as const,
  requests: ["partners", "requests"] as const,
  suggest: (personId: string, service: Service) => ["partners", "suggest", personId, service] as const,
};

/** "SLA 15 min", "SLA 4 h", "SLA 1 h 30 min". */
export function slaText(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `SLA ${h ? `${h} h` : ""}${h && m ? " " : ""}${m || !h ? `${m} min` : ""}`;
}

/** AS-07: "34 / 36", and the missions with a gap, named. */
export function coverageSummary(rows: Coverage[]): { covered: number; total: number; gaps: Coverage[] } {
  const gaps = rows.filter((r) => r.missing.length > 0);
  return { covered: rows.length - gaps.length, total: rows.length, gaps };
}

export function usePartners() {
  return useQuery({
    queryKey: partnerKeys.directory,
    queryFn: () => apiGet<Partner[]>("/api/partners"),
    staleTime: 5 * 60_000, // seeded reference data (PC-21)
  });
}

export function useCoverage() {
  return useQuery({ queryKey: partnerKeys.coverage, queryFn: () => apiGet<Coverage[]>("/api/partners/coverage") });
}

export function usePartnerRequests() {
  return useQuery({ queryKey: partnerKeys.requests, queryFn: () => apiGet<PartnerRequest[]>("/api/partner-requests") });
}

export function useSuggestion(personId: string | undefined, service: Service) {
  return useQuery({
    queryKey: partnerKeys.suggest(personId ?? "", service),
    queryFn: () => apiGet<Suggestion>("/api/partners/suggest", { person_id: personId ?? "", service }),
    enabled: !!personId,
    retry: false, // a 409 (restricted traveller) is an answer, not a glitch
  });
}

function usePartnerMutation<T>(send: (arg: T) => Promise<PartnerRequest>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => void client.invalidateQueries({ queryKey: partnerKeys.all }),
  });
}

export function useRequestPartner() {
  return usePartnerMutation((body: RequestBody) => apiSend<PartnerRequest>("POST", "/api/partner-requests", body));
}

export function useRequestAction() {
  return usePartnerMutation(({ id, action }: { id: string; action: "cancel" | "complete" }) =>
    apiSend<PartnerRequest>("POST", `/api/partner-requests/${id}/${action}`, {}),
  );
}
