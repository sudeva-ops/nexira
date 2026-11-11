import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { Map as MapLibreMap } from "maplibre-gl";

import type { Annotation, AnnotationKind, AnnotationSymbol, Shape } from "../api/annotations";

// Map annotations on the world maps (ANN-01..06, D-52; plan-pilot-map §2): the features the
// layers draw, and our own small drawing (plan G-3): click to place each point, finish with a
// double-click or Enter, cancel with Escape. Pure, apart from addAnnotationLayers.

export type LonLat = [number, number];

/** The drawing tools are on from here (plan G-6): a globe at world zoom is too coarse. */
export const DRAW_MIN_ZOOM = 5;

// Their own colours: not the severities' (zones, missions) nor the people's (staff, citizens).
export const SYMBOL_COLOUR: Record<AnnotationSymbol, string> = {
  CHECKPOINT: "#FBD065",
  CLOSED_ROAD: "#F5498B",
  RALLY_POINT: "#72CA9B",
  HAZARD: "#D69FD6",
  NOTE: "#ABB3BF",
};
export const LINE_COLOUR = "#F5498B"; // a route or a closed stretch
export const AREA_COLOUR = "#BD6BBD"; // an area to avoid, a cordon

export function annotationColour(a: { kind: AnnotationKind; symbol: string | null }): string {
  if (a.kind === "LINE") return LINE_COLOUR;
  if (a.kind === "AREA") return AREA_COLOUR;
  return SYMBOL_COLOUR[a.symbol as AnnotationSymbol] ?? SYMBOL_COLOUR.NOTE;
}

function feature(geometry: Geometry, properties: Record<string, unknown>): Feature {
  return { type: "Feature", geometry, properties };
}

/** The live annotations, for the map's layers; the label only where a screen may show it. */
export function annotationFeatures(list: Annotation[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: list.map((a) =>
      feature(a.shape, { id: a.id, kind: a.kind, colour: annotationColour(a), label: a.label }),
    ),
  };
}

/** Annotations standing at t on the replay (ANN-06): from added until withdrawn or ended. */
export function standing<T extends { created_at: string; until: string | null }>(list: T[], t: number): T[] {
  return list.filter((a) => Date.parse(a.created_at) <= t && (a.until === null || t < Date.parse(a.until)));
}

// --- drawing -----------------------------------------------------------------------------------

export interface Draft {
  kind: AnnotationKind;
  points: LonLat[];
}

const SAME = 1e-7; // degrees: the two clicks of a double-click land on the same point

/** A draft with one more point; a mark has just one, and a repeated point is ignored. */
export function addPoint(draft: Draft, p: LonLat): Draft {
  if (draft.kind === "MARK") return { ...draft, points: [p] };
  const last = draft.points.at(-1);
  if (last && Math.abs(last[0] - p[0]) < SAME && Math.abs(last[1] - p[1]) < SAME) return draft;
  if (draft.points.length >= 499) return draft; // the table's limit, with the ring closed (PC-54)
  return { ...draft, points: [...draft.points, p] };
}

/** Undo the last point. */
export function dropPoint(draft: Draft): Draft {
  return { ...draft, points: draft.points.slice(0, -1) };
}

export function canFinish(draft: Draft): boolean {
  return draft.points.length >= { MARK: 1, LINE: 2, AREA: 3 }[draft.kind];
}

/** The finished shape, as the API takes it (an area's ring closed). */
export function draftShape(draft: Draft): Shape | null {
  if (!canFinish(draft)) return null;
  const [first] = draft.points;
  if (!first) return null;
  if (draft.kind === "MARK") return { type: "Point", coordinates: first };
  if (draft.kind === "LINE") return { type: "LineString", coordinates: draft.points };
  return { type: "Polygon", coordinates: [[...draft.points, first]] };
}

/** What the draft looks like while drawing: its points and the outline so far. */
export function draftFeatures(draft: Draft | null): FeatureCollection {
  if (!draft) return { type: "FeatureCollection", features: [] };
  const points = draft.points.map((p) => feature({ type: "Point", coordinates: p }, { part: "point" }));
  const outline =
    draft.kind !== "MARK" && draft.points.length >= 2
      ? [
          feature(
            {
              type: "LineString",
              coordinates:
                draft.kind === "AREA" && draft.points.length >= 3 ? [...draft.points, draft.points[0] as LonLat] : draft.points,
            },
            { part: "outline" },
          ),
        ]
      : [];
  return { type: "FeatureCollection", features: [...outline, ...points] };
}

/** "Click the map to place the checkpoint" and the like, for the toolbar. */
export function drawHint(draft: Draft): string {
  if (draft.kind === "MARK") return "Click the map to place the mark.";
  const need = draft.kind === "LINE" ? 2 : 3;
  const left = need - draft.points.length;
  return left > 0
    ? `Click the map to add points (${left} more needed). Escape cancels.`
    : "Click to add points; double-click or Enter to finish. Escape cancels.";
}

// --- layers ------------------------------------------------------------------------------------

export const ANNOTATION_LAYERS = ["annotations-area", "annotations-line", "annotations-mark"] as const;
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

/** The annotation and draft layers, above the zones and under the people (ANN-01). */
export function addAnnotationLayers(map: MapLibreMap, labels: boolean): void {
  map.addSource("annotations", { type: "geojson", data: EMPTY });
  map.addSource("draft", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "annotations-area",
    type: "fill",
    source: "annotations",
    filter: ["==", ["get", "kind"], "AREA"],
    paint: { "fill-color": ["get", "colour"], "fill-opacity": 0.2 },
  });
  map.addLayer({
    id: "annotations-edge",
    type: "line",
    source: "annotations",
    filter: ["==", ["get", "kind"], "AREA"],
    paint: { "line-color": ["get", "colour"], "line-width": 1.5 },
  });
  map.addLayer({
    id: "annotations-line",
    type: "line",
    source: "annotations",
    filter: ["==", ["get", "kind"], "LINE"],
    layout: { "line-cap": "round" },
    paint: { "line-color": ["get", "colour"], "line-width": 3.5, "line-dasharray": [2, 1.5] },
  });
  map.addLayer({
    id: "annotations-mark",
    type: "circle",
    source: "annotations",
    filter: ["==", ["get", "kind"], "MARK"],
    paint: {
      "circle-color": ["get", "colour"],
      "circle-radius": 7,
      "circle-stroke-color": "#f6f7f9",
      "circle-stroke-width": 2,
    },
  });
  if (labels) {
    map.addLayer({
      id: "annotations-label",
      type: "symbol",
      source: "annotations",
      minzoom: DRAW_MIN_ZOOM,
      layout: {
        "text-field": ["get", "label"],
        "text-font": ["Noto Sans Regular"],
        "text-size": 11,
        "text-offset": [0, 1.3],
        "text-anchor": "top",
        "text-max-width": 12,
      },
      paint: { "text-color": "#f6f7f9", "text-halo-color": "#111418", "text-halo-width": 1.5 },
    });
  }
  map.addLayer({
    id: "draft-outline",
    type: "line",
    source: "draft",
    filter: ["==", ["get", "part"], "outline"],
    paint: { "line-color": "#f6f7f9", "line-width": 2, "line-dasharray": [1.5, 1.5] },
  });
  map.addLayer({
    id: "draft-points",
    type: "circle",
    source: "draft",
    filter: ["==", ["get", "part"], "point"],
    paint: {
      "circle-color": "#4C90F0",
      "circle-radius": 5,
      "circle-stroke-color": "#f6f7f9",
      "circle-stroke-width": 2,
    },
  });
}
