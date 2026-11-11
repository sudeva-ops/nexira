import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Annotation } from "../../api/annotations";
import type { Incident } from "../../api/intel";
import type { Weather } from "../../api/weather";
import { DETAIL, INCIDENT, MISSIONS, SIGNALS, SUMMARY, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, mockServer, renderApp } from "../../test/render";

// jsdom has no WebGL; the stand-in renders one button per incident marker and says how
// many missions the weather layer shows.
const POINTS: [number, number][] = [
  [36.8, -1.28],
  [36.81, -1.29],
  [36.82, -1.28],
];

// Annotations (ANN-01..03): it says how many it shows, offers each to pick, and stands in for
// the map's zoom, clicks and double-click.
vi.mock("../../map/OperationsMap", () => ({
  OperationsMap: ({
    incidents,
    onSelect,
    weather,
    annotations = [],
    onDrawPoint,
    onDrawFinish,
    onPickAnnotation,
    onZoom,
  }: {
    incidents: Incident[];
    onSelect: (i: Incident) => void;
    weather: Weather[];
    annotations?: Annotation[];
    onDrawPoint?: (p: [number, number]) => void;
    onDrawFinish?: () => void;
    onPickAnnotation?: (id: string) => void;
    onZoom?: (z: number) => void;
  }) => (
    <div data-testid="operations-map">
      {incidents.map((i) => (
        <button key={i.id} type="button" onClick={() => onSelect(i)}>
          marker {i.reference}
        </button>
      ))}
      <span>weather layer: {weather.length}</span>
      <span>annotations: {annotations.length}</span>
      {annotations.map((a) => (
        <button key={a.id} type="button" onClick={() => onPickAnnotation?.(a.id)}>
          annotation {a.label}
        </button>
      ))}
      <button type="button" onClick={() => onZoom?.(8)}>
        zoom to city
      </button>
      {POINTS.map((p, n) => (
        <button key={n} type="button" onClick={() => onDrawPoint?.(p)}>
          map point {n}
        </button>
      ))}
      <button type="button" onClick={() => onDrawFinish?.()}>
        map double-click
      </button>
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

const CHECKPOINT: Annotation = {
  id: "ann-1",
  kind: "MARK",
  symbol: "CHECKPOINT",
  shape: { type: "Point", coordinates: [36.817, -1.283] },
  label: "Checkpoint · Uhuru Highway",
  note: "Police and army",
  incident_id: INCIDENT.id,
  incident_reference: INCIDENT.reference,
  mission_code: "NBO",
  ends_at: null,
  status: "ACTIVE",
  reason: null,
  role: "Duty Officer",
  created_at: "2026-11-11T09:02:00Z",
  updated_at: null,
  can_edit: true,
};

function server(me = DUTY_OFFICER, canAdd = true, annotations: Annotation[] = [CHECKPOINT]) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/operations/summary": { body: SUMMARY },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/incidents": { body: [INCIDENT] },
    "GET /api/signals": { body: SIGNALS },
    "GET /api/weather": { body: WEATHER },
    "GET /api/annotations": { body: { annotations, can_add: canAdd } },
    "POST /api/annotations": { status: 201, body: CHECKPOINT },
    [`POST /api/annotations/${CHECKPOINT.id}/withdraw`]: { body: { ...CHECKPOINT, status: "WITHDRAWN" } },
  });
}

function sent(fetchMock: ReturnType<typeof server>, method: string, path: string): unknown {
  const call = fetchMock.mock.calls.find(([url, init]) => String(url) === path && init?.method === method);
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
}

describe("Map annotations (ANN-01..04)", () => {
  it("shows them to every role; the Viewer has no tools and no Edit", async () => {
    server(VIEWER, false, [{ ...CHECKPOINT, can_edit: false }]); // as the API answers the Viewer
    renderApp("/operations");
    expect(await screen.findByText("annotations: 1")).toBeInTheDocument();
    expect(screen.queryByRole("toolbar", { name: "Annotate" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: `annotation ${CHECKPOINT.label}` }));
    const card = screen.getByRole("dialog", { name: `Annotation: ${CHECKPOINT.label}` });
    expect(card).toHaveTextContent("Checkpoint");
    expect(card).toHaveTextContent("Police and army");
    expect(card).toHaveTextContent(`Duty Officer · `);
    expect(card).toHaveTextContent(INCIDENT.reference);
    expect(within(card).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Withdraw" })).toBeNull();
    const layer = screen.getByRole("button", { name: "Annotations" });
    await userEvent.click(layer);
    expect(screen.getByText("annotations: 0")).toBeInTheDocument();
    expect(layer).toHaveAttribute("aria-pressed", "false");
  });

  it("draws only from city zoom; a mark is placed with one click and saved from the form", async () => {
    const fetchMock = server();
    renderApp("/operations");
    const tools = await screen.findByRole("toolbar", { name: "Annotate" });
    expect(within(tools).getByText("Zoom in to draw")).toBeInTheDocument();
    expect(within(tools).getByRole("button", { name: "Mark" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "zoom to city" }));
    await userEvent.click(within(tools).getByRole("button", { name: "Mark" }));
    expect(tools).toHaveTextContent("Click the map to place the mark.");
    await userEvent.click(screen.getByRole("button", { name: "map point 1" }));
    const form = await screen.findByRole("dialog", { name: "New mark" });
    await userEvent.selectOptions(within(form).getByLabelText("Symbol"), "RALLY_POINT");
    await userEvent.type(within(form).getByLabelText("Label"), "Rally point · Embassy car park");
    await userEvent.selectOptions(within(form).getByLabelText("Incident"), INCIDENT.id);
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    await vi.waitFor(() => expect(sent(fetchMock, "POST", "/api/annotations")).toBeDefined());
    expect(sent(fetchMock, "POST", "/api/annotations")).toEqual({
      kind: "MARK",
      symbol: "RALLY_POINT",
      shape: { type: "Point", coordinates: [36.81, -1.29] },
      label: "Rally point · Embassy car park",
      note: null,
      incident_id: INCIDENT.id,
      ends_at: null,
    });
    await vi.waitFor(() => expect(screen.queryByRole("dialog", { name: "New mark" })).toBeNull());
  });

  it("draws an area point by point, finishing on double-click; Escape cancels", async () => {
    const fetchMock = server();
    renderApp("/operations");
    const tools = await screen.findByRole("toolbar", { name: "Annotate" });
    await userEvent.click(screen.getByRole("button", { name: "zoom to city" }));
    await userEvent.click(within(tools).getByRole("button", { name: "Line" }));
    await userEvent.click(screen.getByRole("button", { name: "map point 0" }));
    await userEvent.keyboard("{Escape}");
    expect(within(tools).getByRole("button", { name: "Line" })).toBeEnabled();
    await userEvent.click(within(tools).getByRole("button", { name: "Area" }));
    await userEvent.click(screen.getByRole("button", { name: "map point 0" }));
    await userEvent.click(screen.getByRole("button", { name: "map point 1" }));
    expect(tools).toHaveTextContent("1 more needed");
    expect(within(tools).getByRole("button", { name: "Finish" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "map point 2" }));
    await userEvent.click(screen.getByRole("button", { name: "map double-click" }));
    const form = await screen.findByRole("dialog", { name: "New area" });
    expect(within(form).queryByLabelText("Symbol")).toBeNull();
    await userEvent.type(within(form).getByLabelText("Label"), "Avoid: crowd");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    await vi.waitFor(() => expect(sent(fetchMock, "POST", "/api/annotations")).toBeDefined());
    expect(sent(fetchMock, "POST", "/api/annotations")).toMatchObject({
      kind: "AREA",
      symbol: null,
      shape: {
        type: "Polygon",
        coordinates: [
          [
            [36.8, -1.28],
            [36.81, -1.29],
            [36.82, -1.28],
            [36.8, -1.28],
          ],
        ],
      },
    });
  });

  it("withdraws a picked annotation with a reason", async () => {
    const fetchMock = server();
    renderApp("/operations");
    await userEvent.click(await screen.findByRole("button", { name: `annotation ${CHECKPOINT.label}` }));
    const card = screen.getByRole("dialog", { name: `Annotation: ${CHECKPOINT.label}` });
    await userEvent.click(within(card).getByRole("button", { name: "Withdraw" }));
    const confirm = within(card).getByRole("button", { name: "Withdraw" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(card).getByLabelText("Reason"), "Cleared by police");
    await userEvent.click(confirm);
    await vi.waitFor(() =>
      expect(sent(fetchMock, "POST", `/api/annotations/${CHECKPOINT.id}/withdraw`)).toEqual({
        reason: "Cleared by police",
      }),
    );
  });
});
