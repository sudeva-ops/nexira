import type { Zone } from "../../api/twin";

// Rooms that look like rooms (TWN-16, D-53; plan-pilot-twa §4, G-9): faint outlines of each zone
// kind's furniture, as fractions of the zone's rectangle. Decoration only: nothing is counted
// from it. Left out of a zone smaller than 60 × 40 plan units. Pure.

export type Piece =
  | { shape: "rect"; x: number; y: number; w: number; h: number; r?: number }
  | { shape: "line"; x1: number; y1: number; x2: number; y2: number }
  | { shape: "circle"; cx: number; cy: number; r: number };

type Frac = [x: number, y: number, w: number, h: number];

const desks = (cols: number, rows: number): Frac[] =>
  Array.from({ length: cols * rows }, (_, i): Frac => [
    0.08 + (i % cols) * (0.86 / cols),
    0.3 + Math.floor(i / cols) * (0.6 / rows),
    (0.86 / cols) * 0.6,
    (0.6 / rows) * 0.35,
  ]);

const KIND: Partial<Record<Zone["kind"], Frac[]>> = {
  OFFICE: desks(4, 3),
  CONFERENCE: [[0.2, 0.42, 0.6, 0.3]],
  CONSULAR: [
    [0.08, 0.28, 0.84, 0.08], // the counter
    ...Array.from({ length: 6 }, (_, i): Frac => [0.1 + i * 0.14, 0.62, 0.1, 0.1]), // seats
  ],
  COMMS: Array.from({ length: 5 }, (_, i): Frac => [0.1 + i * 0.17, 0.32, 0.1, 0.55]), // racks
  SAFE_ROOM: [
    [0.06, 0.3, 0.38, 0.14],
    [0.06, 0.55, 0.38, 0.14],
    [0.56, 0.3, 0.38, 0.39], // stores
  ],
  LOBBY: [
    [0.1, 0.3, 0.45, 0.1], // the reception desk
    [0.62, 0.6, 0.3, 0.12], // seating
  ],
  SUITE: [
    [0.12, 0.32, 0.36, 0.18], // a desk
    [0.58, 0.58, 0.3, 0.2], // a sofa
  ],
};

export function furniture(zone: Pick<Zone, "kind" | "x" | "y" | "w" | "h">): Piece[] {
  if (zone.w < 60 || zone.h < 40) return [];
  if (zone.kind === "GATE") {
    const y = zone.y + zone.h * 0.62;
    return [{ shape: "line", x1: zone.x + zone.w * 0.15, y1: y, x2: zone.x + zone.w * 0.85, y2: y }];
  }
  if (zone.kind === "CONFERENCE") {
    const [fx, fy, fw, fh] = KIND.CONFERENCE?.[0] ?? [0, 0, 0, 0];
    const table: Piece = {
      shape: "rect",
      x: zone.x + fx * zone.w,
      y: zone.y + fy * zone.h,
      w: fw * zone.w,
      h: fh * zone.h,
      r: 6,
    };
    const chairs = Array.from({ length: 6 }, (_, i): Piece => ({
      shape: "circle",
      cx: zone.x + (0.27 + (i % 3) * 0.23) * zone.w,
      cy: zone.y + (i < 3 ? 0.36 : 0.78) * zone.h,
      r: 3,
    }));
    return [table, ...chairs];
  }
  return (KIND[zone.kind] ?? []).map(([fx, fy, fw, fh]) => ({
    shape: "rect",
    x: zone.x + fx * zone.w,
    y: zone.y + fy * zone.h,
    w: fw * zone.w,
    h: fh * zone.h,
    r: 1.5,
  }));
}
