import type { Annotation } from "../api/annotations";
import {
  addPoint,
  annotationColour,
  annotationFeatures,
  canFinish,
  type Draft,
  draftFeatures,
  draftShape,
  drawHint,
  dropPoint,
  LINE_COLOUR,
  standing,
  SYMBOL_COLOUR,
} from "./annotations";

const draw = (kind: Draft["kind"], ...points: [number, number][]): Draft =>
  points.reduce((d, p) => addPoint(d, p), { kind, points: [] } as Draft);

describe("drawing an annotation", () => {
  it("places a mark with one click; another click moves it", () => {
    const d = draw("MARK", [36.8, -1.2], [36.9, -1.3]);
    expect(d.points).toEqual([[36.9, -1.3]]);
    expect(draftShape(d)).toEqual({ type: "Point", coordinates: [36.9, -1.3] });
  });

  it("needs two points for a line and three for an area", () => {
    expect(canFinish(draw("LINE", [36.8, -1.2]))).toBe(false);
    expect(draftShape(draw("LINE", [36.8, -1.2]))).toBeNull();
    expect(draftShape(draw("LINE", [36.8, -1.2], [36.9, -1.3]))).toEqual({
      type: "LineString",
      coordinates: [
        [36.8, -1.2],
        [36.9, -1.3],
      ],
    });
    expect(canFinish(draw("AREA", [36.8, -1.2], [36.9, -1.2]))).toBe(false);
  });

  it("closes an area's ring", () => {
    const shape = draftShape(draw("AREA", [36.8, -1.2], [36.9, -1.2], [36.9, -1.3]));
    expect(shape).toEqual({
      type: "Polygon",
      coordinates: [
        [
          [36.8, -1.2],
          [36.9, -1.2],
          [36.9, -1.3],
          [36.8, -1.2],
        ],
      ],
    });
  });

  it("ignores the second click of a double-click, and undoes a point", () => {
    const d = draw("LINE", [36.8, -1.2], [36.9, -1.3], [36.9, -1.3]);
    expect(d.points).toHaveLength(2);
    expect(dropPoint(d).points).toEqual([[36.8, -1.2]]);
  });

  it("previews the outline and the points while drawing", () => {
    const area = draftFeatures(draw("AREA", [36.8, -1.2], [36.9, -1.2], [36.9, -1.3]));
    expect(area.features.map((f) => f.properties?.part)).toEqual(["outline", "point", "point", "point"]);
    const ring = area.features[0]?.geometry;
    expect(ring?.type === "LineString" && ring.coordinates.at(-1)).toEqual([36.8, -1.2]);
    expect(draftFeatures(draw("LINE", [36.8, -1.2])).features).toHaveLength(1);
    expect(draftFeatures(null).features).toEqual([]);
  });

  it("says what to do next", () => {
    expect(drawHint(draw("MARK"))).toMatch(/place the mark/);
    expect(drawHint(draw("AREA", [36.8, -1.2]))).toMatch(/2 more needed/);
    expect(drawHint(draw("LINE", [36.8, -1.2], [36.9, -1.3]))).toMatch(/double-click or Enter/);
  });
});

describe("annotations on the map", () => {
  const annotation = (over: Partial<Annotation>): Annotation => ({
    id: "a1",
    kind: "MARK",
    symbol: "CHECKPOINT",
    shape: { type: "Point", coordinates: [36.8, -1.2] },
    label: "Checkpoint · Uhuru Highway",
    note: null,
    incident_id: null,
    incident_reference: null,
    mission_code: "NBO",
    ends_at: null,
    status: "ACTIVE",
    reason: null,
    role: "Duty Officer",
    created_at: "2026-11-11T09:00:00Z",
    updated_at: null,
    can_edit: false,
    ...over,
  });

  it("colours a mark by its symbol, a line and an area by their kind", () => {
    expect(annotationColour({ kind: "MARK", symbol: "RALLY_POINT" })).toBe(SYMBOL_COLOUR.RALLY_POINT);
    expect(annotationColour({ kind: "LINE", symbol: null })).toBe(LINE_COLOUR);
    const [f] = annotationFeatures([annotation({})]).features;
    expect(f?.properties).toEqual({ id: "a1", kind: "MARK", colour: SYMBOL_COLOUR.CHECKPOINT, label: "Checkpoint · Uhuru Highway" });
  });

  it("shows on the replay from when it was added until it was withdrawn or ended", () => {
    const at = (s: number) => Date.parse("2026-11-11T09:00:00Z") + s * 1000;
    const list = [
      { created_at: "2026-11-11T09:00:10Z", until: "2026-11-11T09:00:30Z" },
      { created_at: "2026-11-11T09:00:20Z", until: null },
    ];
    expect(standing(list, at(5))).toEqual([]);
    expect(standing(list, at(10))).toHaveLength(1);
    expect(standing(list, at(25))).toHaveLength(2);
    expect(standing(list, at(30))).toEqual([list[1]]);
  });
});
