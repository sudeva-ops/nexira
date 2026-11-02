import { at, DETAIL, INCIDENT, MISSIONS, NAIROBI, PETER } from "../test/fixtures";
import {
  bearing,
  circlePolygon,
  exposureFeatures,
  flightBearing,
  flightFeatures,
  missionFeatures,
  routeFeatures,
  SEVERITY_COLOUR,
  zoneFeatures,
} from "./geo";

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

  it("pulses missions with an ACTIVE incident", () => {
    expect(at(missionFeatures(MISSIONS).features, 0).properties?.active).toBe(NAIROBI.incident_id !== null);
    expect(at(missionFeatures([{ ...NAIROBI, incident_id: null }]).features, 0).properties?.active).toBe(false);
  });
});

// Abu Dhabi, Nairobi and Mombasa ([lat, lon]), as XW 451's route.
const AUH: [number, number] = [24.43, 54.65];
const NBO: [number, number] = [-1.32, 36.93];
const MBA: [number, number] = [-4.03, 39.59];
const flight = (status: string, at: [number, number] | null, route: [number, number][] = [AUH, NBO, MBA]) => ({
  id: "f1",
  flight_number: "XW 451",
  status,
  lat: at?.[0] ?? null,
  lon: at?.[1] ?? null,
  route,
});

describe("the air picture", () => {
  it("works out compass bearings", () => {
    expect(bearing([0, 0], [1, 0])).toBeCloseTo(0, 5); // north
    expect(bearing([0, 0], [0, 1])).toBeCloseTo(90, 5); // east
    expect(bearing([0, 0], [-1, 0])).toBeCloseTo(180, 5); // south
    expect(bearing([0, 0], [0, -1])).toBeCloseTo(270, 5); // west
  });

  it("points a plane at where it is going: the destination, or the diversion airport", () => {
    // Abu Dhabi to Nairobi is south-west.
    const enRoute = flightBearing(flight("AIRBORNE", [12, 46]));
    expect(enRoute).toBeGreaterThan(200);
    expect(enRoute).toBeLessThan(240);
    expect(flightBearing(flight("SCHEDULED", null))).toBeCloseTo(bearing(AUH, NBO), 5);
    // Diverted near Nairobi: heading south-east to Mombasa.
    const diverted = flightBearing(flight("DIVERTED", [-1.0, 37.0]));
    expect(diverted).toBeGreaterThan(110);
    expect(diverted).toBeLessThan(160);
    const [f] = flightFeatures([flight("HOLDING", [-1.0, 37.0])]).features;
    expect(f?.properties).toMatchObject({ holding: true, label: "XW 451" });
  });

  it("splits a route at the aircraft: flown and ahead", () => {
    const parts = (status: string, at: [number, number] | null) =>
      routeFeatures([flight(status, at)]).features.map((f) => f.properties?.part);
    expect(parts("SCHEDULED", null)).toEqual(["ahead"]);
    expect(parts("AIRBORNE", [12, 46])).toEqual(["flown", "ahead"]);
    expect(parts("LANDED", NBO)).toEqual(["flown"]);
    const [flown, ahead] = routeFeatures([flight("DIVERTED", [-1.0, 37.0])]).features;
    // The part ahead of a diverted flight ends at Mombasa.
    expect(ahead?.geometry.coordinates.at(-1)?.[1]).toBeCloseTo(MBA[0], 3);
    expect(flown?.geometry.coordinates[0]?.[1]).toBeCloseTo(AUH[0], 3);
  });
});
