import { breath, phase, PLANE_PATH, sonar } from "./plane";

describe("map pulses", () => {
  it("repeats a phase, grows and fades a sonar ring, and breathes between two values", () => {
    expect(phase(2500, 1000)).toBeCloseTo(0.5);
    expect(sonar(0, 6, 22)).toEqual({ radius: 6, opacity: 0.6 });
    expect(sonar(1, 6, 22)).toEqual({ radius: 22, opacity: 0 });
    expect(breath(0, 3000, 0.1, 0.24)).toBeCloseTo(0.1);
    expect(breath(1500, 3000, 0.1, 0.24)).toBeCloseTo(0.24);
  });

  it("draws the plane nose up inside its box", () => {
    expect(PLANE_PATH.startsWith("M32 4")).toBe(true);
  });
});
