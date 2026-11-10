import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { DUTY_OFFICER, mockServer, renderApp } from "../../test/render";
import { REPLAY } from "./fixture";

vi.mock("../../map/ReplayMap", () => ({
  ReplayMap: ({ moment }: { moment: { people: unknown[]; zone: boolean } }) => (
    <div data-testid="replay-map" data-people={moment.people.length} data-zone={String(moment.zone)} />
  ),
}));

function setup() {
  return mockServer({
    "GET /api/me": { body: DUTY_OFFICER },
    "GET /api/proposals": { body: [] },
    "GET /api/incidents/inc-1042/replay": { body: REPLAY },
  });
}

const kpi = (label: string) => screen.getByText(label).closest(".nx-kpi") as HTMLElement;

describe("Incident Replay screen (RPL-02, RPL-03, RPL-06, RPL-07)", () => {
  it("opens at the start, with the header and the note on positions", async () => {
    setup();
    renderApp("/incidents/replay?id=inc-1042");
    expect(await screen.findByText("INC-2026-1042")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Incident Replay");
    expect(screen.getByText(/Positions as now; the platform keeps no location history/)).toBeInTheDocument();
    expect(await screen.findByTestId("replay-map")).toHaveAttribute("data-zone", "false");
    expect(within(kpi("Signals")).getByText("1")).toBeInTheDocument();
    expect(within(kpi("Check-in · personnel")).getByText("—")).toBeInTheDocument();
  });

  it("opens at the moment in the address, and a timeline entry jumps there", async () => {
    setup();
    renderApp("/incidents/replay?id=inc-1042&t=30");
    expect(await screen.findByText("1 / 0 / 2")).toBeInTheDocument(); // safe / needs help / waiting
    expect(within(kpi("People exposed")).getByText("5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /a person needs help/ }));
    expect(screen.getByText("1 / 1 / 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Elapsed")).toHaveTextContent("+0:40");
  });

  it("steps entry to entry with the buttons and the arrow keys", async () => {
    setup();
    renderApp("/incidents/replay?id=inc-1042");
    await screen.findByText("INC-2026-1042");
    await userEvent.click(screen.getByRole("button", { name: "Next entry" }));
    expect(screen.getByLabelText("Elapsed")).toHaveTextContent("+0:02");
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByLabelText("Elapsed")).toHaveTextContent("+0:10");
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByLabelText("Elapsed")).toHaveTextContent("+0:02");
  });

  it("plays to the end, where the figures agree with the Safety Check-in", async () => {
    // jsdom has no matchMedia, so this is the reduced-motion player: an entry every 2 s.
    setup();
    renderApp("/incidents/replay?id=inc-1042");
    await screen.findByText("INC-2026-1042");
    await userEvent.click(screen.getByRole("button", { name: "Play replay" }));
    expect(screen.getByRole("button", { name: "Pause replay" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("1 / 1 / 1")).toBeInTheDocument(), { timeout: 10_000 });
    await waitFor(() => expect(screen.getByRole("button", { name: "Play replay" })).toBeInTheDocument(), {
      timeout: 4_000,
    });
    expect(screen.getByLabelText("Elapsed")).toHaveTextContent("+1:00");
  }, 20_000);

  it("never shows a name: the payload has none", async () => {
    setup();
    const { container } = renderApp("/incidents/replay?id=inc-1042&t=60");
    await screen.findByText("1 / 1 / 1");
    expect(container.textContent).not.toMatch(/Hana|Peter|Grace/);
  });

  it("without an incident, says so", async () => {
    setup();
    renderApp("/incidents/replay");
    expect(await screen.findByText("No incident chosen")).toBeInTheDocument();
  });

  it("a SITE entry links to the camera watching that place (TWN-10, G-8)", async () => {
    mockServer({
      "GET /api/me": { body: DUTY_OFFICER },
      "GET /api/proposals": { body: [] },
      "GET /api/incidents/inc-1042/replay": {
        body: {
          ...REPLAY,
          timeline: [
            ...REPLAY.timeline,
            { at: REPLAY.window.end, source: "SITE", text: "Embassy Nairobi · Camera 7: OFFLINE", site_id: "s-nbo", sensor: "CAM-07" },
          ],
        },
      },
    });
    renderApp("/incidents/replay?id=inc-1042");
    const links = await screen.findAllByRole("link", { name: "View camera" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/twin?site=s-nbo&camera=CAM-07");
  });
});
