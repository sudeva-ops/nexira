import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import type { AgentsState } from "../../api/proposals";
import { ADMIN, DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

const STATE: AgentsState = {
  paused: false,
  agents: [
    {
      code: "RESPONSE_PLANNER",
      name: "Response Planner",
      description: "Matches incidents to response playbooks.",
      watches: ["EXPOSURE_COMPUTED"],
      autonomy_level: 2,
      is_enabled: true,
      model_ref: null,
      proposals_pending: 1,
      proposals_total: 4,
      accepted_pct: 75,
    },
  ],
};

function setup(me: Me) {
  return mockApi({
    "/api/me": { body: me },
    "/api/agents": { body: STATE },
    "/api/proposals": { body: [] },
    "/api/agents/RESPONSE_PLANNER": { body: STATE },
    "/api/agents/pause-all": { body: { ...STATE, paused: true } },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AI Agents", () => {
  it("shows the roster read-only to non-admins", async () => {
    setup(DUTY_OFFICER);
    renderApp("/agents");
    const row = (await screen.findByText("Response Planner")).closest("tr");
    expect(row).toHaveTextContent("Exposure of people and sites");
    expect(row).toHaveTextContent("Approve");
    expect(row).toHaveTextContent("75%");
    expect(screen.queryByLabelText("Autonomy for Response Planner")).toBeNull();
    expect(screen.queryByRole("button", { name: /Kill switch/ })).toBeNull();
  });

  it("lets an admin set autonomy and pause all agents after confirming", async () => {
    const fetchMock = setup(ADMIN);
    renderApp("/agents");
    await userEvent.selectOptions(await screen.findByLabelText("Autonomy for Response Planner"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Kill switch · pause all" }));
    const confirm = screen.getByRole("group", { name: "Confirm kill switch" });
    expect(within(confirm).getByText("Pause all agents now?")).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole("button", { name: "Yes, pause all" }));
    const writes = fetchMock.mock.calls
      .filter(([, init]) => init?.method)
      .map(([url, init]) => [String(url), init?.method, init?.body]);
    expect(writes).toEqual([
      ["/api/agents/RESPONSE_PLANNER", "PATCH", JSON.stringify({ autonomy_level: 3 })],
      ["/api/agents/pause-all", "POST", "{}"],
    ]);
  });
});
