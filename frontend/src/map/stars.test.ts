import { project, sidereal, type Star, starOpacity } from "./stars";
import STARS from "./stars.json";

const VIEW = { lon: 20, lat: 15, bearing: 0, width: 800, height: 600, at: new Date("2026-11-11T03:30:00Z") };

describe("the star field", () => {
  it("is the bright catalogue: about 2,900 stars, Sirius the brightest", () => {
    const stars = STARS as Star[];
    expect(stars.length).toBeGreaterThan(2800);
    expect(stars[0]).toEqual([101.29, -16.72, -1.5]);
    expect(stars.every(([ra, dec, mag]) => ra >= 0 && ra < 360 && Math.abs(dec) <= 90 && mag <= 5.5)).toBe(true);
  });

  it("turns the sky once a sidereal day", () => {
    const a = sidereal(new Date("2026-11-11T00:00:00Z"));
    const b = sidereal(new Date("2026-11-11T23:56:04Z"));
    expect(Math.abs(((b - a + 540) % 360) - 180)).toBeLessThan(0.1);
  });

  it("puts the star straight behind the globe at the centre", () => {
    const behind: Star = [(VIEW.lon + sidereal(VIEW.at) + 180) % 360, -VIEW.lat, 1];
    const [[x, y] = []] = project([behind], VIEW);
    expect(x).toBeCloseTo(400, 3);
    expect(y).toBeCloseTo(300, 3);
  });

  it("leaves out the half of the sky in front of the globe and stars off the canvas", () => {
    const front: Star = [(VIEW.lon + sidereal(VIEW.at)) % 360, VIEW.lat, 1];
    expect(project([front], VIEW)).toEqual([]);
    const shown = project(STARS as Star[], VIEW);
    expect(shown.length).toBeGreaterThan(100);
    expect(shown.length).toBeLessThan((STARS as Star[]).length / 2);
    expect(shown.every(([x, y]) => x >= -2 && x <= 802 && y >= -2 && y <= 602)).toBe(true);
  });

  it("moves the stars the other way as the globe turns east, as from a camera in orbit", () => {
    const star: Star = [(VIEW.lon + sidereal(VIEW.at) + 185) % 360, -VIEW.lat, 1]; // 5° east of centre
    const [[x] = []] = project([star], VIEW);
    expect(x).toBeLessThan(400); // east is to the left, as in the sky
    const [[later] = []] = project([star], { ...VIEW, lon: VIEW.lon + 5 });
    expect(later).toBeCloseTo(400, 0);
  });

  it("draws brighter stars bigger and more opaque", () => {
    const at = (mag: number): Star => [(VIEW.lon + sidereal(VIEW.at) + 180) % 360, -VIEW.lat, mag];
    const [[, , r1, a1] = []] = project([at(0)], VIEW);
    const [[, , r5, a5] = []] = project([at(5)], VIEW);
    expect(r1).toBeGreaterThan(r5 ?? 0);
    expect(a1).toBeGreaterThan(a5 ?? 0);
  });

  it("shows only on the globe, fading out as you zoom in", () => {
    expect([starOpacity(true, 2), starOpacity(true, 3.75), starOpacity(true, 5), starOpacity(false, 2)]).toEqual([1, 0.5, 0, 0]);
  });
});
