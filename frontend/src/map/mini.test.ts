import { describe, expect, it } from "vitest";

import { DETAIL, NAIROBI } from "../test/fixtures";
import { SEVERITY_COLOUR } from "./geo";
import { CITY_ZOOM, miniLayers, miniZoom, REGION_ZOOM } from "./mini";

describe("the incident mini-map (GFX-08)", () => {
  it("uses city zoom inside the city extract and regional zoom elsewhere", () => {
    expect(miniZoom(36.8245, -1.2838)).toBe(CITY_ZOOM); // Nairobi
    expect(miniZoom(31.2357, 30.0444)).toBe(REGION_ZOOM); // Cairo: no city tiles
    expect(miniZoom(37.3, -1.28)).toBe(REGION_ZOOM); // just east of the extract
  });

  it("draws the zone, the marker, the incident's mission and the people exposed", () => {
    const other = { ...NAIROBI, id: "other", code: "CAI" };
    const layers = miniLayers(DETAIL, [NAIROBI, other]);
    expect(layers.zone.features).toHaveLength(1);
    expect(layers.marker.features[0]?.properties).toEqual({ colour: SEVERITY_COLOUR[DETAIL.severity] });
    expect(layers.mission.features.map((f) => f.properties?.code)).toEqual(["NBO"]);
    expect(layers.exposure.features).toHaveLength(DETAIL.exposure.filter((e) => e.lat !== null).length);
  });
});
