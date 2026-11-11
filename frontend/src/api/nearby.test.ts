import { distanceText, nearParams, parseNear } from "./nearby";

describe("Nearby in the address (NBY-06)", () => {
  it("reads lat,lon and a known radius, defaulting to 10 km", () => {
    expect(parseNear("-1.2921,36.8219", "25")).toEqual({ lat: -1.2921, lon: 36.8219, km: 25 });
    expect(parseNear("-1.2921,36.8219", null)?.km).toBe(10);
    expect(parseNear("-1.2921,36.8219", "7")?.km).toBe(10); // not one of 1, 5, 10, 25, 50
  });

  it("ignores anything that is not a place on the Earth", () => {
    for (const bad of [null, "", "nairobi", "-1.2,", "95,10", "10,190"]) expect(parseNear(bad, "10")).toBeNull();
  });

  it("writes it back, rounded to about a metre", () => {
    expect(nearParams({ lat: -1.292137, lon: 36.821946, km: 5 })).toEqual({ near: "-1.29214,36.82195", r: "5" });
  });

  it("says distances as people do", () => {
    expect([distanceText(112), distanceText(2240), distanceText(12_600)]).toEqual(["110 m", "2.2 km", "13 km"]);
  });
});
