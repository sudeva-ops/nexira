import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../api/me";
import type { ScenarioState } from "../api/scenario";
import { SUMMARY, VIEWER } from "../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../test/render";

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

function setup(me: Me) {
  return mockApi({
    "/api/me": { body: me },
    "/api/proposals": { body: [] },
    "/api/agents": { body: { paused: false, agents: [] } },
    "/api/agents/activity": { body: [] },
    "/api/scenarios/NBO-CIVIL-UNREST": { body: STATE },
    "/api/scenarios/NBO-CIVIL-UNREST/next": { body: { ...STATE, status: "PLAYING", current_scene: 1 } },
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
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Global Operations");
  });
});
