import { at, INCIDENT, SIGNALS } from "../../test/fixtures";
import { feedItems } from "./feed";

describe("live feed (OPS-02)", () => {
  it("shows fused signals inside their incident, and unfused ones raw", () => {
    const discarded = {
      ...at(SIGNALS, 0),
      id: 9,
      incident_id: null,
      norm_status: "DISCARDED" as const,
    };
    const items = feedItems([INCIDENT], [...SIGNALS, discarded], new Set());
    expect(items.map((i) => i.kind).sort()).toEqual(["incident", "raw"]);
  });

  it("shows a just-arrived signal raw until it merges", () => {
    const items = feedItems([INCIDENT], SIGNALS, new Set([3]));
    const raw = items.filter((i) => i.kind === "raw");
    expect(raw).toHaveLength(1);
    expect(raw[0]).toMatchObject({ merging: true, signal: { id: 3 } });
  });
});
