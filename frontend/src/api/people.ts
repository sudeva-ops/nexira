import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";
import type { Severity } from "./intel";

export interface Mission {
  id: string;
  code: string;
  city: string;
  country_code: string;
  lat: number;
  lon: number;
  risk_level: Severity;
  display_risk: Severity; // plan G-22: raised by the mission's worst ACTIVE incident
  incident_id: string | null;
  incident_reference: string | null;
  personnel: number;
  citizens: number;
}

export interface Person {
  id: string;
  full_name: string;
  person_type: string;
  role_title: string | null;
  mission_code: string | null;
  place_label: string | null;
  lat: number | null;
  lon: number | null;
  location_source: string | null;
  confidence: number | null;
  located_at: string | null;
  in_zone: boolean;
  incident_reference: string | null;
}

export interface Site {
  id: string;
  name: string;
  site_type: string;
  mission_code: string;
  city: string;
  lat: number;
  lon: number;
  readiness_score: number | null;
  last_drill_on: string | null;
  in_zone: boolean;
}

export interface Page<T> {
  total: number;
  items: T[];
}

export interface SitesPage extends Page<Site> {
  mission_property: number;
}

export const peopleKeys = {
  missions: ["missions"] as const,
  people: ["people"] as const,
  sites: ["sites"] as const,
};

export function useMissions() {
  return useQuery({
    queryKey: peopleKeys.missions,
    queryFn: () => apiGet<Mission[]>("/api/missions"),
  });
}

export function usePeople(q: string, limit: number) {
  return useQuery({
    queryKey: [...peopleKeys.people, q, limit],
    queryFn: () => apiGet<Page<Person>>("/api/people", q ? { q, limit } : { limit }),
    placeholderData: keepPreviousData,
  });
}

export function useSites(q: string) {
  return useQuery({
    queryKey: [...peopleKeys.sites, q],
    queryFn: () => apiGet<SitesPage>("/api/sites", q ? { q } : undefined),
    placeholderData: keepPreviousData,
  });
}
