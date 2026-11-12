import type { LayerSpecification } from "maplibre-gl";

import { baseStyle, CITY_MINZOOM, HANDOVER_ZOOM, IMAGERY_ATTRIBUTION } from "./style";

const ORIGIN = "http://nexira.local";
const VECTOR = { base: true, imagery: false };
const IMAGERY = { base: true, imagery: true };

function urls(value: unknown): string[] {
  if (typeof value === "string") return /^[a-z]+:\/\//.test(value) ? [value] : [];
  if (Array.isArray(value)) return value.flatMap(urls);
  if (value && typeof value === "object") return Object.values(value).flatMap(urls);
  return [];
}

describe("base map style (D-24)", () => {
  it("uses only the self-hosted tiles, fonts and sprites", () => {
    const style = baseStyle(ORIGIN, VECTOR);
    const found = urls(style);
    expect(found.length).toBeGreaterThan(0);
    for (const url of found) {
      expect(url.startsWith(`${ORIGIN}/tiles/`) || url.startsWith(`pmtiles://${ORIGIN}/tiles/`)).toBe(
        true,
      );
    }
    expect(style.glyphs).toBe(`${ORIGIN}/tiles/fonts/{fontstack}/{range}.pbf`);
    expect(style.sprite).toBe(`${ORIGIN}/tiles/sprites/v4/dark`);
  });

  it("credits OpenStreetMap", () => {
    const world = baseStyle(ORIGIN, VECTOR).sources.world as { attribution?: string };
    expect(world.attribution).toContain("© OpenStreetMap contributors");
  });

  it("hands over from the world extract to the Nairobi extract at city zoom", () => {
    const { layers } = baseStyle(ORIGIN, VECTOR);
    const nairobi = layers.filter((l) => l.id.startsWith("nairobi-"));
    expect(nairobi.length).toBeGreaterThan(10);
    expect(nairobi.every((l) => (l.minzoom ?? 0) >= CITY_MINZOOM)).toBe(true);
    const worldLabels = layers.filter((l) => l.id.startsWith("world-") && l.type === "symbol");
    expect(worldLabels.every((l) => l.maxzoom === CITY_MINZOOM)).toBe(true);
  });

  it("falls back to a plain background when the tiles are not built", () => {
    const style = baseStyle(ORIGIN, { base: false, imagery: false });
    expect(urls(style)).toEqual([]);
    expect(style.layers.map((l) => l.type)).toEqual(["background"]);
  });

  it("adds the NASA imagery only when it is built, self-hosted and credited (GFX-01, GFX-02)", () => {
    expect(Object.keys(baseStyle(ORIGIN, VECTOR).sources)).not.toContain("earth-day");
    const style = baseStyle(ORIGIN, IMAGERY);
    const source = style.sources["earth-day"] as { type: string; url: string; attribution: string };
    expect(source).toMatchObject({ type: "raster", url: `pmtiles://${ORIGIN}/tiles/earth-day.pmtiles` });
    expect(source.attribution).toBe(IMAGERY_ATTRIBUTION);
    for (const url of urls(style)) expect(url).toMatch(new RegExp(`^(pmtiles://)?${ORIGIN}/tiles/`));
  });

  it("draws the imagery under every vector layer and hands over by zoom 6 (GFX-01)", () => {
    const { layers } = baseStyle(ORIGIN, IMAGERY);
    expect(layers.map((l) => l.id).slice(0, 2)).toEqual(["background", "earth-day"]);
    expect(layers[1]?.maxzoom).toBe(HANDOVER_ZOOM);
  });

  it("clears the world's land and water fills at world zoom, only with the imagery", () => {
    const opacity = (layers: LayerSpecification[], id: string) =>
      (layers.find((l) => l.id === id) as { paint?: Record<string, unknown> }).paint?.["fill-opacity"];
    const withImagery = baseStyle(ORIGIN, IMAGERY).layers;
    expect(opacity(withImagery, "world-earth")).toEqual(["interpolate", ["linear"], ["zoom"], 5, 0, 6, 1]);
    expect(opacity(withImagery, "world-water")).toEqual(["interpolate", ["linear"], ["zoom"], 5, 0, 6, 1]);
    expect(opacity(withImagery, "world-landcover")).toBe(0);
    expect(opacity(baseStyle(ORIGIN, VECTOR).layers, "world-earth")).toBeUndefined();
    // The city extract is untouched.
    expect(opacity(withImagery, "nairobi-earth")).toBeUndefined();
  });
});
