import type { Flight } from "../../api/flights";
import { IN_AIR } from "../../api/flights";
import type { OperationsSummary, Signal } from "../../api/intel";
import type { Activity, AgentRow } from "../../api/proposals";

// GFX-06 (D-55): the Decision Queue at rest. Every figure comes from an existing API; nothing
// here is made up, and a figure not yet loaded is shown as "—".

export interface WatchRow {
  label: string;
  value: string;
  detail: string;
}

const DAY_MS = 24 * 3_600_000;

/** What the agents are watching: missions, people, travellers in transit and feeds. */
export function watchingRows(
  summary: OperationsSummary | undefined,
  flights: Flight[] | undefined,
  signals: Signal[] | undefined,
  now: number,
): WatchRow[] {
  const inAir = (flights ?? []).filter((f) => IN_AIR.includes(f.status));
  const recent = (signals ?? []).filter((s) => now - new Date(s.received_at).getTime() < DAY_MS);
  const feeds = new Set(recent.map((s) => s.source_code)).size;
  const n = (v: number | undefined) => (v === undefined ? "—" : String(v));
  return [
    {
      label: "Missions",
      value: n(summary?.missions),
      detail: summary ? `${summary.missions_elevated} elevated · ${summary.missions_critical} critical` : "",
    },
    {
      label: "People",
      value: n(summary?.personnel),
      detail: summary ? `${summary.personnel_located} located · ${summary.citizens} citizens registered` : "",
    },
    {
      label: "In transit",
      value: flights ? String(inAir.reduce((sum, f) => sum + f.travellers.length, 0)) : "—",
      detail: `${inAir.length} ${inAir.length === 1 ? "flight" : "flights"} in the air${
        summary ? ` · ${summary.trips_active} ${summary.trips_active === 1 ? "trip" : "trips"} under way` : ""
      }`,
    },
    {
      label: "Feeds",
      value: signals ? String(feeds) : "—",
      detail: summary ? `${summary.signals_24h} signals in 24 h` : "",
    },
  ];
}

export interface AgentCheck {
  code: string;
  name: string;
  text: string;
  at: string | null;
}

/** Each agent's latest entry in the activity log, or what it is waiting for when it has none. */
export function agentChecks(agents: AgentRow[], activity: Activity[], paused: boolean): AgentCheck[] {
  return agents.map((a) => {
    const latest = activity.find((x) => x.actor === a.name); // the log is newest first
    if (latest) return { code: a.code, name: a.name, text: latest.text, at: latest.occurred_at };
    const text = paused
      ? "Paused (kill switch)"
      : !a.is_enabled
        ? "Switched off"
        : `Watching ${a.watches.length} event ${a.watches.length === 1 ? "type" : "types"} · nothing proposed yet`;
    return { code: a.code, name: a.name, text, at: null };
  });
}
