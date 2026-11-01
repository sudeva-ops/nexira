import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type {
  Evacuation,
  EvacuationDetail,
  EvacuationPermissions,
  ManifestEntry,
  Plan,
} from "../../api/evacuations";
import { defaultMission, manifestText, total, waitingFor } from "../../api/evacuations";
import type { Me } from "../../api/me";
import type { Mission } from "../../api/people";
import { HOM_NAIROBI, NAIROBI, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const NOW = new Date().toISOString();
const CAIRO: Mission = { ...NAIROBI, id: "m-cai", code: "CAI", city: "Cairo", incident_id: null, incident_reference: null };
const MISSIONS = [NAIROBI, CAIRO];

const PLAN: Plan = {
  id: "p-nbo",
  reference: "EVP-NBO",
  mission_id: NAIROBI.id,
  mission_code: "NBO",
  city: "Nairobi",
  muster_name: "Embassy courtyard",
  route_label: "Route B",
  destination: "Dubai",
  options: [
    {
      role: "PRIMARY",
      kind: "CHARTER",
      label: "Charter · Wilson Airport → Dubai",
      seats: 72,
      partner_id: "pa-atl",
      partner_name: "Atlas Air Evacuation",
      covered: true,
    },
    {
      role: "BACKUP",
      kind: "COMMERCIAL",
      label: "Commercial · JKIA (seats held: 30)",
      seats: 30,
      partner_id: null,
      partner_name: null,
      covered: false,
    },
    {
      role: "CONTINGENCY",
      kind: "ROAD",
      label: "Road · Namanga border → Arusha",
      seats: null,
      partner_id: "pa-sen",
      partner_name: "Sentinel Secure Transport",
      covered: true,
    },
  ],
  source: "Illustrative evacuation plan (simulated)",
  simulated: true,
};
const STEPS = [
  "Decision to evacuate",
  "Manifest confirmed",
  "Assembly at muster point",
  "Convoy departed",
  "Flight departed",
  "Arrival and reception",
];
const steps = (done: number) => STEPS.map((name, i) => ({ step: i + 1, name, at: i < done ? NOW : null }));

const ACTIVE: Evacuation = {
  id: "e-1",
  reference: "EVN-1001",
  plan_reference: "EVP-NBO",
  mission_id: NAIROBI.id,
  incident_id: "i-1042",
  proposal_id: null,
  status: "ACTIVE",
  requested_role: "HEAD_OF_MISSION",
  requested_by_name: "Nairobi HoM",
  requested_at: NOW,
  activated_by_name: "HQ Director",
  activated_at: NOW,
  step: 2,
  steps: steps(2),
  stood_down_reason: null,
  counts: { STAFF: 12, DELEGATE: 3, DEPENDANT: 1, CITIZEN: 44 },
  checked_in: 42,
  seats: 72,
  documents_flagged: 2,
  partner_requests: [
    { reference: "REQ-0551", partner_name: "Atlas Air Evacuation", service: "EVACUATION", status: "EN_ROUTE" },
    { reference: "REQ-0552", partner_name: "Sentinel Secure Transport", service: "SECURE_TRANSPORT", status: "ACCEPTED" },
  ],
  message_reference: "NTF-3105",
  message_status: "PENDING_APPROVAL",
  simulated: true,
};
const entry = (id: string, change: Partial<ManifestEntry>): ManifestEntry => ({
  id,
  category: "STAFF",
  seat: null,
  status: "EXPECTED",
  checked_in_at: null,
  name: `Fictional ${id}`,
  document_flag: false,
  ...change,
});
const MANIFEST = [
  entry("Diplomat A", { status: "CHECKED_IN", seat: "1A", checked_in_at: NOW }),
  entry("Hana Takeda", { name: "Hana Takeda", document_flag: true }),
  entry("Citizen C", { category: "CITIZEN" }),
];
const DETAIL: EvacuationDetail = { ...ACTIVE, manifest: MANIFEST, names_shown: true };
const HIDDEN: EvacuationDetail = {
  ...DETAIL,
  names_shown: false,
  manifest: MANIFEST.map((e) => ({ ...e, name: null, category: null, seat: null, document_flag: null })),
};
const PENDING: Evacuation = {
  ...ACTIVE,
  status: "PENDING_ACTIVATION",
  activated_at: null,
  activated_by_name: null,
  step: null,
  steps: steps(0),
  counts: { STAFF: 0, DELEGATE: 0, DEPENDANT: 0, CITIZEN: 0 },
  checked_in: 0,
  documents_flagged: 0,
  partner_requests: [],
  message_reference: null,
  message_status: null,
};

const NONE: EvacuationPermissions = {
  activate_evacuation: false,
  confirm_evacuation: false,
  check_in_evacuee: false,
  advance_evacuation: false,
  stand_down_evacuation: false,
};
const HQ: Me = { ...DUTY_OFFICER, id: "u-hq", display_name: "HQ Director", roles: [{ code: "HQ_CRISIS_DIRECTOR", mission_id: null, mission_code: null }] };

function setup(me: Me, evacuations: Evacuation[], permissions: EvacuationPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/evacuations/plans": { body: [PLAN] },
    "GET /api/evacuations": { body: evacuations },
    "GET /api/evacuations/e-1": { body: evacuations[0]?.status === "PENDING_ACTIVATION" ? { ...PENDING, manifest: [], names_shown: true } : DETAIL },
    "GET /api/me/permissions": { body: permissions },
    ...extra,
  });
}

function sent(fetchMock: ReturnType<typeof mockServer>, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

/** The banner once it says `text` (it starts empty-handed while the lists load). */
async function banner(text: string | RegExp): Promise<HTMLElement> {
  const b = await screen.findByTestId("evacuation-banner");
  await waitFor(() => expect(b).toHaveTextContent(text));
  return b;
}

afterEach(() => vi.unstubAllGlobals());

describe("Evacuation Management", () => {
  it("shows the plan ready while the mission has an ACTIVE incident, and lets a Head of Mission activate it", async () => {
    const fetchMock = setup(HOM_NAIROBI, [], { ...NONE, activate_evacuation: true }, {
      "POST /api/evacuations": { status: 201, body: PENDING },
    });
    renderApp("/evacuation");
    await banner("Evacuation plan EVP-NBO is ready but not activated.");
    await banner("Route B · Charter · Wilson Airport → Dubai with Atlas Air Evacuation");
    expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue(NAIROBI.id); // the ACTIVE incident's
    expect(screen.getByText("Built at activation")).toBeInTheDocument();
    expect(screen.getByText("No manifest yet")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Activate evacuation" }));
    expect(sent(fetchMock, "/api/evacuations")).toEqual([{ mission_id: NAIROBI.id }]);
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes(`entity_type=evacuation&entity_id=${NAIROBI.id}`)),
    ).toBe(true);
  });

  it("waits for the other role to confirm a request (EV-02, G-1)", async () => {
    const fetchMock = setup(HQ, [PENDING], { ...NONE, confirm_evacuation: true }, {
      "POST /api/evacuations/e-1/confirm": { body: ACTIVE },
    });
    renderApp("/evacuation");
    const b = await banner("Activation of EVP-NBO requested by Nairobi HoM (Head of Mission).");
    expect(b).toHaveTextContent("Waiting for the HQ Crisis Director to confirm");
    expect(within(b).queryByRole("button", { name: "Activate evacuation" })).toBeNull();
    await userEvent.click(await within(b).findByRole("button", { name: "Confirm activation" }));
    expect(sent(fetchMock, "/api/evacuations/e-1/confirm")).toEqual([{}]);
  });

  it("shows an active evacuation: KPIs, the manifest with flags and seats, the sequence and the options", async () => {
    setup(DUTY_OFFICER, [ACTIVE], NONE);
    renderApp("/evacuation");
    await banner("Evacuation EVP-NBO in progress. 42 of 60 evacuees checked in.");
    expect(screen.getByText("16 mission · 44 registered citizens")).toBeInTheDocument();
    expect(screen.getByText("42 / 60")).toBeInTheDocument();
    expect(screen.getByText("Charter · Wilson Airport → Dubai (simulated)")).toBeInTheDocument();
    const rows = within(await screen.findByRole("table", { name: "Evacuation manifest" })).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Fictional Diplomat A");
    expect(rows[0]).toHaveTextContent("1A");
    expect(rows[0]).toHaveTextContent("CHECKED IN");
    expect(rows[1]).toHaveTextContent("Hana Takeda");
    expect(rows[1]).toHaveTextContent("EXPIRING");
    expect(rows[2]).toHaveTextContent("Citizen");
    expect(rows[2]).toHaveTextContent("EXPECTED");
    const sequence = screen.getByLabelText("Evacuation sequence");
    expect(within(sequence).getByText("Manifest confirmed")).not.toHaveClass("nx-dim");
    expect(within(sequence).getByText("Assembly at muster point")).toHaveClass("nx-dim");
    const options = screen.getByRole("table", { name: "Evacuation options" });
    expect(within(options).getAllByRole("row")[0]).toHaveTextContent("72 seats · Atlas Air Evacuation · en route");
    expect(within(options).getAllByRole("row")[1]).toHaveTextContent("No partner");
    expect(screen.getByText(/Movement message NTF-3105 · awaiting a second person/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Check in|Next step|Stand down/ })).toBeNull(); // not allowed
  });

  it("checks people in and moves the sequence when allowed (EV-04, EV-05)", async () => {
    const fetchMock = setup(DUTY_OFFICER, [ACTIVE], { ...NONE, check_in_evacuee: true, advance_evacuation: true }, {
      "POST /api/evacuations/e-1/manifest/Hana Takeda/check-in": { body: ACTIVE },
      "POST /api/evacuations/e-1/advance": { body: ACTIVE },
    });
    renderApp("/evacuation");
    const table = await screen.findByRole("table", { name: "Evacuation manifest" });
    const buttons = await within(table).findAllByRole("button", { name: "Check in" });
    expect(buttons).toHaveLength(2); // the two still expected
    await userEvent.click(buttons[0] as HTMLElement);
    expect(sent(fetchMock, "/api/evacuations/e-1/manifest/Hana Takeda/check-in")).toEqual([{}]);
    await userEvent.click(screen.getByRole("button", { name: "Next step: Assembly at muster point" }));
    expect(sent(fetchMock, "/api/evacuations/e-1/advance")).toEqual([{ step: 3 }]);
  });

  it("stands down with a reason, when allowed (EV-07)", async () => {
    const fetchMock = setup(HQ, [ACTIVE], { ...NONE, stand_down_evacuation: true }, {
      "POST /api/evacuations/e-1/stand-down": { body: { ...ACTIVE, status: "STOOD_DOWN" } },
    });
    renderApp("/evacuation");
    const button = await screen.findByRole("button", { name: "Stand down" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason"), "The unrest has eased");
    await userEvent.click(button);
    expect(sent(fetchMock, "/api/evacuations/e-1/stand-down")).toEqual([{ reason: "The unrest has eased" }]);
  });

  it("says why when an action is refused", async () => {
    setup(HQ, [PENDING], { ...NONE, confirm_evacuation: true }, {
      "POST /api/evacuations/e-1/confirm": { status: 403, body: { detail: "The same person cannot decide two steps (D-16)" } },
    });
    renderApp("/evacuation");
    await userEvent.click(await screen.findByRole("button", { name: "Confirm activation" }));
    expect(await screen.findByText("The same person cannot decide two steps (D-16)")).toBeInTheDocument();
  });

  it("gives a Viewer counts and the sequence, with no names and no buttons (EV-09)", async () => {
    setup(VIEWER, [ACTIVE], NONE, { "GET /api/evacuations/e-1": { body: HIDDEN } });
    renderApp("/evacuation");
    const table = await screen.findByRole("table", { name: "Evacuation manifest" });
    expect(screen.getByRole("note")).toHaveTextContent("you see counts only");
    expect(within(table).queryByText(/Fictional|Hana/)).toBeNull();
    expect(screen.getByText("42 / 60")).toBeInTheDocument();
    expect(screen.getByLabelText("Evacuation sequence")).toHaveTextContent("Manifest confirmed");
    expect(screen.queryAllByRole("button").filter((b) => /Activate|Confirm|Check in|Next step|Stand down/.test(b.textContent ?? ""))).toEqual([]);
  });

  it("shows a completed evacuation and switches missions", async () => {
    setup(DUTY_OFFICER, [{ ...ACTIVE, status: "COMPLETED", step: 6, steps: steps(6) }], NONE);
    renderApp("/evacuation");
    await banner("EVN-1001 complete: the evacuees have arrived.");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Mission" }), CAIRO.id);
    await banner("No active evacuation. Plans are pre-built for every mission.");
    expect(screen.getByText("No evacuation plan for this mission.")).toBeInTheDocument();
  });
});

describe("evacuation helpers", () => {
  it("counts, words and the default mission", () => {
    expect(total(ACTIVE)).toBe(60);
    expect(manifestText(ACTIVE)).toBe("16 mission · 44 registered citizens");
    expect(waitingFor(PENDING)).toBe("HQ Crisis Director");
    expect(waitingFor({ requested_role: "HQ_CRISIS_DIRECTOR" })).toBe("Head of Mission");
    expect(defaultMission([{ ...ACTIVE, mission_id: CAIRO.id }], MISSIONS)).toBe(CAIRO.id); // a live one first
    expect(defaultMission([], MISSIONS)).toBe(NAIROBI.id); // else an ACTIVE incident
    expect(defaultMission([{ ...ACTIVE, status: "COMPLETED" }], [CAIRO])).toBe(CAIRO.id);
  });
});
