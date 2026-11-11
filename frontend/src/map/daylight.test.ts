import { isNight, nightSide, subsolar } from "./daylight";

describe("day and night", () => {
  it("puts the sun over the tropic of Cancer at the June solstice, near Greenwich at noon UTC", () => {
    const sun = subsolar(new Date("2026-06-21T12:00:00Z"));
    expect(sun.lat).toBeCloseTo(23.44, 0);
    expect(Math.abs(sun.lon)).toBeLessThan(3); // the equation of time is under 2 min in June
  });

  it("puts it over the tropic of Capricorn in December and the equator at the equinox", () => {
    expect(subsolar(new Date("2026-12-21T12:00:00Z")).lat).toBeCloseTo(-23.44, 0);
    expect(Math.abs(subsolar(new Date("2026-03-20T15:00:00Z")).lat)).toBeLessThan(0.5);
  });

  it("moves the sun west by 15 degrees an hour", () => {
    const a = subsolar(new Date("2026-11-11T09:00:00Z")).lon;
    const b = subsolar(new Date("2026-11-11T10:00:00Z")).lon;
    expect(a - b).toBeCloseTo(15, 0);
  });

  it("knows night in Nairobi from day", () => {
    const nairobi = [36.82, -1.29] as const;
    expect(isNight(...nairobi, new Date("2026-11-11T09:00:00Z"))).toBe(false); // 12:00 local
    expect(isNight(...nairobi, new Date("2026-11-11T21:00:00Z"))).toBe(true); // midnight local
  });

  it("draws the night side as one closed ring, over the pole the sun does not reach", () => {
    for (const at of ["2026-06-21T12:00:00Z", "2026-12-21T00:00:00Z", "2026-03-20T15:00:00Z"]) {
      const date = new Date(at);
      const [ring] = nightSide(date).geometry.coordinates;
      expect(ring?.[0]).toEqual(ring?.at(-1));
      const pole = subsolar(date).lat >= 0 ? -85.0511 : 85.0511;
      expect(ring?.some(([, lat]) => lat === pole)).toBe(true);
      // Each point of the terminator is on the line: just towards the pole is night, just away is day.
      for (const [lon, lat] of (ring ?? []).filter(([, y]) => Math.abs(y ?? 0) < 80)) {
        const step = pole < 0 ? -0.5 : 0.5;
        expect(isNight(lon ?? 0, (lat ?? 0) + step, date), `${at} ${lon}`).toBe(true);
        expect(isNight(lon ?? 0, (lat ?? 0) - step, date), `${at} ${lon}`).toBe(false);
      }
    }
  });
});
