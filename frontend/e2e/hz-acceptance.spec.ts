import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Natural Hazards & Climate acceptance (Prompt 58; requirements-pilot.md §42, D-38) on the real
// stack. `make acceptance` runs it after the Document Expiry spec (Playwright orders files by
// name), before DAC-CYCLONE has been played; run alone, it needs `make reset-demo` first. The Duty
// Officer plays DAC-CYCLONE from the presenter bar; the Response Planner proposes arming PB-06
// and a Security Officer approves it in the Decision Queue. Scene 3 moves the demo clock on
// 24 h (plan-pilot-hz G-9), and the worker starts the armed run by itself.

interface Hazard {
  incident_id: string;
  reference: string;
  category: string;
  severity: string;
  status: string;
  hazard: Record<string, unknown>;
  landfall_in_h: number | null;
  nearest_mission_code: string | null;
  nearest_mission_m: number | null;
  within_range: boolean;
  exposed: boolean;
  exposure: Record<string, number>;
  armed: { run_id: string; status: string; scheduled_for: string | null } | null;
  simulated: boolean;
}
interface Hazards {
  events: Hazard[];
  demo_advance_h: number;
  sources: number;
}
interface Climate {
  mission_code: string;
  score_2050: number;
  simulated: boolean;
}
interface Proposal {
  id: string;
  action_type: string;
  title: string;
  status: string;
  effective_level: number;
  incident_id: string | null;
  action_payload: Record<string, unknown>;
}
interface Run {
  id: string;
  playbook_code: string;
  status: string;
  scheduled_for: string | null;
  started_by_type: string;
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "DAC-CYCLONE";

test("Natural Hazards acceptance: events, a Dhaka cyclone, PB-06 armed and started, the Viewer", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(420_000);
  const duty = await as(request, "duty.officer");
  const security = await as(request, "security.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const hazards = () => duty.get<Hazards>("/api/hazards");
  const find = async (category: string, mission?: string) =>
    (await hazards()).events.find(
      (e) => e.category === category && (mission === undefined || e.nearest_mission_code === mission),
    );
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);

  // --- 0. The screen, labelled simulated, before the scenario (HZ-08, HZ-09) -----------------
  expect(await find("TROPICAL_CYCLONE", "DAC"), "run from `make reset-demo`").toBeUndefined();
  const climate = await viewer.get<Climate[]>("/api/hazards/climate");
  expect(climate).toHaveLength(36);
  expect(climate[0]?.mission_code).toBe("JKT"); // the highest 2050 score
  expect(climate.every((c) => c.simulated)).toBe(true);

  const page = await signedIn(browser, "duty.officer", "/hazards");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Natural Hazards & Climate");
  await expect(page.getByText("JAKARTA", { exact: true })).toBeVisible();
  const climateTable = page.getByRole("table", { name: "Long-term climate exposure" });
  await expect(climateTable.getByRole("row")).toHaveCount(37);
  await expect(climateTable.getByRole("row").nth(1)).toContainText("Jakarta");
  await expect(page.getByText(/Illustrative climate model \(simulated\)/)).toBeVisible();

  // --- 1. Background events: Ankara LOW and outside its range (HZ-01..03, HZ-11) -------------
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Calm");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  const background = await until(async () => {
    const h = await hazards();
    const kinds = new Set(h.events.map((e) => e.category));
    return ["EARTHQUAKE", "TROPICAL_CYCLONE", "FLOOD", "EXTREME_HEAT", "AIR_QUALITY", "WILDFIRE"].every((k) =>
      kinds.has(k),
    )
      ? h
      : undefined;
  }, "the six background hazard events");
  expect(background.sources).toBe(4);
  expect(background.events.every((e) => e.simulated)).toBe(true);
  const quake = background.events.find((e) => e.category === "EARTHQUAKE" && e.nearest_mission_code === "ANK");
  expect([quake?.severity, quake?.exposed]).toEqual(["LOW", false]);
  expect(quake?.nearest_mission_m).toBeGreaterThan(200_000);
  const fire = background.events.find((e) => e.category === "WILDFIRE");
  expect(fire?.within_range).toBe(false);
  const flood = background.events.find((e) => e.category === "FLOOD" && e.nearest_mission_code === "JKT");
  expect(flood?.exposure.homes).toBe(2);

  const events = page.getByRole("table", { name: "Live hazard events" });
  await expect(events.getByRole("row", { name: /Central Anatolia/ })).toContainText(/Ankara mission · 2\d\d km/, {
    timeout: 20_000,
  });
  await expect(events.getByRole("row", { name: /Central Anatolia/ })).toContainText("LOW");
  await expect(events.getByRole("row", { name: /Ciliwung/ })).toContainText("Jakarta mission · 2 staff homes");
  await expect(events.getByRole("row", { name: /Attica/ })).toContainText("No mission within 300 km");

  // --- 2. Category 2, landfall in 60 h, exposing Dhaka; the arming proposal (HZ-02, HZ-04, HZ-06)
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(2);
  // HIGH from Category 2, raised to CRITICAL by D-11: the chancery is in the zone (G-13). Fusion
  // records the forecast first and exposure raises it after, so wait for both; a raise that never
  // comes still fails here, on the timeout.
  const cyclone = await until(async () => {
    const c = await find("TROPICAL_CYCLONE", "DAC");
    return c?.hazard.cyclone_category === 2 && c.severity === "CRITICAL" ? c : undefined;
  }, "the Category 2 forecast for Dhaka, raised to CRITICAL by D-11");
  expect([cyclone.severity, cyclone.exposed]).toEqual(["CRITICAL", true]);
  expect(cyclone.landfall_in_h).toBeGreaterThan(59);
  expect(cyclone.landfall_in_h).toBeLessThanOrEqual(60);
  expect(cyclone.exposure.staff).toBe(15);
  expect(cyclone.armed).toBeNull();

  const arming = await until(async () => {
    const all = await duty.get<Proposal[]>("/api/proposals?limit=200");
    return all.find((p) => p.action_type === "ARM_PLAYBOOK" && p.incident_id === cyclone.incident_id);
  }, "the arming proposal");
  expect([arming.status, arming.effective_level, arming.action_payload.playbook_code]).toEqual(["PENDING", 2, "PB-06"]);
  expect(arming.title).toContain("Arm PB-06 for");

  // The presenter bar opened the Decision Queue for scene 2; the nav link keeps its scenario.
  await expect(page.locator(`[data-proposal-id="${arming.id}"]`)).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: /Natural Hazards & Climate/ }).click();
  const row = events.getByRole("row", { name: /Barishal/ });
  await expect(row).toContainText("Dhaka mission · landfall in 60 h");
  await expect(row).toContainText("CRITICAL");
  const banner = page.getByTestId(`arming-${cyclone.reference}`);
  await expect(banner).toContainText("Cyclone forecast for Dhaka: landfall in 60 h.");
  await expect(banner.getByRole("button", { name: "Arm playbook" })).toBeVisible(); // a Duty Officer may

  // --- 3. A Viewer: events and scores, no names, no "Arm playbook" (HZ-10) -------------------
  const asViewer = await viewer.get<Hazards>("/api/hazards");
  expect(asViewer.events.length).toBe((await hazards()).events.length);
  expect(JSON.stringify(asViewer)).not.toMatch(/display_name|full_name|holder_name/);
  expect(
    (await viewer.post("/api/playbook-runs/arm", { playbook_code: "PB-06", incident_id: cyclone.incident_id })).status(),
  ).toBe(403);
  const viewerPage = await signedIn(browser, "viewer", "/hazards");
  const viewerBanner = viewerPage.getByTestId(`arming-${cyclone.reference}`);
  await expect(viewerBanner).toContainText("Cyclone forecast for Dhaka");
  await expect(viewerPage.getByRole("table", { name: "Long-term climate exposure" }).getByRole("row")).toHaveCount(37);
  await expect(viewerBanner.getByRole("button")).toHaveCount(0);
  await expect(viewerPage.getByRole("button", { name: "Arm playbook" })).toHaveCount(0);
  await viewerPage.context().close();

  // --- 4. A Security Officer approves; PB-06 is armed for 36 h before landfall (HZ-05) -------
  const secPage = await signedIn(browser, "security.officer", "/");
  await secPage
    .locator(`[data-proposal-id="${arming.id}"]`)
    .getByRole("button", { name: /^Approve as / })
    .click();
  const armed = await until(async () => {
    const runs = await security.get<Run[]>(`/api/playbook-runs?incident_id=${cyclone.incident_id}`);
    return runs.find((r) => r.playbook_code === "PB-06" && r.status === "SCHEDULED");
  }, "PB-06 armed");
  const startsInH = (new Date(String(armed.scheduled_for)).getTime() - Date.now()) / 3_600_000;
  expect(startsInH).toBeGreaterThan(23);
  expect(startsInH).toBeLessThanOrEqual(24);
  await secPage.goto("/hazards");
  const secBanner = secPage.getByTestId(`arming-${cyclone.reference}`);
  await expect(secBanner).toContainText(/PB-06 armed for Dhaka · starts in 2[34] h\./);
  await expect(secBanner.getByRole("button", { name: "Start now" })).toBeVisible();
  await expect(secBanner.getByRole("button", { name: "Disarm" })).toBeVisible();
  await secPage.context().close();

  // --- 5. The demo clock reaches 36 h before landfall: PB-06 starts by itself (HZ-05, G-9) ---
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(3);
  const started = await until(
    async () => {
      const runs = await duty.get<Run[]>(`/api/playbook-runs?incident_id=${cyclone.incident_id}`);
      const run = runs.find((r) => r.id === armed.id);
      return run && run.status !== "SCHEDULED" ? run : undefined;
    },
    "the armed PB-06 started by the worker",
    120,
  );
  expect(["RUNNING", "AWAITING_APPROVAL", "COMPLETED"]).toContain(started.status);
  const after = await find("TROPICAL_CYCLONE", "DAC");
  expect(after?.armed?.status).toBe(started.status);
  expect((await hazards()).demo_advance_h).toBe(24);
  await expect(page.getByText("Simulated · demo clock +24 h")).toBeVisible({ timeout: 20_000 });
  await expect(events.getByRole("row", { name: /Barishal/ })).toContainText(/landfall in 3[56] h/);
  await expect(page.getByTestId(`arming-${cyclone.reference}`)).toHaveCount(0);

  // --- 6. Audited, and the chain verifies (D-20) --------------------------------------------
  const audit = await admin.get<{ action: string; entity_id: string | null }[]>("/api/audit?limit=500");
  for (const action of ["PLAYBOOK.ARM", "PLAYBOOK.ARMED_START", "SCENARIO.CLOCK_ADVANCE", "PROPOSAL.APPROVE"]) {
    expect(audit.some((e) => e.action === action), action).toBe(true);
  }
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
