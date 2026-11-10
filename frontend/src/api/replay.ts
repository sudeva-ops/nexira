import { useQuery } from "@tanstack/react-query";

import type { Severity } from "./intel";
import { apiGet } from "./client";

// Incident Replay (Prompts 122-126; RPL-01..07, D-51). One payload per incident, worked out on
// read from the record; the browser plays it back. People are indexed dots: no name, no id.

export interface Answer {
  at: string;
  status: "SAFE" | "NEED_HELP";
}

export interface ReplayPerson {
  index: number;
  lon: number | null;
  lat: number | null;
  exposed_at: string;
  personnel: boolean;
  asked: boolean;
  answers: Answer[];
}

export interface TimelineEntry {
  at: string;
  source: string;
  text: string;
  site_id: string | null;
  sensor: string | null;
}

export interface Replay {
  window: { start: string; end: string };
  incident: {
    id: string;
    reference: string;
    title: string;
    severity: Severity;
    status: "ACTIVE" | "MONITORING" | "CLOSED";
    lon: number;
    lat: number;
    impact_radius_m: number;
    opened_at: string;
    exercise: boolean;
  };
  signals: { received_at: string; lon: number | null; lat: number | null; severity: Severity | null }[];
  people: ReplayPerson[];
  sites: { name: string; lon: number | null; lat: number | null; exposed_at: string }[];
  trips: number;
  checkin: {
    reference: string;
    sent_at: string | null;
    personnel: Answer[][];
    tally_end: { recipients: number; safe: number; need_help: number; pending: number };
  } | null;
  timeline: TimelineEntry[];
}

export const replayKeys = { one: (id: string) => ["replay", id] as const };

/** A snapshot when opened (plan G-5): no refetch on focus or events; Refresh reloads it. */
export function useReplay(id: string | null) {
  return useQuery({
    queryKey: replayKeys.one(id ?? ""),
    queryFn: () => apiGet<Replay>(`/api/incidents/${id ?? ""}/replay`),
    enabled: id !== null,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
}
