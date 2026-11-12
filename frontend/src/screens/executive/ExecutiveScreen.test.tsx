import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Overview } from "../../api/executive";
import { duration, readinessDetail } from "../../api/executive";
import { VIEWER } from "../../test/fixtures";
import {
  DUTY_OFFICER,
  mockServer,
  type Reply,
  renderApp,
} from "../../test/render";

const NOW = new Date().toISOString();
const INC = {
  id: "i-1042",
  reference: "INC-2026-1042",
  title: "Civil unrest",
  severity: "CRITICAL",
};
const day = (n: number) =>
  new Date(Date.now() - (29 - n) * 86_400_000).toISOString().slice(0, 10);

const OVERVIEW: Overview = {
  posture: { level: "SEVERE", critical_missions: 1, elevated_missions: 4 },
  active_incidents: 1,
  latest_incident: INC,
  detection: {
    median_s: 175,
    incidents: 3,
    current_s: 161,
    current_reference: INC.reference,
  },
  accounted: {
    pct: 94,
    answered: 16,
    asked: 17,
    incident_references: [INC.reference],
  },
  readiness: { mean: 84, sites: 36 },
  // GFX-05: 20 illustrative days, then live ones (quiet until today).
  trend: Array.from({ length: 30 }, (_, n) => ({
    day: day(n),
    signals: n < 20 ? 12 : n === 29 ? 4 : 0,
    incidents: n < 20 ? n % 3 : n === 29 ? 1 : 0,
    source: n < 20 ? ("ILLUSTRATIVE" as const) : ("LIVE" as const),
  })),
  regions: [
    { region: "Africa", exposure: 38, missions: 6 },
    { region: "Europe", exposure: 20, missions: 9 },
  ],
  attention: [
    {
      mission_id: "m-nbo",
      mission_code: "NBO",
      city: "Nairobi",
      risk: "CRITICAL",
      personnel: 17,
      readiness: 79,
      drivers: [
        {
          kind: "INCIDENT",
          label: "Civil unrest (critical)",
          reference: INC.reference,
        },
        {
          kind: "SHELTER",
          label: "Shelter-in-place",
          reference: INC.reference,
        },
        { kind: "FLEET", label: "1 vehicle unavailable", reference: null },
      ],
    },
    {
      mission_id: "m-isb",
      mission_code: "ISB",
      city: "Islamabad",
      risk: "MODERATE",
      personnel: 26,
      readiness: 84,
      drivers: [],
    },
  ],
  timeline: {
    incident: INC,
    events: [
      {
        occurred_at: NOW,
        event_type: "PLAYBOOK_STEP",
        summary: "PB-07 step 4 done: Issue shelter-in-place advisory.",
      },
      {
        occurred_at: NOW,
        event_type: "CHECKIN",
        summary: "Check-in: a person needs help.",
      },
    ],
    recent: [],
  },
  generated_at: NOW,
  simulated: true,
};
const CALM: Overview = {
  ...OVERVIEW,
  posture: { level: "GUARDED", critical_missions: 0, elevated_missions: 4 },
  active_incidents: 0,
  latest_incident: null,
  detection: {
    median_s: null,
    incidents: 0,
    current_s: null,
    current_reference: null,
  },
  accounted: { pct: null, answered: 0, asked: 0, incident_references: [] },
  attention: [],
  timeline: {
    incident: null,
    events: [],
    recent: [
      {
        reference: "INC-2026-1037",
        title: "Flooding",
        change: "CLOSED",
        at: NOW,
      },
    ],
  },
};

function setup(me = DUTY_OFFICER, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/executive/overview": { body: OVERVIEW },
    "POST /api/executive/export": { body: OVERVIEW },
    ...extra,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("Executive Overview", () => {
  it("shows the five figures, the trend, the regions, the missions and the timeline", async () => {
    setup();
    renderApp("/executive");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "Executive Overview",
    );
    expect(await screen.findByText("SEVERE")).toBeInTheDocument();
    expect(
      screen.getByText("1 critical · 4 elevated missions"),
    ).toBeInTheDocument();
    expect(screen.getByText("2m 41s")).toBeInTheDocument(); // the current incident's own time
    expect(
      screen.getByText("INC-2026-1042 · median 2m 55s (3)"),
    ).toBeInTheDocument();
    expect(screen.getByText("94%")).toBeInTheDocument();
    expect(screen.getByText("16 of 17 · INC-2026-1042")).toBeInTheDocument();
    expect(screen.getByText("84/100")).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Last 30 days: 1 incidents from 4 signals; the first 20 days illustrative",
      }),
    ).toBeInTheDocument();
    // GFX-05: the totals are live only, and the illustrative days are said to be so.
    expect(
      screen.getByText(/1 incidents · 4 signals live \(simulated feeds\) · first 20 days illustrative/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/\(illustrative\)$/)).toHaveLength(20);
    // GFX-07: the Active incidents tile has its sparkline.
    expect(screen.getByRole("img", { name: "Incidents opened per day, last 30 days" })).toBeInTheDocument();
    const regions = screen.getByLabelText("Risk exposure by region");
    expect(regions).toHaveTextContent("Africa38");
    const table = screen.getByRole("table", {
      name: "Missions requiring attention",
    });
    const nairobi = within(table)
      .getByText("Nairobi")
      .closest("tr") as HTMLElement;
    expect(nairobi).toHaveTextContent("CRITICAL");
    expect(nairobi).toHaveTextContent(
      "INC-2026-1042 · Civil unrest (critical)",
    );
    expect(nairobi).toHaveTextContent("Shelter-in-place");
    expect(nairobi).toHaveTextContent("1 vehicle unavailable");
    expect(
      within(table).getByText("Islamabad").closest("tr"),
    ).toHaveTextContent("Elevated mission risk");
    expect(
      screen.getByText("INC-2026-1042 · response timeline"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Response timeline")).toHaveTextContent(
      "Check-in: a person needs help.",
    );
  });

  it("shows the calm state: no check-in, recent activity, no mission", async () => {
    setup(VIEWER, { "GET /api/executive/overview": { body: CALM } });
    renderApp("/executive");
    expect(await screen.findByText("GUARDED")).toBeInTheDocument();
    expect(screen.getByText("No active check-in")).toBeInTheDocument();
    expect(screen.getByText("No notification in 30 days")).toBeInTheDocument();
    expect(
      screen.getByText("No mission requires attention."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Recent activity")).toHaveTextContent(
      "INC-2026-1037 closed · Flooding",
    );
  });

  it("opens the print-ready briefing, an audited export with no shell (EXE-03)", async () => {
    const fetchMock = setup(VIEWER);
    renderApp("/executive");
    await userEvent.click(
      await screen.findByRole("button", { name: "Export briefing" }),
    );
    const briefing = await screen.findByTestId("briefing");
    expect(
      within(briefing).getByRole("heading", { level: 1 }),
    ).toHaveTextContent("Leadership briefing");
    expect(briefing).toHaveTextContent("Simulated data");
    expect(
      within(briefing).getByLabelText("Headline figures"),
    ).toHaveTextContent("SEVERE");
    expect(
      within(briefing).getByRole("table", { name: "Briefing missions" }),
    ).toHaveTextContent(
      "NairobiCRITICALINC-2026-1042 · Civil unrest (critical); Shelter-in-place; 1 vehicle unavailable",
    );
    expect(screen.queryByRole("navigation")).toBeNull(); // no shell around it
    const exports = fetchMock.mock.calls.filter(
      ([url, init]) =>
        String(url) === "/api/executive/export" && init?.method === "POST",
    );
    expect(exports).toHaveLength(1);
    expect(
      within(briefing).getByRole("button", { name: "Print / save as PDF" }),
    ).toBeInTheDocument();
  });
});

describe("executive helpers", () => {
  it("says where readiness comes from (EXR-07)", () => {
    expect(readinessDetail({})).toBe("Mean embassy score · seeded values");
    expect(readinessDetail({ from_exercises: 36, illustrative: 35 })).toBe(
      "Mean embassy score · from exercises · 35 illustrative",
    );
    expect(readinessDetail({ from_exercises: 36, illustrative: 0 })).toBe("Mean embassy score · from exercises");
  });

  it("formats durations", () => {
    expect([
      duration(null),
      duration(45),
      duration(161),
      duration(3900),
    ]).toEqual(["—", "45s", "2m 41s", "1h 05m"]);
  });
});
