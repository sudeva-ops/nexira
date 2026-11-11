import { scrolls, tickerItems } from "./tickerItems";

describe("the live ticker", () => {
  it("lists new events first, with the incident's reference, then the open incidents, most severe first", () => {
    const incidents = [
      { id: "i2", reference: "INC-2026-1043", severity: "MODERATE", title: "Planned rally", status: "ACTIVE" },
      { id: "i3", reference: "INC-2026-1040", severity: "HIGH", title: "Flooding", status: "CLOSED" },
      { id: "i1", reference: "INC-2026-1042", severity: "CRITICAL", title: "Civil unrest", status: "MONITORING" },
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

  it("scrolls only when the items do not fit the strip (UIP-01)", () => {
    expect(scrolls(900, 1000)).toBe(false);
    expect(scrolls(1000, 1000)).toBe(false);
    expect(scrolls(1200, 1000)).toBe(true);
    expect(scrolls(1200, 0)).toBe(false); // not laid out yet
  });
});
