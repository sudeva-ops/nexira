import { trendParts } from "./trend";

const day = (n: number, source: "LIVE" | "ILLUSTRATIVE", signals = 5, incidents = 1) => ({
  day: `2026-10-${String(n + 1).padStart(2, "0")}`,
  signals,
  incidents,
  source,
});

describe("the trend's parts (GFX-05)", () => {
  it("counts the illustrative lead-in and totals the live days only", () => {
    const trend = [day(0, "ILLUSTRATIVE", 20, 3), day(1, "ILLUSTRATIVE", 20, 3), day(2, "LIVE", 4, 1), day(3, "LIVE", 0, 0)];
    expect(trendParts(trend)).toEqual({ faint: 2, signals: 4, incidents: 1 });
  });

  it("is all live, or all illustrative", () => {
    expect(trendParts([day(0, "LIVE"), day(1, "LIVE")]).faint).toBe(0);
    expect(trendParts([day(0, "ILLUSTRATIVE"), day(1, "ILLUSTRATIVE")])).toEqual({ faint: 2, signals: 0, incidents: 0 });
  });
});
