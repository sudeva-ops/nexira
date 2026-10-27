import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

// Air Travel Tracking (Prompts 30-31; AT-01..08, D-33). Flights are simulated (D-19) and
// exist only for approved, unrestricted trips: there is nothing to hide on this screen.

export type FlightStatus =
  | "SCHEDULED"
  | "DELAYED"
  | "AIRBORNE"
  | "HOLDING"
  | "DIVERTED"
  | "LANDED"
  | "CANCELLED";
export const IN_AIR: FlightStatus[] = ["AIRBORNE", "HOLDING", "DIVERTED"];

export interface Flight {
  id: string;
  flight_number: string;
  status: FlightStatus;
  from_airport: string;
  from_city: string;
  to_airport: string;
  to_city: string;
  diverted_to: string | null;
  diverted_city: string | null;
  scheduled_dep: string;
  scheduled_arr: string;
  estimated_dep: string;
  estimated_arr: string;
  delay_min: number;
  disrupted: boolean;
  lat: number | null;
  lon: number | null;
  altitude_ft: number | null;
  speed_kt: number | null;
  progress: number;
  route: [number, number][]; // (lat, lon): origin, destination, diversion airport
  travellers: string[];
  trip_id: string;
  trip_reference: string;
  updated_at: string;
  simulated: boolean;
}

export interface FlightEvent {
  event_type: "DEPARTED" | "DELAYED" | "HOLDING" | "DIVERTED" | "LANDED" | "CANCELLED";
  occurred_at: string;
  details: Record<string, unknown>;
}

export interface FlightDetail extends Flight {
  events: FlightEvent[];
}

export interface Airport {
  iata: string;
  name: string;
  city: string;
  country_code: string;
}

export const flightKeys = {
  all: ["flights"] as const, // what realtime invalidates on FLIGHT_UPDATED / FLIGHT_POSITIONS
  list: ["flights", "list"] as const,
  one: (id: string) => ["flights", "one", id] as const,
  airports: ["airports"] as const,
};

export function useFlights() {
  return useQuery({ queryKey: flightKeys.list, queryFn: () => apiGet<Flight[]>("/api/flights") });
}

export function useFlight(id: string | undefined) {
  return useQuery({
    queryKey: flightKeys.one(id ?? ""),
    queryFn: () => apiGet<FlightDetail>(`/api/flights/${id}`),
    enabled: !!id,
  });
}

export function useAirports() {
  return useQuery({
    queryKey: flightKeys.airports,
    queryFn: () => apiGet<Airport[]>("/api/airports"),
    staleTime: Infinity, // simulated reference data (PC-18)
  });
}
