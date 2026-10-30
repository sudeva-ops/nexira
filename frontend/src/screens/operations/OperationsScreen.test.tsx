import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Incident } from "../../api/intel";
import type { Weather } from "../../api/weather";
import { DETAIL, INCIDENT, MISSIONS, SIGNALS, SUMMARY } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

// jsdom has no WebGL; the stand-in renders one button per incident marker and says how
// many missions the weather layer shows.
vi.mock("../../map/OperationsMap", () => ({
  OperationsMap: ({
    incidents,
    onSelect,
    weather,
  }: {
    incidents: Incident[];
    onSelect: (i: Incident) => void;
    weather: Weather[];
  }) => (
    <div data-testid="operations-map">
      {incidents.map((i) => (
        <button key={i.id} type="button" onClick={() => onSelect(i)}>
          marker {i.reference}
        </button>
      ))}
      <span>weather layer: {weather.length}</span>
    </div>
  ),
}));

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
function wx(code: string, city: string, change: Partial<Weather> = {}): Weather {
  return {
    mission_id: `id-${code}`,
    mission_code: code,
    city,
    country_code: "XX",
    lat: 1,
    lon: 2,
    observed_at: ago(3),
    temperature_c: 24,
    condition: "CLEAR",
    wind_kph: 10,
    gust_kph: 14,
    rain_mm: 0,
    source: "xWeather (simulated)",
    stale: false,
    ...change,
  };
}
const WEATHER: Weather[] = [
  wx("BER", "Berlin", { condition: "CLOUD", temperature_c: 9 }),
  wx("MNL", "Manila", {
    condition: "STORM",
    temperature_c: 26,
    wind_kph: 110,
    gust_kph: 150,
    rain_mm: 60,
    source: "xWeather (simulated, scenario)",
  }),
  wx("MOW", "Moscow", { condition: "SNOW", temperature_c: -3, rain_mm: 1.2 }),
  wx("ROM", "Rome", { observed_at: ago(45) }), // the feed stopped for Rome: stale
];

beforeEach(() => {
  mockApi({
    "/api/me": { body: DUTY_OFFICER },
    "/api/operations/summary": { body: SUMMARY },
    "/api/missions": { body: MISSIONS },
    "/api/incidents": { body: [INCIDENT] },
    "/api/signals": { body: SIGNALS },
    [`/api/incidents/${INCIDENT.id}`]: { body: DETAIL },
    "/api/weather": { body: WEATHER },
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

  it("shows the weather at missions, worst first, simulated, with stale readings flagged (WX-02)", async () => {
    renderApp("/operations");
    const table = await screen.findByRole("table", { name: "Weather at missions" });
    const rows = within(table).getAllByRole("row");
    expect(rows.map((r) => within(r).getAllByRole("cell").at(0)?.textContent)).toEqual([
      "Manila MNL",
      "Moscow MOW",
      "Berlin BER",
      "Rome ROM",
    ]);
    expect(rows[0]).toHaveTextContent("Storm");
    expect(rows[0]).toHaveTextContent("26°C");
    expect(rows[0]).toHaveTextContent("110/150");
    expect(rows[0]).toHaveTextContent("60 mm");
    expect(rows[3]).toHaveClass("nx-stale");
    expect(rows[3]).toHaveTextContent("Stale · 45 min");
    expect(rows[0]).not.toHaveTextContent("Stale");
    expect(rows[0]).not.toHaveClass("nx-stale");
    expect(screen.getByText("xWeather (simulated)")).toBeInTheDocument(); // D-19
    expect(screen.getByText("1 severe")).toBeInTheDocument();
    expect(screen.getByText(/· 1 stale/)).toBeInTheDocument();
  });

  it("keeps the weather beside the impact panel, and the layer can be hidden", async () => {
    renderApp("/operations");
    expect(await screen.findByText("weather layer: 4")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Weather" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(toggle);
    expect(screen.getByText("weather layer: 0")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: `marker ${INCIDENT.reference}` }));
    await screen.findByLabelText("Exposure summary");
    expect(screen.getByRole("table", { name: "Weather at missions" })).toBeInTheDocument();
  });
});
