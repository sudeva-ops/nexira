import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";
import type { Severity } from "./intel";
import { checkinKeys } from "./checkin";

// Health Intelligence (Prompts 61-63; HL-01..09, D-39). Advisories, requirements, facilities
// and readiness are simulated (D-19). Every role reads counts, never names (HL-09); the send
// button is hidden unless GET /api/me/permissions allows it, and the backend decides.

export interface AffectedMission {
  mission_id: string;
  code: string;
  city: string;
}

export interface Advisory {
  id: string;
  reference: string;
  topic: string;
  topic_code: string;
  countries: string[];
  region_label: string;
  level: Severity;
  guidance: string;
  source: string;
  status: "OPEN" | "CLOSED";
  published_at: string;
  updated_at: string;
  missions: AffectedMission[]; // HL-02: missions in its countries
  simulated: boolean;
}

export interface HealthSummary {
  open_advisories: number;
  affecting_missions: number;
  missions_with_advisory: number;
  by_level: { level: Severity; missions: number }[]; // CRITICAL first
  staff_not_offered: number; // plan-pilot-hl G-3
  vetted_facilities: number;
  simulated: boolean;
}

export interface Requirement {
  country_code: string;
  mandatory: string;
  recommended: string;
  source: string;
  simulated: boolean;
}

export interface Facility {
  id: string;
  name: string;
  capabilities: string[];
  trauma_level: number | null;
  open_24_7: boolean;
  vetted_by: string | null;
  distance_m: number;
  avoid: boolean; // inside an ACTIVE incident's impact radius (HL-04), computed on every read
  avoid_incident: string | null;
  source: string;
  simulated: boolean;
}

export interface Readiness {
  staff: number;
  blood_type_on_file: number;
  insurance_active: number;
  trauma_kits: number;
  vaccines: { topic_code: string; offered: number; open_advisory: boolean }[];
  as_of: string;
  source: string;
  simulated: boolean;
}

export interface MissionHealth {
  mission_id: string;
  code: string;
  city: string;
  country_code: string;
  level: Severity | null; // its highest OPEN advisory
  facilities: Facility[]; // nearest first
  readiness: Readiness | null;
  requirement: Requirement | null;
}

export interface HealthPermissions {
  send_advisory: boolean;
}

export interface CreatedCampaign {
  campaign_id: string;
  reference: string;
  status: string;
  template: string | null;
}

export const healthKeys = {
  all: ["health"] as const, // what realtime invalidates on advisories and incidents (G-8)
  advisories: ["health", "advisories"] as const,
  summary: ["health", "summary"] as const,
  requirements: ["health", "requirements"] as const,
  mission: (id: string) => ["health", "mission", id] as const,
  permissions: (missionId: string) => ["health", "permissions", missionId] as const,
};

const RANK: Record<Severity, number> = { CRITICAL: 3, HIGH: 2, MODERATE: 1, LOW: 0 };

/** "AVIAN_INFLUENZA" -> "Avian influenza", for a topic with no advisory to name it. */
export function topicWord(code: string): string {
  const words = code.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Each mission's highest OPEN advisory: mission id -> that advisory (HL-02). */
export function missionAdvisories(advisories: Advisory[]): Map<string, Advisory> {
  const found = new Map<string, Advisory>();
  for (const a of advisories) {
    if (a.status !== "OPEN") continue;
    for (const m of a.missions) {
      const seen = found.get(m.mission_id);
      if (!seen || RANK[a.level] > RANK[seen.level]) found.set(m.mission_id, a);
    }
  }
  return found;
}

/** HL-08's default: the mission with the highest advisory level, then the most staff. */
export function defaultMission(
  advisories: Advisory[],
  missions: { id: string; personnel: number }[],
): string | undefined {
  const levels = missionAdvisories(advisories);
  const rank = (id: string) => {
    const a = levels.get(id);
    return a ? RANK[a.level] + 1 : 0;
  };
  const ranked = [...missions].sort((a, b) => rank(b.id) - rank(a.id) || b.personnel - a.personnel);
  return ranked[0]?.id;
}

/** "450 m", "6.2 km". */
export function distanceText(m: number): string {
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

export function useAdvisories() {
  return useQuery({
    queryKey: healthKeys.advisories,
    queryFn: () => apiGet<Advisory[]>("/api/health/advisories"),
  });
}

export function useHealthSummary() {
  return useQuery({
    queryKey: healthKeys.summary,
    queryFn: () => apiGet<HealthSummary>("/api/health/summary"),
  });
}

export function useRequirements() {
  return useQuery({
    queryKey: healthKeys.requirements,
    queryFn: () => apiGet<Requirement[]>("/api/health/requirements"),
    staleTime: 10 * 60_000, // reference data (HL-03)
  });
}

export function useMissionHealth(missionId: string | undefined) {
  return useQuery({
    queryKey: healthKeys.mission(missionId ?? ""),
    queryFn: () => apiGet<MissionHealth>(`/api/health/missions/${missionId}`),
    enabled: !!missionId,
  });
}

export function useHealthPermissions(missionId: string | undefined) {
  return useQuery({
    queryKey: healthKeys.permissions(missionId ?? ""),
    queryFn: () =>
      apiGet<HealthPermissions>("/api/me/permissions", { entity_type: "health", entity_id: missionId ?? "" }),
    enabled: !!missionId,
  });
}

/** HL-06: a DRAFT campaign from the topic's template; it is submitted on Mass Notification. */
export function useCreateHealthCampaign() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ advisoryId, missionId }: { advisoryId: string; missionId: string }) =>
      apiSend<CreatedCampaign>("POST", `/api/health/advisories/${advisoryId}/campaign`, { mission_id: missionId }),
    onSuccess: () => void client.invalidateQueries({ queryKey: checkinKeys.campaigns }),
  });
}
