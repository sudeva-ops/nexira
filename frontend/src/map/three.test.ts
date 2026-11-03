import { EXPOSURE_PULSE_MS, exposureFeatures, exposureTier, ZONE_HEIGHT_M, zoneFeatures } from "./geo";
import { globePreferred, IDLE_MS, setGlobePreferred, shouldSpin } from "./three";
import { DETAIL, INCIDENT } from "../test/fixtures";

describe("the 3D map", () => {
  it("raises an impact zone by its severity", () => {
    const [zone] = zoneFeatures([INCIDENT]).features;
    expect(zone?.properties?.height).toBe(ZONE_HEIGHT_M[INCIDENT.severity]);
    expect(ZONE_HEIGHT_M.CRITICAL).toBeGreaterThan(ZONE_HEIGHT_M.LOW);
  });

  it("pulses exposed people and sites quicker the more critical they are", () => {
    const at = (distance_m: number | null, subject_type: "PERSON" | "SITE" = "PERSON") =>
      exposureTier({ subject_type, distance_m, checkin_status: null }, 5000);
    expect([at(500), at(2500), at(4900), at(null)]).toEqual(["CRITICAL", "HIGH", "MODERATE", "MODERATE"]);
    expect([at(2200, "SITE"), at(4000, "SITE"), at(100, "SITE")]).toEqual(["CRITICAL", "HIGH", "CRITICAL"]);
    expect(at(9000)).toBe("MODERATE"); // outside the zone
    // Once asked in the check-in, a person pulses by the answer, wherever they are.
    const asked = (checkin_status: "SAFE" | "NEED_HELP" | "PENDING") =>
      exposureTier({ subject_type: "PERSON", distance_m: 4900, checkin_status }, 5000);
    expect([asked("NEED_HELP"), asked("PENDING"), asked("SAFE")]).toEqual(["CRITICAL", "HIGH", null]);
    expect(exposureTier({ subject_type: "SITE", distance_m: 4900, checkin_status: "SAFE" }, 5000)).toBe("HIGH");
    expect(EXPOSURE_PULSE_MS.CRITICAL).toBeLessThan(EXPOSURE_PULSE_MS.HIGH);
    expect(EXPOSURE_PULSE_MS.HIGH).toBeLessThan(EXPOSURE_PULSE_MS.MODERATE);
    const tiers = exposureFeatures(DETAIL.exposure).features.map((f) => f.properties?.tier);
    expect(tiers.length).toBeGreaterThan(0);
    expect(tiers.every((t) => ["CRITICAL", "HIGH", "MODERATE"].includes(String(t)))).toBe(true);
  });

  it("turns the world view only on the globe, at world zoom, when nobody touched it", () => {
    expect(shouldSpin(true, 1.4, 0, IDLE_MS)).toBe(true);
    expect(shouldSpin(false, 1.4, 0, IDLE_MS)).toBe(false); // flat
    expect(shouldSpin(true, 6, 0, IDLE_MS)).toBe(false); // zoomed in
    expect(shouldSpin(true, 1.4, 1000, IDLE_MS)).toBe(false); // touched 19 s ago
  });

  it("remembers globe or flat, globe by default", () => {
    window.localStorage.removeItem("nexira.map.globe");
    expect(globePreferred()).toBe(true);
    setGlobePreferred(false);
    expect(globePreferred()).toBe(false);
    setGlobePreferred(true);
    expect(globePreferred()).toBe(true);
  });
});
