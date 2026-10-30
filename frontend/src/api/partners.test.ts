import type { Me } from "./me";
import { type Coverage, coverageSummary, slaText } from "./partners";
import { canRequestPartner } from "./permissions";

const me = (code: string, mission_id: string | null): Me => ({
  id: "u",
  display_name: "U",
  email: "u@demo.nexira.invalid",
  roles: [{ code, mission_id, mission_code: null }],
});

describe("partners (AS-01..07)", () => {
  it("writes SLAs as people read them", () => {
    expect([slaText(15), slaText(60), slaText(240), slaText(90)]).toEqual([
      "SLA 15 min",
      "SLA 1 h",
      "SLA 4 h",
      "SLA 1 h 30 min",
    ]);
  });

  it("counts missions with every service and names the gaps (AS-07)", () => {
    const row = (code: string, missing: Coverage["missing"]): Coverage => ({
      mission_id: code,
      code,
      city: code,
      country_code: "XX",
      missing,
    });
    const summary = coverageSummary([row("NBO", []), row("CBR", ["EVACUATION"]), row("BUE", ["EVACUATION"])]);
    expect([summary.covered, summary.total, summary.gaps.map((g) => g.code)]).toEqual([1, 3, ["CBR", "BUE"]]);
  });

  it("lets Duty and Security Officers request anywhere and a Head of Mission only for their own (§33 Q2)", () => {
    expect(canRequestPartner(me("DUTY_OFFICER", null), "m-nbo")).toBe(true);
    expect(canRequestPartner(me("SECURITY_OFFICER", null), "m-nbo")).toBe(true);
    expect(canRequestPartner(me("HEAD_OF_MISSION", "m-nbo"), "m-nbo")).toBe(true);
    expect(canRequestPartner(me("HEAD_OF_MISSION", "m-cai"), "m-nbo")).toBe(false);
    expect(canRequestPartner(me("TRAVEL_DESK", null), "m-nbo")).toBe(false);
    expect(canRequestPartner(me("VIEWER", null), "m-nbo")).toBe(false);
  });
});
