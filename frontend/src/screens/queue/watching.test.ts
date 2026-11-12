import { describe, expect, it } from "vitest";

import type { Flight } from "../../api/flights";
import type { OperationsSummary, Signal } from "../../api/intel";
import type { AgentRow } from "../../api/proposals";
import { agentChecks, watchingRows } from "./watching";

const NOW = Date.parse("2026-11-12T10:00:00Z");
const SUMMARY = {
  missions: 24,
  missions_elevated: 4,
  missions_critical: 0,
  personnel: 312,
  personnel_located: 298,
  citizens: 1840,
  trips_active: 3,
  signals_24h: 41,
} as OperationsSummary;
const flight = (status: Flight["status"], travellers: string[]) => ({ status, travellers }) as Flight;
const signal = (source_code: string, hoursAgo: number) =>
  ({ source_code, received_at: new Date(NOW - hoursAgo * 3_600_000).toISOString() }) as Signal;
const agent = (over: Partial<AgentRow>) =>
  ({ code: "RISK", name: "Risk Analyst", watches: ["SIGNAL", "INCIDENT"], is_enabled: true, ...over }) as AgentRow;

describe("watchingRows (GFX-06)", () => {
  it("counts missions, people, travellers in the air and the feeds heard from in 24 hours", () => {
    const rows = watchingRows(
      SUMMARY,
      [flight("AIRBORNE", ["a", "b"]), flight("HOLDING", ["c"]), flight("LANDED", ["d"])],
      [signal("DATAMINR", 1), signal("GDACS", 3), signal("DATAMINR", 5), signal("ACLED", 30)],
      NOW,
    );
    expect(rows.map((r) => [r.label, r.value])).toEqual([
      ["Missions", "24"],
      ["People", "312"],
      ["In transit", "3"],
      ["Feeds", "2"],
    ]);
    expect(rows[2]?.detail).toBe("2 flights in the air · 3 trips under way");
    expect(rows[3]?.detail).toBe("41 signals in 24 h");
  });

  it("shows a dash, not a made-up figure, before the data has loaded", () => {
    expect(watchingRows(undefined, undefined, undefined, NOW).map((r) => r.value)).toEqual(["—", "—", "—", "—"]);
  });
});

describe("agentChecks (GFX-06)", () => {
  it("takes each agent's latest log entry, else says what it waits for", () => {
    const activity = [
      { occurred_at: "2026-11-12T09:58:00Z", actor: "Response Planner", action: "PROPOSAL.CREATE", proposal_id: "p", text: "proposed Run PB-07" },
      { occurred_at: "2026-11-12T09:00:00Z", actor: "Response Planner", action: "PROPOSAL.CREATE", proposal_id: "q", text: "older" },
    ];
    const checks = agentChecks(
      [agent({}), agent({ code: "PLAN", name: "Response Planner" }), agent({ code: "OFF", name: "Off", is_enabled: false })],
      activity,
      false,
    );
    expect(checks.map((c) => [c.text, c.at])).toEqual([
      ["Watching 2 event types · nothing proposed yet", null],
      ["proposed Run PB-07", "2026-11-12T09:58:00Z"],
      ["Switched off", null],
    ]);
    expect(agentChecks([agent({})], [], true)[0]?.text).toBe("Paused (kill switch)");
  });
});
