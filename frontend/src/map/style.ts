import { layers, namedFlavor } from "@protomaps/basemaps";
import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

// D-24: every map resource is served by the frontend container under /tiles/,
// built by `make tiles`. No external tile, font or sprite URL is allowed.
export const TILES_PATH = "/tiles";
export const ATTRIBUTION = "© OpenStreetMap contributors · © Protomaps";
// The Nairobi extract has detail to zoom 15; the world extract stops at 6.
export const CITY_MINZOOM = 7;
export const BACKGROUND = "#0E1013";

function prefixed(source: string, minzoom: number, symbols: boolean): LayerSpecification[] {
  return layers(source, namedFlavor("dark"), { lang: "en" })
    .filter((layer) => layer.type !== "background")
    .filter((layer) => symbols || layer.type !== "symbol")
    .map((layer) => ({
      ...layer,
      id: `${source}-${layer.id}`,
      minzoom: Math.max(layer.minzoom ?? 0, minzoom),
    }));
}

/** The base map. Without built tiles it is a plain background, so the overlays
 *  (missions, incidents, people) still work. */
export function baseStyle(origin: string, tilesAvailable: boolean): StyleSpecification {
  const background: LayerSpecification = {
    id: "background",
    type: "background",
    paint: { "background-color": BACKGROUND },
  };
  if (!tilesAvailable) {
    return { version: 8, sources: {}, layers: [background] };
  }
  const tiles = `${origin}${TILES_PATH}`;
  return {
    version: 8,
    glyphs: `${tiles}/fonts/{fontstack}/{range}.pbf`,
    sprite: `${tiles}/sprites/v4/dark`,
    sources: {
      world: { type: "vector", url: `pmtiles://${tiles}/world.pmtiles`, attribution: ATTRIBUTION },
      nairobi: { type: "vector", url: `pmtiles://${tiles}/nairobi.pmtiles` },
    },
    layers: [
      background,
      // World labels stop where the city extract takes over, so names are not doubled.
      ...prefixed("world", 0, true).map((layer) =>
        layer.type === "symbol" ? { ...layer, maxzoom: CITY_MINZOOM } : layer,
      ),
      ...prefixed("nairobi", CITY_MINZOOM, true),
    ],
  };
}
