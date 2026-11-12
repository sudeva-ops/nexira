import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import type { AgentsState, Proposal } from "../../api/proposals";
import { HOM_NAIROBI, INCIDENT, SUMMARY, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

const NOW = Date.now();
const iso = (s: number) => new Date(NOW + s * 1000).toISOString();

function proposal(over: Partial<Proposal>): Proposal {
  return {
    id: "p1",
    agent_code: "RESPONSE_PLANNER",
    agent_name: "Response Planner",
    incident_id: INCIDENT.id,
    incident_reference: INCIDENT.reference,
    proposal_key: "k",
    action_type: "START_PLAYBOOK",
    title: "Run PB-07 · Civil unrest near mission",
    proposed_action: "Start PB-07 for INC-2026-1042.",
    action_payload: { playbook_code: "PB-07" },
    evidence: [{ text: "Large crowds (High)", source: "Dataminr (simulated)" }],
    alternatives: [
      {
        label: "Monitor only: log for the duty team",
        action_type: "POST_INTERNAL_NOTE",
        action_payload: { text: "x" },
        rationale: "If contained.",
      },
    ],
    risk_if_no_action: "Staff are not warned.",
    confidence: 92,
    is_proactive: false,
    effective_level: 2,
    status: "PENDING",
    superseded_by: null,
    edited_action: null,
    edited_payload: null,
    rejection_reason: null,
    deadline_at: iso(600),
    undo_until: null,
    created_at: iso(-60),
    decided_at: null,
    executed_at: null,
    approvals: [
      {
        step_no: 1,
        required_role: "DUTY_OFFICER|SECURITY_OFFICER",
        decision: null,
        decided_by: null,
        decided_by_name: null,
        decided_at: null,
      },
    ],
    can_decide: true,
    can_edit: false,
    can_dismiss: false,
    can_undo: false,
    ...over,
  };
}

const ADVISORY = proposal({
  id: "p2",
  agent_code: "COMMUNICATIONS",
  agent_name: "Communications",
  action_type: "SEND_EXTERNAL_MESSAGE",
  title: "Advise registered citizens · INC-2026-1042",
  action_payload: {
    campaign_type: "ADVISORY",
    message: "Stay indoors.",
    translations: { fr: "Restez à l'intérieur." },
    channels: ["SMS"],
    audience: { exposed: true, person_types: ["CITIZEN"] },
  },
  alternatives: [],
  can_edit: true,
});
const NOTE = proposal({
  id: "p3",
  agent_code: "WATCH_OFFICER",
  agent_name: "Watch Officer",
  action_type: "LOG_INFO",
  title: "Log new incident INC-2026-1042",
  effective_level: 1,
  status: "AUTO_EXECUTED",
  deadline_at: null,
  undo_until: iso(120),
  approvals: [],
  alternatives: [],
  can_decide: false,
  can_undo: true,
});
const EVACUATION = proposal({
  id: "p4",
  action_type: "START_EVACUATION",
  title: "Evacuate Embassy staff via route B",
  effective_level: 3,
  alternatives: [],
  approvals: [
    { step_no: 1, required_role: "HEAD_OF_MISSION", decision: "APPROVE", decided_by: "u1", decided_by_name: "Elias Brandt", decided_at: iso(-10) },
    { step_no: 2, required_role: "HQ_CRISIS_DIRECTOR", decision: null, decided_by: null, decided_by_name: null, decided_at: null },
  ],
  can_decide: false,
});
const AGENTS: AgentsState = { paused: false, agents: [] };

function setup(me: Me, proposals: Proposal[]) {
  return mockApi({
    "/api/me": { body: me },
    "/api/proposals": { body: proposals },
    "/api/agents": { body: AGENTS },
    "/api/agents/activity": {
      body: [{ occurred_at: iso(-5), actor: "Response Planner", action: "PROPOSAL.CREATE", proposal_id: "p1", text: "proposed Run PB-07" }],
    },
    "/api/proposals/p1/approve": { body: {} },
    "/api/proposals/p1/reject": { body: {} },
    "/api/proposals/p1/use-alternative": { body: {} },
    "/api/proposals/p2/edit-approve": { body: {} },
    "/api/proposals/p3/undo": { body: {} },
  });
}

const posts = (fetchMock: ReturnType<typeof mockApi>) =>
  fetchMock.mock.calls
    .filter(([, init]) => init?.method === "POST")
    .map(([url, init]) => [String(url), init?.body]);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Decision Queue", () => {
  it("shows a proposal card with everything DQ-01 asks for", async () => {
    setup(DUTY_OFFICER, [proposal({})]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: "Run PB-07 · Civil unrest near mission" });
    for (const text of [
      "Response Planner agent",
      "Approve",
      "Large crowds (High)",
      "Dataminr (simulated)",
      "92%",
      "Duty Officer or Security Officer",
      "Staff are not warned.",
      "Monitor only: log for the duty team",
    ]) {
      expect(card).toHaveTextContent(text);
    }
    expect(within(card).getByText(/^Decide in (9:5\d|10:00)$/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Decisions pending" })).toHaveTextContent("1 decision pending");
    expect(screen.getByLabelText("Agent activity")).toHaveTextContent("Response Planner · proposed Run PB-07");
  });

  it("at rest, says what the agents are watching from the APIs, and each agent's latest (GFX-06)", async () => {
    mockApi({
      "/api/me": { body: DUTY_OFFICER },
      "/api/proposals": { body: [] },
      "/api/agents": {
        body: {
          paused: false,
          agents: [
            { code: "RESPONSE_PLANNER", name: "Response Planner", watches: ["INCIDENT"], is_enabled: true },
            { code: "WATCH_OFFICER", name: "Watch Officer", watches: ["SIGNAL", "INCIDENT"], is_enabled: true },
          ],
        },
      },
      "/api/agents/activity": {
        body: [{ occurred_at: iso(-5), actor: "Response Planner", action: "PROPOSAL.CREATE", proposal_id: "p1", text: "proposed Run PB-07" }],
      },
      "/api/operations/summary": { body: SUMMARY },
      "/api/flights": { body: [] },
      "/api/signals": { body: [] },
    });
    renderApp("/");
    const watching = await screen.findByLabelText("Watching now");
    await within(watching).findByText("1338");
    expect(watching).toHaveTextContent("36Missions");
    expect(watching).toHaveTextContent("0In transit0 flights in the air · 1 trip under way");
    const checks = screen.getByLabelText("Latest from each agent");
    expect(checks).toHaveTextContent("Response Plannerproposed Run PB-07");
    expect(checks).toHaveTextContent("Watch OfficerWatching 2 event types · nothing proposed yet");
    expect(screen.getByText("No decisions waiting")).toBeInTheDocument();
  });

  it("approves, rejects with a reason and uses an alternative", async () => {
    const fetchMock = setup(DUTY_OFFICER, [proposal({})]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: /Run PB-07/ });
    await userEvent.click(within(card).getByRole("button", { name: "Approve as Duty Officer or Security Officer" }));
    await userEvent.click(within(card).getByRole("button", { name: "Reject" }));
    await userEvent.click(within(card).getByRole("button", { name: "Wrong timing" }));
    await userEvent.click(within(card).getByRole("button", { name: "Use alternative: Monitor only: log for the duty team" }));
    expect(posts(fetchMock)).toEqual([
      ["/api/proposals/p1/approve", "{}"],
      ["/api/proposals/p1/reject", JSON.stringify({ reason: "Wrong timing" })],
      ["/api/proposals/p1/use-alternative", JSON.stringify({ index: 0 })],
    ]);
  });

  it("edits a message's text only and keeps the rest of the payload", async () => {
    const fetchMock = setup(DUTY_OFFICER, [ADVISORY]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: /Advise registered citizens/ });
    await userEvent.click(within(card).getByRole("button", { name: "Edit" }));
    const box = within(card).getByLabelText("Message (English)");
    await userEvent.clear(box);
    await userEvent.type(box, "Stay indoors. Avoid the CBD.");
    await userEvent.click(within(card).getByRole("button", { name: "Save & approve" }));
    const [[url, body]] = posts(fetchMock) as [[string, string]];
    expect(url).toBe("/api/proposals/p2/edit-approve");
    expect(JSON.parse(body)).toEqual({
      edited_action: null,
      edited_payload: { ...ADVISORY.action_payload, message: "Stay indoors. Avoid the CBD." },
    });
  });

  it("shows Edit only when the server says so", async () => {
    setup(DUTY_OFFICER, [proposal({})]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: /Run PB-07/ });
    expect(within(card).queryByRole("button", { name: "Edit" })).toBeNull(); // can_edit false
  });

  it("hides undo once the window has closed", async () => {
    setup(DUTY_OFFICER, [{ ...NOTE, undo_until: iso(-1) }]);
    renderApp("/");
    await userEvent.click(screen.getByRole("tab", { name: /Decided/ }));
    const card = await screen.findByRole("article", { name: /Log new incident/ });
    expect(within(card).queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("offers undo inside the window", async () => {
    const fetchMock = setup(DUTY_OFFICER, [NOTE]);
    renderApp("/");
    await userEvent.click(screen.getByRole("tab", { name: /Decided/ }));
    const card = await screen.findByRole("article", { name: /Log new incident/ });
    expect(card).toHaveTextContent(/undo for (1:5\d|2:00)/);
    await userEvent.click(within(card).getByRole("button", { name: "Undo" }));
    expect(posts(fetchMock)).toEqual([["/api/proposals/p3/undo", "{}"]]);
  });

  it.each([
    ["a Viewer", VIEWER],
    ["the Nairobi HoM on a Duty Officer step", HOM_NAIROBI],
  ])("hides decision buttons from %s (can_decide is false)", async (_who, me) => {
    setup(me, [proposal({ can_decide: false })]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: /Run PB-07/ });
    expect(within(card).queryByRole("button", { name: /Approve|Reject|Use alternative/ })).toBeNull();
  });

  it("shows the approver chain of a two-person decision", async () => {
    setup(DUTY_OFFICER, [EVACUATION]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: /Evacuate Embassy staff/ });
    expect(within(card).getByTestId("approver-1")).toHaveTextContent("✓ Head of Mission · Elias Brandt");
    expect(within(card).getByTestId("approver-2")).toHaveTextContent("HQ Crisis Director");
    expect(card).toHaveTextContent("Senior approval");
  });

  it("shows a travel card with links to the trip and the flight (TA-09)", async () => {
    const advice = proposal({
      id: "p9",
      agent_code: "TRAVEL_AIR",
      agent_name: "Travel & Air",
      incident_id: null,
      incident_reference: null,
      action_type: "ADVISE_REBOOKING",
      title: "Arrange onward travel · XW 451 diverted to Mombasa",
      proposed_action: "Book onward travel and a hotel in Mombasa through the travel management company.",
      action_payload: { trip_id: "t-8818", flight_id: "f-451", at: "Mombasa" },
      alternatives: [],
      effective_level: 4,
      approvals: [],
      can_decide: false,
      can_dismiss: true,
    });
    setup(DUTY_OFFICER, [advice]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: /Arrange onward travel/ });
    expect(card).toHaveTextContent("Advice only: never executed");
    const links = within(card).getByLabelText("Travel links");
    expect(within(links).getByRole("link", { name: "Open trip →" })).toHaveAttribute("href", "/journeys?trip=t-8818");
    expect(within(links).getByRole("link", { name: "Open flight →" })).toHaveAttribute("href", "/air?flight=f-451");
    expect(within(card).queryByRole("button", { name: /^Approve/ })).toBeNull();
    expect(within(card).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("offers the notify alternative on a cancel card", async () => {
    const cancel = proposal({
      id: "p1",
      agent_code: "TRAVEL_AIR",
      agent_name: "Travel & Air",
      incident_id: null,
      incident_reference: null,
      action_type: "CANCEL_TRIP",
      title: "Cancel TRP-8811 Paris · risk now CRITICAL",
      action_payload: { trip_id: "t-8811" },
      alternatives: [
        {
          label: "Notify the travellers instead",
          action_type: "NOTIFY_TRAVELLERS",
          action_payload: { trip_id: "t-8811", message: "x", channels: ["APP"] },
          rationale: "The trip may still go ahead.",
        },
      ],
      approvals: [
        { step_no: 1, required_role: "SECURITY_OFFICER", decision: null, decided_by: null, decided_by_name: null, decided_at: null },
      ],
    });
    const fetchMock = setup(DUTY_OFFICER, [cancel]);
    renderApp("/");
    const card = await screen.findByRole("article", { name: /Cancel TRP-8811/ });
    expect(within(card).getByRole("link", { name: "Open trip →" })).toHaveAttribute("href", "/journeys?trip=t-8811");
    await userEvent.click(within(card).getByRole("button", { name: "Use alternative: Notify the travellers instead" }));
    expect(posts(fetchMock)).toEqual([["/api/proposals/p1/use-alternative", JSON.stringify({ index: 0 })]]);
  });
});
