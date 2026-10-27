import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import type { TripDetail, TripPermissions } from "../../api/trips";
import { formatDays, homeInputToIso, isoToHomeInput } from "../../app/time";
import { MISSIONS, PEOPLE } from "../../test/fixtures";
import { DUTY_OFFICER, type Reply, mockServer, renderApp } from "../../test/render";

const TRAVEL_DESK: Me = {
  id: "u-desk",
  display_name: "Tomas Varga",
  email: "travel.desk@demo.nexira.invalid",
  roles: [{ code: "TRAVEL_DESK", mission_id: null, mission_code: null }],
};
const SECURITY: Me = {
  ...TRAVEL_DESK,
  id: "u-sec",
  roles: [{ code: "SECURITY_OFFICER", mission_id: null, mission_code: null }],
};

const PENDING: TripDetail = {
  id: "t-1",
  reference: "TRP-8814",
  purpose: "Security assessment",
  origin: "Amman",
  destination: "Baghdad",
  destination_country: "IQ",
  starts_on: "2026-10-31",
  ends_on: "2026-11-03",
  approval_status: "PENDING",
  restricted: false,
  risk_level: "HIGH",
  live_risk: "HIGH",
  risk_changed: false,
  mission_id: "m-bgw",
  requested_by: null,
  requested_by_name: null,
  submitted_at: "2026-10-26T06:00:00Z",
  approved_by: null,
  approved_by_name: null,
  approved_at: null,
  approved_risk_level: null,
  rejection_reason: null,
  checklist: {
    security_briefing: true,
    insurance_medical: false,
    emergency_contacts: false,
    checkin_schedule: false,
    security_approval: false,
  },
  travellers_count: 2,
  impacted_by: [],
  created_at: "2026-10-26T06:00:00Z",
  travellers: [
    { id: "p-1", full_name: "Fictional Diplomat A", person_type: "DIPLOMAT" },
    { id: "p-2", full_name: "Fictional Diplomat B", person_type: "DIPLOMAT" },
  ],
  segments: [
    {
      seq: 1,
      kind: "FLIGHT",
      title: "RJ 810",
      place_label: "Amman → Baghdad",
      starts_at: "2026-10-31T05:00:00Z",
      ends_at: "2026-10-31T06:30:00Z",
      flight_number: "RJ 810",
      from_airport: "AMM",
      to_airport: "BGW",
      flight_id: null,
      flight_status: null,
    },
  ],
  country_risk: {
    country_code: "IQ",
    level: "HIGH",
    base_level: "HIGH",
    rated: true,
    security: 78,
    unrest: 60,
    health: 35,
    transport: 62,
    source: "Riskline (simulated)",
    incident_level: null,
    incidents: [],
    simulated: true,
  },
};
const IMPACTED: TripDetail = {
  ...PENDING,
  id: "t-2",
  reference: "TRP-8812",
  purpose: "Trade delegation (3)",
  destination: "Nairobi",
  destination_country: "KE",
  approval_status: "APPROVED",
  risk_level: "MODERATE",
  live_risk: "CRITICAL",
  risk_changed: true,
  approved_risk_level: "MODERATE",
  approved_at: "2026-10-19T06:00:00Z",
  impacted_by: ["INC-2026-1042"],
};
const NONE: TripPermissions = {
  edit_trip: false,
  submit_trip: false,
  approve_trip: false,
  reject_trip: false,
  check_trip: false,
  cancel_trip: false,
};

function server(me: Me, permissions: TripPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/trips": { body: [PENDING, IMPACTED] },
    "GET /api/trips/t-1": { body: PENDING },
    "GET /api/trips/t-2": { body: IMPACTED },
    "GET /api/me/permissions": { body: permissions },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/people": { body: PEOPLE },
    "GET /api/airports": {
      body: [
        { iata: "AUH", name: "Abu Dhabi", city: "Abu Dhabi", country_code: "AE" },
        { iata: "NBO", name: "Nairobi", city: "Nairobi", country_code: "KE" },
      ],
    },
    ...extra,
  });
}

function posted(fetchMock: ReturnType<typeof mockServer>, path: string, method = "POST"): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === method)
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

afterEach(() => vi.unstubAllGlobals());

describe("Journey Management", () => {
  it("lists trips with risk, approval and the impacted status", async () => {
    server(SECURITY, NONE);
    renderApp("/journeys");
    const table = await screen.findByRole("table", { name: "Trips" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("TRP-8814");
    expect(rows[1]).toHaveTextContent("Amman → Baghdad");
    expect(rows[1]).toHaveTextContent("31 Oct–3 Nov");
    expect(rows[1]).toHaveTextContent("Pending");
    expect(rows[2]).toHaveTextContent("Impacted · INC-2026-1042");
    expect(screen.getByRole("alert")).toHaveTextContent("TRP-8812 impacted by INC-2026-1042");
  });

  it("filters through the API", async () => {
    const fetchMock = server(SECURITY, NONE);
    renderApp("/journeys");
    await screen.findByRole("table", { name: "Trips" });
    await userEvent.selectOptions(screen.getByLabelText("Filter by impact"), "true");
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("impacted=true"))).toBe(true),
    );
  });

  it("shows the itinerary, travellers and the simulated risk breakdown", async () => {
    server(SECURITY, NONE);
    renderApp("/journeys?trip=t-1");
    expect(await screen.findByLabelText("Itinerary")).toHaveTextContent("Flight · RJ 810");
    expect(screen.getByLabelText("Travellers")).toHaveTextContent("Fictional Diplomat B");
    const risk = screen.getByLabelText("Destination risk");
    expect(risk).toHaveTextContent("Security78");
    expect(screen.getByText("Riskline (simulated)")).toBeInTheDocument();
  });

  it("flags a risk that rose since approval", async () => {
    server(SECURITY, NONE);
    renderApp("/journeys?trip=t-2");
    expect(await screen.findByText(/Risk now CRITICAL \(approved at MODERATE\)/)).toBeInTheDocument();
  });

  it("lets only those allowed tick the checklist", async () => {
    server(SECURITY, NONE);
    renderApp("/journeys?trip=t-1");
    const list = await screen.findByRole("group", { name: "Pre-travel checklist" });
    for (const box of within(list).getAllByRole("checkbox")) expect(box).toBeDisabled();
  });

  it("ticks a checklist item through the API", async () => {
    const fetchMock = server(SECURITY, { ...NONE, check_trip: true }, {
      "POST /api/trips/t-1/checklist": { body: PENDING },
    });
    renderApp("/journeys?trip=t-1");
    const box = await screen.findByRole("checkbox", { name: "Travel insurance & medical cover" });
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.click(box);
    await waitFor(() =>
      expect(posted(fetchMock, "/api/trips/t-1/checklist")).toEqual([{ item: "insurance_medical", done: true }]),
    );
    // Security approval is set by the approval, never ticked.
    expect(screen.getByRole("checkbox", { name: "Security approval" })).toBeDisabled();
  });

  it("shows no decision buttons to someone who may not decide", async () => {
    server(TRAVEL_DESK, { ...NONE, check_trip: true });
    renderApp("/journeys?trip=t-1");
    await screen.findByText("TRP-8814 · Awaiting approval");
    for (const name of ["Approve trip", "Reject", "Submit for approval", "Edit", "Cancel trip"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("explains the checklist when only rejecting is allowed", async () => {
    server(SECURITY, { ...NONE, reject_trip: true, check_trip: true });
    renderApp("/journeys?trip=t-1");
    await screen.findByRole("button", { name: "Reject" });
    expect(screen.queryByRole("button", { name: "Approve trip" })).toBeNull();
    expect(screen.getByText(/need all four ticked before approval/)).toBeInTheDocument();
  });

  it("approves and rejects with a reason through the API", async () => {
    const fetchMock = server(SECURITY, { ...NONE, approve_trip: true, reject_trip: true }, {
      "POST /api/trips/t-1/approve": { body: { ...PENDING, approval_status: "APPROVED" } },
      "POST /api/trips/t-1/reject": { body: { ...PENDING, approval_status: "DRAFT" } },
    });
    renderApp("/journeys?trip=t-1");
    await userEvent.click(await screen.findByRole("button", { name: "Approve trip" }));
    await waitFor(() => expect(posted(fetchMock, "/api/trips/t-1/approve")).toHaveLength(1));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const sendBack = screen.getByRole("button", { name: "Send back" });
    expect(sendBack).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason for rejecting"), "Postpone");
    await userEvent.click(sendBack);
    await waitFor(() => expect(posted(fetchMock, "/api/trips/t-1/reject")).toEqual([{ reason: "Postpone" }]));
  });

  it("hides planning from those who cannot plan", async () => {
    server(SECURITY, NONE);
    renderApp("/journeys");
    await screen.findByRole("table", { name: "Trips" });
    expect(screen.queryByRole("button", { name: "Plan a trip" })).toBeNull();
  });

  it("plans a draft with travellers and an itinerary in the home zone", async () => {
    const created: TripDetail = { ...PENDING, id: "t-new", approval_status: "DRAFT" };
    const fetchMock = server(DUTY_OFFICER, NONE, {
      "POST /api/trips": { status: 201, body: created },
      "GET /api/trips/t-new": { body: created },
    });
    renderApp("/journeys");
    await userEvent.click(await screen.findByRole("button", { name: "Plan a trip" }));
    const save = screen.getByRole("button", { name: "Save draft" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Purpose"), "Consultations");
    await userEvent.type(screen.getByLabelText("To (city)"), "Paris");
    await userEvent.type(screen.getByLabelText("Country (ISO, e.g. FR)"), "fr");
    await userEvent.type(screen.getByLabelText("Starts"), "2026-11-02");
    await userEvent.type(screen.getByLabelText("Ends"), "2026-11-04");
    await userEvent.type(screen.getByLabelText("Travellers"), "Peter");
    const person = PEOPLE.items[0];
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(`\\+ ${person?.full_name ?? ""}`) }));
    await userEvent.click(screen.getByRole("button", { name: "Add segment" }));
    const segment = screen.getByRole("group", { name: "Segment 1" });
    await userEvent.type(within(segment).getByLabelText("Title"), "AF 655");
    expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(() => expect(posted(fetchMock, "/api/trips")).toHaveLength(1));
    expect(posted(fetchMock, "/api/trips")[0]).toEqual({
      purpose: "Consultations",
      origin: "HQ",
      destination: "Paris",
      destination_country: "FR",
      starts_on: "2026-11-02",
      ends_on: "2026-11-04",
      travellers: [person?.id],
      segments: [
        {
          kind: "FLIGHT",
          title: "AF 655",
          place_label: null,
          starts_at: "2026-11-02T05:00:00.000Z", // 09:00 GST
          ends_at: "2026-11-02T08:00:00.000Z",
          flight_number: null,
          from_airport: null,
          to_airport: null,
        },
      ],
      restricted: false,
    });
  });
});

describe("planning a tracked flight (Prompt 31; D-33)", () => {
  it("needs the flight number and both airports together, and sends the restricted switch", async () => {
    const created: TripDetail = { ...PENDING, id: "t-new", approval_status: "DRAFT" };
    const fetchMock = server(DUTY_OFFICER, NONE, {
      "POST /api/trips": { status: 201, body: created },
      "GET /api/trips/t-new": { body: created },
    });
    renderApp("/journeys");
    await userEvent.click(await screen.findByRole("button", { name: "Plan a trip" }));
    await userEvent.type(screen.getByLabelText("To (city)"), "Nairobi");
    await userEvent.type(screen.getByLabelText("Country (ISO, e.g. FR)"), "KE");
    await userEvent.type(screen.getByLabelText("Starts"), "2026-11-02");
    await userEvent.type(screen.getByLabelText("Ends"), "2026-11-04");
    await userEvent.type(screen.getByLabelText("Travellers"), "Peter");
    await userEvent.click(await screen.findByRole("button", { name: /\+ Peter Mwangi/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add segment" }));
    const segment = screen.getByRole("group", { name: "Segment 1" });
    await userEvent.type(within(segment).getByLabelText("Title"), "XW 451");
    await userEvent.type(within(segment).getByLabelText("Flight number"), "xw 451");
    const save = screen.getByRole("button", { name: "Save draft" });
    expect(save).toBeDisabled(); // a number without airports
    await within(segment).findAllByRole("option", { name: "AUH · Abu Dhabi" });
    await userEvent.selectOptions(within(segment).getByLabelText("From airport"), "AUH");
    await userEvent.selectOptions(within(segment).getByLabelText("To airport"), "NBO");
    await userEvent.click(screen.getByRole("checkbox", { name: /Restricted \(VIP or ministerial\)/ }));
    expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(() => expect(posted(fetchMock, "/api/trips")).toHaveLength(1));
    expect(posted(fetchMock, "/api/trips")[0]).toMatchObject({
      restricted: true,
      segments: [{ kind: "FLIGHT", flight_number: "XW 451", from_airport: "AUH", to_airport: "NBO" }],
    });
  });

  it("links a tracked flight segment to the air view", async () => {
    const tracked: TripDetail = {
      ...IMPACTED,
      segments: PENDING.segments.map((seg) => ({ ...seg, flight_id: "f-1", flight_status: "HOLDING" })),
    };
    server(SECURITY, NONE, { "GET /api/trips/t-2": { body: tracked } });
    renderApp("/journeys?trip=t-2");
    expect(await screen.findByRole("link", { name: "HOLDING" })).toHaveAttribute("href", "/air?flight=f-1");
  });
});

describe("editing a restricted draft (review of Prompt 30, M1)", () => {
  it("sends the restricted flag and the flight fields back unchanged", async () => {
    const draft: TripDetail = { ...PENDING, approval_status: "DRAFT", restricted: true };
    const fetchMock = server(DUTY_OFFICER, { ...NONE, edit_trip: true }, {
      "GET /api/trips/t-1": { body: draft },
      "PATCH /api/trips/t-1": { body: draft },
    });
    renderApp("/journeys?trip=t-1");
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(posted(fetchMock, "/api/trips/t-1", "PATCH")).toHaveLength(1));
    expect(posted(fetchMock, "/api/trips/t-1", "PATCH")[0]).toMatchObject({
      restricted: true,
      segments: [{ flight_number: "RJ 810", from_airport: "AMM", to_airport: "BGW" }],
    });
  });
});

describe("home-zone dates (plan G-8)", () => {
  it("converts datetime-local input in GST both ways", () => {
    expect(homeInputToIso("2026-10-31T09:30", "Asia/Dubai")).toBe("2026-10-31T05:30:00.000Z");
    expect(isoToHomeInput("2026-10-31T05:30:00Z", "Asia/Dubai")).toBe("2026-10-31T09:30");
    expect(homeInputToIso("2026-10-31T00:30", "Asia/Dubai")).toBe("2026-10-30T20:30:00.000Z");
  });

  it("formats day ranges", () => {
    expect(formatDays("2026-10-18", "2026-10-22")).toBe("18–22 Oct");
    expect(formatDays("2026-10-31", "2026-11-03")).toBe("31 Oct–3 Nov");
    expect(formatDays("2026-10-21", "2026-10-21")).toBe("21 Oct");
  });
});
