import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import type { Occupant, Sensor, Twin, Zone } from "../../api/twin";
import { dotsIn, drillAgo } from "../../api/twin";
import { VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const SECURITY: Me = {
  id: "u-sec",
  display_name: "Security Officer",
  email: "security.officer@demo.nexira.invalid",
  roles: [{ code: "SECURITY_OFFICER", mission_id: null, mission_code: null }],
};
const SITE = { id: "s-nbo", name: "Embassy Nairobi", site_type: "EMBASSY", mission_id: "m-nbo", mission_code: "NBO", city: "Nairobi" };

const zone = (code: string, name: string, kind: Zone["kind"], x: number, y: number, count: number, capacity: number | null = null): Zone => ({
  id: `z-${code}`, code, name, kind, x, y, w: 160, h: 100, capacity, count,
});  // prettier-ignore
const ZONES = [
  zone("ch", "Chancery offices", "OFFICE", 130, 30, 2),
  zone("conf", "Conference room", "CONFERENCE", 415, 155, 1),
  zone("comms", "Comms / IT room", "COMMS", 590, 30, 0),
  zone("safe", "Safe room (hardened)", "SAFE_ROOM", 590, 145, 0, 20),
  zone("g2", "Gate 2", "GATE", 680, 340, 1),
];
const occupant = (id: string, kind: Occupant["kind"], zone_code: string, change: Partial<Occupant> = {}): Occupant => ({
  id, kind, zone_code, name: null, label: null, since: "2026-11-02T08:00:00Z", ...change,
});  // prettier-ignore
const sensor = (code: string, kind: string, label: string, zone_code: string | null, change: Partial<Sensor> = {}): Sensor => ({
  code, kind, label, zone_code, status: "OK", detail: null, status_at: "2026-11-02T08:00:00Z", online: true, ...change,
});  // prettier-ignore
const SENSORS = [
  sensor("G1-MAIN", "GATE", "Gate 1 · main", null, { detail: "Open · screening" }),
  sensor("G2-READER", "BADGE_READER", "Gate 2 · badge reader", "g2", { detail: "Online" }),
  sensor("SAFE-ROOM", "SAFE_ROOM", "Safe room", "safe", { detail: "Ready" }),
  sensor("CAM-01", "CCTV", "Camera 1", "ch"),
  sensor("CAM-02", "CCTV", "Camera 2", "ch"),
  sensor("DOOR-01", "ACCESS", "Door 1", "ch"),
];

function twin(change: Partial<Twin> = {}): Twin {
  return {
    site: SITE,
    zones: ZONES,
    occupants: [
      occupant("o1", "STAFF", "ch", { name: "Fictional Officer A" }),
      occupant("o2", "STAFF", "ch", { name: "Fictional Officer B" }),
      occupant("o3", "VISITOR", "conf", { label: "Visitor 1" }),
      occupant("o4", "GUARD", "g2", { label: "Guard 2" }),
    ],
    sensors: SENSORS,
    systems: [
      { code: "GEN-NBO", label: "Generator", state: "AVAILABLE", fuel_pct: 72 },
      { code: "SAT-NBO", label: "Satellite comms", state: "AVAILABLE", fuel_pct: 100 },
    ],
    counts: { on_site: 4, staff: 2, guards: 1, visitors: 1, safe_room: 0, safe_room_capacity: 20, sensors_online: 6, sensors: 6, faults: 0 },
    shelter: null,
    route: null,
    readiness: {
      score: 79,
      last_drill_on: new Date(Date.now() - 21 * 86_400_000).toISOString().slice(0, 10),
      items: [
        { id: "r1", label: "Floor wardens assigned (3)", done: true, done_by_name: "Leila Nasser", done_at: "x", derived: false, detail: null },
        { id: "r4", label: "Generator load test witnessed", done: false, done_by_name: null, done_at: null, derived: false, detail: null },
        { id: null, label: "All access points monitored", done: true, done_by_name: null, done_at: null, derived: true, detail: null },
      ],
    },
    source: "Access control, CCTV and building systems (simulated)",
    simulated: true,
    ...change,
  };
}

function setup(me: Me, shown: Twin, tick = false, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/sites/twin": { body: [SITE] },
    "GET /api/sites/s-nbo/twin": { body: shown },
    "GET /api/me/permissions": { body: { tick_readiness: tick } },
    ...extra,
  });
}

function sent(fetchMock: ReturnType<typeof mockServer>, method: string, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === method)
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

afterEach(() => vi.unstubAllGlobals());

describe("Site Twin", () => {
  it("shows the KPIs, the plan with counts and dots, sensors, occupancy and readiness (TWN-01..05)", async () => {
    setup(DUTY_OFFICER, twin());
    const { container } = renderApp("/twin");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Site Twin");
    expect(await screen.findByText("2 staff · 1 guard · 1 visitor")).toBeInTheDocument();
    expect(screen.getByText("0 / 20")).toBeInTheDocument();
    expect(screen.getByText("6 / 6")).toBeInTheDocument();
    expect(screen.getByText("Last drill 3 weeks ago")).toBeInTheDocument();
    const plan = screen.getByRole("img", { name: "Embassy Nairobi floor plan" });
    expect(within(plan).getByText("Chancery offices")).toBeInTheDocument();
    expect(plan.querySelectorAll("circle")).toHaveLength(4);
    expect(plan.querySelectorAll('circle[data-kind="STAFF"]')).toHaveLength(2);
    // Names only as the API gives them (within scope); labels for guards and visitors.
    const titles = [...plan.querySelectorAll("circle title")].map((t) => t.textContent);
    expect(titles).toContain("Fictional Officer A · Staff · Chancery offices");
    expect(titles).toContain("Visitor 1 · Visitor · Conference room");
    const sensors = screen.getByRole("list", { name: "Sensors and systems" });
    expect(sensors).toHaveTextContent("Gate 2 · badge readerOnlineOK");
    expect(sensors).toHaveTextContent("CCTV2 / 2 onlineOK");
    expect(sensors).toHaveTextContent("Doors & alarms1 / 1 onlineOK");
    expect(sensors).toHaveTextContent("Generator GEN-NBOavailable · 72%OK");
    expect(screen.getByRole("table", { name: "Occupancy by zone" })).toHaveTextContent("Chancery offices2");
    expect(container.querySelector('[data-testid="twin-shelter"]')).toBeNull();
    expect(container.querySelector('[data-testid="twin-route"]')).toBeNull();
    // No tick without permission.
    expect(screen.queryByRole("button", { name: /Mark done/ })).toBeNull();
  });

  it("shows no name where the API gives none", async () => {
    const hidden = twin({ occupants: twin().occupants.map((o) => ({ ...o, name: null })) });
    setup(VIEWER, hidden);
    renderApp("/twin");
    const plan = await screen.findByRole("img", { name: "Embassy Nairobi floor plan" });
    const titles = [...plan.querySelectorAll("circle title")].map((t) => t.textContent);
    expect(titles).toContain("Staff · Staff · Chancery offices");
    expect(plan.textContent).not.toContain("Fictional");
  });

  it("shows shelter-in-place with the safe room and the route while evacuating (TWN-04)", async () => {
    const occupants = [
      occupant("o1", "STAFF", "safe", { name: "A" }),
      occupant("o2", "STAFF", "safe", { name: "B" }),
      occupant("o5", "STAFF", "comms", { name: "C" }),
      occupant("o3", "VISITOR", "conf", { label: "Visitor 1" }),
    ];
    setup(
      DUTY_OFFICER,
      twin({
        occupants,
        counts: { ...twin().counts, safe_room: 2 },
        shelter: { incident_id: "i-1042", incident_reference: "INC-2026-1042" },
        route: { code: "B", label: "Route B → vehicles via Gate 2", path: [[680, 200], [725, 340]], exit_zone_code: "g2", evacuation_reference: "EVN-1001" },
      }),
    );
    const { container } = renderApp("/twin");
    const banner = await screen.findByTestId("twin-shelter");
    expect(banner).toHaveTextContent(
      "Shelter-in-place active (INC-2026-1042): 2 staff in the safe room, 1 staff in the IT room, 1 visitor held in the conference room. Route B approved via Gate 2.",
    );
    expect(within(banner).getByRole("link", { name: "Open incident →" })).toHaveAttribute("href", "/incidents?id=i-1042");
    expect(screen.getByText("2 / 20")).toBeInTheDocument();
    expect(screen.getByText("Sealed")).toBeInTheDocument();
    const route = container.querySelector('[data-testid="twin-route"]');
    expect(route).not.toBeNull();
    expect(route?.textContent).toBe("Route B → vehicles via Gate 2");
  });

  it("shows faults: the gate outlined, the access item open, the KPI alert (TWN-03)", async () => {
    const sensors = SENSORS.map((s) =>
      s.code === "G2-READER"
        ? { ...s, status: "FAULT" as const, detail: "Fault · manual guard", online: false }
        : s.code === "CAM-02"
          ? { ...s, status: "OFFLINE" as const, online: false }
          : s,
    );
    const items = twin().readiness.items.map((i) =>
      i.derived ? { ...i, done: false, detail: "Gate 2 · badge reader: Fault · manual guard" } : i,
    );
    setup(DUTY_OFFICER, twin({ sensors, counts: { ...twin().counts, sensors_online: 4, faults: 2 }, readiness: { ...twin().readiness, items } }));
    renderApp("/twin");
    expect(await screen.findByText("4 / 6")).toBeInTheDocument();
    expect(screen.getByText("2 faults")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Sensors and systems" });
    expect(list).toHaveTextContent("Gate 2 · badge readerFault · manual guardFAULT");
    expect(list).toHaveTextContent("CCTV1 / 2 onlineOFFLINE");
    const plan = screen.getByRole("img", { name: "Embassy Nairobi floor plan" });
    expect(plan.querySelector('g[data-zone="g2"] rect')).toHaveAttribute("stroke", "#CD4246");
    const readiness = screen.getByRole("list", { name: "Emergency readiness" });
    expect(readiness).toHaveTextContent("All access points monitoredGate 2 · badge reader: Fault · manual guard");
  });

  it("ticks a readiness item when allowed (TWN-05)", async () => {
    const fetchMock = setup(SECURITY, twin(), true, { "POST /api/sites/readiness/r4/done": { body: twin() } });
    renderApp("/twin");
    const readiness = await screen.findByRole("list", { name: "Emergency readiness" });
    const button = await within(readiness).findByRole("button", { name: "Mark done: Generator load test witnessed" });
    expect(within(readiness).getAllByRole("button")).toHaveLength(1); // not on done or derived items
    await userEvent.click(button);
    expect(sent(fetchMock, "POST", "/api/sites/readiness/r4/done")).toEqual([{}]);
  });

  it("says when no site has a floor plan", async () => {
    setup(DUTY_OFFICER, twin(), false, { "GET /api/sites/twin": { body: [] } });
    renderApp("/twin");
    expect(await screen.findByText("No site has a floor plan.")).toBeInTheDocument();
  });

  it("puts Site Twin after Assistance Partners", async () => {
    setup(DUTY_OFFICER, twin());
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    await waitFor(() => expect(within(nav).getByText("Site Twin")).toBeInTheDocument());
    const labels = within(nav).getAllByRole("link").map((a) => a.textContent);
    expect(labels.indexOf("Site Twin")).toBe(labels.indexOf("Assistance Partners") + 1);
  });
});

describe("Site Twin helpers", () => {
  it("lays dots on a grid inside the zone and says how long ago the drill was", () => {
    expect(dotsIn({ x: 130, y: 30, w: 70 }, 4)).toEqual([
      { x: 144, y: 66 },
      { x: 160, y: 66 },
      { x: 144, y: 82 }, // two to a row in a 70-unit zone
      { x: 160, y: 82 },
    ]);
    const today = new Date("2026-11-02T12:00:00Z");
    expect(drillAgo("2026-10-12", today)).toBe("3 weeks ago");
    expect(drillAgo("2026-11-01", today)).toBe("1 day ago");
    expect(drillAgo(null, today)).toBeNull();
  });
});
