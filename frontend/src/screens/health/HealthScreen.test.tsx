import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Advisory, HealthPermissions, HealthSummary, MissionHealth, Requirement } from "../../api/health";
import { defaultMission, distanceText, missionAdvisories, topicWord } from "../../api/health";
import type { Me } from "../../api/me";
import type { Mission } from "../../api/people";
import { NAIROBI, VIEWER } from "../../test/fixtures";
import { DUTY_OFFICER, mockServer, type Reply, renderApp } from "../../test/render";

const NOW = new Date().toISOString();

const advisory = (ref: string, change: Partial<Advisory>): Advisory => ({
  id: `a-${ref}`,
  reference: ref,
  topic: ref,
  topic_code: ref,
  countries: [],
  region_label: "—",
  level: "MODERATE",
  guidance: "Follow the mission's guidance.",
  source: "WHO DON (simulated)",
  status: "OPEN",
  published_at: NOW,
  updated_at: NOW,
  missions: [],
  simulated: true,
  ...change,
});

const DHAKA: Mission = { ...NAIROBI, id: "m-dac", code: "DAC", city: "Dhaka", country_code: "BD", personnel: 15 };
const ISLAMABAD: Mission = { ...NAIROBI, id: "m-isb", code: "ISB", city: "Islamabad", country_code: "PK", personnel: 18 };
const MISSIONS = [NAIROBI, DHAKA, ISLAMABAD];

const CHOLERA = advisory("HA-1", {
  topic: "Cholera",
  topic_code: "CHOLERA",
  countries: ["KE"],
  region_label: "Kenya · Nairobi county",
  level: "HIGH",
  guidance: "Drink bottled or boiled water only.",
  missions: [{ mission_id: NAIROBI.id, code: "NBO", city: "Nairobi" }],
});
const MEASLES = advisory("HA-2", {
  topic: "Measles",
  topic_code: "MEASLES",
  countries: ["PK"],
  region_label: "Pakistan",
  level: "MODERATE",
  missions: [{ mission_id: ISLAMABAD.id, code: "ISB", city: "Islamabad" }],
});
const DENGUE = advisory("HA-3", {
  topic: "Dengue",
  topic_code: "DENGUE",
  countries: ["BD"],
  region_label: "Bangladesh · Dhaka",
  status: "CLOSED",
  missions: [{ mission_id: DHAKA.id, code: "DAC", city: "Dhaka" }],
});
const MPOX = advisory("HA-4", { topic: "Mpox", topic_code: "MPOX", countries: ["CD"], region_label: "Central Africa" });
const ADVISORIES = [CHOLERA, MEASLES, MPOX, DENGUE];

const SUMMARY: HealthSummary = {
  open_advisories: 3,
  affecting_missions: 2,
  missions_with_advisory: 2,
  by_level: [
    { level: "HIGH", missions: 1 },
    { level: "MODERATE", missions: 1 },
  ],
  staff_not_offered: 5,
  vetted_facilities: 73,
  simulated: true,
};

const REQUIREMENTS: Requirement[] = [
  ["BD", "None", "Hepatitis A, typhoid"],
  ["KE", "Yellow fever certificate if arriving from risk country", "Cholera, hepatitis A, typhoid"],
  ["PK", "Polio vaccination certificate for stays over 4 weeks", "Measles booster"],
].map(([country_code, mandatory, recommended]) => ({
  country_code: country_code as string,
  mandatory: mandatory as string,
  recommended: recommended as string,
  source: "Illustrative (simulated)",
  simulated: true,
}));

const facility = (name: string, distance_m: number, change: Partial<MissionHealth["facilities"][number]> = {}) => ({
  id: `f-${name}`,
  name,
  capabilities: ["EMERGENCY", "ICU"],
  trauma_level: null,
  open_24_7: true,
  vetted_by: "Kestrel Medical (simulated)",
  distance_m,
  avoid: false,
  avoid_incident: null,
  source: "Partner directory (simulated)",
  simulated: true,
  ...change,
});

const NBO_HEALTH: MissionHealth = {
  mission_id: NAIROBI.id,
  code: "NBO",
  city: "Nairobi",
  country_code: "KE",
  level: "HIGH",
  facilities: [
    facility("Nairobi Central Medical Centre (sample)", 2_100, {
      capabilities: ["EMERGENCY", "TRAUMA", "ICU", "SURGERY"],
      trauma_level: 1,
    }),
    facility("Highland Private Hospital (sample)", 6_400),
    facility("Karen Specialist Hospital (sample)", 10_200, { vetted_by: null, open_24_7: false }),
  ],
  readiness: {
    staff: 14,
    blood_type_on_file: 14,
    insurance_active: 14,
    trauma_kits: 6,
    vaccines: [
      { topic_code: "CHOLERA", offered: 9, open_advisory: true },
      { topic_code: "YELLOW_FEVER", offered: 14, open_advisory: false },
    ],
    as_of: "2026-10-24",
    source: "HR medical office (simulated)",
    simulated: true,
  },
  requirement: REQUIREMENTS[1] ?? null,
};
const AVOIDED: MissionHealth = {
  ...NBO_HEALTH,
  facilities: NBO_HEALTH.facilities.map((f, i) =>
    i === 0 ? { ...f, avoid: true, avoid_incident: "INC-2026-1042" } : f,
  ),
};
const ISB_HEALTH: MissionHealth = {
  ...NBO_HEALTH,
  mission_id: ISLAMABAD.id,
  code: "ISB",
  city: "Islamabad",
  country_code: "PK",
  level: "MODERATE",
  facilities: [facility("Margalla Clinic (sample)", 3_500)],
  readiness: null,
};

const MAY_SEND: HealthPermissions = { send_advisory: true };
const NOTHING: HealthPermissions = { send_advisory: false };

function setup(me: Me, permissions: HealthPermissions, extra: Record<string, Reply> = {}) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/health/advisories": { body: ADVISORIES },
    "GET /api/health/summary": { body: SUMMARY },
    "GET /api/health/requirements": { body: REQUIREMENTS },
    "GET /api/health/missions/m-nbo": { body: NBO_HEALTH },
    "GET /api/health/missions/m-isb": { body: ISB_HEALTH },
    "GET /api/me/permissions": { body: permissions },
    ...extra,
  });
}

function sent(fetchMock: ReturnType<typeof mockServer>, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

const advisoriesTable = () => screen.findByRole("table", { name: "Health advisories" });
const facilitiesTable = () => screen.findByRole("table", { name: "Medical facilities" });
const rowOf = (text: string) => screen.getByText(text).closest("tr") as HTMLElement;

afterEach(() => vi.unstubAllGlobals());

describe("Health Intelligence", () => {
  it("shows the simulated banner and the KPIs from data, under MONITOR (HL-08)", async () => {
    setup(DUTY_OFFICER, MAY_SEND);
    renderApp("/health");
    expect(await screen.findByText("2 affecting mission countries")).toBeInTheDocument();
    expect(screen.getByText(/Health intelligence fused from WHO Disease Outbreak News/)).toBeInTheDocument();
    expect(screen.getByText(/Simulated samples for demonstration/)).toBeInTheDocument();
    expect(screen.getByText("1 High · 1 Moderate")).toBeInTheDocument();
    expect(screen.getByText("Staff not yet offered a vaccine")).toBeInTheDocument();
    expect(screen.getByText("73")).toBeInTheDocument();
    const nav = screen.getByRole("link", { name: /Health Intelligence/ });
    const hazards = screen.getByRole("link", { name: /Natural Hazards & Climate/ });
    // §48 Q9: before Natural Hazards & Climate.
    expect(nav.compareDocumentPosition(hazards) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("lists the advisories with the missions they affect, closed ones marked (HL-01, HL-02)", async () => {
    setup(DUTY_OFFICER, MAY_SEND);
    renderApp("/health");
    const rows = within(await advisoriesTable()).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    expect(rowOf("Cholera")).toHaveTextContent("Affects Nairobi mission");
    expect(rowOf("Cholera")).toHaveTextContent("HIGH");
    expect(rowOf("Cholera")).toHaveTextContent("Kenya · Nairobi county");
    expect(rowOf("Cholera")).toHaveTextContent("Drink bottled or boiled water only.");
    expect(rowOf("Measles")).toHaveTextContent("Affects Islamabad mission");
    expect(rowOf("Mpox")).not.toHaveTextContent("Affects");
    expect(rowOf("Dengue")).toHaveTextContent("CLOSED");
    expect(rowOf("Dengue")).not.toHaveTextContent("Affects");
  });

  it("shows the entry requirements for the mission countries (HL-03)", async () => {
    setup(VIEWER, NOTHING);
    renderApp("/health");
    const table = await screen.findByRole("table", { name: "Entry requirements" });
    expect(within(table).getAllByRole("row").slice(1)).toHaveLength(3);
    expect(within(table).getByText("Yellow fever certificate if arriving from risk country")).toBeInTheDocument();
    expect(within(table).getByText("Islamabad")).toBeInTheDocument();
  });

  it("opens the mission with the highest advisory level, then the most staff (HL-08)", async () => {
    setup(DUTY_OFFICER, MAY_SEND);
    renderApp("/health");
    await facilitiesTable();
    // Islamabad has more staff, but Nairobi's advisory is HIGH.
    expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue(NAIROBI.id);
    expect(screen.getByText("Medical facilities · Nairobi")).toBeInTheDocument();
    const rows = within(await facilitiesTable()).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Emergency · Trauma level 1 · ICU · Surgery · 24/7");
    expect(rows[0]).toHaveTextContent("2.1 km");
    expect(rows[0]).toHaveTextContent("OPEN");
    expect(rows[2]).toHaveTextContent("Not vetted");
  });

  it("switches to the mission picked", async () => {
    setup(DUTY_OFFICER, MAY_SEND);
    renderApp("/health");
    await facilitiesTable();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Mission" }), ISLAMABAD.id);
    expect(await screen.findByText("Medical facilities · Islamabad")).toBeInTheDocument();
    expect(await screen.findByText("Margalla Clinic (sample)")).toBeInTheDocument();
    expect(screen.getByText("No readiness counts for this mission.")).toBeInTheDocument();
  });

  it("flags a facility inside an ACTIVE incident's impact zone as Avoid (HL-04)", async () => {
    setup(DUTY_OFFICER, MAY_SEND, { "GET /api/health/missions/m-nbo": { body: AVOIDED } });
    renderApp("/health");
    await facilitiesTable();
    const central = rowOf("Nairobi Central Medical Centre (sample)");
    expect(central).toHaveTextContent("AVOID");
    expect(central).toHaveTextContent("Avoid · inside impact zone of INC-2026-1042");
    expect(rowOf("Highland Private Hospital (sample)")).toHaveTextContent("OPEN");
    expect(rowOf("Highland Private Hospital (sample)")).not.toHaveTextContent("AVOID");
  });

  it("shows readiness as counts for the open advisories only (HL-05, D-39)", async () => {
    setup(DUTY_OFFICER, MAY_SEND);
    renderApp("/health");
    const readiness = await screen.findByLabelText("Staff health readiness");
    expect(readiness).toHaveTextContent("Blood type on file14 / 14");
    expect(readiness).toHaveTextContent("Medical insurance active14 / 14");
    expect(readiness).toHaveTextContent("Cholera vaccine offered9 / 14");
    expect(readiness).toHaveTextContent("Trauma kits at mission (6)");
    expect(readiness).not.toHaveTextContent("Yellow fever"); // no open advisory for it
  });

  it("lets a composer send the health advisory, as a draft on Mass Notification (HL-06)", async () => {
    const fetchMock = setup(DUTY_OFFICER, MAY_SEND, {
      "POST /api/health/advisories/a-HA-1/campaign": {
        status: 201,
        body: { campaign_id: "c-9", reference: "NTF-1001", status: "DRAFT", template: "HEALTH_CHOLERA" },
      },
      "GET /api/notifications/campaigns": { body: [] },
    });
    renderApp("/health");
    await userEvent.click(await screen.findByRole("button", { name: "Send health advisory to Nairobi" }));
    expect(sent(fetchMock, "/api/health/advisories/a-HA-1/campaign")).toEqual([{ mission_id: NAIROBI.id }]);
    expect(await screen.findByRole("heading", { name: "Mass Notification" })).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes(`entity_type=health&entity_id=${NAIROBI.id}`)),
    ).toBe(true);
  });

  it("says why when sending is refused", async () => {
    setup(DUTY_OFFICER, MAY_SEND, {
      "POST /api/health/advisories/a-HA-1/campaign": { status: 409, body: { detail: "HA-1 is closed" } },
    });
    renderApp("/health");
    await userEvent.click(await screen.findByRole("button", { name: "Send health advisory to Nairobi" }));
    expect(await screen.findByText("HA-1 is closed")).toBeInTheDocument();
  });

  it("gives a Viewer the advisories, facilities and counts, with no send button and no names (HL-09)", async () => {
    setup(VIEWER, NOTHING);
    renderApp("/health");
    await facilitiesTable();
    expect(rowOf("Cholera")).toHaveTextContent("Affects Nairobi mission");
    expect(await screen.findByLabelText("Staff health readiness")).toHaveTextContent("9 / 14");
    expect(screen.queryByRole("button", { name: /Send health advisory/ })).toBeNull();
    expect(screen.queryByText(/Fictional/)).toBeNull();
  });
});

describe("health helpers", () => {
  it("ranks each mission by its highest open advisory, ignoring closed ones", () => {
    const levels = missionAdvisories([...ADVISORIES, { ...MEASLES, id: "a-x", level: "CRITICAL" }]);
    expect(levels.get(NAIROBI.id)?.level).toBe("HIGH");
    expect(levels.get(ISLAMABAD.id)?.level).toBe("CRITICAL");
    expect(levels.has(DHAKA.id)).toBe(false);
    expect(defaultMission(ADVISORIES, MISSIONS)).toBe(NAIROBI.id);
    expect(defaultMission([], MISSIONS)).toBe(ISLAMABAD.id); // no advisory: the most staff
  });

  it("formats distances and topic codes", () => {
    expect(distanceText(450)).toBe("450 m");
    expect(distanceText(6_420)).toBe("6.4 km");
    expect(topicWord("AVIAN_INFLUENZA")).toBe("Avian influenza");
  });
});
