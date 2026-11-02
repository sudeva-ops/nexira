import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import type { Change, Segment, VipPermissions, Visit } from "../../api/vip";
import { localToIso, segmentTime, visitDates } from "../../api/vip";
import { VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const SECURITY: Me = {
  id: "u-sec",
  display_name: "Security Officer",
  email: "security.officer@demo.nexira.invalid",
  roles: [{ code: "SECURITY_OFFICER", mission_id: null, mission_code: null }],
};
const INC = "INC-2026-1043";

const segment = (seq: number, change: Partial<Segment>): Segment => ({
  id: `s-${seq}`,
  seq,
  kind: "MEETING",
  title: `Segment ${seq}`,
  venue_name: `Venue ${seq}`,
  starts_at: "2026-10-24T08:00:00Z",
  ends_at: null,
  attendees: null,
  virtual: false,
  status: "PLANNED",
  risk: "LOW",
  reasons: [],
  recommendation: null,
  pending_change: null,
  ...change,
});
const SEGMENTS: Segment[] = [
  segment(1, { kind: "ARRIVAL", title: "Arrival · Bole Intl. Airport (VIP terminal)", starts_at: "2026-10-24T06:30:00Z" }),
  segment(2, {
    kind: "MOTORCADE",
    title: "Motorcade · Airport → Hotel",
    starts_at: "2026-10-24T06:50:00Z",
    ends_at: "2026-10-24T07:04:00Z",
    risk: "MODERATE",
    reasons: [{ level: "MODERATE", text: "exposed movement", incident_id: null, incident_reference: null }],
  }),
  segment(3, { title: "Bilateral meeting · Ministry of Foreign Affairs" }),
  segment(4, {
    kind: "EVENT",
    title: "Business forum · Conference centre",
    starts_at: "2026-10-24T11:00:00Z",
    attendees: 600,
    risk: "MODERATE",
    reasons: [{ level: "MODERATE", text: "600 attendees", incident_id: null, incident_reference: null }],
  }),
  segment(5, {
    kind: "SITE_VISIT",
    title: "Site visit · Industrial park",
    starts_at: "2026-10-25T07:00:00Z",
    ends_at: "2026-10-25T09:00:00Z",
  }),
  segment(6, { kind: "DEPARTURE", title: "Departure", starts_at: "2026-10-26T13:00:00Z" }),
];
const HIGH_SITE: Partial<Segment> = {
  risk: "HIGH",
  reasons: [{ level: "HIGH", text: `civil unrest 1.2 km away · ${INC}`, incident_id: "i-1043", incident_reference: INC }],
  recommendation: "Move it out of the window, or replace it with a virtual alternative",
};

function visit(change: Partial<Visit> = {}, segments: Segment[] = SEGMENTS): Visit {
  return {
    id: "v-31",
    reference: "VV-2026-031",
    title: "Minister's visit to Addis Ababa",
    mission_id: "m-add",
    mission_code: "ADD",
    starts_on: "2026-10-24",
    ends_on: "2026-10-26",
    status: "PLANNED",
    risk: "MODERATE",
    simulated: true,
    principal_role: "Minister of Foreign Affairs",
    trip_id: "t-8834",
    trip_reference: "TRP-8834",
    country_risk: "MODERATE",
    started_at: null,
    cancelled_at: null,
    cancel_reason: null,
    segments,
    changes: [],
    detail: {
      team_lead: "Close-protection lead (sample)",
      advance_team: "3 officers",
      team_size: 8,
      medic: true,
      vehicles: [
        { code: "VH-11", type_label: "Armoured SUV (B6)", armoured: true, state: "AVAILABLE", available: true },
        { code: "VH-12", type_label: "Armoured SUV (B6)", armoured: true, state: "AVAILABLE", available: true },
      ],
      medical: { facility_name: "Sample Hospital A", facility_distance_m: 1200, partner_name: "Kestrel Medical (simulated)" },
      safe_havens: ["Embassy", "Hotel safe floor", "Sample Hospital A"],
    },
    checklist: [
      { id: "c-1", label: "Threat assessment issued", due_on: "2026-10-17", done: true, done_at: "x", done_by_name: "Security Officer", overdue: false },
      { id: "c-4", label: "Industrial park venue survey", due_on: "2026-10-23", done: false, done_at: null, done_by_name: null, overdue: false },
    ],
    kpis: { segments: 6, high: 0, team_size: 8, vehicles: 2, medics: 1, venues: 5, venues_surveyed: 4 },
    source: "Illustrative visit (simulated)",
    ...change,
  };
}

const NONE: VipPermissions = {
  start_visit: false,
  progress_visit: false,
  cancel_visit: false,
  tick_vip_checklist: false,
  propose_vip_change: [],
  decide_vip_change: [],
};

function setup(me: Me, shown: Visit, permissions: VipPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/vip/access": { body: { visible: true } },
    "GET /api/vip/visits": { body: [shown] },
    "GET /api/vip/visits/v-31": { body: shown },
    "GET /api/me/permissions": { body: permissions },
    ...extra,
  });
}

function sent(fetchMock: ReturnType<typeof mockServer>, method: string, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === method)
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

async function row(seq: number): Promise<HTMLElement> {
  const table = await screen.findByRole("table", { name: "Programme" });
  return await waitFor(() => {
    const found = table.querySelector(`tr[data-seq="${seq}"]`);
    if (!found) throw new Error(`no segment ${seq}`);
    return found as HTMLElement;
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("VIP Protection", () => {
  it("shows the banner, the KPIs from data and the programme with its risks (VIP-02, VIP-07)", async () => {
    setup(SECURITY, visit(), NONE);
    renderApp("/vip");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("VIP Protection");
    const banner = await screen.findByTestId("vip-banner");
    expect(banner).toHaveTextContent("Visit VV-2026-031 · Minister's visit to Addis Ababa · 24–26 Oct.");
    expect(banner).toHaveTextContent("Linked to trip TRP-8834");
    expect(screen.getByText("0 rated High")).toBeInTheDocument();
    expect(screen.getByText("2 vehicles · 1 medic")).toBeInTheDocument();
    expect(screen.getByText("4 / 5")).toBeInTheDocument();
    expect(screen.getByText("Industrial park pending")).toBeInTheDocument();
    expect(await row(1)).toHaveTextContent("24 Oct 09:30");
    expect(await row(2)).toHaveTextContent("09:50 · 14 min");
    expect(await row(2)).toHaveTextContent("MODERATEexposed movement");
    expect(await row(4)).toHaveTextContent("14:00 · 600 attendees");
    expect(await row(5)).toHaveTextContent("25 Oct 10:00");
    expect(await row(5)).toHaveTextContent("LOW");
    expect(screen.queryByTestId("vip-recommendation")).toBeNull();
    const detail = screen.getByRole("table", { name: "Protection detail" });
    expect(detail).toHaveTextContent("VH-11 (armoured) · available · VH-12 (armoured) · available");
    expect(detail).toHaveTextContent("Medic with the team · Sample Hospital A · Kestrel Medical (simulated) standby");
    expect(detail).toHaveTextContent("Embassy · Hotel safe floor · Sample Hospital A");
    // No button without permissions.
    expect(screen.queryByRole("button", { name: /Start visit|Mark done|Propose change|Start segment/ })).toBeNull();
  });

  it("flags a HIGH segment with its incident and the recommendation (VIP-02)", async () => {
    const high = SEGMENTS.map((s) => (s.seq === 5 ? { ...s, ...HIGH_SITE } : s));
    setup(SECURITY, visit({ risk: "HIGH", kpis: { ...visit().kpis, high: 1 } }, high), NONE);
    renderApp("/vip");
    const site = await row(5);
    expect(site).toHaveTextContent(`HIGHcivil unrest 1.2 km away · ${INC}`);
    expect(within(site).getByRole("link", { name: `civil unrest 1.2 km away · ${INC}` })).toHaveAttribute(
      "href",
      "/incidents?id=i-1043",
    );
    const flag = await screen.findByTestId("vip-recommendation");
    expect(flag).toHaveTextContent(
      `Site visit · Industrial park flagged High. civil unrest 1.2 km away · ${INC}. Recommendation: move it out of the window, or replace it with a virtual alternative.`,
    );
    expect(screen.getByText("1 rated High")).toBeInTheDocument();
  });

  it("proposes a new time in Addis Ababa time, with a reason (VIP-05)", async () => {
    const high = SEGMENTS.map((s) => (s.seq === 5 ? { ...s, ...HIGH_SITE } : s));
    const fetchMock = setup(
      SECURITY,
      visit({}, high),
      { ...NONE, propose_vip_change: ["s-5"] },
      { "POST /api/vip/segments/s-5/changes": { body: visit({}, high) } },
    );
    renderApp("/vip");
    await userEvent.click(await screen.findByRole("button", { name: "Propose change" }));
    const time = screen.getByLabelText("New start");
    expect(time).toHaveValue("10:00");
    await userEvent.clear(time);
    await userEvent.type(time, "08:00");
    const propose = screen.getByRole("button", { name: "Propose" });
    expect(propose).toBeDisabled(); // a reason first
    await userEvent.type(screen.getByLabelText("Reason"), "Rally planned 1.2 km away");
    await userEvent.click(propose);
    expect(sent(fetchMock, "POST", "/api/vip/segments/s-5/changes")).toEqual([
      { reason: "Rally planned 1.2 km away", new_starts_at: "2026-10-25T08:00:00+03:00" },
    ]);
  });

  it("proposes a virtual alternative", async () => {
    const high = SEGMENTS.map((s) => (s.seq === 5 ? { ...s, ...HIGH_SITE } : s));
    const fetchMock = setup(
      SECURITY,
      visit({}, high),
      { ...NONE, propose_vip_change: ["s-5"] },
      { "POST /api/vip/segments/s-5/changes": { body: visit({}, high) } },
    );
    renderApp("/vip");
    await userEvent.click(await screen.findByRole("button", { name: "Propose change" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Change" }), "virtual");
    expect(screen.queryByLabelText("New start")).toBeNull();
    await userEvent.type(screen.getByLabelText("Reason"), "Virtual tour instead");
    await userEvent.click(screen.getByRole("button", { name: "Propose" }));
    expect(sent(fetchMock, "POST", "/api/vip/segments/s-5/changes")).toEqual([
      { reason: "Virtual tour instead", make_virtual: true },
    ]);
  });

  const PENDING: Change = {
    id: "ch-1",
    segment_id: "s-5",
    new_starts_at: "2026-10-25T05:00:00Z",
    new_ends_at: "2026-10-25T07:00:00Z",
    make_virtual: false,
    reason: "Rally planned 1.2 km away",
    proposed_by_name: "Security Officer",
    proposed_at: "2026-10-20T08:00:00Z",
    status: "PENDING",
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
  };
  const pendingVisit = () =>
    visit({}, SEGMENTS.map((s) => (s.seq === 5 ? { ...s, ...HIGH_SITE, pending_change: PENDING } : s)));

  it("shows the proposer that a second person decides (D-16)", async () => {
    setup(SECURITY, pendingVisit(), { ...NONE, propose_vip_change: [] });
    renderApp("/vip");
    const change = await screen.findByTestId("vip-change");
    expect(change).toHaveTextContent("Change proposed: move to 08:00–10:00 · “Rally planned 1.2 km away” · Security Officer");
    expect(change).toHaveTextContent("Waiting for the Head of Mission or the HQ Crisis Director (another person).");
    expect(within(change).queryByRole("button")).toBeNull();
    expect(screen.queryByRole("button", { name: "Propose change" })).toBeNull();
  });

  it("lets the decider approve or reject", async () => {
    const fetchMock = setup(
      DUTY_OFFICER,
      pendingVisit(),
      { ...NONE, decide_vip_change: ["ch-1"] },
      {
        "POST /api/vip/changes/ch-1/approve": { body: visit() },
        "POST /api/vip/changes/ch-1/reject": { body: visit() },
      },
    );
    renderApp("/vip");
    const change = await screen.findByTestId("vip-change");
    expect(change).not.toHaveTextContent("Waiting");
    await userEvent.click(within(change).getByRole("button", { name: "Approve" }));
    expect(sent(fetchMock, "POST", "/api/vip/changes/ch-1/approve")).toEqual([{}]);
  });

  it("shows the server's refusal of a decision", async () => {
    setup(
      DUTY_OFFICER,
      pendingVisit(),
      { ...NONE, decide_vip_change: ["ch-1"] },
      { "POST /api/vip/changes/ch-1/reject": { status: 409, body: { detail: "Segment 5 is under way" } } },
    );
    renderApp("/vip");
    const change = await screen.findByTestId("vip-change");
    await userEvent.click(within(change).getByRole("button", { name: "Reject" }));
    expect(await within(change).findByText("Segment 5 is under way")).toBeInTheDocument();
  });

  it("ticks a checklist item when allowed (VIP-03)", async () => {
    const fetchMock = setup(
      SECURITY,
      visit(),
      { ...NONE, tick_vip_checklist: true },
      { "POST /api/vip/checklist/c-4/done": { body: visit() } },
    );
    renderApp("/vip");
    const list = await screen.findByRole("list", { name: "Pre-visit checklist" });
    expect(list).toHaveTextContent("Threat assessment issuedSecurity Officer");
    expect(list).toHaveTextContent("Industrial park venue surveydue 23 Oct");
    expect(within(list).getAllByRole("button")).toHaveLength(1); // done items have none
    await userEvent.click(within(list).getByRole("button", { name: "Mark done: Industrial park venue survey" }));
    expect(sent(fetchMock, "POST", "/api/vip/checklist/c-4/done")).toEqual([{}]);
  });

  it("starts the visit and moves the programme in order, live status only (VIP-04)", async () => {
    const fetchMock = setup(
      SECURITY,
      visit(),
      { ...NONE, start_visit: true },
      { "POST /api/vip/visits/v-31/start": { body: visit({ status: "LIVE" }) } },
    );
    renderApp("/vip");
    await userEvent.click(await screen.findByRole("button", { name: "Start visit" }));
    expect(sent(fetchMock, "POST", "/api/vip/visits/v-31/start")).toEqual([{}]);
  });

  it("shows LIVE and the next step of each segment in programme order", async () => {
    const live = SEGMENTS.map((s) =>
      s.seq === 1 ? { ...s, status: "COMPLETED" as const } : s.seq === 2 ? { ...s, status: "IN_PROGRESS" as const } : s,
    );
    const fetchMock = setup(
      SECURITY,
      visit({ status: "LIVE" }, live),
      { ...NONE, progress_visit: true },
      { "POST /api/vip/segments/s-2/progress": { body: visit({ status: "LIVE" }, live) } },
    );
    renderApp("/vip");
    const banner = await screen.findByTestId("vip-banner");
    await waitFor(() => expect(banner).toHaveTextContent("LIVEprogramme status only"));
    expect(await row(1)).toHaveTextContent("COMPLETED");
    expect(within(await row(2)).getByRole("button", { name: "Complete segment 2" })).toBeInTheDocument();
    // Segment 3 starts only after segment 2 completes.
    expect(within(await row(3)).queryByRole("button")).toBeNull();
    await userEvent.click(within(await row(2)).getByRole("button", { name: "Complete segment 2" }));
    expect(sent(fetchMock, "POST", "/api/vip/segments/s-2/progress")).toEqual([{}]);
  });

  it("is restricted for everyone else: no data, no nav entry (VIP-06)", async () => {
    const fetchMock = mockServer({
      "GET /api/me": { body: VIEWER },
      "GET /api/proposals": { body: [] },
      "GET /api/vip/access": { body: { visible: false } },
    });
    renderApp("/vip");
    expect(await screen.findByText("Restricted")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/vip/access")).toBe(true));
    expect(within(nav).queryByText("VIP Protection")).toBeNull();
    const asked = fetchMock.mock.calls.map(([url]) => String(url));
    expect(asked.some((u) => u.startsWith("/api/vip/visits") || u.includes("vip_visit"))).toBe(false);
  });

  it("puts VIP Protection after Fleet & Assets for those who may see visits (§63 Q8)", async () => {
    setup(SECURITY, visit(), NONE);
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    await within(nav).findByText("VIP Protection");
    const labels = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels.indexOf("VIP Protection")).toBe(labels.indexOf("Fleet & Assets") + 1);
  });
});

describe("VIP helpers", () => {
  it("formats segment times in Addis Ababa time, with the date on a new day", () => {
    const [arrival, motorcade, meeting, forum, site] = SEGMENTS as [Segment, Segment, Segment, Segment, Segment];
    expect(segmentTime(arrival, undefined)).toBe("24 Oct 09:30");
    expect(segmentTime(motorcade, arrival)).toBe("09:50 · 14 min");
    expect(segmentTime(forum, meeting)).toBe("14:00 · 600 attendees");
    expect(segmentTime(site, forum)).toBe("25 Oct 10:00");
    expect(visitDates({ starts_on: "2026-10-24", ends_on: "2026-10-26" })).toBe("24–26 Oct");
    expect(visitDates({ starts_on: "2026-10-30", ends_on: "2026-11-01" })).toBe("30 Oct – 1 Nov");
    expect(localToIso("2026-10-25", "08:00")).toBe("2026-10-25T08:00:00+03:00");
  });
});
