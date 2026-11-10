import type { Sensor, Zone } from "../../api/twin";

// The seeded Nairobi embassy plan and its 16 cameras (simulator seed/data.py; plan-pilot-rpl §4),
// for the coverage tests. Fictional, as the seed.

const zone = (code: string, name: string, kind: Zone["kind"], x: number, y: number, w: number, h: number): Zone => ({
  id: `z-${code}`, code, name, kind, x, y, w, h, capacity: null, count: 0,
}); // prettier-ignore
export const PLAN_ZONES: Zone[] = [
  zone("ch", "Chancery offices", "OFFICE", 130, 30, 270, 220),
  zone("amb", "Ambassador suite", "SUITE", 415, 30, 160, 110),
  zone("conf", "Conference room", "CONFERENCE", 415, 155, 160, 95),
  zone("comms", "Comms / IT room", "COMMS", 590, 30, 180, 100),
  zone("safe", "Safe room (hardened)", "SAFE_ROOM", 590, 145, 180, 105),
  zone("lob", "Lobby & reception", "LOBBY", 130, 265, 170, 120),
  zone("cons", "Consular hall", "CONSULAR", 315, 265, 260, 120),
  zone("must", "Muster point · courtyard", "MUSTER", 590, 265, 180, 60),
  zone("g1", "Gate 1", "GATE", 20, 320, 95, 65),
  zone("g2", "Gate 2", "GATE", 680, 340, 90, 45),
];

const MOUNTS: [string, number, number, number, number, number][] = [
  ["g1", 22, 322, 135, 90, 120], ["g1", 113, 383, 315, 90, 120],
  ["g2", 682, 342, 120, 80, 110], ["g2", 768, 383, 290, 80, 110],
  ["lob", 132, 267, 135, 90, 200], ["lob", 298, 383, 315, 90, 200],
  ["cons", 317, 267, 120, 90, 280], ["cons", 573, 383, 300, 90, 280],
  ["ch", 132, 32, 135, 90, 220], ["ch", 132, 248, 70, 70, 280],
  ["conf", 417, 157, 130, 110, 190],
  ["comms", 768, 32, 225, 110, 205],
  ["safe", 592, 147, 130, 110, 210],
  ["must", 592, 267, 105, 90, 190], ["must", 768, 323, 285, 90, 190],
  ["amb", 417, 32, 130, 110, 200],
]; // prettier-ignore

export function planSensors(down: Record<string, Sensor["status"]> = {}): Sensor[] {
  const cameras = MOUNTS.map(([zone_code, x, y, heading_deg, fov_deg, range_u], i): Sensor => {
    const code = `CAM-${String(i + 1).padStart(2, "0")}`;
    const status = down[code] ?? "OK";
    return {
      code, kind: "CCTV", label: `Camera ${i + 1}`, zone_code, status, detail: null,
      status_at: "2026-11-10T08:00:00Z", online: status === "OK" || status === "DEGRADED",
      mount: { x, y, heading_deg, fov_deg, range_u },
    }; // prettier-ignore
  });
  return [
    {
      code: "G2-READER", kind: "BADGE_READER", label: "Gate 2 · badge reader", zone_code: "g2", status: "OK",
      detail: "Online", status_at: "2026-11-10T08:00:00Z", online: true, mount: null,
    }, // prettier-ignore
    ...cameras,
  ];
}
