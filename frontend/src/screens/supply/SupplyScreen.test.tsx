import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Me } from "../../api/me";
import type { Mission } from "../../api/people";
import type {
  Mitigation,
  Route,
  Supplier,
  SupplierDetail,
  SupplyPermissions,
  SupplySummary,
} from "../../api/supply";
import { bannerTitle, defaultSupplyMission } from "../../api/supply";
import { NAIROBI, VIEWER } from "../../test/fixtures";
import {
  DUTY_OFFICER,
  mockServer,
  type Reply,
  renderApp,
} from "../../test/render";

const NOW = new Date().toISOString();
const CAIRO: Mission = {
  ...NAIROBI,
  id: "m-cai",
  code: "CAI",
  city: "Cairo",
  incident_id: null,
  incident_reference: null,
};
const MISSIONS = [NAIROBI, CAIRO];
const INC = "INC-2026-1042";
const ROAD = "Road closure CBD → JKIA; reroute via Southern Bypass, +55 min";

const supplier = (
  code: string,
  name: string,
  change: Partial<Supplier> = {},
): Supplier => ({
  id: `s-${code}`,
  code,
  name,
  service: "Diplomatic pouch courier",
  mission_id: NAIROBI.id,
  mission_code: "NBO",
  city: "Nairobi",
  tier: 1,
  status: "NORMAL",
  status_detail: null,
  status_at: NOW,
  shown: "NORMAL",
  detail: null,
  impacted: false,
  incident_id: null,
  incident_reference: null,
  backup: null,
  in_bcp: true,
  vetting_valid_until: "2027-06-30",
  vetting_current: true,
  performance_score: 92,
  fuel_stock_hours: null,
  mitigation: null,
  source: "Illustrative supplier register (simulated)",
  ...change,
});
const impacted = {
  impacted: true,
  incident_id: "i-1042",
  incident_reference: INC,
};
const COURIER = supplier("SUP-104", "Swiftline Couriers", {
  shown: "ROUTE_BLOCKED",
  detail: ROAD,
  backup: {
    id: "s-SUP-105",
    code: "SUP-105",
    name: "Falcon Express Couriers",
  },
  ...impacted,
});
const FUEL = supplier("SUP-121", "Rift Valley Fuels", {
  service: "Generator fuel supply",
  tier: 2,
  in_bcp: false,
  status: "DELAYED",
  status_detail: "Fuel delivery postponed 24 h",
  shown: "DELAYED",
  detail: "Fuel delivery postponed 24 h",
  fuel_stock_hours: 72,
  ...impacted,
});
const CATERING = supplier("SUP-130", "Kilima Catering", {
  service: "Catering services",
  tier: 3,
  in_bcp: false,
  vetting_current: false,
});
const SUPPLIERS = [COURIER, FUEL, CATERING];
const route = (
  code: string,
  label: string,
  change: Partial<Route> = {},
): Route => ({
  id: `r-${code}`,
  code,
  label,
  kind: "POUCH",
  mission_id: NAIROBI.id,
  mission_code: "NBO",
  supplier_id: COURIER.id,
  supplier_code: "SUP-104",
  alternate_of_code: null,
  status: "OPEN",
  shown: "OPEN",
  detail: null,
  status_at: NOW,
  zone_incidents: [INC],
  ...change,
});
const ROUTES = [
  route("R-NBO-1", "Pouch: Embassy → JKIA via CBD", {
    status: "BLOCKED",
    shown: "BLOCKED",
    detail: ROAD,
  }),
  route("R-NBO-2", "Pouch: Embassy → JKIA via Southern Bypass", {
    alternate_of_code: "R-NBO-1",
    shown: "ALTERNATE",
  }),
];
const detailOf = (
  s: Supplier,
  change: Partial<SupplierDetail> = {},
): SupplierDetail => ({
  ...s,
  routes: ROUTES,
  mitigations: [],
  ...change,
});
const SUMMARY: SupplySummary = {
  suppliers: 52,
  missions: 36,
  tier1: 14,
  impacted: 2,
  impacted_missions: ["NBO"],
  routes: 37,
  banners: [
    {
      incident_id: "i-1042",
      incident_reference: INC,
      mission_code: "NBO",
      suppliers: [
        {
          code: "SUP-104",
          name: "Swiftline Couriers",
          shown: "ROUTE_BLOCKED",
          detail: ROAD,
        },
        {
          code: "SUP-121",
          name: "Rift Valley Fuels",
          shown: "DELAYED",
          detail: "Fuel delivery postponed 24 h",
        },
      ],
    },
  ],
};
const CALM: SupplySummary = {
  ...SUMMARY,
  impacted: 0,
  impacted_missions: [],
  banners: [],
};
const NONE: SupplyPermissions = {
  activate_mitigation: false,
  stand_down_mitigation: false,
};
const ACTIVATE: SupplyPermissions = {
  activate_mitigation: true,
  stand_down_mitigation: false,
};
const MITIGATION: Mitigation = {
  id: "mit-1",
  supplier_id: COURIER.id,
  supplier_code: "SUP-104",
  incident_id: "i-1042",
  incident_reference: INC,
  backup: COURIER.backup,
  route_code: "R-NBO-2",
  route_label: "Pouch: Embassy → JKIA via Southern Bypass",
  note: null,
  activated_at: NOW,
  activated_by_name: "Duty Officer",
  stood_down_at: null,
  stood_down_by_name: null,
  active: true,
};

function setup(
  me: Me,
  permissions: SupplyPermissions,
  extra: Record<string, Reply> = {},
) {
  return mockServer({
    "GET /api/me": { body: me },
    "GET /api/proposals": { body: [] },
    "GET /api/missions": { body: MISSIONS },
    "GET /api/supply/summary": { body: SUMMARY },
    "GET /api/supply/suppliers": { body: SUPPLIERS },
    "GET /api/supply/suppliers/s-SUP-104": { body: detailOf(COURIER) },
    "GET /api/supply/suppliers/s-SUP-121": {
      body: detailOf(FUEL, { routes: [] }),
    },
    "GET /api/supply/suppliers/s-SUP-130": {
      body: detailOf(CATERING, { routes: [] }),
    },
    "GET /api/me/permissions": { body: permissions },
    ...extra,
  });
}

function sent(
  fetchMock: ReturnType<typeof mockServer>,
  method: string,
  path: string,
): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url) === path && init?.method === method)
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

async function row(code: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", {
    name: "Suppliers and third parties",
  });
  const found = await within(table).findByText(code);
  return found.closest("tr") as HTMLElement;
}

afterEach(() => vi.unstubAllGlobals());

describe("Supply Chain Risk", () => {
  it("opens on the impacted mission: the banner, KPIs, suppliers with their status, the first impacted", async () => {
    const fetchMock = setup(DUTY_OFFICER, NONE);
    renderApp("/supply");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "Supply Chain Risk",
    );
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue(
        NAIROBI.id,
      ),
    );
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes(`/api/supply/suppliers?mission_id=${NAIROBI.id}`),
      ),
    ).toBe(true);
    const banner = await screen.findByTestId("supply-banner");
    expect(banner).toHaveTextContent(`2 third parties impacted by ${INC}.`);
    expect(banner).toHaveTextContent(
      `Swiftline Couriers: route blocked (${ROAD})`,
    );
    expect(screen.getByText("Across 36 missions")).toBeInTheDocument();
    expect(screen.getByText("All in Nairobi")).toBeInTheDocument();
    expect(screen.getByText("3 of 52 shown")).toBeInTheDocument();
    expect(await row("SUP-104")).toHaveTextContent("ROUTE BLOCKED");
    expect(await row("SUP-121")).toHaveTextContent("DELAYED");
    expect(await row("SUP-130")).toHaveTextContent("T3");
    // The first impacted supplier is selected: its card and the mission's routes.
    expect(
      await screen.findByText("SUP-104 · Diplomatic pouch courier"),
    ).toBeInTheDocument();
    const routes = await screen.findByRole("table", {
      name: "Logistics routes",
    });
    expect(
      within(routes)
        .getAllByRole("row")
        .map((r) => r.textContent),
    ).toEqual([
      `Pouch: Embassy → JKIA via CBD${ROAD}Through impact zone · ${INC}BLOCKED`,
      `Pouch: Embassy → JKIA via Southern BypassThrough impact zone · ${INC}ALTERNATE`,
    ]);
  });

  it("shows the dependencies and the fuel stock from Fleet (SUP-01, SUP-03)", async () => {
    setup(DUTY_OFFICER, NONE);
    renderApp("/supply");
    await userEvent.click(await row("SUP-121"));
    expect(
      await screen.findByText(
        "72 h on-site stock · generator fuel from Fleet & Assets",
      ),
    ).toBeInTheDocument();
    const deps = screen.getByRole("list", { name: "Dependencies" });
    expect(
      [...deps.querySelectorAll("li")].map((li) => [
        li.textContent,
        li.dataset.done,
      ]),
    ).toEqual([
      ["Backup supplier identified", "false"],
      ["Included in mission BCP", "false"],
      ["Security vetting currentuntil 2027-06-30", "true"],
    ]);
    expect(
      screen.getByText("No logistics routes monitored."),
    ).toBeInTheDocument();
    await userEvent.click(await row("SUP-130"));
    expect(
      await screen.findByText(
        "No active disruption. Last performance review 92/100.",
      ),
    ).toBeInTheDocument();
  });

  it("activates a mitigation with a note when allowed, and says nothing is sent (SUP-04)", async () => {
    const fetchMock = setup(DUTY_OFFICER, ACTIVATE, {
      "POST /api/supply/suppliers/s-SUP-104/mitigation": {
        status: 201,
        body: detailOf(COURIER, { mitigation: MITIGATION }),
      },
    });
    renderApp("/supply");
    const note = await screen.findByRole("textbox", { name: "Note" });
    expect(note).toHaveAttribute(
      "placeholder",
      expect.stringContaining("no names"),
    );
    expect(
      screen.getByText(
        "NEXIRA records the decision; nothing is sent to the supplier.",
      ),
    ).toBeInTheDocument();
    await userEvent.type(note, "  Backup courier briefed ");
    await userEvent.click(
      screen.getByRole("button", { name: "Activate mitigation" }),
    );
    expect(
      sent(fetchMock, "POST", "/api/supply/suppliers/s-SUP-104/mitigation"),
    ).toEqual([{ note: "Backup courier briefed" }]);
  });

  it("shows an active mitigation and stands it down when allowed", async () => {
    const fetchMock = setup(
      DUTY_OFFICER,
      { activate_mitigation: false, stand_down_mitigation: true },
      {
        "GET /api/supply/suppliers/s-SUP-104": {
          body: detailOf(COURIER, { mitigation: MITIGATION }),
        },
        "POST /api/supply/mitigations/mit-1/stand-down": {
          body: detailOf(COURIER),
        },
      },
    );
    renderApp("/supply");
    const m = await screen.findByTestId("supply-mitigation");
    expect(m).toHaveTextContent(`Mitigation active since`);
    expect(m).toHaveTextContent(`Duty Officer · ${INC}`);
    expect(m).toHaveTextContent(
      "Falcon Express Couriers on standby · Pouch: Embassy → JKIA via Southern Bypass in use",
    );
    expect(
      screen.queryByRole("button", { name: "Activate mitigation" }),
    ).toBeNull();
    await userEvent.click(
      await screen.findByRole("button", { name: "Stand down" }),
    );
    expect(
      sent(fetchMock, "POST", "/api/supply/mitigations/mit-1/stand-down"),
    ).toEqual([{}]);
  });

  it("says why when an activation is refused", async () => {
    setup(DUTY_OFFICER, ACTIVATE, {
      "POST /api/supply/suppliers/s-SUP-104/mitigation": {
        status: 409,
        body: { detail: "SUP-104 already has an active mitigation" },
      },
    });
    renderApp("/supply");
    await userEvent.click(
      await screen.findByRole("button", { name: "Activate mitigation" }),
    );
    expect(
      await screen.findByText("SUP-104 already has an active mitigation"),
    ).toBeInTheDocument();
  });

  it("gives a Viewer the picture and the mitigation without a name or buttons (SUP-06)", async () => {
    const hidden = { ...MITIGATION, activated_by_name: null };
    setup(VIEWER, NONE, {
      "GET /api/supply/suppliers/s-SUP-104": {
        body: detailOf(COURIER, { mitigation: hidden }),
      },
    });
    renderApp("/supply");
    const m = await screen.findByTestId("supply-mitigation");
    expect(m).toHaveTextContent(`Activated · ${INC}`);
    expect(screen.queryByText(/Duty Officer/)).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Activate mitigation|Stand down/ }),
    ).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull();
  });

  it("opens on every mission when nothing is impacted, with no banner", async () => {
    setup(DUTY_OFFICER, NONE, {
      "GET /api/supply/summary": { body: CALM },
      "GET /api/supply/suppliers": { body: [CATERING] },
    });
    renderApp("/supply");
    expect(await screen.findByText("No active disruption")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Mission" })).toHaveValue(""),
    );
    expect(screen.queryByTestId("supply-banner")).toBeNull();
  });
});

describe("supply helpers", () => {
  it("banner titles and the default mission", () => {
    const [banner] = SUMMARY.banners;
    if (!banner) throw new Error("the fixture has a banner");
    expect(bannerTitle(banner)).toBe(`2 third parties impacted by ${INC}.`);
    expect(
      bannerTitle({ ...banner, suppliers: banner.suppliers.slice(0, 1) }),
    ).toBe(`1 third party impacted by ${INC}.`);
    expect(defaultSupplyMission(MISSIONS, SUMMARY)).toBe(NAIROBI.id);
    expect(defaultSupplyMission(MISSIONS, CALM)).toBe("");
    expect(defaultSupplyMission(MISSIONS, undefined)).toBe("");
  });
});
