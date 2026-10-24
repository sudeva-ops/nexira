import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Incident } from "../../api/intel";
import { DETAIL, INCIDENT, MISSIONS, SIGNALS, SUMMARY } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

// jsdom has no WebGL; the stand-in renders one button per incident marker.
vi.mock("../../map/OperationsMap", () => ({
  OperationsMap: ({ incidents, onSelect }: { incidents: Incident[]; onSelect: (i: Incident) => void }) => (
    <div data-testid="operations-map">
      {incidents.map((i) => (
        <button key={i.id} type="button" onClick={() => onSelect(i)}>
          marker {i.reference}
        </button>
      ))}
    </div>
  ),
}));

beforeEach(() => {
  mockApi({
    "/api/me": { body: DUTY_OFFICER },
    "/api/operations/summary": { body: SUMMARY },
    "/api/missions": { body: MISSIONS },
    "/api/incidents": { body: [INCIDENT] },
    "/api/signals": { body: SIGNALS },
    [`/api/incidents/${INCIDENT.id}`]: { body: DETAIL },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Global Operations", () => {
  it("shows KPIs computed by the API (D-27)", async () => {
    renderApp("/operations");
    expect(await screen.findByText("1,338")).toBeInTheDocument();
    expect(screen.getByText("93.4% avg. location confidence")).toBeInTheDocument();
    expect(screen.getByText("1 critical")).toBeInTheDocument();
    expect(screen.getByText(`Driven by ${INCIDENT.reference}`)).toBeInTheDocument();
  });

  it("lists the fused incident in the live feed with simulated sources (D-19)", async () => {
    renderApp("/operations");
    const feed = await screen.findByLabelText("Live intelligence feed");
    const item = await within(feed).findByRole("button", { name: `Open ${INCIDENT.reference}` });
    expect(item).toHaveTextContent("FUSED · 3 SOURCES");
    expect(item).toHaveTextContent("Dataminr (simulated)");
    expect(item).toHaveTextContent("Confidence 92%");
    expect(document.body.textContent).not.toMatch(/Connected|AIP|Object explorer/);
  });

  it("opens the impact panel from the map with exposure from the API", async () => {
    renderApp("/operations");
    await userEvent.click(await screen.findByRole("button", { name: `marker ${INCIDENT.reference}` }));
    const stats = await screen.findByLabelText("Exposure summary");
    // D-23: the Sites figure is mission property only (2), not the hotel.
    expect(within(stats).getByText("Sites").previousSibling).toHaveTextContent("2");
    expect(within(stats).getByText("Staff").previousSibling).toHaveTextContent("14");
    expect(within(stats).getByText("Citizens").previousSibling).toHaveTextContent("212");
    expect(screen.getByText("Peter Mwangi")).toBeInTheDocument();
    expect(screen.getByText("GPS")).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
  });
});
