import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Campaign, CheckinPerson, CheckinSummary } from "../../api/checkin";
import type { Me } from "../../api/me";
import { DETAIL, INCIDENT, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockApi, renderApp } from "../../test/render";

const NOW = new Date().toISOString();
const CAMPAIGN: Campaign = {
  id: "c-3103",
  reference: "NTF-3103",
  incident_id: INCIDENT.id,
  campaign_type: "CHECKIN",
  message: "Safety check-in: are you safe? Reply SAFE or HELP.",
  channels: ["APP", "SMS", "WHATSAPP"],
  status: "SENT",
  created_by_type: "PLAYBOOK",
  created_at: NOW,
  sent_at: NOW,
  escalate_after_s: 20,
  recipients: 229,
  deliveries: { DELIVERED: 687 },
  simulated: true,
};
const SUMMARY: CheckinSummary = {
  campaign_id: CAMPAIGN.id,
  reference: CAMPAIGN.reference,
  incident_id: INCIDENT.id,
  status: "SENT",
  sent_at: NOW,
  escalate_after_s: 20,
  personnel: { recipients: 17, safe: 15, need_help: 1, pending: 1, accounted_pct: 94.1 },
  citizens: { recipients: 212, safe: 168, need_help: 4, pending: 40, accounted_pct: 81.1 },
};
const person = (name: string, status: CheckinPerson["status"]): CheckinPerson => ({
  person_id: `p-${name}`,
  full_name: name,
  person_type: "DIPLOMAT",
  role_title: null,
  mission_code: "NBO",
  status,
  channel: "APP",
  note: null,
  responded_at: status === "PENDING" ? null : NOW,
  escalated: false,
});

function setup(me: Me) {
  return mockApi({
    "/api/me": { body: me },
    "/api/campaigns": { body: [CAMPAIGN] },
    [`/api/incidents/${INCIDENT.id}`]: { body: DETAIL },
    "/api/checkin/c-3103/summary": { body: SUMMARY },
    "/api/checkin/c-3103/responses": {
      body: [person("Peter Mwangi", "NEED_HELP"), person("Grace Wanjiru", "SAFE")],
    },
    "/api/checkin/c-3103/people": { body: [person("Hana Takeda", "PENDING")] },
    "/api/checkin/c-3103/respond": { status: 201, body: {} },
    "/api/checkin/c-3103/escalate": { body: { personnel: ["Hana Takeda"], citizens: 40 } },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Safety Check-in", () => {
  it("at rest, shows its tiles and panels with nothing counted yet (DC-01, DC-03)", async () => {
    mockApi({ "/api/me": { body: DUTY_OFFICER }, "/api/campaigns": { body: [] } });
    const { container } = renderApp("/checkin");
    const figures = await screen.findByRole("group", { name: "Personnel figures" });
    expect(within(figures).getAllByText("—")).toHaveLength(4);
    expect(within(figures).getAllByText("No check-in running")).toHaveLength(4);
    expect(screen.getByText(/^No safety check-in yet\./)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Live responses" })).toBeInTheDocument();
    expect(container.querySelector(".bp6-non-ideal-state")).toBeNull();
  });

  it("shows personnel and citizen figures (CHK-03)", async () => {
    setup(DUTY_OFFICER);
    renderApp("/checkin");
    const figures = await screen.findByLabelText("Personnel figures");
    expect(figures).toHaveTextContent("94%");
    expect(figures).toHaveTextContent("16 of 17 responded");
    expect(screen.getByRole("img", { name: "15 safe, 1 need help, 1 pending" })).toBeInTheDocument();
    expect(screen.getByText("Registered citizens · 212")).toBeInTheDocument();
    const live = screen.getByLabelText("Live responses");
    expect(within(live).getByText("Peter Mwangi")).toBeInTheDocument();
    expect(within(live).getByText("NEEDS HELP")).toBeInTheDocument();
    expect(screen.getByText("APP · SMS · WHATSAPP (simulated)")).toBeInTheDocument();
  });

  it("posts the phone preview answer through the API (D-28) and escalates", async () => {
    const fetchMock = setup(DUTY_OFFICER);
    renderApp("/checkin");
    expect(await screen.findByLabelText("Answer as")).toHaveValue("p-Hana Takeda");
    await userEvent.click(screen.getByRole("button", { name: "I'm safe" }));
    expect(await screen.findByText("Thank you — status shared")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Escalate non-responders" }));
    expect(await screen.findByText("Escalated")).toBeInTheDocument();
    const writes = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(writes.map(([url, init]) => [String(url), init?.body])).toEqual([
      ["/api/checkin/c-3103/respond", JSON.stringify({ person_id: "p-Hana Takeda", status: "SAFE", channel: "APP" })],
      ["/api/checkin/c-3103/escalate", JSON.stringify({})],
    ]);
  });

  it("offers a partner next to each HELP, suggested, for a person to send (AS-06)", async () => {
    setup(DUTY_OFFICER);
    renderApp("/checkin");
    const live = await screen.findByLabelText("Live responses");
    const buttons = within(live).getAllByRole("button", { name: "Request partner" });
    expect(buttons).toHaveLength(1); // Peter only: Grace is safe
    await userEvent.click(buttons[0] as HTMLElement);
    expect(await screen.findByRole("dialog", { name: "Request help for Peter Mwangi" })).toBeInTheDocument();
  });

  it("is read-only for a Viewer", async () => {
    setup(VIEWER);
    renderApp("/checkin");
    expect(await screen.findByText("Preview only.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Escalate non-responders" })).toBeNull();
    expect(screen.queryByRole("button", { name: "I'm safe" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Request partner" })).toBeNull();
  });
});
