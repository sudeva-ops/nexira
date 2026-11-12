import { describe, expect, it } from "vitest";

import { quietLine } from "./quiet";

const NOW = new Date("2026-11-12T10:00:00Z");

describe("quietLine (GFX-06)", () => {
  it("names the last incident on record and how long it has been quiet", () => {
    const last = { reference: "INC-2026-1001", title: "Flooding", change: "CLOSED" as const, at: "2026-10-23T09:00:00Z" };
    expect(quietLine(last, NOW)).toBe(
      "Quiet for 20 days · last incident INC-2026-1001 Flooding, closed 23 Oct 2026.",
    );
  });

  it("says one day, not one days", () => {
    const last = { reference: "INC-2026-1002", title: "Storm", change: "OPENED" as const, at: "2026-11-11T08:00:00Z" };
    expect(quietLine(last, NOW)).toMatch(/^Quiet for 1 day · .* opened 11 Nov 2026\.$/);
  });

  it("invents nothing when no incident is on record", () => {
    expect(quietLine(null, NOW)).toBe("No incident on record yet. Nothing opened or closed in the last 7 days.");
    expect(quietLine(undefined, NOW)).toContain("No incident on record yet");
  });
});
