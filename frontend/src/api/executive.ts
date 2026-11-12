import { useQuery } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

// Executive Overview (Prompts 96-98; EXE-01..06, D-45). Every figure is worked out by the
// backend on read from what the other modules hold; aggregates and references only, never a
// person's name (EXE-04). The briefing's export is audited (EXE-03).

export type Posture = "GUARDED" | "ELEVATED" | "SEVERE";

export interface IncidentRef {
  id: string;
  reference: string;
  title: string;
  severity: string;
}

export interface Driver {
  kind:
    | "INCIDENT"
    | "EVACUATION"
    | "HEALTH"
    | "HAZARD"
    | "SUPPLY"
    | "FLEET"
    | "SHELTER";
  label: string;
  reference: string | null;
}

export interface Attention {
  mission_id: string;
  mission_code: string;
  city: string;
  risk: string;
  personnel: number;
  readiness: number | null;
  drivers: Driver[];
}

export interface Overview {
  posture: {
    level: Posture;
    critical_missions: number;
    elevated_missions: number;
  };
  active_incidents: number;
  latest_incident: IncidentRef | null;
  detection: {
    median_s: number | null;
    incidents: number;
    current_s: number | null;
    current_reference: string | null;
  };
  accounted: {
    pct: number | null;
    answered: number;
    asked: number;
    incident_references: string[];
  };
  // EXR-07: each embassy's latest exercise; illustrative while that is the seeded history.
  readiness: { mean: number | null; sites: number; from_exercises?: number; illustrative?: number };
  // GFX-05 (D-55): days before the first live data are illustrative, worked out on read.
  trend: { day: string; signals: number; incidents: number; source: "LIVE" | "ILLUSTRATIVE" }[];
  regions: { region: string; exposure: number; missions: number }[];
  attention: Attention[];
  timeline: {
    incident: IncidentRef | null;
    events: { occurred_at: string; event_type: string; summary: string }[];
    recent: {
      reference: string;
      title: string;
      change: "OPENED" | "CLOSED";
      at: string;
    }[];
  };
  generated_at: string;
  simulated: boolean;
}

export const executiveKeys = {
  all: ["executive"] as const, // what realtime invalidates
  overview: ["executive", "overview"] as const,
  // Not under "executive": realtime must not refetch it, since every fetch is an audited export.
  briefing: ["executive-briefing"] as const,
};

/** The posture's colour on the KPI (green, amber, red). */
export const POSTURE_COLOUR: Record<Posture, string> = {
  GUARDED: "#72CA9B",
  ELEVATED: "#FBB360",
  SEVERE: "#FA999C",
};

/** A mission risk's chip class. */
export const RISK_SEV: Record<string, string> = {
  CRITICAL: "crit",
  HIGH: "high",
  MODERATE: "med",
  LOW: "low",
};

/** "2m 41s", "45s", "1h 05m"; "—" when there is no figure. */
export function duration(seconds: number | null): string {
  if (seconds === null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600)
    return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

export function useOverview() {
  return useQuery({
    queryKey: executiveKeys.overview,
    queryFn: () => apiGet<Overview>("/api/executive/overview"),
    refetchInterval: 60_000, // the trend and timings move without an event too
  });
}

/** EXE-03: the briefing's figures; each fetch is audited, so it is fetched once per visit. */
export function useBriefing() {
  return useQuery({
    queryKey: executiveKeys.briefing,
    queryFn: () => apiSend<Overview>("POST", "/api/executive/export", {}),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

/** EXR-07: where the embassies' readiness comes from (plan-pilot-exr §5). */
export function readinessDetail(r: { from_exercises?: number; illustrative?: number }): string {
  if (!r.from_exercises) return "Mean embassy score · seeded values";
  return r.illustrative
    ? `Mean embassy score · from exercises · ${r.illustrative} illustrative`
    : "Mean embassy score · from exercises";
}
