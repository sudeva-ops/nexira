import { tickerItems } from "./tickerItems";

describe("the live ticker", () => {
  it("lists new events first, with the incident's reference, then the ACTIVE incidents", () => {
    const incidents = [
      { id: "i1", reference: "INC-2026-1042", severity: "CRITICAL", title: "Civil unrest" },
      { id: "i2", reference: "INC-2026-1043", severity: "MODERATE", title: "Planned rally" },
    ];
    const at = new Date("2026-11-02T08:00:00Z");
    const items = tickerItems(incidents, [
      { id: "e2", event: "FLEET_UPDATED", code: "VH-04", at },
      { id: "e1", event: "INCIDENT_UPDATED", incident_id: "i1", at },
      { id: "e0", event: "PROPOSAL_CREATED", incident_id: "unknown", at },
    ]);
    expect(items.map((i) => [i.text.replace(/^\d\d:\d\d(:\d\d)? · /, ""), i.tone])).toEqual([
      ["Fleet updated · VH-04", "info"],
      ["Incident updated · INC-2026-1042", "info"],
      ["New proposal", "info"],
      ["INC-2026-1042 · CRITICAL · Civil unrest", "crit"],
      ["INC-2026-1043 · MODERATE · Planned rally", "info"],
    ]);
  });
});
