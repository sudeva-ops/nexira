import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Supply Chain acceptance (Prompt 94; requirements-pilot.md §72, D-44) on the real stack.
// `make acceptance` runs it after the Mass Notification spec and before Travel & Air (Playwright
// orders files by name). By now INC-<year>-1042 is ACTIVE (the Document Expiry spec), so Nairobi
// has an ACTIVE incident; its suppliers report NORMAL, so nothing is impacted until NBO-SUPPLY.
// This spec plays NBO-SUPPLY from the presenter bar: the pouch route blocked, then fuel and the
// guards, then the recovery; a mitigation activated and stood down in the browser; names by
// scope and the audit. It leaves every status as seeded and no mitigation active (plan §9).

interface Supplier {
  id: string;
  code: string;
  status: string;
  shown: string;
  detail: string | null;
  impacted: boolean;
  incident_reference: string | null;
  backup: { code: string; name: string } | null;
  in_bcp: boolean;
  vetting_current: boolean;
  fuel_stock_hours: number | null;
  mitigation: Mitigation | null;
  source: string;
}
interface Mitigation {
  id: string;
  backup: { code: string } | null;
  route_code: string | null;
  incident_reference: string | null;
  activated_by_name: string | null;
  stood_down_by_name: string | null;
  active: boolean;
}
interface Detail extends Supplier {
  routes: { code: string; shown: string; zone_incidents: string[] }[];
  mitigations: Mitigation[];
}
interface Summary {
  suppliers: number;
  missions: number;
  tier1: number;
  impacted: number;
  routes: number;
  banners: {
    incident_reference: string;
    suppliers: { code: string; shown: string }[];
  }[];
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "NBO-SUPPLY";
const year = new Date().getUTCFullYear();
const INCIDENT = `INC-${year}-1042`;
const ROAD = "Road closure CBD → JKIA; reroute via Southern Bypass, +55 min";

test("Supply Chain acceptance: the register, NBO-SUPPLY, a mitigation, names, the audit", async ({
  browser,
  request,
}) => {
  test.skip(
    !PASSWORD,
    "DEMO_USER_PASSWORD is not set (run through `make acceptance`)",
  );
  test.setTimeout(300_000);
  const duty = await as(request, "duty.officer");
  const security = await as(request, "security.officer");
  const viewer = await as(request, "viewer");
  const homCairo = await as(request, "hom.cairo");
  const admin = await as(request, "admin");

  const missions =
    await duty.get<{ id: string; code: string }[]>("/api/missions");
  const nbo = missions.find((m) => m.code === "NBO")?.id ?? "";
  const suppliers = async (client = duty) =>
    Object.fromEntries(
      (await client.get<Supplier[]>("/api/supply/suppliers")).map((s) => [
        s.code,
        s,
      ]),
    );
  const summary = () => duty.get<Summary>("/api/supply/summary");
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene &&
        (s.scene_complete || s.status !== "PLAYING")
        ? true
        : undefined;
    }, `scene ${scene} played`);
  const incident = (
    await duty.get<{ id: string; reference: string; status: string }[]>(
      "/api/incidents",
    )
  ).find((i) => i.reference === INCIDENT);
  expect(
    incident?.status,
    "run after the Phase 1 and Document Expiry specs",
  ).toBe("ACTIVE");
  const supplyEntries = async () =>
    (
      await duty.get<{
        timeline: { event_type: string; summary: string; actor_type: string }[];
      }>(`/api/incidents/${incident?.id}`)
    ).timeline.filter((e) => e.event_type === "SUPPLY");

  // --- 0. The seeded register and routes (SUP-01, SUP-02) -------------------------------------
  expect(await summary()).toMatchObject({
    suppliers: 52,
    missions: 36,
    tier1: 14,
    impacted: 0,
    routes: 37,
  });
  const seeded = await suppliers();
  const nairobi = Object.values(seeded).filter((s) =>
    s.code.startsWith("SUP-1"),
  );
  expect(nairobi.map((s) => s.shown)).toEqual(
    Array(nairobi.length).fill("NORMAL"),
  );
  expect([seeded["SUP-251"]?.shown, seeded["SUP-262"]?.shown]).toEqual([
    "WATCH",
    "WATCH",
  ]);
  const courier = seeded["SUP-104"];
  expect(courier).toMatchObject({
    backup: { code: "SUP-105", name: "Falcon Express Couriers" },
    in_bcp: true,
    vetting_current: true,
    source: "Illustrative supplier register (simulated)",
  });
  expect(seeded["SUP-121"]?.fuel_stock_hours).toBe(72); // GEN-NBO from Fleet (G-7)
  if (!courier) return;
  const routes = (await duty.get<Detail>(`/api/supply/suppliers/${courier.id}`))
    .routes;
  expect(routes.map((r) => [r.code, r.shown])).toEqual([
    ["R-NBO-1", "OPEN"],
    ["R-NBO-2", "OPEN"],
    ["R-NBO-3", "OPEN"],
    ["R-NBO-4", "OPEN"],
  ]);
  expect(routes[0]?.zone_incidents).toEqual([INCIDENT]); // tagged; the status stays (G-4)
  const page = await signedIn(browser, "duty.officer", "/supply");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Supply Chain Risk",
  );
  await expect(page.getByText("Across 36 missions")).toBeVisible();
  await expect(
    page.getByText("No active disruption", { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("supply-banner")).toHaveCount(0);
  const before = (await supplyEntries()).length;

  // --- 1. NBO-SUPPLY scene 1: the pouch route via the CBD is blocked (SUP-02, SUP-03) ----------
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Ready");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  const blocked = await until(async () => {
    const s = (await suppliers())["SUP-104"];
    return s?.shown === "ROUTE_BLOCKED" ? s : undefined;
  }, "SUP-104 route blocked");
  expect([
    blocked.detail,
    blocked.impacted,
    blocked.incident_reference,
  ]).toEqual([ROAD, true, INCIDENT]);
  const afterBlock = (
    await duty.get<Detail>(`/api/supply/suppliers/${courier.id}`)
  ).routes;
  expect(afterBlock.slice(0, 2).map((r) => r.shown)).toEqual([
    "BLOCKED",
    "ALTERNATE",
  ]);
  // The presenter bar opens /supply on the impacted mission (SCENE_SCREEN, defaultSupplyMission).
  await expect(page.getByTestId("supply-banner")).toContainText(
    `1 third party impacted by ${INCIDENT}.`,
    {
      timeout: 20_000,
    },
  );
  const table = page.getByRole("table", {
    name: "Suppliers and third parties",
  });
  await expect(table.locator('tr[data-supplier="SUP-104"]')).toContainText(
    "ROUTE BLOCKED",
  );
  await expect(
    page
      .getByRole("table", { name: "Logistics routes" })
      .locator('tr[data-route="R-NBO-2"]'),
  ).toContainText("ALTERNATE");
  expect(
    (await supplyEntries()).slice(before).map((e) => [e.summary, e.actor_type]),
  ).toEqual([
    [`Nairobi · Pouch: Embassy → JKIA via CBD: BLOCKED (${ROAD}).`, "SYSTEM"],
  ]);

  // --- 2. A mitigation in the browser; the Viewer and the Cairo HoM cannot (SUP-04) -----------
  const activate = `/api/supply/suppliers/${courier.id}/mitigation`;
  expect((await viewer.post(activate)).status()).toBe(403);
  expect((await homCairo.post(activate)).status()).toBe(403);
  await page
    .getByRole("textbox", { name: "Note" })
    .fill("Backup courier briefed");
  await page.getByRole("button", { name: "Activate mitigation" }).click();
  await expect(page.getByTestId("supply-mitigation")).toContainText(
    "Falcon Express Couriers on standby · Pouch: Embassy → JKIA via Southern Bypass in use",
  );
  expect((await security.post(activate)).status()).toBe(409); // one active per supplier
  const active = (await suppliers())["SUP-104"]?.mitigation;
  expect(active).toMatchObject({
    backup: { code: "SUP-105" },
    route_code: "R-NBO-2",
    incident_reference: INCIDENT,
    active: true,
  });
  expect(active?.activated_by_name).toBeTruthy(); // the Duty Officer is in the people scope

  // --- 3. Scene 2: fuel and the guards; three impacted (SUP-03) -------------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(2);
  const three = await until(async () => {
    const s = await summary();
    return s.impacted === 3 ? s : undefined;
  }, "three impacted");
  expect(
    three.banners.map((b) => [
      b.incident_reference,
      b.suppliers.map((s) => [s.code, s.shown]),
    ]),
  ).toEqual([
    [
      INCIDENT,
      [
        ["SUP-104", "ROUTE_BLOCKED"],
        ["SUP-117", "AT_RISK"],
        ["SUP-121", "DELAYED"],
      ],
    ],
  ]);
  await expect(page.getByTestId("supply-banner")).toContainText(
    `3 third parties impacted by ${INCIDENT}.`,
    {
      timeout: 20_000,
    },
  );
  await page
    .getByRole("table", { name: "Suppliers and third parties" })
    .locator('tr[data-supplier="SUP-121"]')
    .click();
  await expect(
    page.getByText("72 h on-site stock · generator fuel from Fleet & Assets"),
  ).toBeVisible();
  await expect(
    page.getByText("Fuel delivery postponed 24 h").first(),
  ).toBeVisible();

  // --- 4. Scene 3: the recovery; none impacted -----------------------------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(3);
  await until(
    async () => ((await summary()).impacted === 0 ? true : undefined),
    "the recovery",
  );
  await expect(
    page.getByText("No active disruption", { exact: true }),
  ).toBeVisible({
    timeout: 20_000,
  });
  // 1 block, the activation, 4 in scene 2, 5 recoveries (plan §8).
  expect((await supplyEntries()).length - before).toBe(11);

  // --- 5. Names only within the people scope (SUP-06) -----------------------------------------
  for (const [who, client] of [
    ["viewer", viewer],
    ["hom.cairo", homCairo],
  ] as const) {
    const m = (await suppliers(client))["SUP-104"]?.mitigation;
    expect(m?.active, who).toBe(true);
    expect(m?.activated_by_name, who).toBeNull();
  }
  const viewerPage = await signedIn(
    browser,
    "viewer",
    `/supply?mission=${nbo}`,
  );
  await viewerPage
    .getByRole("table", { name: "Suppliers and third parties" })
    .locator('tr[data-supplier="SUP-104"]')
    .click();
  await expect(viewerPage.getByTestId("supply-mitigation")).toContainText(
    `Activated · ${INCIDENT}`,
  );
  await expect(
    viewerPage.getByRole("button", { name: /Activate mitigation|Stand down/ }),
  ).toHaveCount(0);
  await viewerPage.context().close();

  // --- 6. Stand down in the browser, once -----------------------------------------------------
  await page
    .getByRole("table", { name: "Suppliers and third parties" })
    .locator('tr[data-supplier="SUP-104"]')
    .click();
  await page.getByRole("button", { name: "Stand down" }).click();
  await until(
    async () =>
      (await suppliers())["SUP-104"]?.mitigation === null ? true : undefined,
    "stood down",
  );
  const history = (
    await duty.get<Detail>(`/api/supply/suppliers/${courier.id}`)
  ).mitigations;
  expect(history.map((m) => m.active)).toEqual([false]);
  expect(
    (
      await duty.post(`/api/supply/mitigations/${history[0]?.id}/stand-down`)
    ).status(),
  ).toBe(409);
  expect((await supplyEntries()).at(-1)?.summary).toBe(
    "Nairobi · Swiftline Couriers: mitigation stood down.",
  );

  // --- 7. Every change audited, and the chain verifies (D-20) ---------------------------------
  const actions = [
    ...(await admin.get<{ action: string }[]>(
      "/api/audit?entity_type=supplier&limit=500",
    )),
    ...(await admin.get<{ action: string }[]>(
      "/api/audit?entity_type=logistics_route&limit=500",
    )),
  ].map((e) => e.action);
  for (const action of [
    "SUPPLY.SEED",
    "SUPPLY.ROUTE_STATUS",
    "SUPPLY.SUPPLIER_STATUS",
    "SUPPLY.MITIGATION_ACTIVATED",
    "SUPPLY.MITIGATION_STOOD_DOWN",
  ]) {
    expect(actions, action).toContain(action);
  }
  expect(
    await admin.get<{ intact: boolean }>("/api/audit/verify"),
  ).toMatchObject({ intact: true });

  // --- 8. As found: every status as seeded, no mitigation active (plan §9) --------------------
  expect((await summary()).impacted).toBe(0);
  const after = await suppliers();
  expect(Object.values(after).filter((s) => s.mitigation !== null)).toEqual([]);
  expect(
    Object.entries(after).filter(([, s]) => s.shown !== seeded[s.code]?.shown),
  ).toEqual([]);

  expect(cspViolations).toEqual([]);
});
