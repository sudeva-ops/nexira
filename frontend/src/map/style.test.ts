import { baseStyle, CITY_MINZOOM } from "./style";

const ORIGIN = "http://nexira.local";

function urls(value: unknown): string[] {
  if (typeof value === "string") return /^[a-z]+:\/\//.test(value) ? [value] : [];
  if (Array.isArray(value)) return value.flatMap(urls);
  if (value && typeof value === "object") return Object.values(value).flatMap(urls);
  return [];
}

describe("base map style (D-24)", () => {
  it("uses only the self-hosted tiles, fonts and sprites", () => {
    const style = baseStyle(ORIGIN, true);
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
    const world = baseStyle(ORIGIN, true).sources.world as { attribution?: string };
    expect(world.attribution).toContain("© OpenStreetMap contributors");
  });

  it("hands over from the world extract to the Nairobi extract at city zoom", () => {
    const { layers } = baseStyle(ORIGIN, true);
    const nairobi = layers.filter((l) => l.id.startsWith("nairobi-"));
    expect(nairobi.length).toBeGreaterThan(10);
    expect(nairobi.every((l) => (l.minzoom ?? 0) >= CITY_MINZOOM)).toBe(true);
    const worldLabels = layers.filter((l) => l.id.startsWith("world-") && l.type === "symbol");
    expect(worldLabels.every((l) => l.maxzoom === CITY_MINZOOM)).toBe(true);
  });

  it("falls back to a plain background when the tiles are not built", () => {
    const style = baseStyle(ORIGIN, false);
    expect(urls(style)).toEqual([]);
    expect(style.layers.map((l) => l.type)).toEqual(["background"]);
  });
});
