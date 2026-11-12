import { layers, namedFlavor } from "@protomaps/basemaps";
import type { LayerSpecification, StyleSpecification } from "maplibre-gl";

// D-24: every map resource is served by the frontend container under /tiles/,
// built by `make tiles`. No external tile, font or sprite URL is allowed.
export const TILES_PATH = "/tiles";
export const ATTRIBUTION = "© OpenStreetMap contributors · © Protomaps";
export const IMAGERY_ATTRIBUTION = "Imagery: NASA Earth Observatory";
// The Nairobi extract has detail to zoom 15; the world extract stops at 6.
export const CITY_MINZOOM = 7;
export const BACKGROUND = "#0E1013";
// GFX-01 (D-55): NASA imagery at world zoom, handing over to the vector map between these zooms.
export const IMAGERY_MAXZOOM = 5;
export const HANDOVER_ZOOM = 6;

/** Which self-hosted files `make tiles` has built. */
export interface Tiles {
  base: boolean;
  imagery: boolean;
}

// The dark flavour's world fills that draw at world zoom; they give way to the imagery.
const UNDER_IMAGERY = new Set(["earth", "water"]);
const fadeIn = ["interpolate", ["linear"], ["zoom"], IMAGERY_MAXZOOM, 0, HANDOVER_ZOOM, 1];

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

/** The world fills cleared where the imagery shows (land cover is a world-zoom layer only). */
function underImagery(layer: LayerSpecification): LayerSpecification {
  if (layer.type !== "fill") return layer;
  const name = layer.id.replace(/^world-/, "");
  if (name === "landcover") return { ...layer, paint: { ...layer.paint, "fill-opacity": 0 } };
  if (!UNDER_IMAGERY.has(name)) return layer;
  return { ...layer, paint: { ...layer.paint, "fill-opacity": fadeIn } } as LayerSpecification;
}

/** NASA Blue Marble, toned down to sit under the dark styling, gone by the handover zoom. */
function imageryLayer(): LayerSpecification {
  return {
    id: "earth-day",
    type: "raster",
    source: "earth-day",
    maxzoom: HANDOVER_ZOOM,
    paint: {
      "raster-opacity": ["interpolate", ["linear"], ["zoom"], IMAGERY_MAXZOOM, 1, HANDOVER_ZOOM, 0],
      "raster-brightness-max": 0.7,
      "raster-saturation": -0.25,
      "raster-contrast": 0.1,
      "raster-fade-duration": 0,
    },
  };
}

/** The base map. Without built tiles it is a plain background, so the overlays
 *  (missions, incidents, people) still work; without the imagery it is the dark vector map. */
export function baseStyle(origin: string, tiles: Tiles): StyleSpecification {
  const background: LayerSpecification = {
    id: "background",
    type: "background",
    paint: { "background-color": BACKGROUND },
  };
  if (!tiles.base) {
    return { version: 8, sources: {}, layers: [background] };
  }
  const path = `${origin}${TILES_PATH}`;
  return {
    version: 8,
    glyphs: `${path}/fonts/{fontstack}/{range}.pbf`,
    sprite: `${path}/sprites/v4/dark`,
    sources: {
      world: { type: "vector", url: `pmtiles://${path}/world.pmtiles`, attribution: ATTRIBUTION },
      nairobi: { type: "vector", url: `pmtiles://${path}/nairobi.pmtiles` },
      ...(tiles.imagery && {
        "earth-day": {
          type: "raster",
          url: `pmtiles://${path}/earth-day.pmtiles`,
          tileSize: 256,
          attribution: IMAGERY_ATTRIBUTION,
        },
      }),
    },
    layers: [
      background,
      ...(tiles.imagery ? [imageryLayer()] : []),
      // World labels stop where the city extract takes over, so names are not doubled.
      ...prefixed("world", 0, true)
        .map((layer) => (layer.type === "symbol" ? { ...layer, maxzoom: CITY_MINZOOM } : layer))
        .map((layer) => (tiles.imagery ? underImagery(layer) : layer)),
      ...prefixed("nairobi", CITY_MINZOOM, true),
    ],
  };
}
