import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { defaultMission, type MissionRisk, type PredictiveOverview, shortDay } from "../../api/predictive";
import { VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const TODAY = "2026-11-09";
const day = (n: number) => new Date(Date.parse(`${TODAY}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
const MODEL = "Illustrative model · a projection, not a prediction";

const ADD = { mission_id: "m-add", mission_code: "ADD", city: "Addis Ababa" };
const NBO = { mission_id: "m-nbo", mission_code: "NBO", city: "Nairobi" };

const OVERVIEW: PredictiveOverview = {
  threshold: 70,
  model: MODEL,
  rising: [
    { ...ADD, now: 35, peak: 75, peak_day: day(5), change: 40, crosses: true },
    { ...NBO, now: 38, peak: 41, peak_day: day(9), change: 3, crosses: false },
  ],
  actions: [
    {
      mission_code: "ADD",
      text: `Review movements and venues in Addis Ababa around Rally near the industrial park (${day(5)}).`,
    },
  ],
  simulated: true,
};

function risk(base: typeof ADD, peak: number): MissionRisk {
  return {
    ...base,
    threshold: 70,
    model: MODEL,
    now: 35,
    history: [
      ...Array.from({ length: 30 }, (_, i) => ({ day: day(i - 30), value: 33 + (i % 3), source: "ILLUSTRATIVE" as const })),
      { day: TODAY, value: 35, source: "LIVE" as const },
    ],
    forecast: Array.from({ length: 14 }, (_, i) => {
      const value = i === 4 ? peak : 35;
      return { day: day(i + 1), value, low: value - 3 - i, high: value + 3 + i };
    }),
    drivers: [
      { key: "baseline", label: "Mission baseline (low)", points: 35, change: null },
      { key: "events", label: "Events calendar", points: 0, change: -5 },
    ],
    events: [
      {
        id: "e-1",
        kind: "RALLY",
        title: "Rally near the industrial park",
        place_label: "Industrial park access road",
        starts_on: day(5),
        ends_on: day(5),
        attendance: 5000,
        weight: 30,
        source: "SIMULATED",
      },
    ],
    simulated: true,
  };
}

function setup(me = DUTY_OFFICER, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/predictive/overview": { body: OVERVIEW },
    "GET /api/predictive/missions/m-add": { body: risk(ADD, 75) },
    "GET /api/predictive/missions/m-nbo": { body: { ...risk(NBO, 41), events: [] } },
    ...extra,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("Predictive Risk", () => {
  it("opens on the highest peak with the chart, drivers, calendar, rising risk and actions", async () => {
    setup();
    renderApp("/predictive");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Predictive Risk");
    expect(screen.getByRole("note")).toHaveTextContent("Model output is advisory.");
    expect(screen.getByRole("note")).toHaveTextContent(MODEL);
    const chart = await screen.findByRole("img", {
      name: "Addis Ababa risk index: 35 today, a forecast peak of 75 within 14 days, threshold 70",
    });
    for (const part of ["prd-history", "prd-forecast", "prd-band", "prd-threshold"]) {
      expect(within(chart as unknown as HTMLElement).getByTestId(part)).toBeInTheDocument();
    }
    expect(chart).toHaveTextContent("Elevated threshold · 70");
    expect(chart).toHaveTextContent("Today · 35");
    expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue("m-add");

    const drivers = screen.getByRole("table", { name: "Key drivers" });
    expect(within(drivers).getByText("Mission baseline (low)").closest("tr")).toHaveTextContent("35—");
    expect(within(drivers).getByText("Events calendar").closest("tr")).toHaveTextContent("0-5");

    expect(screen.getByLabelText("Events calendar")).toHaveTextContent(
      `${shortDay(day(5))}Rally near the industrial park · rally · Industrial park access road · about 5,000 people · weight 30`,
    );

    const rising = screen.getByRole("table", { name: "Rising risk" });
    const rows = within(rising).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent(`Addis Ababa ADD3575${shortDay(day(5))}▲ 40`);
    expect(rows[0]).toHaveClass("sel");
    expect(screen.getByLabelText("Recommended actions")).toHaveTextContent(
      "Review movements and venues in Addis Ababa around Rally near the industrial park",
    );
    expect(document.body).not.toHaveTextContent(/visit/i); // never a VIP visit (G-1)
  });

  it("switches mission from the rising-risk table, and the Viewer sees it all", async () => {
    setup(VIEWER);
    renderApp("/predictive");
    const rising = await screen.findByRole("table", { name: "Rising risk" });
    await userEvent.click(within(rising).getByText("Nairobi"));
    expect(
      await screen.findByRole("img", { name: /^Nairobi risk index: 35 today, a forecast peak of 41/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue("m-nbo");
    expect(screen.getByText("No scheduled event in the next 14 days.")).toBeInTheDocument();
  });

  it("says so when no action is recommended", async () => {
    setup(DUTY_OFFICER, { "GET /api/predictive/overview": { body: { ...OVERVIEW, actions: [] } } });
    renderApp("/predictive?mission=m-nbo");
    expect(await screen.findByText("No action recommended: every forecast stays below 70.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue("m-nbo");
  });
});

describe("predictive helpers", () => {
  it("opens on the highest peak and formats days", () => {
    expect(defaultMission(OVERVIEW.rising)).toBe("m-add");
    expect(defaultMission([])).toBeUndefined();
    expect(shortDay("2026-11-05")).toBe("05 Nov");
  });
});
