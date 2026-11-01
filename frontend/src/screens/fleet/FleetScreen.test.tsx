import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Asset, FleetPermissions, FleetSummary, MaintenanceItem, MissionFleet } from "../../api/fleet";
import { defaultFleetMission, dueText, shownStates } from "../../api/fleet";
import type { Me } from "../../api/me";
import type { Mission } from "../../api/people";
import { HOM_NAIROBI, NAIROBI, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const NOW = new Date().toISOString();
const CAIRO: Mission = { ...NAIROBI, id: "m-cai", code: "CAI", city: "Cairo", incident_id: null, incident_reference: null };
const MISSIONS = [NAIROBI, CAIRO];
const ZONE = "INC-2026-1042";

const asset = (code: string, change: Partial<Asset> = {}): Asset => ({
  id: `a-${code}`,
  code,
  kind: "VEHICLE",
  type_label: "Armoured SUV (B6)",
  armoured: true,
  seats: 4,
  mission_id: NAIROBI.id,
  mission_code: "NBO",
  city: "Nairobi",
  location_label: "Embassy garage",
  lat: -1.295,
  lon: 36.808,
  at_site: true,
  fuel_pct: 82,
  position_at: NOW,
  status: "AVAILABLE",
  status_reason: null,
  state: { code: "AVAILABLE", reference: null },
  tags: [],
  available: true,
  driver_assigned: false,
  driver_name: null,
  source: "Illustrative asset register (simulated)",
  simulated: true,
  ...change,
});
const BLOCKED = { code: "BLOCKED", reference: ZONE } as const;
const IN_ZONE = { code: "IN_ZONE", reference: ZONE } as const;
const NAIROBI_ASSETS = [
  asset("VH-01"),
  asset("VH-02", {
    location_label: "Haile Selassie Ave",
    fuel_pct: 46,
    at_site: false,
    status: "IN_USE",
    state: BLOCKED,
    tags: [BLOCKED, IN_ZONE],
    available: false,
    driver_assigned: true,
    driver_name: "Peter Mwangi",
  }),
  asset("VH-03", { type_label: "Minibus 14-seat", armoured: false, seats: 13, fuel_pct: 90 }),
  asset("VH-05", {
    type_label: "Sedan (official)",
    armoured: false,
    seats: 3,
    fuel_pct: 30,
    location_label: "Workshop",
    status: "MAINTENANCE",
    status_reason: "Brake service overdue",
    state: { code: "MAINTENANCE", reference: null },
    tags: [{ code: "MAINTENANCE", reference: null }],
    available: false,
  }),
  asset("GEN-NBO", { kind: "EQUIPMENT", type_label: "Generator 250 kVA", armoured: false, seats: null, fuel_pct: 72, available: false }),
];
const FLEET: MissionFleet = {
  mission_id: NAIROBI.id,
  mission_code: "NBO",
  city: "Nairobi",
  country_code: "KE",
  vehicles: 4,
  available: 2,
  generator_fuel_pct: 72,
  capacity: {
    seats_available: 17,
    seats_needed: 16,
    needed_from: "PEOPLE",
    evacuation_reference: null,
    shortfall: 0,
    suggestion: null,
  },
  simulated: true,
};
const SUMMARY: FleetSummary = { vehicles: 48, armoured: 19, average_fuel_pct: 71, maintenance_due: 3 };
const item = (code: string, task: string, due_on: string, change: Partial<MaintenanceItem> = {}): MaintenanceItem => ({
  id: `i-${code}`,
  asset_id: `a-${code}`,
  asset_code: code,
  mission_id: NAIROBI.id,
  mission_code: "NBO",
  task,
  due_on,
  done_at: null,
  done_by_type: null,
  alert: true,
  overdue: false,
  ...change,
});
const day = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
const ITEMS = [
  item("VH-05", "Brake service", day(-3), { overdue: true }),
  item("VH-03", "Routine service", day(60), { alert: false }),
];
const NONE: FleetPermissions = { set_asset_status: false, complete_maintenance: false };
const ALL: FleetPermissions = { set_asset_status: true, complete_maintenance: true };

function setup(me: Me, permissions: FleetPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/fleet/assets": { body: NAIROBI_ASSETS },
    "GET /api/fleet/summary": { body: SUMMARY },
    "GET /api/fleet/missions/m-nbo": { body: FLEET },
    "GET /api/fleet/maintenance": { body: ITEMS },
    "GET /api/me/permissions": { body: permissions },
    ...extra,
  });
}

function sent(fetchMock: ReturnType<typeof mockServer>, method: string, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === method)
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

async function row(code: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", { name: "Vehicles and critical assets" });
  const found = await within(table).findByText(code);
  return found.closest("tr") as HTMLElement;
}

afterEach(() => vi.unstubAllGlobals());

describe("Fleet & Assets", () => {
  it("opens on the mission with an ACTIVE incident: KPIs, the assets with fuel and tags, capacity", async () => {
    const fetchMock = setup(DUTY_OFFICER, NONE);
    renderApp("/fleet");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Fleet & Assets");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue(NAIROBI.id));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes(`/api/fleet/assets?mission_id=${NAIROBI.id}`))).toBe(true);
    expect(await screen.findByText("19 armoured")).toBeInTheDocument();
    expect(await screen.findByText("Available now · Nairobi")).toBeInTheDocument();
    expect(screen.getByText("Of 4 vehicles")).toBeInTheDocument();
    expect(screen.getByText("Generator: 72%")).toBeInTheDocument();
    expect(screen.getByText("GPS + telematics (simulated)")).toBeInTheDocument();
    const vh02 = await row("VH-02");
    expect(vh02).toHaveTextContent("Haile Selassie Ave");
    expect(vh02).toHaveTextContent("46%");
    expect(vh02).toHaveTextContent("BLOCKED · DRIVER SOS");
    expect(vh02).toHaveTextContent("IN IMPACT ZONE");
    expect(await row("VH-01")).toHaveTextContent("AVAILABLE");
    expect(await row("VH-05")).toHaveTextContent("MAINTENANCE");
    const capacity = await screen.findByLabelText("Evacuation capacity");
    expect(capacity).toHaveTextContent("Seats available17");
    expect(capacity).toHaveTextContent("Seats needed16");
    expect(capacity).toHaveTextContent("Capacity sufficient.");
  });

  it("raises the zone alert for blocked and in-zone vehicles (FLT-05)", async () => {
    setup(DUTY_OFFICER, NONE);
    renderApp("/fleet");
    const alert = await screen.findByTestId("fleet-alert");
    expect(alert).toHaveTextContent(`VH-02 · Haile Selassie Ave · driver needs help (${ZONE}) · in the impact zone of ${ZONE}`);
    expect(alert).not.toHaveTextContent("VH-01");
  });

  it("shows a shortfall with the partner suggestion and requests nothing (FLT-03)", async () => {
    const short = { ...FLEET, capacity: { ...FLEET.capacity, seats_available: 3, shortfall: 13, suggestion: { partner_id: "p", partner_name: "Sentinel Secure Transport", sla_minutes: 30 } } };
    const fetchMock = setup(DUTY_OFFICER, NONE, { "GET /api/fleet/missions/m-nbo": { body: short } });
    renderApp("/fleet");
    const capacity = await screen.findByLabelText("Evacuation capacity");
    await waitFor(() => expect(capacity).toHaveTextContent("Shortfall of 13 seats: Sentinel Secure Transport could add vehicles (a suggestion; nothing is requested)."));
    expect(within(capacity).getByRole("link", { name: "Assistance Partners" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toEqual([]);
  });

  it("lists the maintenance alerts and marks one done when allowed (FLT-04)", async () => {
    const fetchMock = setup(DUTY_OFFICER, ALL, { "POST /api/fleet/maintenance/i-VH-05/done": { body: [] } });
    renderApp("/fleet");
    const alerts = await screen.findByRole("table", { name: "Maintenance alerts" });
    const rows = within(alerts).getAllByRole("row");
    expect(rows).toHaveLength(1); // the routine service in 60 days is not an alert
    expect(rows[0]).toHaveTextContent("VH-05Brake serviceOverdue 3 d");
    await userEvent.click(await within(alerts).findByRole("button", { name: "Mark done" }));
    expect(sent(fetchMock, "POST", "/api/fleet/maintenance/i-VH-05/done")).toEqual([{}]);
  });

  it("sets a vehicle's status with a reason for maintenance (FLT-04)", async () => {
    const fetchMock = setup(DUTY_OFFICER, ALL, { "PATCH /api/fleet/assets/a-VH-03/status": { body: NAIROBI_ASSETS[2] } });
    renderApp("/fleet");
    await userEvent.click(await row("VH-03"));
    const status = await screen.findByRole("combobox", { name: "New status" });
    await userEvent.selectOptions(status, "MAINTENANCE");
    const button = screen.getByRole("button", { name: "Set status" });
    expect(button).toBeDisabled(); // needs a reason
    await userEvent.type(screen.getByLabelText("Reason"), "Tyre puncture");
    await userEvent.click(button);
    expect(sent(fetchMock, "PATCH", "/api/fleet/assets/a-VH-03/status")).toEqual([{ status: "MAINTENANCE", reason: "Tyre puncture" }]);
  });

  it("says why when a status change is refused", async () => {
    setup(HOM_NAIROBI, ALL, {
      "PATCH /api/fleet/assets/a-VH-05/status": { status: 409, body: { detail: "VH-05 is already available" } },
    });
    renderApp("/fleet");
    await userEvent.click(await row("VH-05"));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "New status" }), "AVAILABLE");
    await userEvent.click(screen.getByRole("button", { name: "Set status" }));
    expect(await screen.findByText("VH-05 is already available")).toBeInTheDocument();
  });

  it("shows the driver's name within the scope and 'Driver assigned' otherwise (FLT-07)", async () => {
    setup(DUTY_OFFICER, NONE);
    renderApp("/fleet");
    await userEvent.click(await row("VH-02"));
    expect(await screen.findByRole("table", { name: "Asset details" })).toHaveTextContent("DriverPeter Mwangi");
  });

  it("gives a Viewer the states and capacity, with no driver names and no buttons", async () => {
    const hidden = NAIROBI_ASSETS.map((a) => ({ ...a, driver_name: null }));
    setup(VIEWER, NONE, { "GET /api/fleet/assets": { body: hidden } });
    renderApp("/fleet");
    expect(await row("VH-02")).toHaveTextContent("BLOCKED · DRIVER SOS");
    await userEvent.click(await row("VH-02"));
    const details = await screen.findByRole("table", { name: "Asset details" });
    expect(details).toHaveTextContent("DriverDriver assigned");
    expect(screen.queryByText("Peter Mwangi")).toBeNull();
    expect(screen.queryByRole("button", { name: /Set status|Mark done/ })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "New status" })).toBeNull();
  });

  it("shows every mission and asks for one for capacity", async () => {
    setup(DUTY_OFFICER, ALL);
    renderApp("/fleet");
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Mission" }), "");
    expect(await screen.findByText("Pick a mission to see its road capacity.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark done" })).toBeNull(); // per mission only
  });
});

describe("fleet helpers", () => {
  it("tags, due dates and the default mission", () => {
    expect(shownStates(NAIROBI_ASSETS[0] as Asset)).toEqual([{ code: "AVAILABLE", reference: null }]);
    expect(shownStates(NAIROBI_ASSETS[1] as Asset).map((s) => s.code)).toEqual(["BLOCKED", "IN_ZONE"]);
    const today = new Date(Date.UTC(2026, 10, 1));
    expect(dueText("2026-10-29", today)).toBe("Overdue 3 d");
    expect(dueText("2026-11-01", today)).toBe("Due today");
    expect(dueText("2026-11-11", today)).toBe("Due in 10 d");
    expect(defaultFleetMission(MISSIONS)).toBe(NAIROBI.id);
    expect(defaultFleetMission([CAIRO])).toBe("");
  });
});
