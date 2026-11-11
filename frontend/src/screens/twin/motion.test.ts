import { furniture } from "./furniture";
import { drift, hash, shareFill, spots } from "./motion";

const ZONE = { x: 130, y: 30, w: 270, h: 220 };

describe("people on the plan (TWN-12)", () => {
  it("gives each occupant a stable spot inside its zone, whatever the order", () => {
    const keys = Array.from({ length: 11 }, (_, i) => `person-${i}`);
    const a = spots(ZONE, keys);
    const b = spots(ZONE, [...keys].reverse());
    expect([...a.entries()].sort()).toEqual([...b.entries()].sort());
    for (const { x, y } of a.values()) {
      expect(x).toBeGreaterThan(ZONE.x);
      expect(x).toBeLessThan(ZONE.x + ZONE.w);
      expect(y).toBeGreaterThan(ZONE.y + 20); // under the zone's name
      expect(y).toBeLessThan(ZONE.y + ZONE.h);
    }
  });

  it("keeps people apart, and a newcomer does not move the others", () => {
    const keys = Array.from({ length: 11 }, (_, i) => `person-${i}`);
    const placed = [...spots(ZONE, keys).values()];
    for (const [i, p] of placed.entries()) {
      for (const q of placed.slice(i + 1)) expect(Math.hypot(p.x - q.x, p.y - q.y)).toBeGreaterThan(8);
    }
    const before = spots(ZONE, keys.slice(0, 5));
    const after = spots(ZONE, [...keys.slice(0, 5), "newcomer"]);
    const kept = keys.slice(0, 5).filter((k) => JSON.stringify(before.get(k)) === JSON.stringify(after.get(k)));
    expect(kept.length).toBeGreaterThanOrEqual(4); // at most one gives way to the newcomer
  });

  it("fits a small zone, sharing a spot only when full", () => {
    const gate = { x: 680, y: 340, w: 90, h: 45 };
    const placed = spots(gate, ["a", "b", "c"]);
    expect(placed.size).toBe(3);
    for (const { x, y } of placed.values()) {
      expect(x).toBeGreaterThan(gate.x);
      expect(y).toBeLessThan(gate.y + gate.h);
    }
  });

  it("lets each dot drift on its own, and tints busier rooms", () => {
    expect(drift("a")).not.toEqual(drift("b"));
    expect(drift("a")).toEqual(drift("a"));
    expect(hash("a")).toBe(hash("a"));
    const quiet = Number(shareFill(1, 25).match(/[\d.]+\)$/)?.[0].slice(0, -1));
    const busy = Number(shareFill(11, 25).match(/[\d.]+\)$/)?.[0].slice(0, -1));
    expect(busy).toBeGreaterThan(quiet);
    expect(shareFill(0, 0)).toBe("rgba(76, 144, 240, 0.030)");
  });
});

describe("rooms that look like rooms (TWN-16)", () => {
  it("draws each kind's furniture inside the zone", () => {
    for (const kind of ["OFFICE", "CONFERENCE", "CONSULAR", "COMMS", "SAFE_ROOM", "LOBBY", "SUITE", "GATE"] as const) {
      const pieces = furniture({ kind, ...ZONE });
      expect(pieces.length, kind).toBeGreaterThan(0);
      for (const p of pieces) {
        const [x, y] = p.shape === "rect" ? [p.x, p.y] : p.shape === "circle" ? [p.cx, p.cy] : [p.x1, p.y1];
        expect(x).toBeGreaterThanOrEqual(ZONE.x);
        expect(y).toBeGreaterThanOrEqual(ZONE.y);
      }
    }
    expect(furniture({ kind: "MUSTER", ...ZONE })).toEqual([]);
  });

  it("leaves out a zone too small to furnish", () => {
    expect(furniture({ kind: "OFFICE", x: 0, y: 0, w: 55, h: 100 })).toEqual([]);
  });
});
