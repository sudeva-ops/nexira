import { eventLabel } from "./eventLabel";
import { formatTime, HOME_TZ } from "./time";

// What the live ticker shows (UI 3; Ticker.tsx): new events first, then the open incidents
// (ACTIVE and MONITORING, UIP-01), most severe first.

export interface TickerItem {
  key: string;
  text: string;
  tone: "crit" | "high" | "info";
}

const OPEN = new Set(["ACTIVE", "MONITORING"]);
const RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MODERATE: 2, LOW: 3 };

export function tickerItems(
  incidents: { id: string; reference: string; severity: string; title: string; status: string }[],
  events: { id: string; event: string; incident_id?: string; code?: string; at: Date }[],
): TickerItem[] {
  const reference = new Map(incidents.map((i) => [i.id, i.reference]));
  const live: TickerItem[] = events.map((e) => {
    const about = (e.incident_id && reference.get(e.incident_id)) || e.code;
    return {
      key: e.id,
      text: `${formatTime(e.at, HOME_TZ)} · ${eventLabel(e.event)}${about ? ` · ${about}` : ""}`,
      tone: e.event.includes("ESCALAT") || e.event === "INCIDENT_CREATED" ? "high" : "info",
    };
  });
  const open = incidents
    .filter((i) => OPEN.has(i.status))
    .sort((a, b) => (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9));
  const standing: TickerItem[] = open.map((i) => ({
    key: i.id,
    text: `${i.reference} · ${i.severity} · ${i.title}`,
    tone: i.severity === "CRITICAL" ? "crit" : i.severity === "HIGH" ? "high" : "info",
  }));
  return [...live, ...standing];
}

/** UIP-01: scroll only when the items do not fit the strip; otherwise stand still, once each. */
export function scrolls(track: number, view: number): boolean {
  return view > 0 && track > view;
}
