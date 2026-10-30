import type { IconName } from "@blueprintjs/core";
import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

// Weather (Prompt 41; WX-01, WX-02, D-35). Current conditions per mission from the
// simulated xWeather feed (D-19): refreshed every 15 minutes, stale after 30 (§28 Q2).

export type Condition = "CLEAR" | "CLOUD" | "RAIN" | "STORM" | "DUST" | "FOG" | "SNOW";

export interface Weather {
  mission_id: string;
  mission_code: string;
  city: string;
  country_code: string;
  lat: number;
  lon: number;
  observed_at: string;
  temperature_c: number;
  condition: Condition;
  wind_kph: number;
  gust_kph: number;
  rain_mm: number;
  source: string;
  stale: boolean; // as of the response; the screen re-checks against the clock (plan G-6)
}

export const STALE_AFTER_MS = 30 * 60_000;

export const CONDITION_LABEL: Record<Condition, string> = {
  CLEAR: "Clear",
  CLOUD: "Cloudy",
  RAIN: "Rain",
  STORM: "Storm",
  DUST: "Dust",
  FOG: "Fog",
  SNOW: "Snow",
};

export const CONDITION_ICON: Record<Condition, IconName> = {
  CLEAR: "flash",
  CLOUD: "cloud",
  RAIN: "tint",
  STORM: "lightning",
  DUST: "wind",
  FOG: "eye-off",
  SNOW: "snowflake",
};

/** How rough conditions are, for "worst first" and the map colour. */
export type WeatherLevel = "SEVERE" | "ROUGH" | "FAIR";
const LEVEL_RANK: Record<WeatherLevel, number> = {
  SEVERE: 2,
  ROUGH: 1,
  FAIR: 0,
};
export const LEVEL_COLOUR: Record<WeatherLevel, string> = {
  SEVERE: "#CD4246",
  ROUGH: "#EC9A3C",
  FAIR: "#8ABBFF",
};

export function weatherLevel(w: Weather): WeatherLevel {
  if (
    w.condition === "STORM" ||
    w.condition === "DUST" ||
    w.gust_kph >= 90 ||
    w.rain_mm >= 50 ||
    w.temperature_c >= 45 ||
    w.temperature_c <= -25
  ) {
    return "SEVERE";
  }
  if (
    w.condition === "SNOW" ||
    w.condition === "FOG" ||
    w.gust_kph >= 60 ||
    w.rain_mm >= 10 ||
    w.temperature_c >= 38 ||
    w.temperature_c <= -10
  ) {
    return "ROUGH";
  }
  return "FAIR";
}

/** WX-02: the worst conditions first; then the strongest gusts, then the city. */
export function worstFirst(rows: Weather[]): Weather[] {
  return [...rows].sort(
    (a, b) =>
      LEVEL_RANK[weatherLevel(b)] - LEVEL_RANK[weatherLevel(a)] ||
      b.gust_kph - a.gust_kph ||
      a.city.localeCompare(b.city),
  );
}

export function isStale(w: Weather, now: number = Date.now()): boolean {
  return w.stale || now - Date.parse(w.observed_at) > STALE_AFTER_MS;
}

/** One line: "Storm · 26°C · wind 110 km/h, gusts 150 · rain 60 mm". */
export function weatherSummary(w: Weather): string {
  const parts = [
    CONDITION_LABEL[w.condition],
    `${Math.round(w.temperature_c)}°C`,
    `wind ${w.wind_kph} km/h, gusts ${w.gust_kph}`,
  ];
  if (w.rain_mm > 0) parts.push(`rain ${w.rain_mm} mm`);
  return parts.join(" · ");
}

export interface WeatherMarker {
  code: string;
  lon: number;
  lat: number;
  icon: IconName;
  colour: string;
  title: string;
}

/** The map's weather layer: one icon per mission (WX-02). A stale reading is grey. */
export function weatherMarkers(rows: Weather[], now: number = Date.now()): WeatherMarker[] {
  return rows.map((w) => {
    const stale = isStale(w, now);
    return {
      code: w.mission_code,
      lon: w.lon,
      lat: w.lat,
      icon: CONDITION_ICON[w.condition],
      colour: stale ? "#738091" : LEVEL_COLOUR[weatherLevel(w)],
      title: `${w.city} · ${weatherSummary(w)}${stale ? " · stale" : ""}`,
    };
  });
}

export const weatherKeys = {
  all: ["weather"] as const, // what realtime invalidates on WEATHER_UPDATED
};

export function useWeather() {
  return useQuery({
    queryKey: weatherKeys.all,
    queryFn: () => apiGet<Weather[]>("/api/weather"),
    // Re-check staleness even when no update arrives (the feed may have stopped, G-6).
    refetchInterval: 60_000,
  });
}
