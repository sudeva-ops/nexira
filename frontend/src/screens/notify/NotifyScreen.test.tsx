import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { CampaignPermissions, NtfCampaign, Template } from "../../api/notifications";
import { MISSIONS, NAIROBI } from "../../test/fixtures";
import { DUTY_OFFICER, type Reply, mockServer, renderApp } from "../../test/render";

const PENDING: NtfCampaign = {
  id: "c-1",
  reference: "NTF-3200",
  incident_id: null,
  campaign_type: "ADVISORY",
  message: "Stay indoors in Nairobi.",
  translations: {},
  channels: ["SMS", "APP"],
  audience_filter: { missions: [NAIROBI.id], person_types: ["CITIZEN"] },
  status: "PENDING_APPROVAL",
  created_by_type: "USER",
  created_by: "u-other",
  created_by_name: "Amina Yusuf",
  template_id: null,
  submitted_by: "u-other",
  approved_by: null,
  approved_by_name: null,
  approved_at: null,
  rejection_reason: null,
  created_at: "2026-10-26T06:00:00Z",
  sent_at: null,
  recipients: 0,
  deliveries: {},
  funnel: {},
  simulated: true,
};
const SENT: NtfCampaign = {
  ...PENDING,
  id: "c-2",
  reference: "NTF-3201",
  status: "SENT",
  recipients: 4,
  deliveries: { READ: 6, DELIVERED: 1, FAILED: 1 },
  funnel: { SMS: { READ: 3, DELIVERED: 1 }, APP: { READ: 3, FAILED: 1 } },
};
const TEMPLATE: Template = {
  id: "t-generic",
  code: "SHELTER",
  kind: "ADVISORY",
  mission_id: null,
  name: "Shelter in place",
  texts: { en: "Unrest in central {city}. Stay indoors.", fr: "Troubles à {city}." },
  reviewed: { fr: true },
  is_active: true,
};
const NONE: CampaignPermissions = {
  edit_campaign: false,
  submit_campaign: false,
  approve_campaign: false,
  cancel_campaign: false,
};

function server(permissions: CampaignPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: DUTY_OFFICER },
    "GET /api/proposals": { body: [] },
    "GET /api/campaigns": { body: [PENDING, SENT] },
    "GET /api/campaigns/c-1": { body: PENDING },
    "GET /api/campaigns/c-2": { body: SENT },
    "GET /api/me/permissions": { body: permissions },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/incidents": { body: [] },
    "GET /api/templates": { body: [TEMPLATE] },
    ...extra,
  });
}

function posted(fetchMock: ReturnType<typeof mockServer>, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

afterEach(() => vi.unstubAllGlobals());

describe("Mass Notification", () => {
  it("lists campaigns and shows the delivery funnel per channel", async () => {
    server(NONE);
    renderApp("/notifications?campaign=c-2");
    const table = await screen.findByRole("table", { name: "Campaigns" });
    expect(within(table).getByText("NTF-3200")).toBeInTheDocument();
    expect(within(table).getByText("Awaiting approval")).toBeInTheDocument();
    const funnel = await screen.findByLabelText("Delivery funnel");
    expect(within(funnel).getByLabelText("SMS funnel")).toHaveTextContent("3/4 read");
    expect(within(funnel).getByLabelText("App push funnel")).toHaveTextContent("3/4 read");
  });

  it("names a Travel & Air message's audience", async () => {
    const trip: NtfCampaign = {
      ...SENT,
      id: "c-3",
      reference: "NTF-3202",
      campaign_type: "ALERT",
      audience_filter: { trip_id: "t-8818" },
      created_by_type: "AGENT",
    };
    server(NONE, { "GET /api/campaigns": { body: [trip] } });
    renderApp("/notifications");
    const table = await screen.findByRole("table", { name: "Campaigns" });
    expect(within(table).getByText("A trip's travellers (Travel & Air)")).toBeInTheDocument();
  });

  it("shows approve and reject only to someone who may decide", async () => {
    server(NONE);
    renderApp("/notifications?campaign=c-1");
    await screen.findByText("NTF-3200 · Awaiting approval");
    expect(screen.queryByRole("button", { name: "Approve and send" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("approves through the API", async () => {
    const fetchMock = server(
      { ...NONE, approve_campaign: true },
      { "POST /api/campaigns/c-1/approve": { body: { ...PENDING, status: "SENDING" } } },
    );
    renderApp("/notifications?campaign=c-1");
    await userEvent.click(await screen.findByRole("button", { name: "Approve and send" }));
    await waitFor(() => expect(posted(fetchMock, "/api/campaigns/c-1/approve")).toHaveLength(1));
  });

  it("needs a reason to send a campaign back", async () => {
    const fetchMock = server(
      { ...NONE, approve_campaign: true },
      { "POST /api/campaigns/c-1/reject": { body: { ...PENDING, status: "DRAFT" } } },
    );
    renderApp("/notifications?campaign=c-1");
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const sendBack = screen.getByRole("button", { name: "Send back" });
    expect(sendBack).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason for rejecting"), "Too broad");
    await userEvent.click(sendBack);
    await waitFor(() =>
      expect(posted(fetchMock, "/api/campaigns/c-1/reject")).toEqual([{ reason: "Too broad" }]),
    );
  });

  it("composes from a template, previews and submits for approval", async () => {
    const created: NtfCampaign = { ...PENDING, id: "c-new", status: "DRAFT" };
    const fetchMock = server(NONE, {
      "POST /api/campaigns": { status: 201, body: created },
      "POST /api/campaigns/c-new/preview": {
        body: { recipients: 2, by_person_type: { CITIZEN: 2 }, by_mission: { NBO: 2 } },
      },
      "POST /api/campaigns/c-new/submit": { body: { ...created, status: "PENDING_APPROVAL" } },
    });
    renderApp("/notifications");
    await screen.findByRole("option", { name: `${NAIROBI.code} · ${NAIROBI.city}` }); // loaded
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "ADVISORY");
    await userEvent.selectOptions(screen.getByLabelText("Add mission"), NAIROBI.id);
    await userEvent.selectOptions(screen.getByLabelText("Template"), "SHELTER");
    // The generic template, filled in for the chosen mission (MN-03).
    expect(screen.getByLabelText("Message (English)")).toHaveValue(
      `Unrest in central ${NAIROBI.city}. Stay indoors.`,
    );
    expect(screen.getByText("reviewed template text")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const recipients = await screen.findByLabelText("Recipients");
    expect(recipients).toHaveTextContent("2 recipients");
    expect(recipients).toHaveTextContent("a second person must approve");
    expect(posted(fetchMock, "/api/campaigns")[0]).toMatchObject({
      kind: "ADVISORY",
      missions: [NAIROBI.id],
      template_id: "t-generic",
      translations: { fr: `Troubles à ${NAIROBI.city}.` },
    });

    await userEvent.click(screen.getByRole("button", { name: "Submit for approval" }));
    await waitFor(() => expect(posted(fetchMock, "/api/campaigns/c-new/submit")).toHaveLength(1));
  });

  it("asks to confirm a large staff send", async () => {
    const created: NtfCampaign = { ...PENDING, id: "c-big", status: "DRAFT", campaign_type: "ALERT" };
    const fetchMock = server(NONE, {
      "POST /api/campaigns": { status: 201, body: created },
      "POST /api/campaigns/c-big/preview": {
        body: { recipients: 900, by_person_type: { DIPLOMAT: 900 }, by_mission: { NBO: 900 } },
      },
      "POST /api/campaigns/c-big/submit": { body: { ...created, status: "SENDING" } },
    });
    renderApp("/notifications");
    await screen.findByRole("option", { name: `${NAIROBI.code} · ${NAIROBI.city}` }); // loaded
    await userEvent.selectOptions(screen.getByLabelText("Add mission"), NAIROBI.id);
    await userEvent.type(screen.getByLabelText("Message (English)"), "Shelter in place.");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send to 900 recipients" }));
    expect(posted(fetchMock, "/api/campaigns/c-big/submit")).toHaveLength(0); // not yet
    await userEvent.click(screen.getByRole("button", { name: "Confirm: send to 900" }));
    await waitFor(() => expect(posted(fetchMock, "/api/campaigns/c-big/submit")).toHaveLength(1));
  });
});
