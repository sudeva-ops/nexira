import type { QueryKey } from "@tanstack/react-query";

import { aarKeys } from "./aar";
import { checkinKeys } from "./checkin";
import { documentKeys } from "./documents";
import { evacuationKeys } from "./evacuations";
import { executiveKeys } from "./executive";
import { predictiveKeys } from "./predictive";
import { fleetKeys } from "./fleet";
import { supplyKeys } from "./supply";
import { twinKeys } from "./twin";
import { partnerKeys } from "./partners";
import { flightKeys } from "./flights";
import { hazardKeys } from "./hazards";
import { healthKeys } from "./health";
import { keys } from "./intel";
import { peopleKeys } from "./people";
import { playbookKeys } from "./playbooks";
import { proposalKeys } from "./proposals";
import { tripKeys } from "./trips";
import { weatherKeys } from "./weather";

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

// The events that move an Executive Overview figure (plan-pilot-exe §7).
const EXECUTIVE_EVENTS = new Set([
  "SIGNAL_INGESTED",
  "INCIDENT_CREATED",
  "INCIDENT_UPDATED",
  "EXPOSURE_COMPUTED",
  "PLAYBOOK_STEP", // a shelter alert
  "CAMPAIGN_QUEUED",
  "CAMPAIGN_UPDATED",
  "CHECKIN_UPDATED",
  "CHECKIN_ESCALATED",
  "EVACUATION_UPDATED",
  "HEALTH_ADVISORY_UPDATED",
  "FLEET_UPDATED",
  "SUPPLY_UPDATED",
]);

// The events that move a mission's risk index or forecast (plan-pilot-prd §9).
const PREDICTIVE_EVENTS = new Set([
  "PREDICTIVE_UPDATED", // a snapshot, or a calendar entry added
  "INCIDENT_CREATED",
  "INCIDENT_UPDATED",
  "EXPOSURE_COMPUTED",
  "HEALTH_ADVISORY_UPDATED",
  "WEATHER_UPDATED",
]);

/** The cached queries an event makes stale. */
export function staleKeys(event: RealtimeEvent): QueryKey[] {
  return [
    ...moduleKeys(event),
    ...(EXECUTIVE_EVENTS.has(event.event) ? [executiveKeys.all] : []),
    ...(PREDICTIVE_EVENTS.has(event.event) ? [predictiveKeys.all] : []),
  ];
}

function moduleKeys(event: RealtimeEvent): QueryKey[] {
  const incidentId = typeof event.data.incident_id === "string" ? event.data.incident_id : null;
  const incident = incidentId ? [keys.incident(incidentId)] : [];
  switch (event.event) {
    case "SIGNAL_INGESTED":
      return [keys.signals, keys.summary];
    case "INCIDENT_CREATED":
    case "INCIDENT_UPDATED":
      return [
        keys.incidents,
        keys.signals,
        keys.summary,
        peopleKeys.missions,
        hazardKeys.all,
        healthKeys.all, // a facility's Avoid flag follows ACTIVE incidents (plan-pilot-hl G-8)
        evacuationKeys.all, // "plan ready" needs an ACTIVE incident (plan-pilot-ev G-6)
        fleetKeys.all, // "in the impact zone" follows ACTIVE incidents (plan-pilot-flt §3)
        twinKeys.all, // shelter-in-place follows ACTIVE incidents (plan-pilot-twn §5)
        supplyKeys.all, // "impacted" and the zone tag follow ACTIVE incidents (plan-pilot-sup §4)
        aarKeys.all, // "ready for review" follows MONITORING and CLOSED incidents (D-47)
        ...incident,
      ];
    case "EXPOSURE_COMPUTED":
      return [
        keys.incidents,
        keys.summary,
        peopleKeys.missions,
        peopleKeys.people,
        peopleKeys.sites,
        hazardKeys.all, // the hazards screen's exposure counts (HZ-03)
        ...incident,
      ];
    case "INCIDENT_NOTE_ADDED":
      return incident;
    case "PLAYBOOK_RUN_STARTED":
    case "PLAYBOOK_RUN_UPDATED":
    case "PLAYBOOK_STEP":
    case "PLAYBOOK_STEP_APPROVED": {
      const runId = typeof event.data.run_id === "string" ? [playbookKeys.run(event.data.run_id)] : [];
      // Shelter-in-place follows a playbook's shelter alert (plan-pilot-twn G-4).
      return [playbookKeys.runs, playbookKeys.permissions, ["audit"], hazardKeys.all, twinKeys.all, ...runId, ...incident];
    }
    case "PLAYBOOK_RUN_ARMED": // the banner and the event's armed run (HZ-05, HZ-09)
    case "PLAYBOOK_RUN_DISARMED": {
      const runId = typeof event.data.run_id === "string" ? [playbookKeys.run(event.data.run_id)] : [];
      return [hazardKeys.all, playbookKeys.runs, ["audit"], ...runId];
    }
    case "HAZARD_CLOCK_ADVANCED": // countdowns read the hazard clock (plan-pilot-hz G-9)
      return [hazardKeys.all];
    case "HEALTH_ADVISORY_UPDATED": // the advisories, the KPIs and the mission's readiness (HL-08)
      return [healthKeys.all];
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
      // An evacuation's movement message shows its status there too (plan-pilot-ev §10).
      // A driver's check-in answer blocks or frees their vehicle (plan-pilot-flt G-2).
      return [checkinKeys.campaigns, ...campaignId, evacuationKeys.all, fleetKeys.all, ...incident];
    }
    case "TRIP_UPDATED":
      return [tripKeys.all];
    case "FLIGHT_UPDATED": // the trip shows each flight's status (AT-07)
      return [flightKeys.all, tripKeys.all];
    case "FLIGHT_POSITIONS": // the list and the open flight's altitude and speed
      return [flightKeys.all];
    case "PARTNER_REQUEST_UPDATED": // the requests list, and an evacuation's options (AS-03)
      return [partnerKeys.all, evacuationKeys.all];
    case "EVACUATION_UPDATED": // requested, activated, a check-in, a step, stood down (D-40)
      // Vehicles are assigned and the site's route shows while it is ACTIVE (plan-pilot-twn §5).
      return [evacuationKeys.all, fleetKeys.all, twinKeys.all];
    case "FLEET_UPDATED": {
      // A position, a status or a maintenance item (D-41). A zone crossing names its incidents,
      // whose timelines gain a FLEET entry: the event is not INCIDENT_UPDATED, which would make
      // the worker recompute exposure (plan-pilot-flt §6, review of Prompt 73).
      const ids = Array.isArray(event.data.incident_ids) ? event.data.incident_ids : [];
      const crossed = ids.filter((id): id is string => typeof id === "string").map((id) => keys.incident(id));
      // The twin shows the generator's state; a fuel supplier its stock (plan-pilot-sup G-7).
      return [fleetKeys.all, twinKeys.all, supplyKeys.all, ...crossed];
    }
    case "SITE_UPDATED": {
      // Presence, a sensor or readiness (D-43); a fault in an ACTIVE zone adds a SITE entry to
      // its incidents' timelines (plan-pilot-twn §4). Ids and counts only (G-8).
      const ids = Array.isArray(event.data.incident_ids) ? event.data.incident_ids : [];
      const touched = ids.filter((id): id is string => typeof id === "string").map((id) => keys.incident(id));
      return [twinKeys.all, ...touched];
    }
    case "SUPPLY_UPDATED":
      // A route, a supplier or a mitigation (D-44); ids and statuses only (G-8). A change at a
      // mission with an ACTIVE incident adds a SUPPLY entry to its timeline (plan-pilot-sup §4),
      // and the event does not name the incident, so every open incident detail refetches.
      return [supplyKeys.all, ["incident"]];
    case "WEATHER_UPDATED": // the panel, the map layer and the mission popup (WX-02)
      return [weatherKeys.all];
    case "AAR_UPDATED": // a review started, decided or finalised; its id only (D-47)
      return [aarKeys.all];
    case "DOCUMENT_UPDATED": // the register, its KPIs, and the trip warnings (DX-04, DX-06)
      return [documentKeys.all, tripKeys.all];
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
