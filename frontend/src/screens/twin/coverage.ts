import type { Mount, Sensor, Twin, Zone } from "../../api/twin";

// Camera coverage (TWN-09..11, D-51; docs/plan-pilot-rpl.md §5). Pure and worked out on read
// from the mounts (TWN-08) and the live statuses. A camera sees a sector from its mount, clipped
// to its own zone's rectangle: no walls or line of sight beyond it (§108 Q3). Coverage is sampled
// on a 5-unit grid of each zone (plan G-7): a cell is covered when its centre is inside an online
// camera's sector. Nothing is detected or counted from the views (§108 Q5).

export const CELL = 5;
const ARC_STEPS = 24;

export type Point = [number, number];
type Rect = Pick<Zone, "x" | "y" | "w" | "h">;

export interface Gap {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ZoneCoverage {
  zone: Zone;
  cells: number;
  covered: number;
  gaps: Gap[]; // uncovered cells, merged along each row
}

export interface Coverage {
  pct: number | null; // covered cells / all cells, rounded down; null with no mounted camera
  zones: ZoneCoverage[];
  notCovered: Zone[]; // no online camera covers any of it
  blind: { zone: Zone; pct: number }[]; // partly covered: the share no camera sees
}

/** A camera with its mount and zone. */
export interface Placed {
  sensor: Sensor;
  mount: Mount;
  zone: Zone;
}

/** Heading 0 is up the plan, clockwise. */
function along(m: Mount, deg: number, r: number): Point {
  const a = (deg * Math.PI) / 180;
  return [m.x + Math.sin(a) * r, m.y - Math.cos(a) * r];
}

/** The camera's sector as a polygon: the mount, then the arc. */
export function sector(m: Mount): Point[] {
  const from = m.heading_deg - m.fov_deg / 2;
  const arc = Array.from({ length: ARC_STEPS + 1 }, (_, i): Point =>
    along(m, from + (m.fov_deg * i) / ARC_STEPS, m.range_u),
  );
  return [[m.x, m.y], ...arc];
}

/** Sutherland–Hodgman against an axis-aligned rectangle. */
export function clip(polygon: Point[], r: Rect): Point[] {
  const atX = (a: Point, b: Point, x: number): Point => [x, a[1] + ((b[1] - a[1]) * (x - a[0])) / (b[0] - a[0])];
  const atY = (a: Point, b: Point, y: number): Point => [a[0] + ((b[0] - a[0]) * (y - a[1])) / (b[1] - a[1]), y];
  const edges: [(p: Point) => boolean, (a: Point, b: Point) => Point][] = [
    [(p) => p[0] >= r.x, (a, b) => atX(a, b, r.x)],
    [(p) => p[0] <= r.x + r.w, (a, b) => atX(a, b, r.x + r.w)],
    [(p) => p[1] >= r.y, (a, b) => atY(a, b, r.y)],
    [(p) => p[1] <= r.y + r.h, (a, b) => atY(a, b, r.y + r.h)],
  ];
  let out = polygon;
  for (const [inside, cut] of edges) {
    const input = out;
    out = [];
    input.forEach((p, i) => {
      const prev = input[(i + input.length - 1) % input.length];
      if (!prev) return;
      if (inside(p)) {
        if (!inside(prev)) out.push(cut(prev, p));
        out.push(p);
      } else if (inside(prev)) {
        out.push(cut(prev, p));
      }
    });
  }
  return out;
}

/** The clipped cone as an SVG path. */
export function cone(c: Placed): string {
  const points = clip(sector(c.mount), c.zone);
  if (points.length < 3) return "";
  return `M${points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join("L")}Z`;
}

/** Whether a point of the camera's own zone is inside its sector. */
export function sees(m: Mount, x: number, y: number): boolean {
  const dx = x - m.x;
  const dy = y - m.y;
  const d = Math.hypot(dx, dy);
  if (d > m.range_u) return false;
  if (d === 0) return true;
  const bearing = ((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360;
  const off = Math.abs(((bearing - m.heading_deg + 540) % 360) - 180);
  return off <= m.fov_deg / 2;
}

/** The site's cameras with a mount, on a zone of the plan. */
export function placed(twin: Pick<Twin, "zones" | "sensors">): Placed[] {
  const zones = new Map(twin.zones.map((z) => [z.code, z]));
  return twin.sensors.flatMap((s) => {
    const zone = s.zone_code ? zones.get(s.zone_code) : undefined;
    return s.kind === "CCTV" && s.mount && zone ? [{ sensor: s, mount: s.mount, zone }] : [];
  });
}

function zoneCoverage(zone: Zone, cameras: Mount[]): ZoneCoverage {
  const cols = Math.floor(zone.w / CELL);
  const rows = Math.floor(zone.h / CELL);
  let covered = 0;
  const gaps: Gap[] = [];
  for (let j = 0; j < rows; j++) {
    const y = zone.y + j * CELL;
    let run: Gap | null = null;
    for (let i = 0; i < cols; i++) {
      const x = zone.x + i * CELL;
      if (cameras.some((m) => sees(m, x + CELL / 2, y + CELL / 2))) {
        covered++;
        run = null;
      } else if (run) {
        run.w += CELL;
      } else {
        run = { x, y, w: CELL, h: CELL };
        gaps.push(run);
      }
    }
  }
  return { zone, cells: cols * rows, covered, gaps };
}

/** TWN-09, TWN-11: each zone's coverage by online cameras, the KPI and what no camera sees. */
export function coverage(twin: Pick<Twin, "zones" | "sensors">): Coverage {
  const cameras = placed(twin);
  const zones = twin.zones.map((z) =>
    zoneCoverage(
      z,
      cameras.filter((c) => c.zone.code === z.code && c.sensor.online).map((c) => c.mount),
    ),
  );
  const cells = zones.reduce((n, z) => n + z.cells, 0);
  const covered = zones.reduce((n, z) => n + z.covered, 0);
  return {
    pct: cameras.length && cells ? Math.floor((100 * covered) / cells) : null,
    zones,
    notCovered: zones.filter((z) => z.cells > 0 && z.covered === 0).map((z) => z.zone),
    blind: zones
      .filter((z) => z.covered > 0 && z.covered < z.cells)
      .map((z) => ({ zone: z.zone, pct: Math.max(1, Math.round((100 * (z.cells - z.covered)) / z.cells)) })),
  };
}

/** TWN-10: the camera that watches a zone: the online camera covering most of it, else its
 * offline one (NO SIGNAL), else none. */
export function watching(twin: Pick<Twin, "zones" | "sensors">, zoneCode: string): Sensor | null {
  const here = placed(twin).filter((c) => c.zone.code === zoneCode);
  const seen = (c: Placed) => zoneCoverage(c.zone, [c.mount]).covered;
  const online = here.filter((c) => c.sensor.online).sort((a, b) => seen(b) - seen(a));
  return (online[0] ?? here[0])?.sensor ?? null;
}

/** TWN-10: what `?camera=` or `?zone=` asks for. A camera opens itself; any other sensor (a
 * gate or door from a SITE timeline entry) opens the camera watching its zone. */
export function target(
  twin: Pick<Twin, "zones" | "sensors">,
  ask: { camera: string | null; zone: string | null },
): { camera: Sensor | null; zone: Zone | null } | null {
  const sensor = ask.camera ? twin.sensors.find((s) => s.code === ask.camera) : undefined;
  if (sensor?.kind === "CCTV") return { camera: sensor, zone: twin.zones.find((z) => z.code === sensor.zone_code) ?? null };
  const code = sensor?.zone_code ?? ask.zone;
  const zone = code ? twin.zones.find((z) => z.code === code) : undefined;
  if (!zone) return null;
  return { camera: watching(twin, zone.code), zone };
}
