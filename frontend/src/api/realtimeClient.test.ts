import { vi } from "vitest";

import { connectRealtime, type RealtimeEvent, staleKeys } from "./realtimeClient";

class FakeSocket {
  static sockets: FakeSocket[] = [];
  static at(i: number): FakeSocket {
    const socket = FakeSocket.sockets[i];
    if (!socket) throw new Error(`no socket ${i}`);
    return socket;
  }
  readyState = 0;
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.sockets.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
  }
  receive(msg: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(msg) }));
  }
}

const event = (name: string, data: Record<string, unknown> = {}): RealtimeEvent => ({
  type: "event",
  event: name,
  id: "e1",
  occurred_at: "2026-10-24T10:00:00Z",
  data,
});

describe("realtime client (PLT-05)", () => {
  beforeEach(() => {
    FakeSocket.sockets = [];
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("authenticates in the first message, never in the URL", async () => {
    const statuses: string[] = [];
    const events: RealtimeEvent[] = [];
    const stop = connectRealtime({
      url: "ws://host/ws",
      getToken: () => Promise.resolve("tok-1"),
      onEvent: (e) => events.push(e),
      onStatus: (s) => statuses.push(s),
      socket: (u) => new FakeSocket(u) as unknown as WebSocket,
    });
    const ws = FakeSocket.at(0);
    expect(ws.url).toBe("ws://host/ws");
    ws.open();
    await vi.waitFor(() => expect(ws.sent).toEqual([{ type: "auth", token: "tok-1" }]));
    ws.receive({ type: "ready" });
    ws.receive(event("INCIDENT_CREATED", { incident_id: "i1" }));
    expect(statuses).toEqual(["connecting", "live"]);
    expect(events.map((e) => e.event)).toEqual(["INCIDENT_CREATED"]);
    stop();
  });

  it("renews the token on the open socket", async () => {
    let n = 0;
    const stop = connectRealtime({
      url: "ws://host/ws",
      getToken: () => Promise.resolve(`tok-${++n}`),
      onEvent: () => undefined,
      onStatus: () => undefined,
      renewEveryMs: 1_000,
      socket: (u) => new FakeSocket(u) as unknown as WebSocket,
    });
    const ws = FakeSocket.at(0);
    ws.open();
    ws.receive({ type: "ready" });
    await vi.advanceTimersByTimeAsync(2_100);
    expect(ws.sent).toEqual([
      { type: "auth", token: "tok-1" },
      { type: "auth", token: "tok-2" },
      { type: "auth", token: "tok-3" },
    ]);
    stop();
  });

  it("reconnects with backoff and refetches once ready again", async () => {
    const statuses: string[] = [];
    const ready = vi.fn();
    const stop = connectRealtime({
      url: "ws://host/ws",
      getToken: () => Promise.resolve("t"),
      onEvent: () => undefined,
      onStatus: (s) => statuses.push(s),
      onReady: ready,
      socket: (u) => new FakeSocket(u) as unknown as WebSocket,
    });
    FakeSocket.at(0).close();
    expect(statuses.at(-1)).toBe("offline");
    await vi.advanceTimersByTimeAsync(999);
    expect(FakeSocket.sockets).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.sockets).toHaveLength(2);
    FakeSocket.at(1).open();
    FakeSocket.at(1).receive({ type: "ready" });
    expect(ready).toHaveBeenCalledTimes(1);
    stop();
    expect(statuses.at(-1)).toBe("live");
  });

  it("maps events to the queries they make stale", () => {
    expect(staleKeys(event("SIGNAL_INGESTED"))).toEqual([["signals"], ["operations-summary"]]);
    expect(staleKeys(event("EXPOSURE_COMPUTED", { incident_id: "i1" }))).toContainEqual([
      "incident",
      "i1",
    ]);
    expect(staleKeys(event("EXPOSURE_COMPUTED"))).toContainEqual(["people"]);
    expect(staleKeys(event("INCIDENT_NOTE_ADDED", { incident_id: "i1" }))).toEqual([
      ["incident", "i1"],
    ]);
    // D-33: a flight's status also shows on its trip (AT-07); positions only on the air view.
    expect(staleKeys(event("FLIGHT_UPDATED", { flight_id: "f1" }))).toEqual([["flights"], ["trips"]]);
    expect(staleKeys(event("FLIGHT_POSITIONS"))).toEqual([["flights"]]);
    // D-35: every 15 minutes and on a scenario override.
    expect(staleKeys(event("WEATHER_UPDATED", { missions: 36 }))).toEqual([["weather"]]);
    // D-36: a request made or moved (by a person, a playbook or the simulated partner).
    expect(staleKeys(event("PARTNER_REQUEST_UPDATED", { request_id: "r1" }))).toEqual([["partners"], ["evacuations"]]);
    // D-38: arming, disarming and the demo clock refresh the hazards screen (HZ-04, HZ-05).
    expect(staleKeys(event("PLAYBOOK_RUN_ARMED", { run_id: "r1", incident_id: "i1" }))).toEqual([
      ["hazards"],
      ["playbook-runs"],
      ["audit"],
      ["playbook-run", "r1"],
    ]);
    expect(staleKeys(event("PLAYBOOK_RUN_DISARMED", { run_id: "r1" }))).toContainEqual(["hazards"]);
    expect(staleKeys(event("HAZARD_CLOCK_ADVANCED", { advance_h: 24 }))).toEqual([["hazards"]]);
    expect(staleKeys(event("PLAYBOOK_RUN_STARTED", { run_id: "r1" }))).toContainEqual(["hazards"]);
    expect(staleKeys(event("INCIDENT_UPDATED", { incident_id: "i1" }))).toContainEqual(["hazards"]);
    expect(staleKeys(event("EXPOSURE_COMPUTED", { incident_id: "i1" }))).toContainEqual(["hazards"]);
    // D-39: an advisory's level or status, and an incident for the Avoid flag (plan-pilot-hl G-8).
    expect(staleKeys(event("HEALTH_ADVISORY_UPDATED", { advisory_id: "a1" }))).toEqual([["health"]]);
    expect(staleKeys(event("INCIDENT_CREATED", { incident_id: "i1" }))).toContainEqual(["health"]);
    expect(staleKeys(event("INCIDENT_UPDATED", { incident_id: "i1" }))).toContainEqual(["health"]);
    // D-40: the evacuation, its partners, its message and the incident behind it.
    expect(staleKeys(event("EVACUATION_UPDATED", { evacuation_id: "e1" }))).toEqual([["evacuations"], ["fleet"]]);
    expect(staleKeys(event("CAMPAIGN_UPDATED", { campaign_id: "c1" }))).toContainEqual(["evacuations"]);
    expect(staleKeys(event("INCIDENT_UPDATED", { incident_id: "i1" }))).toContainEqual(["evacuations"]);
    // D-41: the fleet, and the timelines a zone crossing wrote to (not INCIDENT_UPDATED, which
    // would recompute exposure); its states follow incidents, check-ins and evacuations.
    expect(staleKeys(event("FLEET_UPDATED", { asset_id: "a1", incident_ids: ["i1", 7] }))).toEqual([
      ["fleet"],
      ["incident", "i1"],
    ]);
    expect(staleKeys(event("FLEET_UPDATED", { asset_id: "a1", incident_ids: [] }))).toEqual([["fleet"]]);
    for (const type of ["INCIDENT_UPDATED", "CHECKIN_UPDATED", "EVACUATION_UPDATED"]) {
      expect(staleKeys(event(type, { incident_id: "i1" })), type).toContainEqual(["fleet"]);
    }
    expect(staleKeys(event("SOMETHING_ELSE"))).toEqual([]);
  });
});
