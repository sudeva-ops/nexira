import { eventLabel } from "./eventLabel";
import { formatTime, HOME_TZ } from "./time";

// What the live ticker shows (UI 3; Ticker.tsx): new events first, then the ACTIVE incidents.

export interface TickerItem {
  key: string;
  text: string;
  tone: "crit" | "high" | "info";
}

export function tickerItems(
  incidents: { id: string; reference: string; severity: string; title: string }[],
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
  const standing: TickerItem[] = incidents.map((i) => ({
    key: i.id,
    text: `${i.reference} · ${i.severity} · ${i.title}`,
    tone: i.severity === "CRITICAL" ? "crit" : i.severity === "HIGH" ? "high" : "info",
  }));
  return [...live, ...standing];
}
