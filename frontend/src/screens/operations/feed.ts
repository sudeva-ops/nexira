import type { Incident, Signal } from "../../api/intel";

export const MERGE_MS = 2_500;

export type FeedItem =
  | { kind: "incident"; at: string; incident: Incident }
  | { kind: "raw"; at: string; signal: Signal; merging: boolean };

/** OPS-02: fused incidents, unfused signals, and newly arrived signals that are
 *  shown raw for a moment before they merge into their incident. */
export function feedItems(incidents: Incident[], signals: Signal[], merging: Set<number>): FeedItem[] {
  const items: FeedItem[] = incidents.map((incident) => ({
    kind: "incident",
    at: incident.last_signal_at,
    incident,
  }));
  for (const signal of signals) {
    const isMerging = merging.has(signal.id);
    if (signal.incident_id === null || isMerging) {
      items.push({ kind: "raw", at: signal.received_at, signal, merging: isMerging });
    }
  }
  return items.sort((a, b) => b.at.localeCompare(a.at));
}
