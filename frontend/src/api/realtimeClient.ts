import type { QueryKey } from "@tanstack/react-query";

import { checkinKeys } from "./checkin";
import { keys } from "./intel";
import { peopleKeys } from "./people";
import { playbookKeys } from "./playbooks";
import { proposalKeys } from "./proposals";
import { tripKeys } from "./trips";

// PLT-05: one WebSocket per tab (backend: app/core/realtime.py). Events carry ids
// only; screens refetch through the REST API, so the cache stays the single
// source of what is shown.

export type RealtimeStatus = "connecting" | "live" | "offline";

export interface RealtimeEvent {
  type: "event";
  event: string;
  id: string;
  occurred_at: string;
  data: Record<string, unknown>;
}

/** The cached queries an event makes stale. */
export function staleKeys(event: RealtimeEvent): QueryKey[] {
  const incidentId = typeof event.data.incident_id === "string" ? event.data.incident_id : null;
  const incident = incidentId ? [keys.incident(incidentId)] : [];
  switch (event.event) {
    case "SIGNAL_INGESTED":
      return [keys.signals, keys.summary];
    case "INCIDENT_CREATED":
    case "INCIDENT_UPDATED":
      return [keys.incidents, keys.signals, keys.summary, peopleKeys.missions, ...incident];
    case "EXPOSURE_COMPUTED":
      return [
        keys.incidents,
        keys.summary,
        peopleKeys.missions,
        peopleKeys.people,
        peopleKeys.sites,
        ...incident,
      ];
    case "INCIDENT_NOTE_ADDED":
      return incident;
    case "PLAYBOOK_RUN_STARTED":
    case "PLAYBOOK_RUN_UPDATED":
    case "PLAYBOOK_STEP":
    case "PLAYBOOK_STEP_APPROVED": {
      const runId = typeof event.data.run_id === "string" ? [playbookKeys.run(event.data.run_id)] : [];
      return [playbookKeys.runs, playbookKeys.permissions, ["audit"], ...runId, ...incident];
    }
    case "PROPOSAL_CREATED":
    case "PROPOSAL_UPDATED":
    case "PROPOSAL_EXPIRED":
      return [proposalKeys.proposals, proposalKeys.agents, ...incident];
    case "CAMPAIGN_QUEUED":
    case "CAMPAIGN_UPDATED":
    case "CHECKIN_UPDATED":
    case "CHECKIN_ESCALATED": {
      const campaignId =
        typeof event.data.campaign_id === "string" ? [checkinKeys.checkin(event.data.campaign_id)] : [];
      return [checkinKeys.campaigns, ...campaignId, ...incident];
    }
    case "TRIP_UPDATED":
      return [tripKeys.all];
    default:
      return [];
  }
}

export interface ConnectOptions {
  url: string;
  getToken: () => Promise<string>;
  onEvent: (event: RealtimeEvent) => void;
  onStatus: (status: RealtimeStatus) => void;
  onReady?: () => void;
  renewEveryMs?: number;
  socket?: (url: string) => WebSocket;
}

const BACKOFF_MS = [1_000, 2_000, 5_000, 10_000];

/** Connects, authenticates with the first message, renews the token, reconnects
 *  with backoff. Returns a function that closes for good. */
export function connectRealtime(options: ConnectOptions): () => void {
  const { url, getToken, onEvent, onStatus, onReady } = options;
  const renewEveryMs = options.renewEveryMs ?? 60_000;
  const open = options.socket ?? ((u: string) => new WebSocket(u));
  let ws: WebSocket | null = null;
  let renew: ReturnType<typeof setInterval> | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;
  let stopped = false;

  const sendToken = async () => {
    try {
      const token = await getToken();
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "auth", token }));
    } catch {
      ws?.close();
    }
  };

  const connect = () => {
    if (stopped) return;
    onStatus("connecting");
    ws = open(url);
    ws.onopen = () => void sendToken();
    ws.onmessage = (message: MessageEvent<string>) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(message.data);
      } catch {
        return;
      }
      if (typeof parsed !== "object" || parsed === null) return;
      const msg = parsed as { type?: string };
      if (msg.type === "ready") {
        attempt = 0;
        onStatus("live");
        onReady?.();
        clearInterval(renew);
        renew = setInterval(() => void sendToken(), renewEveryMs);
      } else if (msg.type === "event") {
        onEvent(parsed as RealtimeEvent);
      }
    };
    ws.onclose = () => {
      clearInterval(renew);
      if (stopped) return;
      onStatus("offline");
      const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      retry = setTimeout(connect, delay);
    };
  };

  connect();
  return () => {
    stopped = true;
    clearInterval(renew);
    clearTimeout(retry);
    ws?.close();
  };
}
