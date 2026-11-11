import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Occupant, Sensor, Twin, Zone } from "../../api/twin";
import { floor, H, rng, step, W, walkers } from "./cctv";
import { CctvWall } from "./CctvWall";

const zone = (code: string, name: string, kind: Zone["kind"], count: number): Zone => ({
  id: `z-${code}`, code, name, kind, x: 0, y: 0, w: 100, h: 100, capacity: null, count,
}); // prettier-ignore
const camera = (code: string, zone_code: string, change: Partial<Sensor> = {}): Sensor => ({
  code, kind: "CCTV", label: code, zone_code, status: "OK", detail: null, status_at: "2026-11-10T08:00:00Z", online: true, mount: null, ...change,
}); // prettier-ignore
const person = (id: string, kind: Occupant["kind"], zone_code: string): Occupant => ({
  id, kind, zone_code, name: null, label: null, since: "2026-11-10T08:00:00Z",
}); // prettier-ignore

const ZONES = [
  zone("g1", "Gate 1", "GATE", 1),
  zone("g2", "Gate 2", "GATE", 1),
  zone("lob", "Lobby & reception", "LOBBY", 2),
  zone("cons", "Consular hall", "CONSULAR", 3),
  zone("safe", "Safe room (hardened)", "SAFE_ROOM", 0),
  zone("must", "Muster point", "MUSTER", 0),
  zone("ch", "Chancery offices", "OFFICE", 1),
];
const CAMERAS = [
  camera("CAM-01", "g1"),
  camera("CAM-03", "g2"),
  camera("CAM-05", "lob"),
  camera("CAM-07", "cons", {
    status: "OFFLINE",
    online: false,
    detail: "Offline",
  }),
  camera("CAM-08", "cons"),
  camera("CAM-13", "safe"),
  camera("CAM-14", "must"),
  camera("CAM-09", "ch"),
];

function twin(sensors: Sensor[] = CAMERAS): Twin {
  return {
    site: {
      id: "s",
      name: "Embassy Nairobi",
      site_type: "EMBASSY",
      mission_id: "m",
      mission_code: "NBO",
      city: "Nairobi",
    },
    zones: ZONES,
    occupants: [
      person("o1", "GUARD", "g1"),
      person("o2", "GUARD", "g2"),
      person("o3", "VISITOR", "lob"),
      person("o4", "STAFF", "lob"),
      person("o5", "VISITOR", "cons"),
      person("o6", "VISITOR", "cons"),
      person("o7", "STAFF", "cons"),
      person("o8", "STAFF", "ch"),
    ],
    sensors: [
      ...sensors,
      { ...camera("G2-READER", "g2"), kind: "BADGE_READER" },
    ],
    systems: [],
    counts: {
      on_site: 8,
      staff: 3,
      guards: 2,
      visitors: 3,
      safe_room: 0,
      safe_room_capacity: 20,
      sensors_online: 8,
      sensors: 9,
      faults: 1,
    },
    shelter: null,
    route: null,
    readiness: { score: 79, last_drill_on: null, items: [] },
    source: "simulated",
    simulated: true,
  } as unknown as Twin;
}

describe("the CCTV wall", () => {
  it("shows one camera per key zone, the offline one where it is, and all on request", async () => {
    render(<CctvWall twin={twin()} />);
    const wall = screen.getByLabelText("CCTV cameras");
    const tiles = () =>
      within(wall)
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label"));
    expect(tiles()).toEqual([
      "CAM-01 · Gate 1",
      "CAM-03 · Gate 2",
      "CAM-05 · Lobby & reception",
      "CAM-07 · Consular hall · offline", // the offline one stands for its zone
      "CAM-13 · Safe room (hardened)",
      "CAM-14 · Muster point",
    ]);
    expect(
      screen.getByText(
        /7 \/ 8 online · simulated feeds; nothing is recorded/,
      ),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show all 8" }));
    expect(tiles()).toHaveLength(8);
    await userEvent.click(screen.getByRole("button", { name: "Key cameras" }));
    expect(tiles()).toHaveLength(6);
  });

  it("counts who is in view, says NO SIGNAL when offline, and enlarges a camera", async () => {
    render(<CctvWall twin={twin()} />);
    const feed = (code: string) =>
      document.querySelector(
        `.nx-cctv-tile [data-camera="${code}"]`,
      ) as HTMLElement;
    expect(feed("CAM-05")).toHaveTextContent("2 in zone · access control (simulated)");
    expect(feed("CAM-05")).toHaveTextContent("CAM-05 · LOBBY & RECEPTION");
    expect(feed("CAM-07")).toHaveTextContent("NO SIGNAL");
    expect(feed("CAM-07")).not.toHaveTextContent("REC");
    // TWN-15: over a clip, the zone's people as figures from presence; none on a dead camera.
    expect(feed("CAM-05").querySelector('[data-testid="figures-CAM-05"]')).not.toBeNull();
    expect(feed("CAM-07").querySelector("canvas.nx-cctv-figures")).toBeNull();
    expect(feed("CAM-07")).not.toHaveTextContent("in zone");
    await userEvent.click(
      screen.getByRole("button", { name: "CAM-05 · Lobby & reception" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("CAM-05 · Lobby & reception"),
    ).toBeInTheDocument();
    expect(dialog.querySelector(".nx-cctv-feed.large")).toHaveTextContent(
      /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC/,
    );
  });

  it("plays each zone kind's clip, mirrors a zone's second camera, and draws when a clip is missing", async () => {
    render(<CctvWall twin={twin()} />);
    const video = (code: string) =>
      document.querySelector(
        `.nx-cctv-tile [data-camera="${code}"] video`,
      ) as HTMLVideoElement | null;
    expect(video("CAM-01")?.getAttribute("src")).toBe("/cctv/gate.mp4");
    expect(video("CAM-05")?.getAttribute("src")).toBe("/cctv/lobby.mp4");
    expect(video("CAM-01")?.muted).toBe(true);
    expect(video("CAM-07")).toBeNull(); // offline: static, no clip
    await userEvent.click(screen.getByRole("button", { name: "Show all 8" }));
    expect(video("CAM-08")).toHaveClass("mirrored"); // the consular hall's second camera
    expect(video("CAM-01")).not.toHaveClass("mirrored");
    expect(video("CAM-03")).toHaveClass("mirrored"); // the second gate: the same clip, flipped
    fireEvent.error(video("CAM-05") as HTMLVideoElement);
    expect(video("CAM-05")).toBeNull(); // no lobby clip: the generated view
    expect(
      document.querySelector('.nx-cctv-tile [data-camera="CAM-05"] canvas'),
    ).not.toBeNull();
  });

  it("frames four cameras on one clip four ways: plain, mirrored, tight, both", async () => {
    const gates = ["CAM-01", "CAM-02", "CAM-03", "CAM-04"].map((c, i) =>
      camera(c, i < 2 ? "g1" : "g2"),
    );
    render(<CctvWall twin={twin(gates)} />);
    await userEvent.click(screen.getByRole("button", { name: "Show all 4" }));
    const classes = gates.map(
      (g) =>
        document.querySelector(`.nx-cctv-tile [data-camera="${g.code}"] video`)
          ?.className ?? "",
    );
    expect(classes).toEqual(["", "mirrored", "tight", "mirrored tight"]);
  });

  it("falls back to the first cameras when none is at a key zone, and hides without cameras", () => {
    const { unmount } = render(
      <CctvWall twin={twin([camera("CAM-09", "ch")])} />,
    );
    expect(
      screen.getByRole("button", { name: "CAM-09 · Chancery offices" }),
    ).toBeInTheDocument();
    unmount();
    const { container } = render(<CctvWall twin={twin([])} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the generated scene", () => {
  it("places one figure per person, the same way each time, and keeps them on the floor", () => {
    const a = walkers("CAM-07", "CONSULAR", ["STAFF", "VISITOR", "VISITOR"]);
    expect(a).toHaveLength(3);
    expect(
      walkers("CAM-07", "CONSULAR", ["STAFF", "VISITOR", "VISITOR"]),
    ).toEqual(a);
    const r = rng("x");
    for (let i = 0; i < 400; i += 1) step(a, "CONSULAR", 0.1, r);
    for (const p of a) {
      expect(p.v).toBeGreaterThanOrEqual(0.3);
      expect(p.v).toBeLessThanOrEqual(1);
    }
  });

  it("maps the floor into the picture, nearer is lower and larger", () => {
    const back = floor(0.5, 0);
    const front = floor(0.5, 1);
    expect(front.y).toBe(H);
    expect(front.s).toBeGreaterThan(back.s);
    expect(floor(0, 1).x).toBe(0);
    expect(floor(1, 1).x).toBe(W);
  });
});
