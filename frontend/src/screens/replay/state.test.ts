import { describe, expect, it } from "vitest";

import { at, REPLAY, T0 } from "./fixture";
import type { Replay } from "../../api/replay";
import { axis, elapsed, entryAt, PLAY_MS, QUIET_MS, rate, stateAt, step, toPlay, toRecord } from "./state";

const t = (s: number) => T0 + s * 1000;

describe("the incident at a moment (RPL-02, RPL-04)", () => {
  it("before the incident opened, only the first signal", () => {
    const m = stateAt(REPLAY, t(1));
    expect([m.signals.length, m.zone, m.people.length, m.exposed, m.tally]).toEqual([1, false, 0, 0, null]);
  });

  it("exposed, not yet asked", () => {
    const m = stateAt(REPLAY, t(5));
    expect(m.zone).toBe(true);
    expect(m.exposed).toBe(5); // the one without a place counts but is not drawn
    expect(m.people.map((p) => p.state)).toEqual(["NOT_ASKED", "NOT_ASKED", "NOT_ASKED", "NOT_ASKED"]);
    expect(m.sites).toHaveLength(1);
    expect(m.tally).toBeNull();
  });

  it("the check-in sent: waiting, then the answers given by then and no later ones", () => {
    expect(stateAt(REPLAY, t(10)).tally).toEqual({ recipients: 3, safe: 0, need_help: 0, pending: 3 });
    const m = stateAt(REPLAY, t(30));
    expect(m.people.map((p) => p.state)).toEqual(["SAFE", "WAITING", "WAITING", "NOT_ASKED"]);
    expect(m.tally).toEqual({ recipients: 3, safe: 1, need_help: 0, pending: 2 });
  });

  it("at the end it agrees with the Safety Check-in (tally_end)", () => {
    const end = Date.parse(REPLAY.window.end);
    const tally = stateAt(REPLAY, end).tally;
    expect(tally).toEqual({ recipients: 3, safe: 1, need_help: 1, pending: 1 });
    expect(REPLAY.checkin?.tally_end).toEqual(tally);
  });
});

describe("playing (RPL-03)", () => {
  it("with no quiet stretch, the whole window plays in a minute at 1×", () => {
    const a = axis(REPLAY);
    expect([a.total, a.breaks]).toEqual([60_000, []]);
    expect(rate(a, 1) * PLAY_MS).toBe(60_000);
    expect(rate(a, 4)).toBe(4 * rate(a, 1));
    expect(toPlay(a, t(25))).toBe(25_000);
  });

  it("an hour of quiet after the response plays as 30 s (G-9)", () => {
    const late: Replay = {
      ...REPLAY,
      window: { ...REPLAY.window, end: at(3660) },
      timeline: [
        ...REPLAY.timeline,
        { at: at(3660), source: "AGENT", text: "A proposal was escalated.", site_id: null, sensor: null },
      ],
    };
    const a = axis(late);
    expect(a.total).toBe(40_000 + QUIET_MS); // the last answer at 40 s, then the quiet hour
    expect(a.breaks).toEqual([{ from: 40_000, to: 40_000 + QUIET_MS, quietMs: 3_620_000 }]);
    expect(toPlay(a, t(40))).toBe(40_000);
    expect(toPlay(a, t(3660))).toBe(a.total);
    expect(toRecord(a, toPlay(a, t(30)))).toBe(t(30));
    expect(toRecord(a, a.total)).toBe(t(3660));
  });

  it("steps from entry to entry, inside the window", () => {
    expect(step(REPLAY, t(0), 1)).toBe(t(2));
    expect(step(REPLAY, t(10), 1)).toBe(t(40));
    expect(step(REPLAY, t(40), 1)).toBe(t(60));
    expect(step(REPLAY, t(10), -1)).toBe(t(2));
    expect(step(REPLAY, t(0), -1)).toBe(t(0));
  });

  it("the entry in force at t", () => {
    expect(entryAt(REPLAY, t(0) - 1)).toBe(-1);
    expect(entryAt(REPLAY, t(15))).toBe(2);
    expect(entryAt(REPLAY, Date.parse(at(60)))).toBe(3);
  });

  it("elapsed time", () => {
    expect(elapsed(0)).toBe("+0:00");
    expect(elapsed(754_000)).toBe("+12:34");
    expect(elapsed(3_723_000)).toBe("+1:02:03");
  });
});

describe("annotations on the replay (ANN-06)", () => {
  it("shows each from when it was added until it was withdrawn, with no label", () => {
    const kinds = (s: number) => stateAt(REPLAY, t(s)).annotations.map((a) => a.kind);
    expect([kinds(10), kinds(15), kinds(35), kinds(45), kinds(60)]).toEqual([
      [],
      ["MARK"],
      ["MARK", "AREA"],
      ["AREA"],
      ["AREA"],
    ]);
    expect(JSON.stringify(stateAt(REPLAY, t(35)).annotations)).not.toMatch(/label|note/);
  });
});
