import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Campaign, CheckinPerson } from "../../api/checkin";
import type { Me } from "../../api/me";
import type { Coverage, Partner, PartnerRequest } from "../../api/partners";
import { DETAIL, HOM_CAIRO, INCIDENT, MISSIONS, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const NOW = new Date().toISOString();
const LATER = new Date(Date.now() + 30 * 60_000).toISOString();
const partner = (code: string, name: string, services: Partner["services"], sla: number): Partner => ({
  id: `p-${code}`,
  code,
  name,
  services,
  coverage: ["KE", "FR"],
  sla_minutes: sla,
  hours: "24/7",
  is_active: true,
  simulated: true,
});
const KES = partner("KES", "Kestrel Medical Assistance", ["MEDICAL"], 15);
const SEN = partner("SEN", "Sentinel Secure Transport", ["SECURE_TRANSPORT"], 30);
const MER = partner("MER", "Meridian Relocation", ["RELOCATION", "SECURE_TRANSPORT"], 60);
const COVERAGE: Coverage[] = Array.from({ length: 36 }, (_, n) => ({
  mission_id: `m-${n}`,
  code: n === 0 ? "CBR" : n === 1 ? "BUE" : `M${n}`,
  city: n === 0 ? "Canberra" : n === 1 ? "Buenos Aires" : `City ${n}`,
  country_code: "XX",
  missing: n < 2 ? ["EVACUATION"] : [],
}));
const request = (
  ref: string,
  status: PartnerRequest["status"],
  change: Partial<PartnerRequest> = {},
): PartnerRequest => ({
  id: `r-${ref}`,
  reference: ref,
  partner_id: KES.id,
  partner_name: KES.name,
  service: "MEDICAL",
  mission_id: INCIDENT.mission_id ?? "",
  mission_code: "NBO",
  incident_id: INCIDENT.id,
  incident_reference: INCIDENT.reference,
  person_id: null,
  person_name: null,
  person_role: null,
  place_label: "Nairobi",
  note: `Standby · ${INCIDENT.reference}`,
  status,
  eta: status === "REQUESTED" ? null : LATER,
  created_by_type: "PLAYBOOK",
  requested_at: NOW,
  accepted_at: status === "REQUESTED" ? null : NOW,
  completed_at: null,
  updated_at: NOW,
  ...change,
});
const CHECKIN: Campaign = {
  id: "c-3103",
  reference: "NTF-3103",
  incident_id: INCIDENT.id,
  campaign_type: "CHECKIN",
  message: "Safety check-in",
  channels: ["APP"],
  status: "SENT",
  created_by_type: "PLAYBOOK",
  created_at: NOW,
  sent_at: NOW,
  escalate_after_s: 600,
  recipients: 229,
  deliveries: {},
  simulated: true,
};
const PETER: CheckinPerson = {
  person_id: "p-peter",
  full_name: "Peter Mwangi",
  person_type: "LOCAL_STAFF",
  role_title: "Driver (local staff)",
  mission_code: "NBO",
  status: "NEED_HELP",
  channel: "APP",
  note: null,
  responded_at: NOW,
  escalated: false,
};
const HANA: CheckinPerson = { ...PETER, person_id: "p-hana", full_name: "Hana Takeda", role_title: "Cultural Attaché" };
const CITIZEN: CheckinPerson = {
  ...PETER,
  person_id: "p-citizen",
  full_name: "Registered Citizen",
  person_type: "CITIZEN",
  role_title: null,
};
const SUGGESTION = {
  person_id: PETER.person_id,
  service: "SECURE_TRANSPORT",
  mission_id: INCIDENT.mission_id,
  mission_code: "NBO",
  country_code: "KE",
  partners: [SEN, MER],
};

function setup(
  me: Me,
  requests: PartnerRequest[],
  extra: Record<string, Reply> = {},
  helpNeeded: CheckinPerson[] = [PETER],
) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/partners": { body: [KES, MER, SEN] },
    "GET /api/partners/coverage": { body: COVERAGE },
    "GET /api/partner-requests": { body: requests },
    "GET /api/campaigns": { body: [CHECKIN] },
    "GET /api/checkin/c-3103/responses": { body: helpNeeded },
    [`GET /api/incidents/${INCIDENT.id}`]: { body: DETAIL },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/partners/suggest": { body: SUGGESTION },
    ...extra,
  });
}

/** The check-in and its incident have been fetched, so an absent banner means something. */
async function loaded(fetchMock: ReturnType<typeof setup>) {
  await waitFor(() => {
    const paths = fetchMock.mock.calls.map(([url]) => String(url).split("?")[0]);
    expect(paths).toContain("/api/checkin/c-3103/responses");
    expect(paths).toContain(`/api/incidents/${INCIDENT.id}`);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Assistance Partners", () => {
  it("lists the partner network, labelled simulated, with coverage and its gaps (AS-01, AS-07)", async () => {
    setup(VIEWER, []);
    renderApp("/partners");
    const network = await screen.findByLabelText("Partner network");
    const rows = within(network).getAllByText(/countries ·/);
    expect(rows.map((r) => r.textContent)).toEqual([
      "2 countries · SLA 15 min · 24/7",
      "2 countries · SLA 1 h · 24/7",
      "2 countries · SLA 30 min · 24/7",
    ]);
    expect(within(network).getByText("Relocation · Secure transport")).toBeInTheDocument();
    expect(screen.getByText("Fictional partners · simulated")).toBeInTheDocument();
    expect(screen.getByText("34 / 36")).toBeInTheDocument();
    const gaps = screen.getByLabelText("Coverage gaps");
    expect(gaps).toHaveTextContent("Canberra (CBR) · no evacuation");
    expect(gaps).toHaveTextContent("Buenos Aires (BUE) · no evacuation");
    expect(screen.queryByRole("button", { name: "Request" })).toBeNull(); // a Viewer reads only
  });

  it("tracks requests with status and ETA; people with the role complete or cancel (AS-03)", async () => {
    const fetchMock = setup(
      DUTY_OFFICER,
      [
        request("REQ-0552", "EN_ROUTE", {
          partner_id: SEN.id,
          partner_name: SEN.name,
          service: "SECURE_TRANSPORT",
          person_name: "Peter Mwangi",
          person_role: "Driver (local staff)",
          person_id: PETER.person_id,
          created_by_type: "USER",
          note: "Vehicle blocked",
        }),
        request("REQ-0551", "ACCEPTED"),
      ],
      { "POST /api/partner-requests/r-REQ-0552/complete": { body: request("REQ-0552", "COMPLETED") } },
    );
    renderApp("/partners");
    const table = await screen.findByRole("table", { name: "Partner requests" });
    const enRoute = within(table).getByText("REQ-0552").closest("tr") as HTMLElement;
    expect(enRoute).toHaveTextContent("EN ROUTE");
    expect(enRoute).toHaveTextContent("Secure transport · Vehicle blocked");
    expect(enRoute).toHaveTextContent("Peter Mwangi (Driver (local staff)) · NBO mission");
    const standby = within(table).getByText("REQ-0551").closest("tr") as HTMLElement;
    expect(standby).toHaveTextContent("by playbook");
    expect(within(standby).queryByRole("button", { name: "Complete" })).toBeNull(); // not en route yet
    expect(screen.getByText("1 en route")).toBeInTheDocument();
    await userEvent.click(within(enRoute).getByRole("button", { name: "Complete" }));
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST").map(([url]) => String(url));
    expect(posts).toEqual(["/api/partner-requests/r-REQ-0552/complete"]);
  });

  it("offers no actions to a Head of Mission elsewhere", async () => {
    const fetchMock = setup(HOM_CAIRO, [request("REQ-0551", "ACCEPTED")]);
    renderApp("/partners");
    const table = await screen.findByRole("table", { name: "Partner requests" });
    expect(within(table).queryByRole("button")).toBeNull();
    await loaded(fetchMock);
    expect(screen.queryByRole("alert")).toBeNull(); // the Nairobi SOS is not theirs
  });

  it("suggests the nearest capable partner for an SOS; a person sends it (AS-06)", async () => {
    const fetchMock = setup(DUTY_OFFICER, [request("REQ-0551", "ACCEPTED")], {
      "POST /api/partner-requests": { status: 201, body: request("REQ-0552", "REQUESTED") },
    });
    renderApp("/partners");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(`Peter Mwangi (Driver (local staff)) needs help on ${INCIDENT.reference}`);
    await userEvent.click(within(banner).getByRole("button", { name: "Request help" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/Suggested:/)).toHaveTextContent(
      "Suggested: Sentinel Secure Transport · SLA 30 min · NBO mission",
    );
    expect(within(dialog).getByText("Partners are simulated (D-19): nothing leaves the platform.")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Note for the partner/), "Vehicle blocked");
    await userEvent.click(within(dialog).getByRole("button", { name: "Request" }));
    const post = fetchMock.mock.calls.find(
      ([url, init]) => init?.method === "POST" && String(url) === "/api/partner-requests",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      partner_id: SEN.id,
      service: "SECURE_TRANSPORT",
      person_id: PETER.person_id,
      incident_id: INCIDENT.id,
      note: "Vehicle blocked",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("names only staff who need help and have no request yet", async () => {
    setup(DUTY_OFFICER, [request("REQ-0552", "ACCEPTED", { person_id: PETER.person_id })], {}, [
      CITIZEN, // citizens are helped through advisories, not the SOS banner
      PETER, // already has a request
      HANA,
    ]);
    renderApp("/partners");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(`Hana Takeda (Cultural Attaché) needs help on ${INCIDENT.reference}.`);
    expect(banner).not.toHaveTextContent("more");
  });

  it("says why when a restricted traveller cannot be suggested", async () => {
    setup(DUTY_OFFICER, [], {
      "GET /api/partners/suggest": { status: 409, body: { detail: "A restricted traveller cannot be named (AS-08)" } },
    });
    renderApp("/partners");
    await userEvent.click(within(await screen.findByRole("alert")).getByRole("button", { name: "Request help" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText("A restricted traveller cannot be named to a partner (AS-08)"),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Request" })).toBeDisabled();
  });
});
