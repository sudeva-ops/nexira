import { expect, test } from "@playwright/test";

import { as, cspViolations, PASSWORD, signedIn, until } from "./support";

// Health Intelligence acceptance (Prompt 64; requirements-pilot.md §47, D-39) on the real stack.
// `make acceptance` runs it after the Document Expiry spec (Playwright orders files by name),
// which leaves INC-<year>-1042 ACTIVE; run alone from reset-demo, it plays NBO-CIVIL-UNREST up
// to scene 2 itself. The Duty Officer plays NBO-CHOLERA from the presenter bar: the Communications
// agent proposes the Nairobi health advisory, the Duty Officer approves it in the Decision Queue,
// and the campaign it creates still needs a second person, the Consular Officer (plan-pilot-hl G-2).

interface Advisory {
  id: string;
  reference: string;
  topic_code: string;
  level: string;
  status: string;
  missions: { code: string }[];
  simulated: boolean;
}
interface Requirement {
  country_code: string;
  mandatory: string;
  simulated: boolean;
}
interface MissionHealth {
  facilities: { name: string; avoid: boolean; avoid_incident: string | null; simulated: boolean }[];
  readiness: { staff: number; vaccines: { topic_code: string; offered: number }[]; simulated: boolean } | null;
}
interface Proposal {
  id: string;
  action_type: string;
  title: string;
  status: string;
  effective_level: number;
  evidence: { text: string }[];
}
interface Campaign {
  id: string;
  reference: string;
  status: string;
  created_by_type: string;
  created_by: string | null;
  message: string;
  recipients: number;
  deliveries: Record<string, number>;
}
interface Incident {
  id: string;
  reference: string;
  status: string;
}
interface Scenario {
  status: string;
  current_scene: number;
  scene_complete: boolean;
}

const SCENARIO = "NBO-CHOLERA";
const CENTRAL = "Nairobi Central Medical Centre (sample)";
const year = new Date().getUTCFullYear();

test("Health Intelligence acceptance: advisories, Avoid, NBO-CHOLERA, second person, the Viewer", async ({
  browser,
  request,
}) => {
  test.skip(!PASSWORD, "DEMO_USER_PASSWORD is not set (run through `make acceptance`)");
  test.setTimeout(360_000);
  const duty = await as(request, "duty.officer");
  const consular = await as(request, "consular.officer");
  const viewer = await as(request, "viewer");
  const admin = await as(request, "admin");
  const advisories = () => duty.get<Advisory[]>("/api/health/advisories");
  const cholera = async () => (await advisories()).find((a) => a.topic_code === "CHOLERA");
  const missions = await duty.get<{ id: string; code: string }[]>("/api/missions");
  const nbo = missions.find((m) => m.code === "NBO")?.id ?? "";
  const nboHealth = () => duty.get<MissionHealth>(`/api/health/missions/${nbo}`);
  const sceneDone = (scene: number) =>
    until(async () => {
      const s = await duty.get<Scenario>(`/api/scenarios/${SCENARIO}`);
      return s.current_scene === scene && (s.scene_complete || s.status !== "PLAYING") ? true : undefined;
    }, `scene ${scene} played`);

  // --- 0. The seeded advisories, requirements, facilities and counts, simulated (HL-01..05) --
  const seeded = await advisories();
  expect(seeded.filter((a) => a.status === "OPEN")).toHaveLength(6);
  expect(seeded.every((a) => a.simulated)).toBe(true);
  expect([(await cholera())?.level, (await cholera())?.missions.map((m) => m.code)]).toEqual(["MODERATE", ["NBO"]]);
  const requirements = await viewer.get<Requirement[]>("/api/health/requirements");
  expect(requirements.every((r) => r.simulated)).toBe(true);
  expect(requirements.find((r) => r.country_code === "KE")?.mandatory).toContain("Yellow fever certificate");
  const readiness = (await nboHealth()).readiness;
  expect(readiness?.staff).toBe(14);
  expect(readiness?.vaccines.find((v) => v.topic_code === "CHOLERA")?.offered).toBe(9);

  // --- 1. NBO-CIVIL-UNREST ACTIVE: Nairobi Central is to be avoided, the others not (HL-04) --
  const unrest = async () =>
    (await duty.get<Incident[]>("/api/incidents")).find((i) => i.reference === `INC-${year}-1042`);
  if (!(await unrest())) {
    for (let scene = 0; scene < 2; scene += 1) await duty.post("/api/scenarios/NBO-CIVIL-UNREST/next");
  }
  const incident = await until(unrest, "INC-1042", 90);
  if (incident.status !== "ACTIVE") {
    expect((await duty.patch(`/api/incidents/${incident.id}/status`, { status: "ACTIVE" })).ok()).toBeTruthy();
  }
  const facilities = await until(async () => {
    const f = (await nboHealth()).facilities;
    return f.find((x) => x.name === CENTRAL)?.avoid ? f : undefined;
  }, "Nairobi Central flagged Avoid");
  expect(facilities.filter((f) => f.avoid).map((f) => [f.name, f.avoid_incident])).toEqual([
    [CENTRAL, incident.reference],
  ]);
  expect(facilities.every((f) => f.simulated)).toBe(true);

  const page = await signedIn(browser, "duty.officer", "/health");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Health Intelligence");
  await expect(page.getByText(/simulated samples for demonstration/)).toBeVisible();
  const table = page.getByRole("table", { name: "Health advisories" });
  await expect(table.locator("tbody tr")).toHaveCount(seeded.length);
  await expect(table.getByRole("row", { name: /Cholera/ })).toContainText("Affects Nairobi mission");
  await expect(table.getByRole("row", { name: /Cholera/ })).toContainText("MODERATE");
  await expect(page.getByRole("table", { name: "Entry requirements" })).toContainText("Yellow fever certificate");
  // Before scene 1 no advisory is HIGH, so the default is a MODERATE mission with more staff.
  await page.getByRole("combobox", { name: "Mission" }).selectOption(nbo);
  const central = page.locator(`tr[data-facility="${CENTRAL}"]`);
  await expect(central).toContainText("AVOID");
  await expect(central).toContainText(`Avoid · inside impact zone of ${incident.reference}`);
  await expect(page.getByLabel("Staff health readiness")).toContainText("Cholera vaccine offered9 / 14");

  // While the incident is at MONITORING it is no longer ACTIVE: Avoid clears, live (G-8).
  expect((await duty.patch(`/api/incidents/${incident.id}/status`, { status: "MONITORING" })).ok()).toBeTruthy();
  await expect(central).toContainText("OPEN", { timeout: 20_000 });
  await expect(central).not.toContainText("AVOID");
  expect((await duty.patch(`/api/incidents/${incident.id}/status`, { status: "ACTIVE" })).ok()).toBeTruthy();
  await expect(central).toContainText("AVOID", { timeout: 20_000 });

  // --- 2. Scene 1: cholera HIGH; the Communications agent proposes (HL-07, HL-10) -----------
  const bar = page.getByRole("toolbar", { name: "Presenter" });
  await bar.getByLabel("Scenario").selectOption(SCENARIO);
  await expect(bar).toContainText("Calm");
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(1);
  await until(async () => ((await cholera())?.level === "HIGH" ? true : undefined), "cholera HIGH");
  await expect(table.getByRole("row", { name: /Cholera/ })).toContainText("HIGH", { timeout: 20_000 });
  // HL-08: the screen now opens on Nairobi, the mission with the highest advisory level. The nav
  // link, not a reload, keeps the presenter bar's scenario.
  await page.getByRole("link", { name: "Decision Queue" }).click();
  await page.getByRole("link", { name: /Health Intelligence/ }).click();
  await expect(page.getByRole("combobox", { name: "Mission" })).toHaveValue(nbo);
  const proposal = await until(async () => {
    const all = await duty.get<Proposal[]>("/api/proposals?limit=200");
    return all.find((p) => p.action_type === "PREPARE_HEALTH_ADVISORY" && p.status === "PENDING");
  }, "the health advisory proposal");
  expect([proposal.title, proposal.effective_level]).toEqual([
    "Health advisory recommended for Nairobi staff and citizens",
    2,
  ]);
  expect(proposal.evidence.map((e) => e.text)).toContain("9 of 14 staff offered the cholera vaccine");

  // --- 3. The Duty Officer approves it; the campaign waits for a second person (G-2, D-31) ---
  await page.getByRole("link", { name: "Decision Queue" }).click();
  await page
    .locator(`[data-proposal-id="${proposal.id}"]`)
    .getByRole("button", { name: /^Approve as / })
    .click();
  const campaign = await until(async () => {
    const all = await duty.get<Campaign[]>("/api/campaigns");
    return all.find((c) => c.created_by === proposal.id);
  }, "the agent's campaign");
  expect([campaign.status, campaign.created_by_type, campaign.recipients]).toEqual(["PENDING_APPROVAL", "AGENT", 0]);
  expect(campaign.message).toContain("Nairobi");
  expect((await duty.post(`/api/campaigns/${campaign.id}/approve`)).status()).toBe(403);
  expect((await viewer.post(`/api/campaigns/${campaign.id}/approve`)).status()).toBe(403);

  // --- 4. The Consular Officer approves and sends it; deliveries are simulated (HL-06) ------
  const approver = await signedIn(browser, "consular.officer", `/notifications?campaign=${campaign.id}`);
  await approver.getByRole("button", { name: "Approve and send" }).click();
  const sent = await until(
    async () => {
      const c = await consular.get<Campaign>(`/api/campaigns/${campaign.id}`);
      return c.status === "SENT" && (c.deliveries.READ ?? 0) + (c.deliveries.DELIVERED ?? 0) > 0 ? c : undefined;
    },
    "the health advisory sent",
    90,
  );
  expect(sent.recipients).toBeGreaterThan(0);
  expect(sent.deliveries.FAILED ?? 0).toBe(0);
  await approver.context().close();

  // --- 5. Scene 2: dengue closed, off the open list (HL-10) ---------------------------------
  await bar.getByRole("button", { name: "Next scene" }).click();
  await sceneDone(2);
  await until(async () => {
    const dengue = (await advisories()).find((a) => a.topic_code === "DENGUE");
    return dengue?.status === "CLOSED" ? true : undefined;
  }, "dengue closed");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Health Intelligence");
  await expect(table.getByRole("row", { name: /Dengue/ })).toContainText("CLOSED", { timeout: 20_000 });
  expect((await advisories()).filter((a) => a.status === "OPEN")).toHaveLength(5);

  // --- 6. A Viewer: the screen, no send button, no names (HL-09) ----------------------------
  const asViewer = await viewer.get<MissionHealth>(`/api/health/missions/${nbo}`);
  expect(asViewer.readiness?.staff).toBe(14);
  expect(JSON.stringify([asViewer, await viewer.get("/api/health/advisories")])).not.toMatch(
    /display_name|full_name|holder_name/,
  );
  const open = (await advisories()).find((a) => a.topic_code === "CHOLERA");
  expect((await viewer.post(`/api/health/advisories/${open?.id}/campaign`, { mission_id: nbo })).status()).toBe(403);
  const viewerPage = await signedIn(browser, "viewer", "/health");
  await expect(viewerPage.locator(`tr[data-facility="${CENTRAL}"]`)).toContainText("AVOID");
  await expect(viewerPage.getByLabel("Staff health readiness")).toContainText("9 / 14");
  await expect(viewerPage.getByRole("button", { name: /Send health advisory/ })).toHaveCount(0);
  await viewerPage.context().close();
  // A composer does get it (HL-06).
  await expect(page.getByRole("button", { name: "Send health advisory to Nairobi" })).toBeVisible();

  // --- 7. Audited, and the chain verifies (D-20) --------------------------------------------
  const audit = await admin.get<{ action: string }[]>("/api/audit?limit=500");
  const actions = audit.map((e) => e.action);
  for (const action of ["HEALTH_ADVISORY.UPDATE", "HEALTH_ADVISORY.CLOSE", "CAMPAIGN.PREPARE", "PROPOSAL.APPROVE"]) {
    expect(actions, action).toContain(action);
  }
  expect(await admin.get<{ intact: boolean }>("/api/audit/verify")).toMatchObject({ intact: true });

  expect(cspViolations).toEqual([]);
});
