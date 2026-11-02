import { exposureColumns, ZONE_HEIGHT_M, zoneFeatures } from "./geo";
import { globePreferred, IDLE_MS, setGlobePreferred, shouldSpin } from "./three";
import { DETAIL, INCIDENT } from "../test/fixtures";

describe("the 3D map", () => {
  it("raises an impact zone by its severity", () => {
    const [zone] = zoneFeatures([INCIDENT]).features;
    expect(zone?.properties?.height).toBe(ZONE_HEIGHT_M[INCIDENT.severity]);
    expect(ZONE_HEIGHT_M.CRITICAL).toBeGreaterThan(ZONE_HEIGHT_M.LOW);
  });

  it("draws exposed people and sites as small closed columns, sites taller", () => {
    const columns = exposureColumns(DETAIL.exposure).features;
    expect(columns.length).toBeGreaterThan(0);
    for (const c of columns) {
      const ring = c.geometry.coordinates[0] ?? [];
      expect(ring).toHaveLength(5);
      expect(ring[0]).toEqual(ring[4]);
      expect(c.properties?.height).toBe(c.properties?.kind === "SITE" ? 1500 : 700);
    }
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
