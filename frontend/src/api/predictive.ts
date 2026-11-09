import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

// Predictive Risk (Prompts 100-104; PRD-01..07, D-46). A stated, rule-based index per mission
// and a 14-day projection; advisory only, nothing changes because of a forecast (PRD-06). Every
// role reads it: aggregates, mission references and public calendar events only.

export interface Driver {
  key: string; // baseline, incidents, signals, health, hazard, weather, events
  label: string;
  points: number;
  change: number | null; // against 7 days ago; null when that day has no computed components
}

export interface HistoryPoint {
  day: string;
  value: number;
  source: "COMPUTED" | "ILLUSTRATIVE" | "LIVE";
}

export interface ForecastPoint {
  day: string;
  value: number;
  low: number;
  high: number;
}

export interface CalendarEvent {
  id: string;
  kind: string;
  title: string;
  place_label: string | null;
  starts_on: string;
  ends_on: string;
  attendance: number | null;
  weight: number;
  source: string;
}

export interface Rising {
  mission_id: string;
  mission_code: string;
  city: string;
  now: number;
  peak: number;
  peak_day: string;
  change: number;
  crosses: boolean;
}

export interface PredictiveOverview {
  threshold: number;
  model: string;
  rising: Rising[];
  actions: { mission_code: string; text: string }[];
  simulated: boolean;
}

export interface MissionRisk {
  mission_id: string;
  mission_code: string;
  city: string;
  threshold: number;
  model: string;
  now: number;
  history: HistoryPoint[]; // 30 days before today, then today's live figure
  forecast: ForecastPoint[]; // 14 days after today
  drivers: Driver[];
  events: CalendarEvent[]; // today and the next 14 days
  simulated: boolean;
}

export const predictiveKeys = {
  all: ["predictive"] as const, // what realtime invalidates
  overview: ["predictive", "overview"] as const,
  mission: (id: string) => ["predictive", "mission", id] as const,
};

/** The mission the screen opens on: the highest peak (§9), the first by code on a tie. */
export function defaultMission(rising: Rising[]): string | undefined {
  return [...rising].sort((a, b) => b.peak - a.peak || a.mission_code.localeCompare(b.mission_code))[0]
    ?.mission_id;
}

/** "05 Nov" from an ISO day, read as a calendar date (no time zone shift). */
export function shortDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1)).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}

export function usePredictiveOverview() {
  return useQuery({
    queryKey: predictiveKeys.overview,
    queryFn: () => apiGet<PredictiveOverview>("/api/predictive/overview"),
  });
}

export function useMissionRisk(id: string | undefined) {
  return useQuery({
    queryKey: predictiveKeys.mission(id ?? ""),
    queryFn: () => apiGet<MissionRisk>(`/api/predictive/missions/${id ?? ""}`),
    enabled: Boolean(id),
  });
}
