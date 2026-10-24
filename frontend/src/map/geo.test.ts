import { at, DETAIL, INCIDENT, MISSIONS, NAIROBI, PETER } from "../test/fixtures";
import { circlePolygon, exposureFeatures, missionFeatures, SEVERITY_COLOUR, zoneFeatures } from "./geo";

function haversineM([lon1, lat1]: [number, number], [lon2, lat2]: [number, number]): number {
  const r = (d: number) => (d * Math.PI) / 180;
  const a =
    Math.sin(r(lat2 - lat1) / 2) ** 2 +
    Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lon2 - lon1) / 2) ** 2;
  return 2 * 6_371_008.8 * Math.asin(Math.sqrt(a));
}

describe("map geometry", () => {
  it("draws the impact zone as a closed circle of the incident radius", () => {
    const ring = at(circlePolygon(36.8245, -1.2838, 5000).coordinates, 0);
    expect(at(ring, 0)).toEqual(at(ring, ring.length - 1));
    for (const [lon, lat] of ring) {
      expect(haversineM([36.8245, -1.2838], [lon ?? 0, lat ?? 0])).toBeCloseTo(5000, 0);
    }
  });

  it("colours missions by display risk with D-08 labels (G-22)", () => {
    const nbo = at(missionFeatures(MISSIONS).features, 0);
    expect(nbo.properties).toMatchObject({
      code: "NBO",
      risk: "CRITICAL",
      label: "Critical",
      colour: SEVERITY_COLOUR.CRITICAL,
    });
    const normal = at(missionFeatures([{ ...NAIROBI, display_risk: "LOW" }]).features, 0);
    expect(normal.properties?.label).toBe("Normal");
  });

  it("builds one zone per incident and plots exposed people, not trips", () => {
    expect(zoneFeatures([INCIDENT]).features).toHaveLength(1);
    const trip = { ...PETER, subject_type: "TRIP" as const, lat: null, lon: null };
    const features = exposureFeatures([...DETAIL.exposure, trip]).features;
    expect(features.map((f) => f.properties?.name)).toEqual(["Peter Mwangi", "Hana Takeda"]);
  });
});
