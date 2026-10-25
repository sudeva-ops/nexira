// Pure formatting helpers shared by the screens.

import type { SourceRef } from "../api/intel";

/** D-19: simulated sources say so and are never labelled "Connected". */
export function sourceLabel(source: Pick<SourceRef, "name" | "simulated">): string {
  return source.simulated ? `${source.name} (simulated)` : source.name;
}

const LOCATION_SOURCE_LABEL: Record<string, string> = {
  MOBILE_GPS: "GPS",
  ACCESS_CONTROL: "Access control",
  CHECKIN: "Check-in",
  FLIGHT: "Flight",
  TRAVEL_BOOKING: "Travel booking",
  CALENDAR_HR: "Calendar / HR",
  MANUAL: "Manual",
};

/** The Location Confidence Engine's sources (PPL-03), in words. */
export function locationSourceLabel(source: string | null): string {
  return source ? (LOCATION_SOURCE_LABEL[source] ?? source) : "—";
}

/** Personnel before citizens, then nearest first (OPS-04, as in the demo). */
export function personnelFirst<T extends { kind: string; distance_m: number | null }>(xs: T[]): T[] {
  return [...xs].sort(
    (a, b) =>
      Number(a.kind === "CITIZEN") - Number(b.kind === "CITIZEN") ||
      (a.distance_m ?? 0) - (b.distance_m ?? 0),
  );
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

const PERSON_TYPE_LABEL: Record<string, string> = {
  DIPLOMAT: "Diplomat",
  LOCAL_STAFF: "Local staff",
  DEPENDANT: "Dependant",
  DELEGATE: "Delegate",
  CITIZEN: "Citizen",
  CONTRACTOR: "Contractor",
};

export function personTypeLabel(type: string): string {
  return PERSON_TYPE_LABEL[type] ?? type;
}

export function categoryLabel(category: string | null): string {
  if (!category) return "—";
  const words = category.toLowerCase().split("_");
  return words.map((w, i) => (i === 0 ? w[0]?.toUpperCase() + w.slice(1) : w)).join(" ");
}

/** Weeks since the last drill, or "—". */
export function drillAge(lastDrill: string | null, now: Date = new Date()): string {
  if (!lastDrill) return "—";
  const days = Math.floor((now.getTime() - new Date(lastDrill).getTime()) / 86_400_000);
  if (days < 7) return "this week";
  const weeks = Math.floor(days / 7);
  return `${weeks} week${weeks === 1 ? "" : "s"} ago`;
}

const ROLE_LABEL: Record<string, string> = {
  ADMIN: "Administrator",
  DUTY_OFFICER: "Duty Officer",
  SECURITY_OFFICER: "Security Officer",
  HEAD_OF_MISSION: "Head of Mission",
  HQ_CRISIS_DIRECTOR: "HQ Crisis Director",
  TRAVEL_DESK: "Travel Desk",
  CONSULAR_OFFICER: "Consular Officer",
  VIEWER: "Viewer",
};

/** "DUTY_OFFICER|SECURITY_OFFICER" -> "Duty Officer or Security Officer" (D-16). */
export function roleLabel(roles: string): string {
  return roles
    .split("|")
    .map((r) => ROLE_LABEL[r.trim()] ?? r.trim())
    .join(" or ");
}
