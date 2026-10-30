import type { Flight } from "../api/flights";
import { GROW_MS, glideFlights, growScale, lerpLonLat, positions } from "./motion";

const flight = (id: string, lon: number | null, lat: number | null) => ({ id, lon, lat }) as Flight;

describe("lerpLonLat", () => {
  it("moves in a straight line between two points", () => {
    expect(lerpLonLat([10, 0], [20, 10], 0.5)).toEqual([15, 5]);
  });

  it("goes the short way across the 180° meridian", () => {
    const [lon] = lerpLonLat([170, 0], [-170, 0], 0.5);
    expect(Math.abs(lon)).toBe(180);
    expect(lerpLonLat([170, 0], [-170, 0], 0.25)[0]).toBe(175);
    expect(lerpLonLat([-170, 0], [170, 0], 0.25)[0]).toBe(-175);
  });
});

describe("glideFlights", () => {
  const from = new Map<string, [number, number]>([["a", [0, 0]]]);
  const to = [flight("a", 10, 10), flight("b", 5, 5), flight("c", null, null)];

  it("starts where the aircraft were drawn and ends at their new positions", () => {
    expect(glideFlights(from, to, 0)[0]).toMatchObject({ lon: 0, lat: 0 });
    expect(glideFlights(from, to, 1)[0]).toMatchObject({ lon: 10, lat: 10 });
    const mid = glideFlights(from, to, 0.5)[0];
    expect(mid?.lon).toBeCloseTo(5);
  });

  it("puts a new aircraft, or one without a position, straight where it is", () => {
    const [, b, c] = glideFlights(from, to, 0.3);
    expect(b).toMatchObject({ lon: 5, lat: 5 });
    expect(c).toMatchObject({ lon: null, lat: null });
  });

  it("remembers only aircraft with a position", () => {
    expect([...positions(to).keys()]).toEqual(["a", "b"]);
  });
});

describe("growScale", () => {
  it("grows a new zone from nothing to whole over GROW_MS", () => {
    expect(growScale(0)).toBe(0);
    expect(growScale(GROW_MS / 2)).toBeGreaterThan(0.5); // eased out: fast, then slowing
    expect(growScale(GROW_MS)).toBe(1);
    expect(growScale(GROW_MS * 3)).toBe(1);
  });
});
