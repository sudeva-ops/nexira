import PLACES from "./places.json";
import { fold, MAX_RESULTS, parseCoordinates, type Place, type Result, search } from "./search";

const places = PLACES as Place[];
const record = (kind: Result["kind"], label: string, detail = ""): Result => ({
  kind,
  id: label,
  label,
  detail,
  lon: 36.82,
  lat: -1.29,
  zoom: 12,
});
const RECORDS = [
  record("MISSION", "Nairobi", "NBO · Kenya"),
  record("MISSION", "Mombasa liaison office", "MBA · Kenya"),
  record("SITE", "Embassy Nairobi", "NBO"),
  record("INCIDENT", "INC-2026-1042", "Civil unrest · Nairobi CBD"),
];

describe("coordinates (SRC-02)", () => {
  it("reads decimal degrees, latitude first, with signs or hemisphere letters", () => {
    expect(parseCoordinates("-1.2921, 36.8219")).toEqual({ lat: -1.2921, lon: 36.8219 });
    expect(parseCoordinates("1.2921 S 36.8219 E")).toEqual({ lat: -1.2921, lon: 36.8219 });
    expect(parseCoordinates("40.7128N, 74.006W")).toEqual({ lat: 40.7128, lon: -74.006 });
    expect(parseCoordinates("-1.2921 36.8219")).toEqual({ lat: -1.2921, lon: 36.8219 });
  });

  it("reads degrees, minutes and seconds", () => {
    const at = parseCoordinates(`1°17'31"S 36°49'19"E`);
    expect(at?.lat).toBeCloseTo(-1.29194, 4);
    expect(at?.lon).toBeCloseTo(36.82194, 4);
    expect(parseCoordinates("1°17′S, 36°49′E")?.lon).toBeCloseTo(36.8167, 3);
  });

  it("reads a geo: URI (RFC 5870), WGS84 only", () => {
    expect(parseCoordinates("geo:-4.04,39.67")).toEqual({ lat: -4.04, lon: 39.67 });
    expect(parseCoordinates("geo:-4.04,39.67,12;u=35")).toEqual({ lat: -4.04, lon: 39.67 });
    expect(parseCoordinates("geo:-4.04,39.67;crs=wgs84")).toEqual({ lat: -4.04, lon: 39.67 });
    expect(parseCoordinates("geo:1,2;crs=EPSG:3857")).toBeNull();
  });

  it("refuses what is not a place on the Earth, or not coordinates at all", () => {
    for (const q of ["95, 10", "10, 190", "Nairobi", "1042", "1°75'S 36°49'E", "geo:"]) {
      expect(parseCoordinates(q), q).toBeNull();
    }
  });
});

describe("search (SRC-01..03)", () => {
  it("puts platform records first, then places, at most eight", () => {
    const found = search("nairobi", RECORDS, places);
    expect(found.slice(0, 2).map((r) => [r.kind, r.label])).toEqual([
      ["MISSION", "Nairobi"],
      ["SITE", "Embassy Nairobi"],
    ]);
    expect(found.find((r) => r.kind === "PLACE")).toMatchObject({ label: "Nairobi", detail: "KE" });
    expect(search("s", RECORDS, places).length).toBeLessThanOrEqual(MAX_RESULTS);
  });

  it("finds a mission by code and an incident by reference", () => {
    expect(search("NBO", RECORDS, places)[0]?.label).toBe("Nairobi");
    expect(search("inc-2026-1042", RECORDS, places)[0]?.kind).toBe("INCIDENT");
    expect(search("1042", RECORDS, places)[0]?.kind).toBe("INCIDENT");
  });

  it("finds places by prefix, the most populous first, with or without accents", () => {
    expect(search("Kampala", [], places)[0]).toMatchObject({ kind: "PLACE", label: "Kampala", detail: "UG" });
    expect(search("sao paulo", [], places)[0]?.label).toBe("São Paulo");
    expect(search("zurich", [], places)[0]?.label).toBe("Zürich");
    expect(search("Mom", [], places)[0]?.label).toBe("Mombasa");
    expect(search("k", [], places)).toEqual([]); // a single letter matches records only
  });

  it("answers coordinates with the point itself", () => {
    expect(search("geo:-4.04,39.67", RECORDS, places)).toEqual([
      { kind: "COORDINATES", id: "-4.04,39.67", label: "-4.0400, 39.6700", detail: "Coordinates", lat: -4.04, lon: 39.67, zoom: 8 },
    ]);
  });

  it("folds case and accents", () => {
    expect(fold("  São Paulo ")).toBe("sao paulo");
  });

  it("bundles the gazetteer: about 7,300 public-domain places", () => {
    expect(places.length).toBeGreaterThan(7000);
    expect(places.every(([name, , , , lon, lat]) => name && Math.abs(lon) <= 180 && Math.abs(lat) <= 90)).toBe(true);
  });
});
