import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../api/me";
import type { ScenarioState } from "../api/scenario";
import { SCENE_SCREEN } from "./scenes";
import { SUMMARY, VIEWER } from "../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../test/render";

// "Next scene" navigates to the map screens; jsdom has no WebGL, so the maps are stubbed
// (as in the screens' own tests).
vi.mock("../map/OperationsMap", () => ({ OperationsMap: () => <div data-testid="operations-map" /> }));
vi.mock("../map/AirMap", () => ({ AirMap: () => <div data-testid="air-map" /> }));

const NAMES = ["Calm", "Signals fused", "Impact", "Playbook", "Check-in", "Decisions", "Review"];
const STATE: ScenarioState = {
  code: "NBO-CIVIL-UNREST",
  name: "Civil unrest near the Nairobi Embassy",
  run_id: "r1",
  status: "IDLE",
  current_scene: 0,
  position: 0,
  scene_complete: false,
  scenes: NAMES.map((name, i) => ({ scene_no: i, name, expect: `Expect ${i}`, events: 1 })),
};

const FRANCE: ScenarioState = {
  ...STATE,
  code: "FRA-NATIONAL-PROTESTS",
  name: "Nationwide protests in France",
  scenes: ["Calm", "Paris marches", "Nationwide", "Second day"].map((name, i) => ({
    scene_no: i,
    name,
    expect: `France ${i}`,
    events: 1,
  })),
};

function setup(me: Me) {
  return mockApi({
    "/api/me": { body: me },
    "/api/proposals": { body: [] },
    "/api/agents": { body: { paused: false, agents: [] } },
    "/api/agents/activity": { body: [] },
    "/api/scenarios/NBO-CIVIL-UNREST": { body: STATE },
    "/api/scenarios/NBO-CIVIL-UNREST/next": { body: { ...STATE, status: "PLAYING", current_scene: 1 } },
    "/api/scenarios/FRA-NATIONAL-PROTESTS": { body: FRANCE },
    "/api/incidents": { body: [] },
    "/api/signals": { body: [] },
    "/api/missions": { body: [] },
    "/api/operations/summary": { body: SUMMARY },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("Presenter bar", () => {
  it("is not there outside demo mode", async () => {
    vi.stubEnv("VITE_DEMO_MODE", "false");
    setup(DUTY_OFFICER);
    renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("toolbar", { name: "Presenter" })).toBeNull();
  });

  it("is not there for users who cannot drive the scenario", async () => {
    vi.stubEnv("VITE_DEMO_MODE", "true");
    setup(VIEWER);
    renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("toolbar", { name: "Presenter" })).toBeNull();
  });

  it("shows scenes 0-6 and advances through the scenario API", async () => {
    vi.stubEnv("VITE_DEMO_MODE", "true");
    const fetchMock = setup(DUTY_OFFICER);
    renderApp("/");
    const bar = await screen.findByRole("toolbar", { name: "Presenter" });
    expect(within(bar).getByText("Calm")).toBeInTheDocument();
    expect(within(bar).getByText("Expect 0")).toBeInTheDocument();
    await userEvent.click(within(bar).getByRole("button", { name: "Next scene" }));
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => String(url) === "/api/scenarios/NBO-CIVIL-UNREST/next" && init?.method === "POST",
      ),
    ).toBe(true);
    // Scene 1 is watched on Global Operations.
    expect(await screen.findByRole("heading", { level: 1, name: "Global Operations" })).toBeInTheDocument();
  });

  it("switches to the France scenario", async () => {
    vi.stubEnv("VITE_DEMO_MODE", "true");
    const fetchMock = setup(DUTY_OFFICER);
    renderApp("/");
    const bar = await screen.findByRole("toolbar", { name: "Presenter" });
    await userEvent.selectOptions(within(bar).getByLabelText("Scenario"), "FRA-NATIONAL-PROTESTS");
    expect(await within(bar).findByText("France 0")).toBeInTheDocument();
    expect(within(bar).getAllByText(/^\d$/)).toHaveLength(4); // scenes 0-3, not Nairobi's 0-6
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/scenarios/FRA-NATIONAL-PROTESTS")).toBe(
      true,
    );
  });

  it("offers every demo scenario, the Manila storm included (WX-07)", async () => {
    vi.stubEnv("VITE_DEMO_MODE", "true");
    setup(DUTY_OFFICER);
    renderApp("/");
    const bar = await screen.findByRole("toolbar", { name: "Presenter" });
    const options = within(within(bar).getByLabelText("Scenario")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Nairobi civil unrest",
      "France protests",
      "Inbound flight diversion",
      "Manila tropical storm",
      "Dhaka cyclone",
      "Nairobi cholera",
      "Nairobi evacuation",
      "Nairobi fleet",
      "Protection programme",
    ]);
    expect(SCENE_SCREEN["MNL-TROPICAL-STORM"]).toEqual({
      0: "/operations",
      1: "/operations",
      2: "/operations",
      3: "/operations",
    });
    // D-38: the cyclone plays on the Natural Hazards screen; the arming proposal in the queue.
    expect(SCENE_SCREEN["DAC-CYCLONE"]).toEqual({
      0: "/hazards",
      1: "/hazards",
      2: "/",
      3: "/hazards",
      4: "/hazards",
      5: "/hazards",
    });
    // D-39: the cholera advisory rising and dengue closing, on the Health Intelligence screen.
    expect(SCENE_SCREEN["NBO-CHOLERA"]).toEqual({ 0: "/health", 1: "/health", 2: "/health" });
    // D-40: the evacuation plays on its own screen.
    expect(Object.values(SCENE_SCREEN["NBO-EVACUATION"])).toEqual(Array(5).fill("/evacuation"));
    expect(Object.values(SCENE_SCREEN["NBO-FLEET"])).toEqual(Array(4).fill("/fleet"));
    expect(Object.values(SCENE_SCREEN["ADD-VISIT"])).toEqual(Array(4).fill("/vip"));
  });
});
