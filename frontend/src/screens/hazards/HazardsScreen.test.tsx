import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { ArmingPermissions, ClimateRisk, HazardEvent, Hazards } from "../../api/hazards";
import { exposureText, hoursUntil, landfallText, measureText } from "../../api/hazards";
import type { Me } from "../../api/me";
import { VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const NOW = new Date().toISOString(); // "updated" is relative to the real time
const hoursFrom = (iso: string, h: number) => new Date(new Date(iso).getTime() + h * 3_600_000).toISOString();
const ZERO = { staff: 0, people: 0, homes: 0, mission_sites: 0 };

const event = (ref: string, change: Partial<HazardEvent>): HazardEvent => ({
  incident_id: `i-${ref}`,
  reference: ref,
  title: ref,
  category: "FLOOD",
  severity: "MODERATE",
  status: "ACTIVE",
  place_label: null,
  lat: 0,
  lon: 0,
  impact_radius_m: 20_000,
  opened_at: hoursFrom(NOW, -5),
  updated_at: hoursFrom(NOW, -1),
  hazard: {},
  landfall_at: null,
  landfall_in_h: null,
  nearest_mission_code: null,
  nearest_mission_city: null,
  nearest_mission_m: null,
  within_range: true,
  exposed: false,
  exposure: ZERO,
  sources: ["xWeather (simulated)"],
  armed: null,
  simulated: true,
  ...change,
});

const QUAKE = event("INC-1001", {
  category: "EARTHQUAKE",
  title: "Earthquake M5.2, depth 10 km, central Anatolia",
  severity: "LOW",
  place_label: "Central Anatolia · 210 km south of Ankara",
  hazard: { magnitude: 5.2, depth_km: 10 },
  nearest_mission_code: "ANK",
  nearest_mission_city: "Ankara",
  nearest_mission_m: 210_400,
});
const CYCLONE = event("INC-1002", {
  category: "TROPICAL_CYCLONE",
  title: "Cyclone upgraded to Category 2: landfall near Barishal in 60 h",
  severity: "CRITICAL",
  place_label: "Bay of Bengal · Barishal coast",
  hazard: { cyclone_category: 2, landfall_in_h: 60, track_km: 110 },
  landfall_at: hoursFrom(NOW, 60),
  landfall_in_h: 60,
  nearest_mission_code: "DAC",
  nearest_mission_city: "Dhaka",
  nearest_mission_m: 110_000,
  exposed: true,
  exposure: { staff: 15, people: 15, homes: 0, mission_sites: 1 },
});
const FLOOD = event("INC-1003", {
  title: "River flooding along the Ciliwung in Jakarta",
  place_label: "Jakarta · Ciliwung river",
  nearest_mission_code: "JKT",
  nearest_mission_city: "Jakarta",
  nearest_mission_m: 3_000,
  exposed: true,
  exposure: { staff: 2, people: 2, homes: 2, mission_sites: 0 },
});
const AIR = event("INC-1004", {
  category: "AIR_QUALITY",
  title: "Very poor air quality in New Delhi: AQI 310",
  severity: "CRITICAL",
  hazard: { aqi: 310 },
  nearest_mission_code: "DEL",
  nearest_mission_city: "New Delhi",
  nearest_mission_m: 2_000,
  exposed: true,
  exposure: { staff: 14, people: 14, homes: 0, mission_sites: 1 },
});
const FIRE = event("INC-1005", {
  category: "WILDFIRE",
  title: "Wildfire risk: active fires in Attica",
  place_label: "Attica, Greece",
  within_range: false,
});
const HAZARDS: Hazards = { events: [CYCLONE, AIR, FLOOD, FIRE, QUAKE], clock_now: NOW, demo_advance_h: 0, sources: 4 };
const CLIMATE: ClimateRisk[] = [
  ["JKT", "Jakarta", ["Flood", "Sea-level rise"], 82, 88],
  ["DAC", "Dhaka", ["Cyclone", "Flood"], 79, 86],
  ["LON", "London", ["Flood (pluvial)"], 22, 27],
].map(([code, city, hazards, today, y2050]) => ({
  mission_id: `m-${String(code).toLowerCase()}`,
  mission_code: code as string,
  city: city as string,
  hazards: hazards as string[],
  score_today: today as number,
  score_2050: y2050 as number,
  scenario: "Illustrative 2050 (simulated)",
  source: "Climate model (simulated)",
  simulated: true,
}));
const MAY_ARM: ArmingPermissions = { arm_playbook: true, start_armed: false, disarm: false };
const NOTHING: ArmingPermissions = { arm_playbook: false, start_armed: false, disarm: false };

function setup(me: Me, permissions: ArmingPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/hazards": { body: HAZARDS },
    "GET /api/hazards/climate": { body: CLIMATE },
    "GET /api/me/permissions": { body: permissions },
    ...extra,
  });
}

function sent(fetchMock: ReturnType<typeof mockServer>, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

const eventsTable = () => screen.findByRole("table", { name: "Live hazard events" });
const rowOf = (title: string) => screen.getByText(title).closest("tr") as HTMLElement;

afterEach(() => vi.unstubAllGlobals());

describe("Natural Hazards & Climate", () => {
  it("shows the KPIs from data, in the nav under MONITOR (HZ-09)", async () => {
    setup(DUTY_OFFICER, MAY_ARM);
    renderApp("/hazards");
    expect(await screen.findByText("JAKARTA")).toBeInTheDocument();
    expect(screen.getByText("4 within 300 km of a mission")).toBeInTheDocument();
    expect(screen.getByText("2 Critical · 1 Moderate")).toBeInTheDocument(); // DAC, DEL; JKT
    expect(screen.getByText("Flood · Sea-level rise · 88 / 100")).toBeInTheDocument();
    expect(screen.getByText(/xWeather · seismic · air quality/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Natural Hazards & Climate/ })).toBeInTheDocument();
  });

  it("lists every event with its mission exposure and level (HZ-03)", async () => {
    setup(DUTY_OFFICER, MAY_ARM);
    renderApp("/hazards");
    const rows = within(await eventsTable()).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    expect(rowOf(FLOOD.title)).toHaveTextContent("Jakarta mission · 2 staff homes");
    expect(rowOf(QUAKE.title)).toHaveTextContent("Ankara mission · 210 km");
    expect(rowOf(QUAKE.title)).toHaveTextContent("M5.2");
    expect(rowOf(QUAKE.title)).toHaveTextContent("LOW");
    expect(rowOf(AIR.title)).toHaveTextContent("New Delhi mission · 14 staff");
    expect(rowOf(FIRE.title)).toHaveTextContent("No mission within 300 km");
    expect(rowOf(CYCLONE.title)).toHaveTextContent("Cat 2");
    expect(rowOf(FLOOD.title)).toHaveTextContent("1 h ago");
    expect(screen.getAllByText("Simulated").length).toBeGreaterThan(0);
  });

  it("filters the events by type with the tabs", async () => {
    setup(DUTY_OFFICER, MAY_ARM);
    renderApp("/hazards");
    const table = await eventsTable();
    await userEvent.click(screen.getByRole("tab", { name: "Earthquake" }));
    expect(within(table).getAllByRole("row").slice(1)).toHaveLength(1);
    expect(within(table).getByText(QUAKE.title)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Heat" }));
    expect(screen.getByText(/^No hazard events\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "All" }));
    expect(within(await eventsTable()).getAllByRole("row").slice(1)).toHaveLength(5);
  });

  it("counts down to landfall, on the demo clock when it has moved on (HZ-04, G-9)", async () => {
    setup(DUTY_OFFICER, MAY_ARM, {
      "GET /api/hazards": { body: { ...HAZARDS, clock_now: hoursFrom(NOW, 24), demo_advance_h: 24 } },
    });
    renderApp("/hazards");
    await eventsTable();
    expect(rowOf(CYCLONE.title)).toHaveTextContent("Dhaka mission · landfall in 36 h");
    expect(screen.getByText("Simulated · demo clock +24 h")).toBeInTheDocument();
    // 36 h is not more than 36 h: no longer armable, so no banner.
    expect(screen.queryByTestId("arming-INC-1002")).toBeNull();
  });

  it("offers arming PB-06 to a Duty Officer and sends it (HZ-05, HZ-10)", async () => {
    const fetchMock = setup(DUTY_OFFICER, MAY_ARM, {
      "POST /api/playbook-runs/arm": { status: 201, body: {} },
    });
    renderApp("/hazards");
    const banner = await screen.findByTestId("arming-INC-1002");
    expect(banner).toHaveTextContent("Cyclone forecast for Dhaka: landfall in 60 h.");
    expect(banner).toHaveTextContent("arm PB-06 Severe weather, to start 36 h before landfall");
    await userEvent.click(await within(banner).findByRole("button", { name: "Arm playbook" }));
    expect(sent(fetchMock, "/api/playbook-runs/arm")).toEqual([{ playbook_code: "PB-06", incident_id: "i-INC-1002" }]);
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("entity_type=hazards&entity_id=i-INC-1002")),
    ).toBe(true);
  });

  it("says why when arming is refused", async () => {
    setup(DUTY_OFFICER, MAY_ARM, {
      "POST /api/playbook-runs/arm": { status: 409, body: { detail: "A playbook can only be armed for a cyclone forecast" } },
    });
    renderApp("/hazards");
    const banner = await screen.findByTestId("arming-INC-1002");
    await userEvent.click(await within(banner).findByRole("button", { name: "Arm playbook" }));
    expect(await within(banner).findByText("A playbook can only be armed for a cyclone forecast")).toBeInTheDocument();
  });

  it("shows an armed run with start now and disarm, as permitted", async () => {
    const armed: HazardEvent = {
      ...CYCLONE,
      armed: {
        run_id: "run-9",
        playbook_code: "PB-06",
        status: "SCHEDULED",
        scheduled_for: hoursFrom(NOW, 24),
        starts_in_h: 24,
        forecast_changed: true,
      },
    };
    const fetchMock = setup(
      DUTY_OFFICER,
      { arm_playbook: false, start_armed: true, disarm: true },
      {
        "GET /api/hazards": { body: { ...HAZARDS, events: [armed] } },
        "POST /api/playbook-runs/run-9/disarm": { body: {} },
      },
    );
    renderApp("/hazards");
    const banner = await screen.findByTestId("arming-INC-1002");
    expect(banner).toHaveTextContent("PB-06 armed for Dhaka · starts in 24 h.");
    expect(banner).toHaveTextContent("The forecast has changed since it was armed.");
    expect(within(banner).queryByRole("button", { name: "Arm playbook" })).toBeNull();
    expect(await within(banner).findByRole("button", { name: "Start now" })).toBeInTheDocument();
    await userEvent.click(within(banner).getByRole("button", { name: "Disarm" }));
    expect(sent(fetchMock, "/api/playbook-runs/run-9/disarm")).toEqual([{}]);
  });

  it("shows a started armed run on its row, with no banner", async () => {
    const started: HazardEvent = {
      ...CYCLONE,
      landfall_in_h: 30,
      landfall_at: hoursFrom(NOW, 30),
      armed: {
        run_id: "run-9",
        playbook_code: "PB-06",
        status: "AWAITING_APPROVAL",
        scheduled_for: hoursFrom(NOW, -6),
        starts_in_h: null,
        forecast_changed: false,
      },
    };
    setup(DUTY_OFFICER, NOTHING, { "GET /api/hazards": { body: { ...HAZARDS, events: [started] } } });
    renderApp("/hazards");
    await eventsTable();
    expect(rowOf(CYCLONE.title)).toHaveTextContent("PB-06 awaiting approval");
    expect(screen.queryByTestId("arming-INC-1002")).toBeNull();
  });

  it("gives a Viewer the events, counts and climate, with no arming (HZ-10)", async () => {
    setup(VIEWER, NOTHING);
    renderApp("/hazards");
    await eventsTable();
    expect(rowOf(FLOOD.title)).toHaveTextContent("Jakarta mission · 2 staff homes");
    expect(await screen.findByRole("table", { name: "Long-term climate exposure" })).toBeInTheDocument();
    const banner = screen.getByTestId("arming-INC-1002");
    expect(banner).toHaveTextContent("Cyclone forecast for Dhaka");
    expect(within(banner).queryByRole("button")).toBeNull();
  });

  it("shows the climate table, highest 2050 first, labelled illustrative (HZ-08)", async () => {
    setup(VIEWER, NOTHING);
    renderApp("/hazards");
    const table = await screen.findByRole("table", { name: "Long-term climate exposure" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0]?.textContent)).toEqual(["Jakarta", "Dhaka", "London"]);
    expect(rows[0]).toHaveTextContent("Flood · Sea-level rise");
    expect(rows[0]).toHaveTextContent("8288");
    expect(screen.getByText(/Illustrative climate model \(simulated\) · Illustrative 2050 \(simulated\)/)).toBeInTheDocument();
  });
});

describe("hazard formatting", () => {
  it("counts down from the hazard clock as time passes (HZ-04)", () => {
    const landfall = hoursFrom(NOW, 60);
    expect(hoursUntil(landfall, NOW, 0)).toBe(60);
    expect(hoursUntil(landfall, NOW, 90 * 60_000)).toBe(58.5);
    expect(landfallText(59.6)).toBe("landfall in 60 h");
    expect(landfallText(0.5)).toBe("landfall in 30 min");
    expect(landfallText(-1)).toBe("landfall now");
  });

  it("names the measure and the exposure in words (HZ-03)", () => {
    expect(measureText(QUAKE)).toBe("M5.2");
    expect(measureText(AIR)).toBe("AQI 310");
    expect(measureText(FLOOD)).toBe("");
    expect(exposureText(CYCLONE, 60)).toBe("Dhaka mission · landfall in 60 h");
    expect(exposureText({ ...FLOOD, exposure: { ...ZERO, homes: 1 } }, null)).toBe("Jakarta mission · 1 staff home");
    expect(exposureText({ ...FLOOD, exposure: { ...ZERO, mission_sites: 2 } }, null)).toBe("Jakarta mission · 2 sites");
  });
});
