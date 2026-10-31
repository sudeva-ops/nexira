import type { IconName } from "@blueprintjs/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";
import type { Severity } from "./intel";
import { playbookKeys, type PlaybookRun } from "./playbooks";

// Natural Hazards & Climate (Prompts 55-57; HZ-03, HZ-04, HZ-09, HZ-10, D-38). Feeds and
// climate scores are simulated (D-19). Every role reads counts, never names (HZ-10); the
// arming actions are hidden unless GET /api/me/permissions allows them, and the backend
// decides (G-1).

export type HazardCategory =
  "EARTHQUAKE" | "TROPICAL_CYCLONE" | "FLOOD" | "EXTREME_HEAT" | "AIR_QUALITY" | "WILDFIRE";
// backend/app/modules/intel/hazards.py HAZARD_CATEGORIES, in the design's tab order.
export const HAZARD_CATEGORIES: HazardCategory[] = [
  "EARTHQUAKE",
  "TROPICAL_CYCLONE",
  "FLOOD",
  "EXTREME_HEAT",
  "AIR_QUALITY",
  "WILDFIRE",
];
export const HAZARD_LABEL: Record<HazardCategory, string> = {
  EARTHQUAKE: "Earthquake",
  TROPICAL_CYCLONE: "Cyclone",
  FLOOD: "Flood",
  EXTREME_HEAT: "Heat",
  AIR_QUALITY: "Air quality",
  WILDFIRE: "Wildfire",
};
// Each hazard's own icon, on this screen and on the Global Operations map (HZ-09).
export const HAZARD_ICON: Record<HazardCategory, IconName> = {
  EARTHQUAKE: "pulse",
  TROPICAL_CYCLONE: "hurricane",
  FLOOD: "tint",
  EXTREME_HEAT: "temperature",
  AIR_QUALITY: "wind",
  WILDFIRE: "flame",
};

export function isHazard(category: string): category is HazardCategory {
  return (HAZARD_CATEGORIES as string[]).includes(category);
}

// The playbook the Response Planner arms for a cyclone (backend response_planner ARMED_PLAYBOOK).
export const ARMED_PLAYBOOK = "PB-06";
export const LANDFALL_LEAD_H = 36; // backend intel/hazards.py LANDFALL_LEAD_H (§43 Q4)

export interface HazardExposure {
  staff: number;
  people: number;
  homes: number;
  mission_sites: number;
}

export interface ArmedRun {
  run_id: string;
  playbook_code: string;
  status: string; // SCHEDULED, RUNNING, AWAITING_APPROVAL, COMPLETED, ..., DISARMED
  scheduled_for: string | null;
  starts_in_h: number | null;
  forecast_changed: boolean;
}

export interface HazardEvent {
  incident_id: string;
  reference: string;
  title: string;
  category: HazardCategory;
  severity: Severity;
  status: string;
  place_label: string | null;
  lat: number;
  lon: number;
  impact_radius_m: number;
  opened_at: string;
  updated_at: string;
  hazard: Record<string, unknown>;
  landfall_at: string | null;
  landfall_in_h: number | null;
  nearest_mission_code: string | null;
  nearest_mission_city: string | null;
  nearest_mission_m: number | null;
  within_range: boolean;
  exposed: boolean;
  exposure: HazardExposure;
  sources: string[];
  armed: ArmedRun | null;
  simulated: boolean;
}

export interface Hazards {
  events: HazardEvent[];
  clock_now: string; // the hazard clock: real time plus the demo advance (plan-pilot-hz §5)
  demo_advance_h: number;
  sources: number;
}

export interface ClimateRisk {
  mission_id: string;
  mission_code: string;
  city: string;
  hazards: string[];
  score_today: number;
  score_2050: number;
  scenario: string;
  source: string;
  simulated: boolean;
}

export interface ArmingPermissions {
  arm_playbook: boolean;
  start_armed: boolean;
  disarm: boolean;
}

export const hazardKeys = {
  all: ["hazards"] as const, // what realtime invalidates on incidents, arming and the demo clock
  events: ["hazards", "events"] as const,
  climate: ["hazards", "climate"] as const,
  permissions: (incidentId: string) => ["hazards", "permissions", incidentId] as const,
};

const HOUR_MS = 3_600_000;

/** Hours from the hazard clock to `iso`, `elapsedMs` after the list was read (HZ-04). */
export function hoursUntil(iso: string, clockNow: string, elapsedMs: number): number {
  return (new Date(iso).getTime() - new Date(clockNow).getTime() - elapsedMs) / HOUR_MS;
}

/** "landfall in 60 h", then "landfall in 40 min", then "landfall now". */
export function landfallText(hours: number): string {
  if (hours <= 0) return "landfall now";
  if (hours < 1) return `landfall in ${Math.max(1, Math.round(hours * 60))} min`;
  return `landfall in ${Math.round(hours)} h`;
}

/** The measure in words: "M5.2", "Cat 2", "AQI 310"; empty when there is none. */
export function measureText(e: Pick<HazardEvent, "category" | "hazard">): string {
  const h = e.hazard;
  if (e.category === "EARTHQUAKE" && typeof h.magnitude === "number") return `M${h.magnitude.toFixed(1)}`;
  if (e.category === "TROPICAL_CYCLONE" && typeof h.cyclone_category === "number") return `Cat ${h.cyclone_category}`;
  if (e.category === "AIR_QUALITY" && typeof h.aqi === "number") return `AQI ${h.aqi}`;
  return "";
}

/** HZ-03: the nearest mission and what is exposed there, e.g. "Jakarta mission · 2 staff homes". */
export function exposureText(e: HazardEvent, landfallInH: number | null): string {
  if (!e.within_range || !e.nearest_mission_code) return "No mission within 300 km";
  const mission = `${e.nearest_mission_city ?? e.nearest_mission_code} mission`;
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (e.category === "TROPICAL_CYCLONE" && landfallInH !== null) return `${mission} · ${landfallText(landfallInH)}`;
  if (e.exposure.homes > 0) return `${mission} · ${plural(e.exposure.homes, "staff home")}`;
  if (e.exposure.staff > 0) return `${mission} · ${e.exposure.staff} staff`;
  if (e.exposure.mission_sites > 0) return `${mission} · ${plural(e.exposure.mission_sites, "site")}`;
  const km = Math.round((e.nearest_mission_m ?? 0) / 1000);
  return `${mission} · ${km} km`;
}

const RANK: Record<Severity, number> = { CRITICAL: 3, HIGH: 2, MODERATE: 1, LOW: 0 };

/** HZ-09: the missions exposed now, each at the highest level of its events. */
export function exposedMissions(events: HazardEvent[]): Map<string, Severity> {
  const found = new Map<string, Severity>();
  for (const e of events) {
    if (!e.exposed || !e.nearest_mission_code) continue;
    const seen = found.get(e.nearest_mission_code);
    if (!seen || RANK[e.severity] > RANK[seen]) found.set(e.nearest_mission_code, e.severity);
  }
  return found;
}

/** HZ-09: a cyclone forecast that can still be armed: landfall more than 36 h away, no live run. */
export function armable(e: HazardEvent, landfallInH: number | null): boolean {
  return (
    e.category === "TROPICAL_CYCLONE" &&
    e.status === "ACTIVE" &&
    landfallInH !== null &&
    landfallInH > LANDFALL_LEAD_H &&
    (e.armed === null || e.armed.status === "DISARMED")
  );
}

export function useHazards() {
  return useQuery({
    queryKey: hazardKeys.events,
    queryFn: () => apiGet<Hazards>("/api/hazards"),
  });
}

export function useClimate() {
  return useQuery({
    queryKey: hazardKeys.climate,
    queryFn: () => apiGet<ClimateRisk[]>("/api/hazards/climate"),
    staleTime: 10 * 60_000, // reference data (HZ-08)
  });
}

export function useArmingPermissions(incidentId: string | undefined) {
  return useQuery({
    queryKey: hazardKeys.permissions(incidentId ?? ""),
    queryFn: () =>
      apiGet<ArmingPermissions>("/api/me/permissions", { entity_type: "hazards", entity_id: incidentId ?? "" }),
    enabled: !!incidentId,
  });
}

function useArmingMutation<T>(send: (arg: T) => Promise<PlaybookRun>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: hazardKeys.all });
      void client.invalidateQueries({ queryKey: playbookKeys.runs });
    },
  });
}

export function useArm() {
  return useArmingMutation((incidentId: string) =>
    apiSend<PlaybookRun>("POST", "/api/playbook-runs/arm", {
      playbook_code: ARMED_PLAYBOOK,
      incident_id: incidentId,
    }),
  );
}

export function useStartArmedNow() {
  return useArmingMutation((runId: string) => apiSend<PlaybookRun>("POST", `/api/playbook-runs/${runId}/start-now`, {}));
}

export function useDisarm() {
  return useArmingMutation((runId: string) => apiSend<PlaybookRun>("POST", `/api/playbook-runs/${runId}/disarm`, {}));
}
