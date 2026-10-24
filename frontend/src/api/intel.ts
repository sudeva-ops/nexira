import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "./client";

export type Severity = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
export type IncidentStatus = "ACTIVE" | "MONITORING" | "CLOSED";

export interface SourceRef {
  code: string;
  name: string;
  simulated: boolean;
}

export interface Signal {
  id: number;
  source_code: string;
  source_name: string;
  source_simulated: boolean;
  external_id: string;
  title: string;
  provider_category: string | null;
  provider_severity: string | null;
  norm_category: string | null;
  norm_severity: Severity | null;
  norm_status: "NEW" | "NORMALISED" | "FUSED" | "DISCARDED";
  lat: number | null;
  lon: number | null;
  place_label: string | null;
  occurred_at: string;
  received_at: string;
  incident_id: string | null;
  incident_reference: string | null;
}

export interface Incident {
  id: string;
  reference: string;
  title: string;
  category: string;
  severity: Severity;
  signal_severity: Severity;
  status: IncidentStatus;
  confidence: number | null;
  mission_id: string | null;
  lat: number;
  lon: number;
  impact_radius_m: number;
  place_label: string | null;
  opened_at: string;
  last_signal_at: string;
  signal_count: number;
  sources: SourceRef[];
}

export interface ExposureSummary {
  staff: number;
  delegates: number;
  citizens: number;
  people: number;
  sites: number;
  mission_sites: number;
  protected_sites: number;
  trips: number;
}

export interface Exposure {
  subject_type: "PERSON" | "SITE" | "TRIP";
  subject_id: string;
  name: string;
  kind: string;
  mission_code: string | null;
  lat: number | null;
  lon: number | null;
  distance_m: number | null;
  confidence: number | null;
  location_source: string | null;
  place_label: string | null;
}

export interface IncidentEvent {
  id: number;
  event_type: string;
  summary: string;
  actor_type: "SYSTEM" | "AGENT" | "USER";
  actor_id: string | null;
  occurred_at: string;
  data: Record<string, unknown>;
}

export interface IncidentDetail extends Incident {
  mission_code: string | null;
  exposure_summary: ExposureSummary;
  exposure: Exposure[];
  signals: Signal[];
  timeline: IncidentEvent[];
}

export interface OperationsSummary {
  missions: number;
  missions_elevated: number;
  missions_critical: number;
  personnel: number;
  personnel_located: number;
  avg_location_confidence: number | null;
  citizens: number;
  mission_sites: number;
  trips_active: number;
  travellers_active: number;
  signals_24h: number;
  incidents_active: number;
  highest_active_severity: Severity | null;
}

export const keys = {
  incidents: ["incidents"] as const,
  incident: (id: string) => ["incident", id] as const,
  signals: ["signals"] as const,
  summary: ["operations-summary"] as const,
};

export function useIncidents(status?: IncidentStatus) {
  return useQuery({
    queryKey: [...keys.incidents, status ?? "all"],
    queryFn: () => apiGet<Incident[]>("/api/incidents", status ? { status } : undefined),
  });
}

export function useIncident(id: string | undefined) {
  return useQuery({
    queryKey: keys.incident(id ?? ""),
    queryFn: () => apiGet<IncidentDetail>(`/api/incidents/${id}`),
    enabled: !!id,
  });
}

export function useSignals(limit = 50) {
  return useQuery({
    queryKey: [...keys.signals, limit],
    queryFn: () => apiGet<Signal[]>("/api/signals", { limit }),
  });
}

export function useOperationsSummary() {
  return useQuery({
    queryKey: keys.summary,
    queryFn: () => apiGet<OperationsSummary>("/api/operations/summary"),
  });
}

function useIncidentMutation<T>(id: string, send: (body: T) => Promise<IncidentEvent>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.incident(id) });
      void client.invalidateQueries({ queryKey: keys.incidents });
    },
  });
}

export function useChangeStatus(id: string) {
  return useIncidentMutation(id, (status: IncidentStatus) =>
    apiSend<IncidentEvent>("PATCH", `/api/incidents/${id}/status`, { status }),
  );
}

export function useAddNote(id: string) {
  return useIncidentMutation(id, (text: string) =>
    apiSend<IncidentEvent>("POST", `/api/incidents/${id}/notes`, { text }),
  );
}
