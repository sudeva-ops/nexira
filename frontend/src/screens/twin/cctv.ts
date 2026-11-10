import type { OccupantKind, ZoneKind } from "../../api/twin";

// Generated CCTV views for the Site Twin (TWN-03, simulated): a scene drawn for the zone's kind,
// in perspective, with one walking figure per person the twin places there. Nothing is filmed,
// recorded or fetched: no footage of anyone exists (AGENTS.md: no real personal data; D-24).

export const W = 384;
export const H = 216;

export interface Walker {
  kind: OccupantKind;
  u: number; // across the floor, 0..1
  v: number; // into the scene: 0 at the back, 1 at the front
  tu: number; // where it is heading
  tv: number;
  speed: number; // floor units per second
  pause: number; // seconds left standing still
  phase: number; // the gait
}

/** A small deterministic generator, so a camera's people start where they did last time. */
export function rng(seed: string): () => number {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

/** Where people can stand: the visible floor, kept off the walls and the furniture's back row. */
const AREA: Record<ZoneKind, [number, number, number, number]> = {
  GATE: [0.15, 0.85, 0.25, 0.95],
  LOBBY: [0.1, 0.9, 0.2, 0.95],
  CONSULAR: [0.08, 0.92, 0.35, 0.95],
  OFFICE: [0.1, 0.9, 0.3, 0.95],
  SUITE: [0.15, 0.85, 0.3, 0.9],
  CONFERENCE: [0.1, 0.9, 0.25, 0.9],
  COMMS: [0.15, 0.85, 0.3, 0.95],
  SAFE_ROOM: [0.1, 0.9, 0.2, 0.9],
  MUSTER: [0.1, 0.9, 0.2, 0.95],
};

/** How much people move: guards hold their post, visitors drift, staff work. */
const RESTLESS: Record<OccupantKind, number> = {
  GUARD: 0.15,
  STAFF: 0.45,
  VISITOR: 0.8,
};

export function walkers(
  seed: string,
  zone: ZoneKind,
  kinds: OccupantKind[],
): Walker[] {
  const r = rng(seed);
  const [u0, u1, v0, v1] = AREA[zone];
  const at = () => [u0 + r() * (u1 - u0), v0 + r() * (v1 - v0)] as const;
  return kinds.slice(0, 24).map((kind) => {
    const [u, v] = at();
    const [tu, tv] = at();
    return {
      kind,
      u,
      v,
      tu,
      tv,
      speed: 0.05 + r() * 0.06,
      pause: r() * 3,
      phase: r() * 6,
    };
  });
}

/** Move everyone on by dt seconds: walk to a point, stand a while, pick another. */
export function step(
  people: Walker[],
  zone: ZoneKind,
  dt: number,
  r: () => number,
): void {
  const [u0, u1, v0, v1] = AREA[zone];
  for (const p of people) {
    if (p.pause > 0) {
      p.pause -= dt;
      continue;
    }
    const du = p.tu - p.u;
    const dv = p.tv - p.v;
    const d = Math.hypot(du, dv);
    const move = p.speed * dt;
    if (d <= move) {
      p.u = p.tu;
      p.v = p.tv;
      p.pause = 1 + r() * 5 * (1 - RESTLESS[p.kind]);
      p.tu = u0 + r() * (u1 - u0);
      p.tv = v0 + r() * (v1 - v0);
      if (r() > RESTLESS[p.kind]) {
        p.tu = Math.min(u1, Math.max(u0, p.u + (r() - 0.5) * 0.08)); // mostly stay near
        p.tv = Math.min(v1, Math.max(v0, p.v + (r() - 0.5) * 0.05));
      }
    } else {
      p.u += (du / d) * move;
      p.v += (dv / d) * move;
      p.phase += dt * 8;
    }
  }
}

// --- the room in perspective ------------------------------------------------------------------

const BACK = { x0: W * 0.27, x1: W * 0.73, y0: H * 0.1, y1: H * 0.46 }; // the far wall

/** A floor point (u across, v from the back wall to the camera) to the screen, with its scale. */
export function floor(
  u: number,
  v: number,
): { x: number; y: number; s: number } {
  const left = BACK.x0 + (0 - BACK.x0) * v;
  const right = BACK.x1 + (W - BACK.x1) * v;
  return {
    x: left + (right - left) * u,
    y: BACK.y1 + (H - BACK.y1) * v,
    s: 0.38 + 0.62 * v,
  };
}

function poly(
  ctx: CanvasRenderingContext2D,
  pts: [number, number][],
  fill: string,
): void {
  ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
}

function box(
  ctx: CanvasRenderingContext2D,
  u0: number,
  u1: number,
  v: number,
  height: number,
  fill: string,
): void {
  const a = floor(u0, v);
  const b = floor(u1, v);
  const h = height * a.s;
  ctx.fillStyle = fill;
  ctx.fillRect(a.x, a.y - h, b.x - a.x, h);
  ctx.fillStyle = "rgba(255,255,255,0.12)";
  ctx.fillRect(a.x, a.y - h, b.x - a.x, Math.max(1, 3 * a.s));
}

function room(
  ctx: CanvasRenderingContext2D,
  wall: string,
  floorColour: string,
): void {
  const { x0, x1, y0, y1 } = BACK;
  poly(
    ctx,
    [
      [0, 0],
      [W, 0],
      [x1, y0],
      [x0, y0],
    ],
    "#2b2f35",
  ); // ceiling
  poly(
    ctx,
    [
      [0, 0],
      [x0, y0],
      [x0, y1],
      [0, H],
    ],
    "#565c64",
  ); // left wall
  poly(
    ctx,
    [
      [W, 0],
      [x1, y0],
      [x1, y1],
      [W, H],
    ],
    "#4c525a",
  ); // right wall
  poly(
    ctx,
    [
      [x0, y0],
      [x1, y0],
      [x1, y1],
      [x0, y1],
    ],
    wall,
  ); // far wall
  poly(
    ctx,
    [
      [x0, y1],
      [x1, y1],
      [W, H],
      [0, H],
    ],
    floorColour,
  ); // floor
  ctx.strokeStyle = "rgba(0,0,0,0.18)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 8; i += 1) {
    const a = floor(i / 8, 0);
    const b = floor(i / 8, 1);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  for (const v of [0.12, 0.28, 0.48, 0.72]) {
    const a = floor(0, v);
    const b = floor(1, v);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(255,255,240,0.55)"; // ceiling lights
  for (const f of [0.3, 0.7]) {
    ctx.fillRect(W * f - 22, H * 0.035, 44, 4);
  }
}

function door(ctx: CanvasRenderingContext2D, at: number): void {
  const { x0, x1, y1 } = BACK;
  const x = x0 + (x1 - x0) * at;
  ctx.fillStyle = "#2a2e33";
  ctx.fillRect(x - 11, y1 - 36, 22, 36);
  ctx.fillStyle = "#9aa3ad";
  ctx.fillRect(x + 6, y1 - 18, 2, 3);
}

function gate(ctx: CanvasRenderingContext2D): void {
  const sky = ctx.createLinearGradient(0, 0, 0, H * 0.4);
  sky.addColorStop(0, "#8a96a3");
  sky.addColorStop(1, "#b9c1c9");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#6e747b"; // the perimeter wall
  ctx.fillRect(0, H * 0.24, W, BACK.y1 - H * 0.24);
  ctx.fillStyle = "#3b4046"; // the gate
  ctx.fillRect(W * 0.38, H * 0.2, W * 0.24, BACK.y1 - H * 0.2);
  ctx.strokeStyle = "#8b939b";
  for (let x = W * 0.39; x < W * 0.62; x += 7) {
    ctx.beginPath();
    ctx.moveTo(x, H * 0.21);
    ctx.lineTo(x, BACK.y1);
    ctx.stroke();
  }
  poly(
    ctx,
    [
      [0, BACK.y1],
      [W, BACK.y1],
      [W, H],
      [0, H],
    ],
    "#5a5f65",
  ); // the forecourt
  ctx.fillStyle = "#e9e3c8"; // road markings
  for (let v = 0.1; v < 1; v += 0.22) {
    const p = floor(0.5, v);
    ctx.fillRect(p.x - 2 * p.s, p.y, 4 * p.s, 10 * p.s);
  }
  box(ctx, 0.04, 0.2, 0.42, 40, "#7d848b"); // the guard booth
  ctx.fillStyle = "#c7ced6";
  const w = floor(0.06, 0.42);
  ctx.fillRect(w.x + 3, w.y - 32 * w.s, 18 * w.s, 10 * w.s);
}

function muster(ctx: CanvasRenderingContext2D): void {
  ctx.fillStyle = "#a9b1b9";
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#7c838a";
  ctx.fillRect(0, H * 0.18, W, BACK.y1 - H * 0.18);
  poly(
    ctx,
    [
      [0, BACK.y1],
      [W, BACK.y1],
      [W, H],
      [0, H],
    ],
    "#8d9399",
  );
  ctx.fillStyle = "#59705c"; // planters
  for (const u of [0.08, 0.92]) {
    const p = floor(u, 0.2);
    ctx.beginPath();
    ctx.arc(p.x, p.y - 18 * p.s, 16 * p.s, 0, Math.PI * 2);
    ctx.fill();
  }
  const sign = floor(0.5, 0.05); // the assembly point sign
  ctx.fillStyle = "#3f454b";
  ctx.fillRect(sign.x - 1, sign.y - 30, 2, 30);
  ctx.fillStyle = "#dde3e8";
  ctx.fillRect(sign.x - 16, sign.y - 42, 32, 14);
  ctx.fillStyle = "#3f454b";
  ctx.font = "bold 7px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("ASSEMBLY", sign.x, sign.y - 32);
}

/** The still part of the view: drawn once into a buffer, then copied every frame. */
export function scene(ctx: CanvasRenderingContext2D, zone: ZoneKind): void {
  if (zone === "GATE") return gate(ctx);
  if (zone === "MUSTER") return muster(ctx);
  room(
    ctx,
    zone === "SAFE_ROOM" ? "#71777e" : "#8a9097",
    zone === "SAFE_ROOM" ? "#555a60" : "#666c73",
  );
  switch (zone) {
    case "CONSULAR": // the counter with its windows
      box(ctx, 0.05, 0.95, 0.22, 34, "#5b6168");
      ctx.fillStyle = "rgba(220,230,240,0.35)";
      for (let u = 0.08; u < 0.92; u += 0.17) {
        const a = floor(u, 0.22);
        ctx.fillRect(a.x, a.y - 52 * a.s, 40 * a.s, 18 * a.s);
      }
      door(ctx, 0.1);
      break;
    case "LOBBY": // the reception desk and the screening arch
      box(ctx, 0.55, 0.85, 0.35, 26, "#5b6168");
      box(ctx, 0.18, 0.21, 0.5, 60, "#3d4248");
      box(ctx, 0.31, 0.34, 0.5, 60, "#3d4248");
      door(ctx, 0.5);
      break;
    case "OFFICE":
      for (const v of [0.35, 0.65]) {
        box(ctx, 0.1, 0.35, v, 20, "#5d636a");
        box(ctx, 0.62, 0.88, v, 20, "#5d636a");
      }
      door(ctx, 0.85);
      break;
    case "CONFERENCE":
      box(ctx, 0.22, 0.78, 0.55, 18, "#4f555b");
      door(ctx, 0.15);
      break;
    case "COMMS": // the racks
      for (const u of [0.05, 0.2, 0.68, 0.83])
        box(ctx, u, u + 0.12, 0.25, 70, "#2f3338");
      ctx.fillStyle = "#9fe0a6";
      for (const u of [0.07, 0.22, 0.7, 0.85]) {
        const a = floor(u, 0.25);
        for (let i = 0; i < 5; i += 1)
          ctx.fillRect(a.x + 2, a.y - (60 - i * 10) * a.s, 2, 2);
      }
      break;
    case "SAFE_ROOM": // benches and the hardened door
      box(ctx, 0.04, 0.3, 0.3, 14, "#4a4f55");
      box(ctx, 0.7, 0.96, 0.3, 14, "#4a4f55");
      ctx.fillStyle = "#3a3f44";
      ctx.fillRect(BACK.x0 + 70, BACK.y1 - 44, 34, 44);
      ctx.strokeStyle = "#a7afb7";
      ctx.strokeRect(BACK.x0 + 70, BACK.y1 - 44, 34, 44);
      break;
    case "SUITE":
      box(ctx, 0.3, 0.7, 0.4, 22, "#5a4f46");
      door(ctx, 0.15);
      break;
    default:
      door(ctx, 0.5);
  }
}

const TONE: Record<OccupantKind, [string, string]> = {
  STAFF: ["#2c3138", "#d7c4b0"],
  GUARD: ["#14171b", "#c9b39c"], // dark uniform
  VISITOR: ["#8f969e", "#e0cdb8"],
};

/** The people, back to front so nearer figures overlap farther ones. */
export function people(
  ctx: CanvasRenderingContext2D,
  walkersNow: Walker[],
): void {
  for (const p of [...walkersNow].sort((a, b) => a.v - b.v)) {
    const { x, y, s } = floor(p.u, p.v);
    const [body, skin] = TONE[p.kind];
    const h = 46 * s;
    const sway = Math.sin(p.phase) * 1.5 * s;
    ctx.fillStyle = "rgba(0,0,0,0.25)";
    ctx.beginPath();
    ctx.ellipse(x, y, 7 * s, 2.5 * s, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = body;
    ctx.fillRect(x - 3.5 * s + sway, y - h * 0.45, 3 * s, h * 0.45); // legs
    ctx.fillRect(x + 0.5 * s - sway, y - h * 0.45, 3 * s, h * 0.45);
    ctx.beginPath();
    ctx.roundRect(x - 6 * s, y - h * 0.86, 12 * s, h * 0.46, 3 * s); // the torso
    ctx.fill();
    ctx.fillStyle = skin;
    ctx.beginPath();
    ctx.arc(x, y - h * 0.94, 4.2 * s, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** Sensor grain: a noise tile drawn at a new offset each frame. */
export function grain(
  ctx: CanvasRenderingContext2D,
  noise: HTMLCanvasElement,
  r: () => number,
  alpha: number,
): void {
  ctx.globalAlpha = alpha;
  ctx.drawImage(noise, -r() * 60, -r() * 60, W + 60, H + 60);
  ctx.globalAlpha = 1;
}

export function noiseTile(r: () => number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 160;
  c.height = 90;
  const ctx = c.getContext("2d");
  if (!ctx) return c;
  const img = ctx.createImageData(c.width, c.height);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = Math.floor(r() * 255);
    img.data[i] = v;
    img.data[i + 1] = v;
    img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

/** The clip each zone kind plays: frontend/public/cctv/<name>.mp4. */
export const CLIP: Record<ZoneKind, string> = {
  GATE: "gate",
  LOBBY: "lobby",
  CONSULAR: "consular",
  OFFICE: "office",
  CONFERENCE: "conference",
  COMMS: "comms",
  SAFE_ROOM: "safe-room",
  SUITE: "suite",
  MUSTER: "muster",
};
