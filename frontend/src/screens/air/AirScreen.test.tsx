import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Flight, FlightDetail } from "../../api/flights";
import { DUTY_OFFICER, mockServer, renderApp } from "../../test/render";

// jsdom has no WebGL; the stand-in renders one button per flight on the map.
vi.mock("../../map/AirMap", () => ({
  AirMap: ({ flights, onSelect }: { flights: Flight[]; onSelect: (id: string) => void }) => (
    <div data-testid="air-map">
      {flights.map((f) => (
        <button key={f.id} type="button" onClick={() => onSelect(f.id)}>
          plane {f.flight_number}
        </button>
      ))}
    </div>
  ),
}));

const BASE: Flight = {
  id: "f-451",
  flight_number: "XW 451",
  status: "HOLDING",
  from_airport: "AUH",
  from_city: "Abu Dhabi",
  to_airport: "NBO",
  to_city: "Nairobi",
  diverted_to: null,
  diverted_city: null,
  scheduled_dep: "2026-10-27T06:00:00Z",
  scheduled_arr: "2026-10-27T10:30:00Z",
  estimated_dep: "2026-10-27T06:00:00Z",
  estimated_arr: "2026-10-27T10:40:00Z",
  delay_min: 10,
  disrupted: true,
  lat: -1.1,
  lon: 36.7,
  altitude_ft: 12000,
  speed_kt: 230,
  progress: 0.97,
  route: [
    [24.43, 54.65],
    [-1.32, 36.93],
  ],
  travellers: ["Fictional Officer A", "Fictional Officer B", "Fictional Officer C"],
  trip_id: "t-8818",
  trip_reference: "TRP-8818",
  updated_at: "2026-10-27T10:35:00Z",
  simulated: true,
};
const CRUISING: Flight = {
  ...BASE,
  id: "f-812",
  flight_number: "XW 812",
  status: "AIRBORNE",
  from_airport: "CGK",
  from_city: "Jakarta",
  to_airport: "AMS",
  to_city: "Amsterdam",
  disrupted: false,
  delay_min: 0,
  altitude_ft: 37000,
  speed_kt: 460,
  progress: 0.4,
  travellers: ["Fictional Officer D", "Fictional Officer E"],
  trip_id: "t-8819",
  trip_reference: "TRP-8819",
};
const DIVERTED: Flight = { ...BASE, status: "DIVERTED", diverted_to: "MBA", diverted_city: "Mombasa" };
const DETAIL: FlightDetail = {
  ...BASE,
  events: [
    { event_type: "DEPARTED", occurred_at: "2026-10-27T06:00:00Z", details: {} },
    { event_type: "HOLDING", occurred_at: "2026-10-27T10:30:00Z", details: { reason: "Arrivals restricted" } },
  ],
};

function server(flights: Flight[]) {
  return mockServer({
    "GET /api/me": { body: DUTY_OFFICER },
    "GET /api/flights": { body: flights },
    "GET /api/flights/f-451": { body: DETAIL },
    "GET /api/proposals": {
      body: [
        {
          id: "p1",
          status: "PENDING",
          title: "Notify XW 451 travellers · holding near Nairobi",
          effective_level: 2,
          action_payload: { trip_id: "t-8818", message: "x" },
        },
      ],
    },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("Air Travel Tracking", () => {
  it("lists tracked flights with altitude, ETA and status, and counts officials airborne", async () => {
    server([BASE, CRUISING]);
    renderApp("/air");
    const table = await screen.findByRole("table", { name: "Tracked flights" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("XW 451");
    expect(rows[1]).toHaveTextContent("3 · TRP-8818");
    expect(rows[1]).toHaveTextContent("12,000 ft · 230 kt");
    expect(rows[1]).toHaveTextContent("Holding");
    expect(rows[2]).toHaveTextContent("CGK → AMS");
    expect(screen.getByText("Officials airborne").parentElement).toHaveTextContent("5");
    expect(screen.getByText("Disrupted flights").parentElement).toHaveTextContent("1");
    expect(screen.getByText("Simulated")).toBeInTheDocument();
  });

  it("shows a banner for a holding flight and for a diverted one", async () => {
    server([BASE]);
    const { unmount } = renderApp("/air");
    expect(await screen.findByRole("alert")).toHaveTextContent("XW 451 holding near Nairobi");
    unmount();
    vi.unstubAllGlobals();
    server([DIVERTED]);
    renderApp("/air");
    expect(await screen.findByRole("alert")).toHaveTextContent("XW 451 diverted to Mombasa");
    const table = await screen.findByRole("table", { name: "Tracked flights" });
    expect(table).toHaveTextContent("AUH → MBA");
    expect(table).toHaveTextContent("Diverted · Mombasa");
  });

  it("shows the selected flight's travellers, trip and events", async () => {
    server([BASE, CRUISING]);
    renderApp("/air");
    await userEvent.click(await screen.findByRole("button", { name: "plane XW 451" }));
    const events = await screen.findByLabelText("Flight events");
    expect(events).toHaveTextContent("Departed");
    expect(events).toHaveTextContent("Holding · Arrivals restricted");
    expect(screen.getByRole("link", { name: "TRP-8818" })).toHaveAttribute("href", "/journeys?trip=t-8818");
    expect(screen.getByText("Fictional Officer A, Fictional Officer B, Fictional Officer C")).toBeInTheDocument();
    expect(screen.getByLabelText("Agent proposals")).toHaveTextContent("Notify XW 451 travellers · holding near Nairobi");
  });

  it("states the safeguards", async () => {
    server([]);
    renderApp("/air");
    const safeguards = await screen.findByLabelText("Safeguards");
    expect(safeguards).toHaveTextContent("restricted) trips are never tracked or shown");
    expect(await screen.findByText(/^No tracked flights\./)).toBeInTheDocument();
  });
});
