import { describe, expect, it } from "vitest";

import { clip, cone, coverage, placed, sector, sees, target, watching } from "./coverage";
import { PLAN_ZONES, planSensors } from "./plan.fixture";

const plan = (down: Parameters<typeof planSensors>[0] = {}) => ({ zones: PLAN_ZONES, sensors: planSensors(down) });
const names = (zones: { name: string }[]) => zones.map((z) => z.name);

describe("geometry", () => {
  const m = { x: 0, y: 0, heading_deg: 90, fov_deg: 90, range_u: 100 }; // facing right

  it("a camera sees within its range and either side of its heading", () => {
    expect(sees(m, 50, 0)).toBe(true);
    expect(sees(m, 50, 49)).toBe(true); // just inside 45°
    expect(sees(m, 50, 51)).toBe(false);
    expect(sees(m, 101, 0)).toBe(false);
    expect(sees(m, -10, 0)).toBe(false); // behind
    expect(sees(m, 0, 0)).toBe(true);
    expect(sees({ ...m, heading_deg: 0 }, 0, -50)).toBe(true); // 0 is up the plan
    expect(sees({ ...m, heading_deg: 350 }, 3, -50)).toBe(true); // across north
  });

  it("the sector is the mount and its arc, clipped to the zone's walls", () => {
    const s = sector(m);
    expect(s[0]).toEqual([0, 0]);
    expect(s).toHaveLength(26);
    const clipped = clip(s, { x: 0, y: -20, w: 40, h: 40 });
    expect(Math.max(...clipped.map(([x]) => x))).toBeCloseTo(40);
    expect(Math.min(...clipped.map(([, y]) => y))).toBeCloseTo(-20);
    expect(clipped.every(([x, y]) => x >= 0 && x <= 40 && y >= -20 && y <= 20)).toBe(true);
  });

  it("a cone is a closed SVG path inside its zone", () => {
    for (const c of placed(plan())) {
      const path = cone(c);
      expect(path).toMatch(/^M.+Z$/);
      const points = path.slice(1, -1).split("L").map((p) => p.split(",").map(Number));
      const { x, y, w, h } = c.zone;
      expect(points.every(([px = NaN, py = NaN]) => px >= x && px <= x + w && py >= y && py <= y + h)).toBe(true);
    }
  });
});

describe("coverage on the seeded embassy (TWN-09, TWN-11; plan §4)", () => {
  it("is below 100%: the chancery's north-east corner is the one blind spot", () => {
    const c = coverage(plan());
    expect(c.pct).toBe(97);
    expect(c.notCovered).toEqual([]);
    expect(c.blind.map((b) => [b.zone.name, b.pct])).toEqual([["Chancery offices", 7]]);
    const gaps = c.zones.find((z) => z.zone.code === "ch")?.gaps ?? [];
    expect(gaps.length).toBeGreaterThan(0);
    // The north-east corner: the chancery's right-most 50 units, tapering down from the top wall.
    expect(gaps[0]).toEqual({ x: 350, y: 30, w: 50, h: 5 });
    expect(gaps.every((g) => g.x >= 350 && g.x + g.w === 400 && g.y + g.h <= 160)).toBe(true);
  });

  it("falls with CAM-07 offline; CAM-08 still covers the consular hall, so it is not listed", () => {
    const c = coverage(plan({ "CAM-07": "OFFLINE" }));
    expect(c.pct).toBe(96);
    expect(c.notCovered).toEqual([]);
    expect(names(c.blind.map((b) => b.zone))).toEqual(["Chancery offices", "Consular hall"]);
  });

  it("lists a zone no online camera covers; DEGRADED still covers", () => {
    const c = coverage(plan({ "CAM-03": "OFFLINE", "CAM-04": "FAULT", "CAM-05": "DEGRADED" }));
    expect(names(c.notCovered)).toEqual(["Gate 2"]);
    expect(c.zones.find((z) => z.zone.code === "g2")?.gaps).toHaveLength(9); // 18 × 9 cells, merged by row
    expect(c.zones.find((z) => z.zone.code === "lob")?.covered).toBeGreaterThan(0);
  });

  it("recovers with the camera", () => {
    expect(coverage(plan({ "CAM-07": "OFFLINE" })).pct).toBe(96);
    expect(coverage(plan({ "CAM-07": "OK" })).pct).toBe(97);
  });

  it("has no figure without a mounted camera", () => {
    expect(coverage({ zones: PLAN_ZONES, sensors: [] }).pct).toBeNull();
  });
});

describe("from a place to its camera (TWN-10)", () => {
  it("the online camera covering the zone, else its offline one, else none", () => {
    expect(watching(plan(), "cons")?.code).toMatch(/^CAM-0[78]$/);
    expect(watching(plan({ "CAM-07": "OFFLINE" }), "cons")?.code).toBe("CAM-08");
    expect(watching(plan({ "CAM-07": "OFFLINE", "CAM-08": "FAULT" }), "cons")?.code).toBe("CAM-07");
    expect(watching({ zones: PLAN_ZONES, sensors: [] }, "cons")).toBeNull();
  });

  it("a camera opens itself; another sensor opens the camera watching its zone", () => {
    const p = plan({ "CAM-07": "OFFLINE" });
    expect(target(p, { camera: "CAM-07", zone: null })?.camera?.code).toBe("CAM-07");
    expect(target(p, { camera: "G2-READER", zone: null })?.zone?.code).toBe("g2");
    expect(target(p, { camera: "G2-READER", zone: null })?.camera?.zone_code).toBe("g2");
    expect(target(p, { camera: null, zone: "cons" })?.camera?.code).toBe("CAM-08");
    expect(target({ zones: PLAN_ZONES, sensors: [] }, { camera: null, zone: "g1" })).toEqual({
      camera: null,
      zone: PLAN_ZONES.find((z) => z.code === "g1"),
    });
    expect(target(p, { camera: "NOPE", zone: null })).toBeNull();
  });
});
