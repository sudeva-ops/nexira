import { locationSourceLabel, personnelFirst, sourceLabel } from "./format";

describe("formatting", () => {
  it("puts personnel before citizens, nearest first (OPS-04)", () => {
    const order = personnelFirst([
      { kind: "CITIZEN", distance_m: 100 },
      { kind: "DIPLOMAT", distance_m: 2000 },
      { kind: "DELEGATE", distance_m: 1500 },
    ]).map((p) => p.kind);
    expect(order).toEqual(["DELEGATE", "DIPLOMAT", "CITIZEN"]);
  });

  it("labels simulated sources (D-19) and location sources", () => {
    expect(sourceLabel({ name: "Dataminr", simulated: true })).toBe("Dataminr (simulated)");
    expect(sourceLabel({ name: "Dataminr", simulated: false })).toBe("Dataminr");
    expect(locationSourceLabel("CALENDAR_HR")).toBe("Calendar / HR");
    expect(locationSourceLabel(null)).toBe("—");
  });
});
